"""KB-wide verification service (eval-v3 themes B/C, 2026-06-12).

Four read-mostly capabilities that turn the provenance graph's structural
claims into *checked* ones:

  - link-support audit: a provenance link existing is not the same as the
    dependent's content being supported by the linked evidence ("citation
    present" diverges from "citation supports" ~50% of the time even for
    frontier models). Lexical Phase-1; NLI entailment is the documented
    Phase-2 upgrade (same split as the Writer's verify_provenance).
  - staleness review filing: walks every stale root (superseded/retracted)
    through GraphService.staleness_impact and files review_queue rows for
    direct dependents, so overturned knowledge surfaces instead of waiting
    to be noticed.
  - mission guard: negative knowledge for Executor mission pickup — the
    retracted/superseded/contradicted entities lexically relevant to a
    mission's objective (the Vending-Bench repeated-mistake failure mode:
    re-running an approach that was already falsified).
  - belief-as-of: reconstructs the knowledge state at a past date from
    created_at + supersession chains ("what did we believe in March, and
    what changed since?"). Supersession transition times are exact (the
    successor's created_at); retraction times are approximated by
    updated_at and marked as such.
"""

from __future__ import annotations

import json
import re
from typing import Any

from rka.infra.ids import generate_id
from rka.services.base import BaseService
from rka.services.graph import GraphService

_STOPWORDS = frozenset(
    "a an the and or of to in on at for with about from into over is are was were "
    "be been being do does did have has had can could should would will may might "
    "must this that these those it its they them their there we our as by not no "
    "than then so such also more most some any each per via using used use".split()
)

# Lexical-support calibration (mirrors the Writer's verify_provenance:
# advisory near-zero threshold + a scorability floor so thin evidence
# does not fire false positives).
_MIN_SCORABLE_TOKENS = 12
_LOW_SUPPORT_THRESHOLD = 0.08


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
            if t not in _STOPWORDS and len(t) > 2}


def _support(claim_text: str, evidence_text: str):
    """(score, scorable) — fraction of claim tokens present in evidence."""
    ct = _tokens(claim_text)
    et = _tokens(evidence_text)
    if not ct:
        return 1.0, False
    if len(et) < _MIN_SCORABLE_TOKENS:
        return None, False
    return len(ct & et) / len(ct), True


class VerificationService(BaseService):
    """Cross-entity verification reads + review-queue filing."""

    # ------------------------------------------------------------------
    # B1 — link-support audit
    # ------------------------------------------------------------------

    async def audit_link_support(self, *, limit: int = 200) -> dict[str, Any]:
        """Audit content-level support behind provenance links.

        Pairs checked (lexical Phase-1, advisory):
          decision.rationale  vs union of its justified_by journal content
          cluster.synthesis   vs union of its member claims' content

        Returns unsupported pairs; does NOT file review items (see
        file_unsupported_link_reviews for the write path).
        """
        pid = self.project_id
        findings: list[dict] = []

        # Decisions: rationale supported by linked evidence?
        dec_rows = await self.db.fetchall(
            """SELECT d.id, d.question, d.rationale FROM decisions d
               WHERE d.project_id = ? AND d.status = 'active'
                 AND d.rationale IS NOT NULL AND length(d.rationale) > 40
               ORDER BY d.created_at DESC LIMIT ?""",
            [pid, limit],
        )
        for d in dec_rows:
            ev_rows = await self.db.fetchall(
                """SELECT j.content FROM entity_links el
                   JOIN journal j ON j.id = el.target_id
                   WHERE el.project_id = ? AND el.source_id = ?
                     AND el.link_type = 'justified_by'""",
                [pid, d["id"]],
            )
            if not ev_rows:
                continue  # link-PRESENCE gaps are the maintenance manifest's job
            evidence = " ".join(r["content"] or "" for r in ev_rows)
            score, scorable = _support(d["rationale"], evidence)
            if scorable and score < _LOW_SUPPORT_THRESHOLD:
                findings.append({
                    "item_type": "decision", "item_id": d["id"],
                    "label": (d["question"] or "")[:100],
                    "support": round(score, 2),
                    "detail": "rationale shares almost no content with its justified_by evidence",
                })

        # Clusters: synthesis supported by member claims?
        cl_rows = await self.db.fetchall(
            """SELECT ec.id, ec.label, ec.synthesis FROM evidence_clusters ec
               WHERE ec.project_id = ? AND ec.synthesis IS NOT NULL
                 AND length(ec.synthesis) > 40
               ORDER BY ec.created_at DESC LIMIT ?""",
            [pid, limit],
        )
        for c in cl_rows:
            member_rows = await self.db.fetchall(
                """SELECT cl.content FROM claim_edges ce
                   JOIN claims cl ON cl.id = ce.source_claim_id
                   WHERE ce.project_id = ? AND ce.cluster_id = ?
                     AND ce.relation = 'member_of'""",
                [pid, c["id"]],
            )
            if not member_rows:
                continue
            evidence = " ".join(r["content"] or "" for r in member_rows)
            score, scorable = _support(c["synthesis"], evidence)
            if scorable and score < _LOW_SUPPORT_THRESHOLD:
                findings.append({
                    "item_type": "cluster", "item_id": c["id"],
                    "label": (c["label"] or "")[:100],
                    "support": round(score, 2),
                    "detail": "synthesis shares almost no content with its member claims",
                })

        return {
            "checked_decisions": len(dec_rows),
            "checked_clusters": len(cl_rows),
            "unsupported": findings,
            "method": "lexical-phase1 (NLI entailment is the Phase-2 upgrade)",
        }

    # ------------------------------------------------------------------
    # B2/B3 — staleness review filing
    # ------------------------------------------------------------------

    async def file_staleness_reviews(self, *, max_depth: int = 1) -> dict[str, Any]:
        """File review_queue rows for entities resting on stale knowledge.

        Walks every stale root (superseded/abandoned decisions, superseded/
        retracted journal entries) through GraphService.staleness_impact and
        files a 'stale_dependency' review item per impacted entity. Idempotent:
        skips (item_id, flag) pairs that already have a pending row.
        """
        pid = self.project_id
        graph = GraphService(self.db)

        roots: list[str] = []
        for sql in (
            "SELECT id FROM decisions WHERE project_id = ? AND status IN ('superseded','abandoned')",
            "SELECT id FROM journal WHERE project_id = ? AND confidence IN ('superseded','retracted')",
        ):
            roots.extend(r["id"] for r in await self.db.fetchall(sql, [pid]))

        existing = {
            (r["item_id"], r["flag"])
            for r in await self.db.fetchall(
                "SELECT item_id, flag FROM review_queue "
                "WHERE project_id = ? AND status = 'pending'",
                [pid],
            )
        }

        filed: list[dict] = []
        for root in roots:
            impact = await graph.staleness_impact(root, max_depth=max_depth, project_id=pid)
            for node in impact["impacted"]:
                # The successor in a supersede chain is not "resting on" the
                # stale root; skip nodes that are themselves stale roots too.
                if node["id"] in roots:
                    continue
                key = (node["id"], "stale_dependency")
                if key in existing:
                    continue
                existing.add(key)
                review_id = generate_id("review")
                context = json.dumps({
                    "stale_root": root,
                    "root_status": impact["root_status"],
                    "via": node["via"],
                    "depth": node["depth"],
                })
                await self.db.execute(
                    """INSERT INTO review_queue
                       (id, item_type, item_id, flag, context, priority, raised_by, project_id)
                       VALUES (?, ?, ?, 'stale_dependency', ?, 40, 'system', ?)""",
                    [review_id, node["type"], node["id"], context, pid],
                )
                filed.append({"review_id": review_id, "item_id": node["id"],
                              "stale_root": root})
        await self.db.commit()
        if filed:
            await self.audit("create", "review", filed[0]["review_id"], "system",
                             {"filed": len(filed), "kind": "stale_dependency"})
        return {"stale_roots": len(roots), "filed": len(filed), "items": filed}

    # ------------------------------------------------------------------
    # A4 — mission pickup guard (negative knowledge)
    # ------------------------------------------------------------------

    async def mission_guard(self, mission_id: str) -> dict[str, Any]:
        """Negative knowledge relevant to a mission, for Executor pickup.

        Surfaces (a) retracted/superseded journal entries and (b) claims on
        either side of an unresolved contradicts edge whose content overlaps
        the mission's objective+context tokens. The Executor reads this as
        'approaches already falsified or contested; do not repeat them
        unknowingly'.
        """
        pid = self.project_id
        mission = await self.db.fetchone(
            "SELECT objective, context FROM missions WHERE id = ? AND project_id = ?",
            [mission_id, pid],
        )
        if mission is None:
            raise ValueError(f"Mission {mission_id} not found")
        probe = _tokens((mission["objective"] or "") + " " + (mission["context"] or ""))

        def _relevance(text: str) -> float:
            t = _tokens(text)
            if not t or not probe:
                return 0.0
            return len(t & probe) / min(len(t), len(probe))

        warnings: list[dict] = []

        rows = await self.db.fetchall(
            """SELECT id, content, confidence, superseded_by FROM journal
               WHERE project_id = ? AND confidence IN ('retracted', 'superseded')""",
            [pid],
        )
        for r in rows:
            rel = _relevance(r["content"] or "")
            if rel >= 0.15:
                warnings.append({
                    "id": r["id"], "kind": r["confidence"],
                    "relevance": round(rel, 2),
                    "superseded_by": r["superseded_by"],
                    "excerpt": (r["content"] or "")[:200],
                    "guidance": ("do not assert; see successor" if r["superseded_by"]
                                 else "retracted; do not rely on this finding"),
                })

        ce_rows = await self.db.fetchall(
            """SELECT ce.source_claim_id, ce.target_claim_id,
                      c1.content AS source_content, c2.content AS target_content
               FROM claim_edges ce
               JOIN claims c1 ON c1.id = ce.source_claim_id
               JOIN claims c2 ON c2.id = ce.target_claim_id
               WHERE ce.project_id = ? AND ce.relation = 'contradicts'""",
            [pid],
        )
        for r in ce_rows:
            rel = max(_relevance(r["source_content"] or ""),
                      _relevance(r["target_content"] or ""))
            if rel >= 0.15:
                warnings.append({
                    "id": r["source_claim_id"], "kind": "contradicted",
                    "relevance": round(rel, 2),
                    "contradicts": r["target_claim_id"],
                    "excerpt": (r["source_content"] or "")[:200],
                    "guidance": "unresolved contradiction; verify before relying on either side",
                })

        warnings.sort(key=lambda w: w["relevance"], reverse=True)
        return {"mission_id": mission_id, "warnings": warnings[:20],
                "checked": {"stale_journal": len(rows), "contradictions": len(ce_rows)}}

    # ------------------------------------------------------------------
    # C1 — belief-as-of (temporal reconstruction)
    # ------------------------------------------------------------------

    async def belief_as_of(self, date: str) -> dict[str, Any]:
        """Reconstruct the believed-current decisions and journal at `date`.

        An entity was believed-current at T iff created_at <= T and its
        successor (superseded_by row) either does not exist or was created
        AFTER T. Supersession transition times are therefore exact; the
        retraction transition has no stored timestamp, so retracted entries
        use updated_at as an approximation and carry approximate=true.

        Returns {as_of, then_current: {...}, changed_since: [...]}: what was
        believed then, and which of those beliefs have since been overturned.
        """
        pid = self.project_id
        then_decisions: list[dict] = []
        changed: list[dict] = []

        rows = await self.db.fetchall(
            """SELECT d.id, d.question, d.chosen, d.status, d.superseded_by, d.created_at,
                      s.created_at AS successor_created
               FROM decisions d
               LEFT JOIN decisions s ON s.id = d.superseded_by
               WHERE d.project_id = ? AND d.created_at <= ?
               ORDER BY d.created_at""",
            [pid, date],
        )
        for r in rows:
            overturned_later = bool(
                r["successor_created"] and r["successor_created"] > date
            ) or (r["status"] == "abandoned")
            current_then = (
                r["superseded_by"] is None and r["status"] == "active"
            ) or bool(r["successor_created"] and r["successor_created"] > date)
            if current_then:
                entry = {"id": r["id"], "question": (r["question"] or "")[:120],
                         "chosen": (r["chosen"] or "")[:120]}
                then_decisions.append(entry)
                if overturned_later or r["superseded_by"]:
                    if r["successor_created"] and r["successor_created"] > date:
                        changed.append({
                            "id": r["id"], "type": "decision",
                            "was": (r["chosen"] or "")[:120],
                            "changed_at": r["successor_created"],
                            "superseded_by": r["superseded_by"],
                        })

        then_journal: list[dict] = []
        j_rows = await self.db.fetchall(
            """SELECT j.id, j.content, j.confidence, j.superseded_by, j.created_at,
                      j.updated_at, s.created_at AS successor_created
               FROM journal j
               LEFT JOIN journal s ON s.id = j.superseded_by
               WHERE j.project_id = ? AND j.created_at <= ?
               ORDER BY j.created_at""",
            [pid, date],
        )
        for r in j_rows:
            superseded_by_then = bool(
                r["superseded_by"] and r["successor_created"]
                and r["successor_created"] <= date
            )
            retracted_now = r["confidence"] == "retracted"
            # Approximation: a retraction is assumed to have happened at
            # updated_at; if updated_at <= date, treat as already retracted.
            retracted_then = retracted_now and (r["updated_at"] or "") <= date
            if superseded_by_then or retracted_then:
                continue
            entry = {"id": r["id"], "excerpt": (r["content"] or "")[:120],
                     "confidence_now": r["confidence"]}
            if retracted_now and not retracted_then:
                entry["approximate"] = True
                changed.append({
                    "id": r["id"], "type": "journal", "was": (r["content"] or "")[:120],
                    "changed_at": r["updated_at"], "change": "retracted",
                    "approximate": True,
                })
            elif r["superseded_by"] and r["successor_created"] and r["successor_created"] > date:
                changed.append({
                    "id": r["id"], "type": "journal", "was": (r["content"] or "")[:120],
                    "changed_at": r["successor_created"],
                    "superseded_by": r["superseded_by"],
                })
            then_journal.append(entry)

        return {
            "as_of": date,
            "then_current": {
                "decisions": then_decisions,
                "journal_count": len(then_journal),
                "journal": then_journal[:100],
            },
            "changed_since": sorted(changed, key=lambda c: c.get("changed_at") or ""),
            "note": ("supersession transitions are exact (successor created_at); "
                     "retraction transitions are approximated by updated_at"),
        }
