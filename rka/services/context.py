"""Context engine — prepares importance-ranked context packages for Brain and Executor.

v2.4 (Improvement 1, dec_01KQQPD6Y6B362T3K08368BDMP): the temperature classifier
(HOT/WARM/COLD bucketing on day-thresholds) and the token-budget arithmetic were
removed. Rationale per the probe report (mis_01KQQPHC2649SXJG30JMCR0WFK):

- Day-threshold buckets systematically excluded older relevant content.
- Frontier model context windows make a bookkeeper-imposed token budget
  unnecessary; the bookkeeper invariant says compute at SQL time, not at
  retrieval time.
- The `journal.importance` column already exists with an index; pairing it
  with `entity_links` centrality gives a deterministic SQL-time ranking that
  doesn't drift with wall-clock time.

v2.5.3 (D2, dec_01KRSMMCS8MD7KQDBS0E2DVKBQ): the post-fetch ranker grew two
shapes that close documented-vs-implemented gaps surfaced by Eval-v2's
ordering_score = 0.251 finding:

- Topic path (``get_context(topic=...)``): preserves search relevance as the
  primary sort key. Pre-v2.5.3 the BM25/vector relevance ordering returned
  by ``SearchService.search`` was discarded by the importance-only re-sort.
- Overview path (``get_context()``): weighted-sum score lifts recency from
  tie-break to multiplicative term, matching the v2.4 design at
  ``dec_01KQQPD6Y6B362T3K08368BDMP`` ("ordered by importance + centrality
  + recency"). Pre-v2.5.3 recency was a tuple tie-break only.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timezone
from rka.infra.database import Database
from rka.infra.llm import LLMClient
from rka.models.context import ContextPackage
from rka.services.search import SearchService

logger = logging.getLogger(__name__)

# Importance text → numeric rank for ORDER BY. Mirrors the journal.importance
# CHECK constraint in schema.sql.
_IMPORTANCE_CASE = """CASE j.importance
    WHEN 'critical' THEN 4
    WHEN 'high' THEN 3
    WHEN 'normal' THEN 2
    WHEN 'low' THEN 1
    WHEN 'archived' THEN 0
    ELSE 2
END"""

# ---------------------------------------------------------------------------
# v2.5.3 overview-path weighted-sum coefficients (dec_01KRSMMCS8MD7KQDBS0E2DVKBQ).
# Module-level constants so A/B coefficient tuning is a single-file edit.
# The weighted-sum applies ONLY to the overview path; the topic path uses
# search relevance as primary sort key.
#
# v2.5.4 (mis_01KRSP44W7BDZH11PZRGXH1WM4): coefficients are env-var-backed
# so the eval-v2 A/B sweep swaps configs via docker restart (no source
# rebuild per config). Read at module-import time. Tests that monkey-patch
# env vars must call `_reload_coefficients_from_env()` after the patch.
# ---------------------------------------------------------------------------

# Sweep coefficient defaults.
#
# History:
# - v2.5.3 hypothesis Config 1 (dec_01KRSMMCS8MD7KQDBS0E2DVKBQ): w_imp=0.5,
#   w_cent=0.3, w_recency=0.2.
# - v2.5.4 D2 5-config sweep (mis_01KRSP44W7BDZH11PZRGXH1WM4): same as
#   Config 1 retained (no winner improvement found).
# - Phase-3.1 T4 64-config sweep (mis_01KS3EB2671CDD4V9RZCMYCEH1; Brain
#   ratification of chk_01KS3K40N6JRHV118969RMBNF0): cfg11 winner =
#   N=1 / w_recency=0.15 / bundle_K=80. Recall improved +0.021 over v2.5.7
#   (0.801 → 0.822); ordering improved +0.040 above floor (0.363 → 0.403).
#   The 0.85 recall floor + 0.13 efficiency floor were NOT achievable via
#   parameter tuning — both have STRUCTURAL ceilings (recall 0.822,
#   efficiency 0.044) in the post-PR-#17 corpus + current candidate-
#   generation surface. Phase-3 chapter closes PARTIAL; recall + efficiency
#   deferred to Phase-3.2 (candidate-generation track, NOT coefficient
#   tuning).
_DEFAULT_W_IMPORTANCE = 0.5
_DEFAULT_W_CENTRALITY = 0.3
_DEFAULT_W_RECENCY = 0.15  # Phase-3.1 cfg11 winner (was 0.20 in v2.5.3 baseline)
# PI-source lift. Spec text references "0.05" but the v2.5.3 implementation
# preserves the pre-v2.5.3 +5/40 = +0.125 normalized magnitude. Keeping
# 0.125 here (matches existing test test_pi_source_lift_applied_within_band).
# Per mission assumption 7, PI lift is NOT part of the A/B sweep; the env
# var exists for operator flexibility only.
_DEFAULT_PI_SOURCE_LIFT_NORMALIZED = 0.125
# Phase-3.1 T4: recency decay shape parameter. score = 1 / (1 + days/N).
# Sweep across {1, 30, 90, 365} showed shape_N effect was within noise
# (<0.005 recall variance) — the recency-amplification mechanism is real
# but its magnitude is too small to bridge the structural floor gaps.
# cfg11 winner pins N=1 (the simplest shape; reproduces the pre-Phase-3.1
# Per-entry render cap. Previously read from the LLM client
# (`_evidence_block_limit`), which tied a purely local rendering decision
# to whether a language model happened to be configured. 400 was the
# fallback that applied whenever it was not.
_EVIDENCE_BLOCK_LIMIT = 400

# 1/(1+days) shape exactly). Operator override via RKA_CTX_RECENCY_SHAPE_N
# preserved for Phase-3.2 candidate-set experimentation.
_DEFAULT_RECENCY_SHAPE_N = 1.0


def _read_coeff(env_var: str, default: float) -> float:
    """Read a float coefficient from the env, falling back to `default`."""
    raw = os.getenv(env_var)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "Invalid float in %s=%r; falling back to default %s", env_var, raw, default
        )
        return default


def _reload_coefficients_from_env() -> None:
    """Test helper: refresh module-level coefficient constants from env.

    Production: env vars set at container startup; module imports happen
    once. Tests: ``monkeypatch.setenv(...)`` + this call to pick up the
    overrides. Sweep harness: docker restart between configs → fresh
    process → fresh module import → fresh constants (no need to call this).
    """
    global _W_IMPORTANCE, _W_CENTRALITY, _W_RECENCY, _PI_SOURCE_LIFT_NORMALIZED
    global _RECENCY_SHAPE_N
    _W_IMPORTANCE = _read_coeff("RKA_CTX_W_IMP", _DEFAULT_W_IMPORTANCE)
    _W_CENTRALITY = _read_coeff("RKA_CTX_W_CENT", _DEFAULT_W_CENTRALITY)
    _W_RECENCY = _read_coeff("RKA_CTX_W_RECENCY", _DEFAULT_W_RECENCY)
    _PI_SOURCE_LIFT_NORMALIZED = _read_coeff(
        "RKA_CTX_PI_LIFT", _DEFAULT_PI_SOURCE_LIFT_NORMALIZED
    )
    _RECENCY_SHAPE_N = _read_coeff(
        "RKA_CTX_RECENCY_SHAPE_N", _DEFAULT_RECENCY_SHAPE_N
    )


_W_IMPORTANCE: float = _read_coeff("RKA_CTX_W_IMP", _DEFAULT_W_IMPORTANCE)
_W_CENTRALITY: float = _read_coeff("RKA_CTX_W_CENT", _DEFAULT_W_CENTRALITY)
_W_RECENCY: float = _read_coeff("RKA_CTX_W_RECENCY", _DEFAULT_W_RECENCY)
_PI_SOURCE_LIFT_NORMALIZED: float = _read_coeff(
    "RKA_CTX_PI_LIFT", _DEFAULT_PI_SOURCE_LIFT_NORMALIZED
)
_RECENCY_SHAPE_N: float = _read_coeff(
    "RKA_CTX_RECENCY_SHAPE_N", _DEFAULT_RECENCY_SHAPE_N
)

def _compute_recency_score(days: float, shape_n: float) -> float:
    """Pure ``1 / (1 + days / shape_n)`` clamped to [0, 1].

    Phase-3.1 (mis_01KS3EB2671CDD4V9RZCMYCEH1 T1): generalizes the
    pre-Phase-3.1 ``1/(1+days)`` to ``1/(1+days/N)``. N=1 is the
    backward-compat default (bit-identical to the pre-refactor formula).
    Larger N produces slower decay (a 30-day-old entry scores 0.5 at N=30
    vs 0.032 at N=1; a 365-day-old entry scores 0.5 at N=365 vs 0.003 at
    N=1). Negative or zero ``shape_n`` raises ZeroDivisionError-equivalent
    behavior via a defensive fallback to N=1 — operators should set
    positive values; tests should pin the shape they're exercising.
    """
    if shape_n <= 0:
        # Defensive: a non-positive N would either divide-by-zero or invert
        # the decay direction. Treat as misconfiguration and reproduce the
        # backward-compat shape rather than crashing the engine.
        shape_n = 1.0
    days = max(0.0, days)
    score = 1.0 / (1.0 + days / shape_n)
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Bundle-truncation policy.
#
# v2.5.4 (D4 — mis_01KS0C8BKTHCA8GB38BGDR1PTQ): introduced post-rank-merge
# top-K truncation with anchor-aware-tool UNION protection, gated by an
# `anchor_aware_present` flag. Default K=30. Backward-compat path preserved
# v2.5.3 behavior (no truncation) when the flag was False.
#
# Phase-3.1 T2 (mis_01KS3EB2671CDD4V9RZCMYCEH1; per Brain ratification of
# chk_01KS3FZDX78FD89CVR4K6VYJFK Option B + K-placement refinement):
# truncation is now **always-on**. The post-rank-merge cap is the bundle's
# load-bearing efficiency lever — the v2.5.4-D4 conditional gating left
# un-anchored bundles at ~200 entities, structurally unable to clear the
# 0.13 efficiency floor. Empirical avg bundle size 173 (T0 baseline,
# jrn_01KS3GH21FPSJ0EKCZKX1EQZ4X). Default K bumped 30 → 50 (the corpus-
# refresh diagnosis estimated bundle ≈ 50 is needed to clear 0.13).
#
# The anchor-aware UNION protection is preserved: when `anchor_aware_ids`
# is provided by the caller (composed call sequence that exercised
# rka_get_ego_graph / rka_multi_hop_retrieval / rka_assemble_evidence),
# those entity IDs pass through the cap regardless of weighted-sum
# position. Critical-entity recall preserved.
#
# The `anchor_aware_present` parameter is retained for API/Pydantic
# backward-compat (so v2.5.4-D4 callers don't break), but it no longer
# gates truncation — the policy is post-rank-merge, unconditional.
# ---------------------------------------------------------------------------

_DEFAULT_BUNDLE_K: int = 80  # Phase-3.1 cfg11 winner (T2 was 50; v2.5.4-D4 was 30)


def _read_bundle_k() -> int:
    """Top-K cap for the anchor-aware-present truncation path.

    Sweep-friendly: `RKA_CTX_BUNDLE_K` env var overrides the default. Test
    discipline mirrors `_reload_coefficients_from_env`: monkeypatch the env
    var, then call this helper at the assertion site (no global state to
    reload because K is read per-call, not at module import).
    """
    raw = os.getenv("RKA_CTX_BUNDLE_K")
    if raw is None or raw == "":
        return _DEFAULT_BUNDLE_K
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "Invalid int in RKA_CTX_BUNDLE_K=%r; falling back to default %d",
            raw,
            _DEFAULT_BUNDLE_K,
        )
        return _DEFAULT_BUNDLE_K

# Importance band normalized to [0, 1]. Mirrors _sort_key's importance map
# divided by the critical=4 ceiling.
_IMPORTANCE_BAND_NORMALIZED: dict[str, float] = {
    "critical": 1.0,
    "high": 0.75,
    "normal": 0.5,
    "low": 0.25,
    "archived": 0.0,
}


class ContextEngine:
    """Prepares importance-ranked context packages.

    Ranking signal (deterministic, SQL-time):
      1. journal.importance (critical=4 → archived=0); other entity types
         do not have an importance column and use a baseline of 2 ('normal').
      2. entity_links centrality — sum of inbound + outbound edge degree
         for the entity. High-centrality nodes surface first within a band.
      3. created_at DESC as a tie-breaker; newer entries win ties.
    """

    def __init__(
        self,
        db: Database,
        search: SearchService,
        llm: LLMClient | None = None,
    ):
        self.db = db
        self.search = search
        self.llm = llm

    async def get_context(
        self,
        topic: str | None = None,
        phase: str | None = None,
        project_id: str = "proj_default",
        anchor_aware_present: bool = False,
        anchor_aware_ids: list[str] | None = None,
    ) -> ContextPackage:
        """Build a ranked context package.

        Args:
            topic: Optional search query. If provided, candidates are seeded by
                hybrid search and then re-ranked by importance + centrality.
            phase: Optional phase filter for the overview path. If both `topic`
                and `phase` are None, falls through to the recent-with-importance
                overview.
            project_id: Project scope. Defaults to 'proj_default'; callers
                normally inject from the API request.
            anchor_aware_present: v2.5.4 (D4) signal that anchor-aware
                tools fired in the composed call sequence. **No longer gates
                truncation as of Phase-3.1 T2** — the post-rank-merge
                bundle_K cap is now unconditional. Parameter retained for
                API backward-compat; v2.5.4-D4 callers continue to pass it
                without effect.
            anchor_aware_ids: When provided, entities with matching ``id``
                pass through the top-K cap regardless of weighted-sum
                position (UNION protection). Typically populated by the
                caller from the composed call sequence's anchor-aware-tool
                outputs (rka_get_ego_graph / rka_multi_hop_retrieval /
                rka_assemble_evidence). Independent of
                ``anchor_aware_present`` after Phase-3.1 T2.

        Returns a ContextPackage with `entries` populated (legacy bucket fields
        left empty).
        """
        if topic:
            hits = await self.search.with_project(project_id).search(topic, limit=50)
            candidates = await self._hydrate_hits(hits, project_id=project_id)
            # Preserve search relevance order as the primary sort signal
            # before centrality re-annotation. Lower rank = more relevant.
            for i, c in enumerate(candidates):
                c["_search_rank"] = i
            candidates = await self._rerank_by_importance_and_centrality(
                candidates, project_id=project_id
            )
        else:
            candidates = await self._get_overview_candidates(phase, project_id=project_id)

        current_phase = phase or await self._get_current_phase(project_id=project_id)

        package = ContextPackage(topic=topic, phase=current_phase)

        # Render the ranked list. v2.5.3 splits the sort by retrieval path:
        # topic-driven queries preserve search relevance (BM25/vector ranking);
        # overview queries use a weighted-sum that lifts recency from
        # tie-break to multiplicative term. PI-sourced entries get a small
        # lift within their importance band on either path.
        pinned_ids: set[str] = set()
        if topic:
            candidates.sort(key=self._topic_sort_key)
        else:
            candidates.sort(key=self._overview_score, reverse=True)
            # Pinned tier (eval-v3, 2026-06-11): on a live 185-entity corpus
            # the weighted-sum buried two PI-critical directives at bundle
            # positions #58/#60 — the v2.5.4 coefficient sweep already showed
            # weights are not the lever, composition policy is. Entries that
            # are pinned, critical-importance, or PI directives are lifted to
            # the FRONT of the bundle (score order preserved within the tier)
            # and are exempt from the top-K cap below.
            pinned = [e for e in candidates if self._is_pinned_entry(e)]
            if pinned:
                pinned_ids = {e["id"] for e in pinned}
                candidates = pinned + [
                    e for e in candidates if e["id"] not in pinned_ids
                ]

        # Phase-3.1 T2 (post-rank-merge, always-on): cap the bundle to
        # top-K by weighted-sum / search-relevance score. Entities surfaced
        # by anchor-aware tools (passed via ``anchor_aware_ids``) UNION
        # through the cap so the anchor-aware path's targeted retrieval is
        # preserved regardless of K — and so does the pinned tier. The
        # v2.5.4-D4 ``anchor_aware_present`` gating has been removed — the
        # policy is unconditional because the un-anchored backward-compat
        # path left the efficiency floor structurally unreachable
        # (corpus-refresh diagnosis).
        k = _read_bundle_k()
        head = candidates[:k]
        head_ids = {e["id"] for e in head}
        extras: list[dict] = []
        requested_anchor_ids = list(dict.fromkeys(anchor_aware_ids or ()))
        union_ids = set(requested_anchor_ids) | pinned_ids
        if union_ids:
            for entry in candidates[k:]:
                if entry["id"] in union_ids and entry["id"] not in head_ids:
                    extras.append(entry)
                    head_ids.add(entry["id"])

        # Anchor-aware tools may surface an entity outside the overview/search
        # candidate window (for example, the journal overview query is capped
        # at 50 rows).  The public contract says those explicit IDs survive the
        # bundle cap, so hydrate any still-missing IDs directly.  The lookup is
        # project-scoped: a foreign-project ID is ignored rather than leaked.
        missing_anchor_ids = [
            entity_id
            for entity_id in requested_anchor_ids
            if entity_id not in head_ids
        ]
        if missing_anchor_ids:
            direct_extras = await self._hydrate_context_ids(
                missing_anchor_ids,
                project_id=project_id,
            )
            for entry in direct_extras:
                if entry["id"] not in head_ids:
                    extras.append(entry)
                    head_ids.add(entry["id"])
        candidates = head + extras
        truncated_to_k = k

        rendered = [self._render_entry(entry) for entry in candidates]
        package.entries = rendered
        package.sources = [e["id"] for e in candidates]

        if topic:
            package.note = (
                "Topic-anchored context: ordered by search relevance "
                "(BM25/vector); importance/centrality break ties within rank. "
                "No token-budget truncation (v2.4 / dec_01KQQPD6Y6B362T3K08368BDMP; "
                "v2.5.3 / dec_01KRSMMCS8MD7KQDBS0E2DVKBQ)."
            )
        else:
            anchor_note = (
                f" + UNION with {len(extras)} anchor-aware-tool extras"
                if extras
                else ""
            )
            package.note = (
                f"Importance-ranked context: weighted-sum of "
                f"journal.importance, entity_links centrality, and recency "
                f"(N={_RECENCY_SHAPE_N:g} decay shape). Bundle capped at top-"
                f"{truncated_to_k} entities (Phase-3.1 T2 post-rank-merge "
                f"truncation per dec_01KS3E6ZJXXV7542QPWZ9W8BQS){anchor_note}; "
                f"anchor_aware_ids preserved via UNION regardless of K. "
                "No token-budget truncation "
                "(v2.4 / dec_01KQQPD6Y6B362T3K08368BDMP)."
            )
        # Informational; no longer drives truncation.
        package.token_estimate = sum(self._estimate_tokens(t) for t in rendered)
        return package

    @staticmethod
    def _is_pinned_entry(entry: dict) -> bool:
        """Overview-path pinned-tier membership.

        Two signals only: the explicit ``pinned`` flag, and PI directives
        (instructions, not findings — eval-v3 found two critical PI
        directives buried at bundle positions #58/#60). Bare
        ``importance='critical'`` is deliberately NOT in the tier:
        dec_01KRSMMCS8MD7KQDBS0E2DVKBQ ratified that critical *findings*
        compete through the weighted-sum (strict critical-dominance was
        the pre-v2.5.3 bug), and only journal rows carry these columns —
        ``.get`` keeps decisions/literature/missions out of the tier.
        """
        if entry.get("pinned"):
            return True
        return entry.get("source") == "pi" and entry.get("type") == "directive"

    @staticmethod
    def _importance_band_normalized(entry: dict) -> float:
        """Normalized importance ∈ [0, 1.125] (1.0 critical + 0.125 PI lift).

        Used by the overview-path weighted-sum. The PI-source lift preserves
        the pre-v2.5.3 +5/40 = +0.125 magnitude (dec_01KRSMMCS8MD7KQDBS0E2DVKBQ).
        """
        imp = _IMPORTANCE_BAND_NORMALIZED.get(
            entry.get("importance") or "normal", 0.5
        )
        if entry.get("source") == "pi":
            imp += _PI_SOURCE_LIFT_NORMALIZED
        return imp

    @staticmethod
    def _recency_score(entry: dict) -> float:
        """``_compute_recency_score(days_since_created, _RECENCY_SHAPE_N)``.

        Parses the entry's ``created_at`` timestamp, derives days-since,
        and delegates to the pure helper. Backward-compat at N=1 reproduces
        the pre-Phase-3.1 ``1/(1+days)`` shape bit-for-bit.
        """
        raw = entry.get("created_at") or ""
        if not raw:
            return 0.0
        try:
            # SQLite default format: 'YYYY-MM-DDTHH:MM:SSZ'.
            ts = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return 0.0
        delta = (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
        # Future-dated rows (clock skew, fixtures) clamp to "today".
        days = max(0.0, delta)
        return _compute_recency_score(days, _RECENCY_SHAPE_N)

    @classmethod
    def _overview_score(cls, entry: dict) -> float:
        """Weighted-sum score for the overview path (no topic).

        score = _W_IMPORTANCE * importance_band_normalized
              + _W_CENTRALITY * log1p(centrality_degree)
              + _W_RECENCY    * recency_score

        Sort DESC (higher = first). Module-level constants make A/B
        coefficient tuning a single-file edit.
        """
        imp = cls._importance_band_normalized(entry)
        centrality = float(entry.get("centrality_degree") or 0)
        recency = cls._recency_score(entry)
        return (
            _W_IMPORTANCE * imp
            + _W_CENTRALITY * math.log1p(centrality)
            + _W_RECENCY * recency
        )

    @classmethod
    def _topic_sort_key(cls, entry: dict) -> tuple[int, float, float]:
        """Topic-path sort key. Sort ASC (no reverse=True).

        Primary: ``_search_rank`` (lower = more relevant, rank 0 = best hit).
        Tie-breaks (within identical search rank, which essentially never
        happens because BM25/vector hits have distinct positions): importance
        band DESC, then centrality DESC. Negate DESC terms so the tuple
        sorts cleanly ascending.

        Entries lacking ``_search_rank`` (defensive; shouldn't happen on the
        topic path) sort last via a large sentinel rank.
        """
        rank = entry.get("_search_rank")
        rank_int = int(rank) if rank is not None else 10**9
        imp = cls._importance_band_normalized(entry)
        centrality = float(entry.get("centrality_degree") or 0)
        return (rank_int, -imp, -centrality)

    async def _rerank_by_importance_and_centrality(
        self, candidates: list[dict], project_id: str
    ) -> list[dict]:
        """Annotate candidates with centrality_degree from entity_links."""
        if not candidates:
            return candidates
        ids = [c["id"] for c in candidates]
        placeholders = ",".join("?" for _ in ids)
        rows = await self.db.fetchall(
            f"""SELECT id, SUM(degree) AS centrality_degree FROM (
                    SELECT source_id AS id, COUNT(*) AS degree FROM entity_links
                    WHERE project_id = ? AND source_id IN ({placeholders})
                    GROUP BY source_id
                  UNION ALL
                    SELECT target_id AS id, COUNT(*) AS degree FROM entity_links
                    WHERE project_id = ? AND target_id IN ({placeholders})
                    GROUP BY target_id
                ) GROUP BY id""",
            [project_id, *ids, project_id, *ids],
        )
        degree_map = {r["id"]: int(r["centrality_degree"]) for r in rows}
        for c in candidates:
            c["centrality_degree"] = degree_map.get(c["id"], 0)
        return candidates

    async def _hydrate_hits(self, hits, project_id: str = "proj_default") -> list[dict]:
        """Convert search hits to full entity dicts.

        Defect 1 (mis_01KR1Z28QW9WYXG4VV8PGYWD8G T4): pre-v2.3.4 the table_map
        omitted claim and cluster, so v2.3.3's multi-hop retrieval primitive
        returned claim/cluster nodes that ContextEngine then silently dropped.
        Extension is symmetric with the existing render path: SELECT * gated
        on (id, project_id) plus an entity_type annotation.
        """
        table_map = {
            "journal": "journal",
            "decision": "decisions",
            "literature": "literature",
            "mission": "missions",
            "claim": "claims",
            "cluster": "evidence_clusters",
        }
        results = []
        for hit in hits:
            table = table_map.get(hit.entity_type)
            if not table:
                continue
            row = await self.db.fetchone(
                f"SELECT * FROM {table} WHERE id = ? AND project_id = ?",
                [hit.entity_id, project_id],
            )
            if row:
                row["entity_type"] = hit.entity_type
                results.append(row)
        return results

    async def _hydrate_context_ids(
        self,
        entity_ids: list[str],
        *,
        project_id: str,
    ) -> list[dict]:
        """Hydrate explicit context IDs in caller order and project scope."""
        prefix_map = {
            "jrn_": ("journal", "journal"),
            "dec_": ("decision", "decisions"),
            "lit_": ("literature", "literature"),
            "mis_": ("mission", "missions"),
            "clm_": ("claim", "claims"),
            "clu_": ("cluster", "evidence_clusters"),
        }
        results: list[dict] = []
        for entity_id in entity_ids:
            mapping = next(
                (
                    entity_mapping
                    for prefix, entity_mapping in prefix_map.items()
                    if entity_id.startswith(prefix)
                ),
                None,
            )
            if mapping is None:
                continue
            entity_type, table = mapping
            row = await self.db.fetchone(
                f"SELECT * FROM {table} WHERE id = ? AND project_id = ?",
                [entity_id, project_id],
            )
            if row:
                row["entity_type"] = entity_type
                results.append(row)
        return results

    async def _get_overview_candidates(
        self,
        phase: str | None = None,
        project_id: str = "proj_default",
    ) -> list[dict]:
        """Get importance-ranked overview candidates when no topic is specified.

        Pulls from journal (importance-aware ORDER BY), decisions (active),
        literature (in-progress states), and missions (active/pending). The
        per-entity-type LIMITs are upper bounds; the final ranker re-orders
        across types so the top of the result list is the highest-importance
        regardless of source table.
        """
        candidates: list[dict] = []
        phase_filter = "AND phase = ?" if phase else ""

        # Journal: ORDER BY importance, then created_at — uses idx_journal_importance.
        params: list = [project_id]
        if phase:
            params.append(phase)
        params.append(50)
        rows = await self.db.fetchall(
            f"""SELECT *, 'journal' AS entity_type, {_IMPORTANCE_CASE} AS imp_rank
                FROM journal j
                WHERE project_id = ? AND confidence != 'superseded' {phase_filter}
                ORDER BY imp_rank DESC, created_at DESC LIMIT ?""",
            params,
        )
        candidates.extend(rows)

        # Pinned-tier candidates are fetched UNCONDITIONALLY — the
        # importance/recency-ordered LIMIT above drops older
        # normal-importance PI directives from the pool entirely, so the
        # pinned-tier lift in get_context never sees them (eval-v3 live
        # probe: 3 of 15 PI directives reached the pool). Dedup against the
        # main query happens via the seen-id filter below.
        seen_ids = {r["id"] for r in rows}
        pinned_rows = await self.db.fetchall(
            f"""SELECT *, 'journal' AS entity_type, {_IMPORTANCE_CASE} AS imp_rank
                FROM journal j
                WHERE project_id = ? AND confidence != 'superseded'
                  AND (pinned = 1 OR (source = 'pi' AND type = 'directive'))
                ORDER BY imp_rank DESC, created_at DESC LIMIT 30""",
            [project_id],
        )
        candidates.extend(r for r in pinned_rows if r["id"] not in seen_ids)

        # Decisions: active, ranked by recency.
        params2: list = [project_id]
        if phase:
            params2.append(phase)
        params2.append(30)
        rows = await self.db.fetchall(
            f"""SELECT *, 'decision' AS entity_type FROM decisions
                WHERE project_id = ? AND status = 'active' {phase_filter}
                ORDER BY created_at DESC LIMIT ?""",
            params2,
        )
        candidates.extend(rows)

        # Literature: status filter, recency.
        rows = await self.db.fetchall(
            """SELECT *, 'literature' AS entity_type FROM literature
                WHERE project_id = ? AND status IN ('to_read', 'reading', 'read')
                ORDER BY created_at DESC LIMIT ?""",
            [project_id, 20],
        )
        candidates.extend(rows)

        # Missions: active/pending, recency.
        params3: list = [project_id]
        if phase:
            params3.append(phase)
        params3.append(15)
        rows = await self.db.fetchall(
            f"""SELECT *, 'mission' AS entity_type FROM missions
                WHERE project_id = ? AND status IN ('active', 'pending') {phase_filter}
                ORDER BY created_at DESC LIMIT ?""",
            params3,
        )
        candidates.extend(rows)

        # Annotate with centrality so the cross-type ranker can use it.
        return await self._rerank_by_importance_and_centrality(candidates, project_id=project_id)

    async def _get_current_phase(self, project_id: str = "proj_default") -> str | None:
        """Get the current project phase."""
        row = await self.db.fetchone(
            "SELECT current_phase FROM project_states WHERE project_id = ?",
            [project_id],
        )
        if row is None and project_id == "proj_default":
            row = await self.db.fetchone("SELECT current_phase FROM project_state LIMIT 1")
        return row["current_phase"] if row else None

    def _render_entry(self, entry: dict, max_len: int | None = None) -> str:
        """Render an entry as a concise text block.

        `max_len` defaults to the LLM's per-evidence-block hint when an LLM is
        configured (~400 chars), else 400. This is a per-entry display cap, not
        a context-engine token budget.
        """
        if max_len is None:
            max_len = _EVIDENCE_BLOCK_LIMIT
        etype = entry.get("entity_type", "unknown")
        eid = entry.get("id", "?")

        if etype == "journal":
            pi_tag = " [PI]" if entry.get("source") == "pi" else ""
            verbatim = entry.get("verbatim_input")
            verbatim_line = f"\n  PI said: \"{verbatim[:200]}\"" if verbatim else ""
            return (
                f"[{entry.get('type', 'note')}|{entry.get('confidence', '?')}|"
                f"{entry.get('importance', 'normal')}]{pi_tag} {eid}: "
                f"{(entry.get('content') or '')[:max_len]}{verbatim_line}"
            )
        elif etype == "decision":
            chosen = f" → {entry['chosen']}" if entry.get("chosen") else ""
            return f"[decision|{entry.get('status', '?')}] {eid}: {(entry.get('question') or '')[:max_len]}{chosen}"
        elif etype == "literature":
            return f"[lit|{entry.get('status', '?')}] {eid}: {(entry.get('title') or '')[:max_len]}"
        elif etype == "mission":
            return f"[mission|{entry.get('status', '?')}] {eid}: {(entry.get('objective') or '')[:max_len]}"
        elif etype == "cluster":
            # Affordance B (Mission B): apply STALE prefix when cluster is
            # flagged needs_reprocessing. Single helper, four call sites.
            from rka.services.rendering import with_staleness_prefix
            label = entry.get("label") or "?"
            synthesis = (entry.get("synthesis") or "")[:max_len]
            decorated = with_staleness_prefix(synthesis, entry.get("needs_reprocessing"))
            return f"[cluster|{entry.get('confidence', '?')}] {eid} ({label}): {decorated or ''}"
        else:
            return f"[{etype}] {eid}: {str(entry)[:max_len]}"

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimation: ~4 chars per token. Used only for the
        informational `token_estimate` field on ContextPackage; no longer
        drives truncation."""
        return max(1, len(text) // 4)
