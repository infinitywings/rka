"""Eval-v2 runner — composed-context coverage execution.

Mission `mis_01KRPF3DERZS2W5VFDYE9E9GKM` Task T3.

For each scenario in the corpus, this runner invokes the composed call
sequence (per the scenario's ``tools_invoked`` field) against a running
RKA REST API, captures the returned entity IDs in tool order, and
serializes the result bundle to
``eval-harness/v2/results/raw/<scenario_id>.jsonl``.

The runner is REST-direct: it hits the same `/api/*` endpoints the MCP
tools themselves call. This keeps the runner hermetic to one HTTP layer
(no stdio MCP subprocess) and easier to mock at test time.

Usage:

    python -m eval-harness.v2.runner \\
        --corpus eval-harness/v2/corpus/scenarios.jsonl \\
        --rka-url http://localhost:9712 \\
        --output-dir eval-harness/v2/results/raw \\
        --project-id prj_01KKQM9JFG67GT5FGWTAHD9YE4

Sister-uncertainties from the T2 gate (per Brain directive: probe with
checkpoint-on-divergence, don't hold):

  - Tag-anchored journal retrieval (S14, S15)
  - rka_assemble_evidence shape (S9, S10)
  - cluster ego_graph shape (S7, S8, S9, S10)

The runner logs a structured ``ProbeDivergence`` record for any
unexpected response shape; the caller decides whether to surface it as
a checkpoint or accept and continue. Per Brain directive, the default
is "accept and continue with a logged divergence."
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entity-id extraction
# ---------------------------------------------------------------------------

# Matches any rka entity id with one of the canonical prefixes.
_ENTITY_ID_RX = re.compile(
    r"\b(jrn_|dec_|mis_|clm_|ecl_|lit_|chk_)[A-Za-z0-9_-]{16,32}\b"
)


def walk_for_entity_ids(payload: Any) -> list[str]:
    """Recursively walk a JSON payload and yield every entity id found,
    preserving discovery order (depth-first, dict-key-order preserving).

    Returns the de-duplicated list, where the first occurrence wins.
    """
    seen: dict[str, None] = {}

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)
        elif isinstance(node, str):
            for match in _ENTITY_ID_RX.finditer(node):
                eid = match.group(0)
                if eid not in seen:
                    seen[eid] = None

    _walk(payload)
    return list(seen.keys())


# ---------------------------------------------------------------------------
# Tool dispatch + REST mapping
# ---------------------------------------------------------------------------


@dataclass
class ToolInvocation:
    """One tool's contribution to the per-scenario bundle."""

    tool: str
    path: str  # REST endpoint
    status_code: int
    entity_ids: list[str]  # ordered, deduped
    divergence: str | None = None  # populated on sister-uncertainty probe failures
    notes: str = ""


@dataclass
class ScenarioBundle:
    scenario_id: str
    actor: str
    invocations: list[ToolInvocation] = field(default_factory=list)
    # combined_ranking: deduped + ordered across tools in the order they
    # appear in `invocations` (preserves first-discovery per entity)
    combined_ranking: list[str] = field(default_factory=list)

    def compute_combined_ranking(self) -> None:
        seen: dict[str, None] = {}
        for inv in self.invocations:
            for eid in inv.entity_ids:
                if eid not in seen:
                    seen[eid] = None
        self.combined_ranking = list(seen.keys())


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class EvalV2Runner:
    """One-shot runner for a corpus against a running RKA REST API."""

    def __init__(
        self,
        *,
        rka_url: str,
        project_id: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._rka_url = rka_url.rstrip("/")
        self._project_id = project_id
        self._http = http_client

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=self._rka_url, timeout=60.0)
        return self._http

    def _params(self, extra: dict | None = None) -> dict:
        out: dict = {}
        if self._project_id:
            out["project_id"] = self._project_id
        if extra:
            out.update(extra)
        return out

    def _extract_json_entities(
        self, resp: httpx.Response, path: str
    ) -> tuple[list[str], str | None]:
        """Try to parse the response body as JSON; on parse failure (e.g.,
        SPA fallback returning HTML), return ([], divergence-note) so the
        caller can attribute the empty bundle to a real shape mismatch.

        Discovered during T5 live run: some endpoints that don't exist
        fall through to the React SPA serving index.html with a 200,
        which then makes `r.json()` raise JSONDecodeError. Defensive
        handling here keeps the runner moving across the corpus instead
        of crashing on the first bad endpoint.
        """
        if resp.status_code != 200:
            return ([], None)
        try:
            payload = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            return (
                [],
                f"{path}: 200 but body is not JSON ({exc!s}); likely SPA fallback for a missing route",
            )
        return (walk_for_entity_ids(payload), None)

    async def probe_health(self) -> None:
        """Probe `/api/health`; exit(2) on failure."""
        try:
            r = await self._client().get("/api/health")
        except httpx.HTTPError as exc:
            logger.error("RKA unreachable at %s: %s", self._rka_url, exc)
            sys.exit(2)
        if r.status_code != 200:
            logger.error(
                "RKA /api/health returned %s (expected 200)", r.status_code
            )
            sys.exit(2)
        logger.info("RKA health OK at %s", self._rka_url)

    async def _invoke_one(
        self, tool: str, scenario: dict[str, Any]
    ) -> ToolInvocation:
        """Dispatch one tool call. Returns the ToolInvocation record."""
        # Some tools need an anchor entity from the scenario's expected_entities.
        critical = [
            e for e in scenario["expected_entities"]
            if e["importance"] == "critical"
        ]
        anchor_id = critical[0]["entity_id"] if critical else None
        # Filter critical entities by type to pick the right kind of anchor
        # for tools that need a specific entity_type (e.g., rka_get_mission
        # needs a mis_ id, ego_graph anchors at any entity id).
        first_mission = next(
            (e["entity_id"] for e in critical if e["entity_type"] == "mission"),
            None,
        )

        try:
            if tool == "rka_get_context":
                return await self._call_get_context()
            if tool == "rka_get_status":
                return await self._call_get_status()
            if tool == "rka_get_pending_maintenance":
                return await self._call_pending_maintenance()
            if tool == "rka_get_checkpoints":
                return await self._call_get_checkpoints()
            if tool == "rka_get_review_queue":
                return await self._call_review_queue()
            if tool == "rka_get_research_map":
                return await self._call_research_map()
            if tool == "rka_get_mission":
                return await self._call_get_mission(first_mission)
            if tool == "rka_get_journal":
                return await self._call_get_journal()
            if tool == "rka_multi_hop_retrieval":
                return await self._call_multi_hop(anchor_id, scenario)
            if tool == "rka_get_ego_graph":
                return await self._call_ego_graph(anchor_id)
            if tool == "rka_assemble_evidence":
                return await self._call_assemble_evidence(anchor_id, scenario)
        except httpx.HTTPError as exc:
            return ToolInvocation(
                tool=tool,
                path="(unknown)",
                status_code=-1,
                entity_ids=[],
                divergence=f"HTTP error: {exc!s}",
            )

        # Unknown tool — record a divergence and continue.
        return ToolInvocation(
            tool=tool,
            path="(no mapping)",
            status_code=0,
            entity_ids=[],
            divergence=f"runner has no REST mapping for tool {tool!r}",
        )

    # ------------------------------------------------------------------
    # Per-tool REST callers
    # ------------------------------------------------------------------

    async def _call_get_context(self) -> ToolInvocation:
        path = "/api/context"
        r = await self._client().post(path, json={}, params=self._params())
        ids, div = self._extract_json_entities(r, path)
        return ToolInvocation(
            tool="rka_get_context",
            path=path,
            status_code=r.status_code,
            entity_ids=ids,
            divergence=div,
        )

    async def _call_get_status(self) -> ToolInvocation:
        path = "/api/status"
        r = await self._client().get(path, params=self._params())
        ids, div = self._extract_json_entities(r, path)
        return ToolInvocation(
            tool="rka_get_status",
            path=path,
            status_code=r.status_code,
            entity_ids=ids,
            divergence=div,
        )

    async def _call_pending_maintenance(self) -> ToolInvocation:
        path = "/api/maintenance/summary"
        r = await self._client().get(path, params=self._params())
        ids, div = self._extract_json_entities(r, path)
        return ToolInvocation(
            tool="rka_get_pending_maintenance",
            path=path,
            status_code=r.status_code,
            entity_ids=ids,
            divergence=div,
        )

    async def _call_get_checkpoints(self) -> ToolInvocation:
        path = "/api/checkpoints"
        r = await self._client().get(
            path, params=self._params({"status": "open"})
        )
        ids, div = self._extract_json_entities(r, path)
        return ToolInvocation(
            tool="rka_get_checkpoints",
            path=path,
            status_code=r.status_code,
            entity_ids=ids,
            divergence=div,
        )

    async def _call_review_queue(self) -> ToolInvocation:
        path = "/api/review-queue"
        r = await self._client().get(path, params=self._params())
        ids, div = self._extract_json_entities(r, path)
        return ToolInvocation(
            tool="rka_get_review_queue",
            path=path,
            status_code=r.status_code,
            entity_ids=ids,
            divergence=div,
        )

    async def _call_research_map(self) -> ToolInvocation:
        path = "/api/research-map"
        r = await self._client().get(path, params=self._params())
        ids, div = self._extract_json_entities(r, path)
        return ToolInvocation(
            tool="rka_get_research_map",
            path=path,
            status_code=r.status_code,
            entity_ids=ids,
            divergence=div,
        )

    async def _call_get_mission(self, mission_id: str | None) -> ToolInvocation:
        if not mission_id:
            path = "/api/missions/active"
        else:
            path = f"/api/missions/{mission_id}"
        r = await self._client().get(path, params=self._params())
        ids, div = self._extract_json_entities(r, path)
        return ToolInvocation(
            tool="rka_get_mission",
            path=path,
            status_code=r.status_code,
            entity_ids=ids,
            divergence=div,
            notes=f"anchor={mission_id or '(active)'}",
        )

    async def _call_get_journal(self) -> ToolInvocation:
        # The actual route is /api/notes (journal entries are "notes" in
        # the REST surface). Discovered during T5 live run.
        path = "/api/notes"
        r = await self._client().get(path, params=self._params({"limit": 20}))
        entity_ids, divergence = self._extract_json_entities(r, path)
        return ToolInvocation(
            tool="rka_get_journal",
            path=path,
            status_code=r.status_code,
            entity_ids=entity_ids,
            divergence=divergence,
        )

    async def _call_multi_hop(
        self, anchor: str | None, scenario: dict
    ) -> ToolInvocation:
        path = "/api/graph/multi-hop"
        # v2.5.1: route schema is `{query: Optional[str], seeds: Optional[list[str]]}`
        # (rka/api/routes/graph.py:MultiHopRequest). Always populate `query`
        # from the scenario trigger so the search-based seeding path is
        # exercised when no anchor is present; ALSO pass `seeds=[anchor]`
        # (note: list, not the v2.4-era singular `start_entity`) when the
        # scenario provides one. Both-populated is accepted — the service
        # layer's seeds-set branch bypasses the search step entirely
        # (rka/services/graph.py:multi_hop_retrieval).
        body: dict[str, Any] = {
            "max_depth": 2,
            "query": scenario.get("trigger", "")[:200],
        }
        if anchor:
            body["seeds"] = [anchor]
        r = await self._client().post(path, json=body, params=self._params())
        # Sister-uncertainty probe: any non-2xx is a divergence per T2 gate.
        divergence = None
        if r.status_code >= 400:
            divergence = (
                f"rka_multi_hop_retrieval: {r.status_code} "
                f"(probable shape divergence — Brain T2-gate sister-uncertainty)"
            )
        ids, div = self._extract_json_entities(r, path)
        return ToolInvocation(
            tool="rka_multi_hop_retrieval",
            path=path,
            status_code=r.status_code,
            entity_ids=ids,
            divergence=divergence or div,
            notes=f"anchor={anchor or '(query-fallback)'}",
        )

    async def _call_ego_graph(self, anchor: str | None) -> ToolInvocation:
        if not anchor:
            return ToolInvocation(
                tool="rka_get_ego_graph",
                path="(skipped)",
                status_code=0,
                entity_ids=[],
                divergence="no anchor entity in scenario critical-set",
            )
        path = f"/api/graph/ego/{anchor}"
        r = await self._client().get(path, params=self._params({"depth": 1}))
        divergence = None
        if r.status_code >= 400:
            divergence = (
                f"rka_get_ego_graph: {r.status_code} "
                f"(cluster-anchored ego_graph — Brain T2-gate sister-uncertainty)"
            )
        ids, div = self._extract_json_entities(r, path)
        return ToolInvocation(
            tool="rka_get_ego_graph",
            path=path,
            status_code=r.status_code,
            entity_ids=ids,
            divergence=divergence or div,
            notes=f"anchor={anchor}",
        )

    async def _call_assemble_evidence(
        self, anchor: str | None, scenario: dict
    ) -> ToolInvocation:
        path = "/api/assemble-evidence"
        params = self._params()
        if anchor:
            params["entity_id"] = anchor
        r = await self._client().get(path, params=params)
        # Sister-uncertainty probe: this is the tool whose shape we
        # explicitly weren't sure about at the T2 gate.
        divergence = None
        if r.status_code >= 400:
            divergence = (
                f"rka_assemble_evidence: {r.status_code} "
                f"(Brain T2-gate sister-uncertainty — shape unknown)"
            )
        ids, div = self._extract_json_entities(r, path)
        return ToolInvocation(
            tool="rka_assemble_evidence",
            path=path,
            status_code=r.status_code,
            entity_ids=ids,
            divergence=divergence or div,
            notes=f"anchor={anchor or '(none)'}",
        )

    # ------------------------------------------------------------------
    # Per-scenario orchestration
    # ------------------------------------------------------------------

    async def run_scenario(self, scenario: dict[str, Any]) -> ScenarioBundle:
        bundle = ScenarioBundle(
            scenario_id=scenario["scenario_id"], actor=scenario["actor"]
        )
        for tool in scenario["tools_invoked"]:
            invocation = await self._invoke_one(tool, scenario)
            bundle.invocations.append(invocation)
        bundle.compute_combined_ranking()
        return bundle

    async def run_corpus(
        self, scenarios: list[dict[str, Any]]
    ) -> list[ScenarioBundle]:
        bundles: list[ScenarioBundle] = []
        for scenario in scenarios:
            bundle = await self.run_scenario(scenario)
            bundles.append(bundle)
        return bundles


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_bundle(bundle: ScenarioBundle, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{bundle.scenario_id}.jsonl"
    payload = asdict(bundle)
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Eval-v2 composed-context runner")
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("eval-harness/v2/corpus/scenarios.jsonl"),
    )
    parser.add_argument(
        "--rka-url",
        default="http://localhost:9712",
    )
    parser.add_argument(
        "--project-id",
        default="prj_01KKQM9JFG67GT5FGWTAHD9YE4",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("eval-harness/v2/results/raw"),
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Schema-validate the corpus before any HTTP work.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from v2.schema_validator import load_corpus

    scenarios = load_corpus(args.corpus)
    logger.info("loaded %d scenarios from %s", len(scenarios), args.corpus)

    async def _main() -> None:
        runner = EvalV2Runner(
            rka_url=args.rka_url, project_id=args.project_id
        )
        await runner.probe_health()
        bundles = await runner.run_corpus(scenarios)
        for bundle in bundles:
            path = serialize_bundle(bundle, args.output_dir)
            divergences = sum(
                1 for inv in bundle.invocations if inv.divergence
            )
            logger.info(
                "wrote %s (%d entities; %d divergences)",
                path,
                len(bundle.combined_ranking),
                divergences,
            )

    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
