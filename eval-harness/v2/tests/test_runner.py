"""T3 integration tests for the Eval-v2 runner.

The spec calls for "4 integration tests using a fixture-mode RKA
database to keep CI hermetic". We use httpx.MockTransport to inject
canned responses per `/api/*` endpoint — strictly hermetic, no Docker
required, and the response fixtures double as documentation of the
expected REST surface.

Tests cover at minimum (per spec): one scenario per actor + per tool
category. Brain session-start covers GET-heavy endpoints; Executor
mission-pickup covers the `rka_get_mission` path; one cluster-anchored
scenario exercises the multi_hop/ego_graph sister-uncertainty probes;
one bundle-serialization test locks the on-disk shape.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

_V2_DIR = Path(__file__).resolve().parent.parent
if str(_V2_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_V2_DIR.parent))

from v2.runner import (
    EvalV2Runner,
    ScenarioBundle,
    ToolInvocation,
    serialize_bundle,
    walk_for_entity_ids,
)


# ---------------------------------------------------------------------------
# Fixture-mode HTTP transport — one canned response per RKA endpoint
# ---------------------------------------------------------------------------


def _fixture_transport() -> httpx.MockTransport:
    """A MockTransport that serves canonical-shaped fake responses per route.

    Endpoint fixtures here ARE the documented assumption about the RKA
    REST surface — if production response shape drifts, these fixtures
    are what surface the drift at test time.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "version": "2.4.1+test"})
        if path == "/api/context":
            return httpx.Response(
                200,
                json={
                    "topic": None,
                    "entries": [
                        "[dec_01ABC0000000000000000000] Recent strategic decision",
                        "[mis_01DEF0000000000000000000] Active mission",
                        "[chk_01GHI0000000000000000000] Open checkpoint",
                    ],
                    "sources": [],
                },
            )
        if path == "/api/status":
            return httpx.Response(
                200,
                json={
                    "phase": "design",
                    "active_mission_id": "mis_01DEF0000000000000000000",
                    "recent_decisions": ["dec_01ABC0000000000000000000"],
                },
            )
        if path == "/api/maintenance/summary":
            return httpx.Response(
                200,
                json={"total_items": 0, "top_categories": []},
            )
        if path == "/api/checkpoints":
            return httpx.Response(
                200,
                json=[
                    {"id": "chk_01GHI0000000000000000000", "reason": "x"},
                    {"id": "chk_01JKL0000000000000000000", "reason": "y"},
                ],
            )
        if path == "/api/review-queue":
            return httpx.Response(200, json=[])
        if path == "/api/research-map":
            return httpx.Response(
                200,
                json={
                    "rqs": [
                        {
                            "rq_id": "dec_01MNO0000000000000000000",
                            "clusters": ["ecl_01PQR0000000000000000000"],
                        }
                    ]
                },
            )
        if path == "/api/journal":
            return httpx.Response(
                200,
                json=[
                    {"id": "jrn_01STU0000000000000000000", "content": "..."},
                ],
            )
        if path.startswith("/api/missions/"):
            mid = path.split("/")[-1]
            return httpx.Response(
                200,
                json={
                    "id": mid if mid != "active" else "mis_01DEF0000000000000000000",
                    "motivated_by_decision": "dec_01ABC0000000000000000000",
                    "tasks": [],
                },
            )
        if path == "/api/graph/multi-hop":
            return httpx.Response(
                200,
                json={
                    "anchor": "dec_01ABC0000000000000000000",
                    "entities": [
                        "dec_01ABC0000000000000000000",
                        "mis_01DEF0000000000000000000",
                        "jrn_01STU0000000000000000000",
                    ],
                },
            )
        if path.startswith("/api/graph/ego/"):
            return httpx.Response(
                200,
                json={
                    "center": path.split("/")[-1],
                    "neighbors": [
                        "ecl_01PQR0000000000000000000",
                        "clm_01VWX0000000000000000000",
                    ],
                },
            )
        if path == "/api/assemble-evidence":
            return httpx.Response(
                200,
                json={
                    "assembled": [
                        "clm_01VWX0000000000000000000",
                        "ecl_01PQR0000000000000000000",
                    ]
                },
            )
        # Unknown endpoint — 404 to surface unmocked paths in tests.
        return httpx.Response(404, json={"detail": f"no fixture for {path}"})

    return httpx.MockTransport(_handler)


@pytest.fixture
def runner() -> EvalV2Runner:
    client = httpx.AsyncClient(transport=_fixture_transport(), base_url="http://test")
    return EvalV2Runner(
        rka_url="http://test", project_id="prj_test", http_client=client
    )


# ---------------------------------------------------------------------------
# Test #1 — Brain session-start scenario (GET-heavy)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brain_session_start_scenario_runs(runner: EvalV2Runner):
    """A canonical Brain session-start scenario invokes 6 tools; the
    runner must record each invocation + extract entity ids."""
    scenario = {
        "scenario_id": "test-brain-session-start",
        "actor": "brain",
        "trigger": "Brain resumes the project after a 2-day break.",
        "tools_invoked": [
            "rka_get_context",
            "rka_get_status",
            "rka_get_pending_maintenance",
            "rka_get_checkpoints",
            "rka_get_review_queue",
            "rka_get_research_map",
        ],
        "expected_entities": [
            {"entity_id": "dec_01ABC0000000000000000000", "entity_type": "decision", "importance": "critical"},
            {"entity_id": "mis_01DEF0000000000000000000", "entity_type": "mission", "importance": "critical"},
            {"entity_id": "chk_01GHI0000000000000000000", "entity_type": "checkpoint", "importance": "critical"},
            {"entity_id": "jrn_01STU0000000000000000000", "entity_type": "journal", "importance": "useful"},
            {"entity_id": "ecl_01PQR0000000000000000000", "entity_type": "cluster", "importance": "nice-to-have"},
        ],
    }
    bundle = await runner.run_scenario(scenario)

    assert bundle.scenario_id == "test-brain-session-start"
    assert bundle.actor == "brain"
    assert len(bundle.invocations) == 6
    # Each tool produced a 2xx response
    for inv in bundle.invocations:
        assert 200 <= inv.status_code < 300, f"{inv.tool}: {inv.status_code}"

    # The combined ranking should include the 3 critical-anchor entity ids,
    # all of which appear in the fixtures.
    assert "dec_01ABC0000000000000000000" in bundle.combined_ranking
    assert "mis_01DEF0000000000000000000" in bundle.combined_ranking
    assert "chk_01GHI0000000000000000000" in bundle.combined_ranking


# ---------------------------------------------------------------------------
# Test #2 — Executor mission-pickup scenario
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_mission_pickup_uses_critical_mission_anchor(runner: EvalV2Runner):
    """Executor variant + rka_get_mission needs to anchor at the
    first critical mission in expected_entities."""
    scenario = {
        "scenario_id": "test-executor-mission-pickup",
        "actor": "executor",
        "trigger": "Executor picks up a mission from the spec.",
        "tools_invoked": [
            "rka_get_context",
            "rka_get_status",
            "rka_get_mission",
            "rka_get_journal",
        ],
        "expected_entities": [
            {"entity_id": "mis_01TARGET00000000000000000", "entity_type": "mission", "importance": "critical"},
            {"entity_id": "dec_01ABC0000000000000000000", "entity_type": "decision", "importance": "critical"},
            {"entity_id": "mis_01PRIOR000000000000000000", "entity_type": "mission", "importance": "critical"},
            {"entity_id": "jrn_01STU0000000000000000000", "entity_type": "journal", "importance": "useful"},
            {"entity_id": "ecl_01PQR0000000000000000000", "entity_type": "cluster", "importance": "nice-to-have"},
        ],
    }
    bundle = await runner.run_scenario(scenario)
    assert bundle.actor == "executor"

    # Find the rka_get_mission invocation; verify it used the first critical
    # mission as anchor (NOT 'active').
    mission_inv = next(i for i in bundle.invocations if i.tool == "rka_get_mission")
    assert "mis_01TARGET00000000000000000" in mission_inv.path
    assert "anchor=mis_01TARGET00000000000000000" in mission_inv.notes


# ---------------------------------------------------------------------------
# Test #3 — cluster-anchored sister-uncertainty probes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cluster_anchored_scenario_probes_sister_uncertainties(runner: EvalV2Runner):
    """A scenario anchored at a cluster (the T2-gate-flagged sister-
    uncertainty cluster) should run rka_get_ego_graph + rka_assemble_evidence
    without crashing; record divergences if any."""
    scenario = {
        "scenario_id": "test-brain-contradiction-cluster-anchor",
        "actor": "brain",
        "trigger": "Brain investigates a cluster-to-cluster contradiction.",
        "tools_invoked": [
            "rka_get_context",
            "rka_get_ego_graph",
            "rka_multi_hop_retrieval",
            "rka_assemble_evidence",
        ],
        "expected_entities": [
            {"entity_id": "ecl_01PQR0000000000000000000", "entity_type": "cluster", "importance": "critical"},
            {"entity_id": "ecl_01ZAB0000000000000000000", "entity_type": "cluster", "importance": "critical"},
            {"entity_id": "dec_01MNO0000000000000000000", "entity_type": "decision", "importance": "critical"},
            {"entity_id": "clm_01VWX0000000000000000000", "entity_type": "claim", "importance": "useful"},
            {"entity_id": "ecl_01CDE0000000000000000000", "entity_type": "cluster", "importance": "nice-to-have"},
        ],
    }
    bundle = await runner.run_scenario(scenario)

    # ego_graph anchored at the first critical entity (which is the cluster)
    ego = next(i for i in bundle.invocations if i.tool == "rka_get_ego_graph")
    assert "ecl_01PQR0000000000000000000" in ego.path
    # No divergence — fixture returns 200.
    assert ego.divergence is None
    # The neighbors list is in the response → walked into the bundle.
    assert "clm_01VWX0000000000000000000" in ego.entity_ids

    # multi_hop anchored at the same critical
    mh = next(i for i in bundle.invocations if i.tool == "rka_multi_hop_retrieval")
    assert mh.divergence is None
    assert "ecl_01PQR0000000000000000000" in mh.notes

    # assemble_evidence — sister-uncertainty probe
    assemble = next(i for i in bundle.invocations if i.tool == "rka_assemble_evidence")
    assert assemble.divergence is None


# ---------------------------------------------------------------------------
# Test #4 — bundle serialization shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bundle_serialization_writes_canonical_shape(runner: EvalV2Runner, tmp_path: Path):
    scenario = {
        "scenario_id": "test-serialize-bundle",
        "actor": "brain",
        "trigger": "Bundle-serialization smoke",
        "tools_invoked": ["rka_get_context", "rka_get_status"],
        "expected_entities": [
            {"entity_id": "dec_01ABC0000000000000000000", "entity_type": "decision", "importance": "critical"},
            {"entity_id": "mis_01DEF0000000000000000000", "entity_type": "mission", "importance": "critical"},
            {"entity_id": "chk_01GHI0000000000000000000", "entity_type": "checkpoint", "importance": "critical"},
            {"entity_id": "jrn_01STU0000000000000000000", "entity_type": "journal", "importance": "useful"},
            {"entity_id": "ecl_01PQR0000000000000000000", "entity_type": "cluster", "importance": "nice-to-have"},
        ],
    }
    bundle = await runner.run_scenario(scenario)
    out_path = serialize_bundle(bundle, tmp_path)

    assert out_path.name == "test-serialize-bundle.jsonl"
    payload = json.loads(out_path.read_text())
    assert payload["scenario_id"] == "test-serialize-bundle"
    assert payload["actor"] == "brain"
    assert isinstance(payload["invocations"], list)
    assert len(payload["invocations"]) == 2
    assert isinstance(payload["combined_ranking"], list)
    # Each invocation has the documented fields
    for inv in payload["invocations"]:
        assert {"tool", "path", "status_code", "entity_ids", "divergence", "notes"} <= set(inv)


# ---------------------------------------------------------------------------
# Walker behavior — anchor for the metric-layer tests at T4
# ---------------------------------------------------------------------------


def test_walker_extracts_entity_ids_in_discovery_order():
    payload = {
        "first": "see dec_01ABC0000000000000000000 here",
        "deep": {
            "nested": ["and mis_01DEF0000000000000000000", "plus dec_01ABC0000000000000000000 again"],
        },
        "third": "lit_01ZZZ0000000000000000000",
    }
    out = walk_for_entity_ids(payload)
    # dec_ first (top-level string), then mis_ (nested list), then lit_;
    # duplicate dec_ collapsed (first-discovery wins).
    assert out == [
        "dec_01ABC0000000000000000000",
        "mis_01DEF0000000000000000000",
        "lit_01ZZZ0000000000000000000",
    ]


def test_walker_ignores_strings_without_entity_prefix():
    out = walk_for_entity_ids({"a": "no entities here", "b": ["nor here"]})
    assert out == []


# ---------------------------------------------------------------------------
# v2.5.1 — _call_multi_hop body-shape regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_multi_hop_body_matches_v2_5_1_schema():
    """The runner MUST send a body that matches the v2.5.1
    MultiHopRequest schema in rka/api/routes/graph.py:

      - `seeds` is a list[str] (NOT the v2.4-era singular `start_entity`)
      - `query` is always present (so the schema's "neither query nor
        seeds" branch never fires, even on seeds-only invocations)

    Pre-fix bug: runner sent ``{"start_entity": "...", "max_depth": 2}``
    which the schema rejected with FastAPI's default per-field 422, the
    surfacing finding in jrn_01KRPGY39DJA2K9KV20XD733GK.
    """
    captured: dict[str, dict] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/graph/multi-hop":
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"entities": []})
        return httpx.Response(404, json={"detail": "no fixture"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler), base_url="http://test"
    )
    r = EvalV2Runner(rka_url="http://test", project_id="prj_test", http_client=client)

    scenario = {"trigger": "investigate the v2.5.1 schema fix for multi-hop"}
    await r._call_multi_hop(["dec_01ABC0000000000000000000"], scenario)

    body = captured["body"]
    # `seeds` is a LIST of strings — not the v2.4-era `start_entity` singular.
    assert "start_entity" not in body, (
        f"runner sent legacy `start_entity` key — schema drift not fixed: {body}"
    )
    assert body.get("seeds") == ["dec_01ABC0000000000000000000"], (
        f"seeds must be [anchor] for anchored invocations; got {body!r}"
    )
    # `query` is always populated (even when seeds present), so the route
    # schema's neither-set 422 branch never fires.
    assert body.get("query"), f"query must always be populated; got {body!r}"
    assert "v2.5.1" in body["query"]  # populated from scenario.trigger


# ---------------------------------------------------------------------------
# Phase-3.3 R1 — multi-anchor seeding when critical[0] is a decision but a
# first_mission is also present (mis_01KS5KEPXK77MAG54GW5M6DA79,
# chk_01KS5NJN1652XHAKZ5DYZ4RZX9 Brain ratification preference 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_hop_seeds_decision_and_first_mission_when_both_critical():
    """When the scenario's critical[0] is a decision AND a mission-type
    critical entity is also present, the runner must send BOTH as seeds
    to multi_hop so the BFS expands from both neighborhoods. Pre-fix
    (Phase-3.2 v2.5.11): only critical[0]'s neighborhood was reached;
    mis_-class critical entities were stranded outside the BFS reach
    even when they ranked well in /api/search.
    """
    captured: dict[str, dict] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/graph/multi-hop":
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"nodes": [], "edges": []})
        return httpx.Response(404, json={"detail": "no fixture"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler), base_url="http://test"
    )
    r = EvalV2Runner(rka_url="http://test", project_id="prj_test", http_client=client)

    scenario = {
        "scenario_id": "test-decision-then-mission",
        "actor": "brain",
        "trigger": "test scenario where decision precedes mission",
        "tools_invoked": ["rka_multi_hop_retrieval"],
        "expected_entities": [
            {"entity_id": "dec_01ABC0000000000000000000", "entity_type": "decision", "importance": "critical"},
            {"entity_id": "mis_01DEF0000000000000000000", "entity_type": "mission", "importance": "critical"},
        ],
    }
    await r.run_scenario(scenario)
    seeds = captured["body"].get("seeds")
    assert seeds == ["dec_01ABC0000000000000000000", "mis_01DEF0000000000000000000"], (
        f"R1 fix: when critical[0] is decision + first_mission present, seeds must "
        f"include BOTH (preserving decision-anchor BFS coverage while adding mission-"
        f"anchor BFS reach). Got: {seeds!r}"
    )


@pytest.mark.asyncio
async def test_multi_hop_seeds_only_critical_when_critical_zero_is_mission():
    """When critical[0] IS already a mission (the v2.5.11 baseline anchor
    behavior), the R1 fix is a no-op — single-seed BFS preserved."""
    captured: dict[str, dict] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/graph/multi-hop":
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"nodes": [], "edges": []})
        return httpx.Response(404, json={"detail": "no fixture"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler), base_url="http://test"
    )
    r = EvalV2Runner(rka_url="http://test", project_id="prj_test", http_client=client)

    scenario = {
        "scenario_id": "test-mission-first",
        "actor": "brain",
        "trigger": "test scenario where mission is critical[0]",
        "tools_invoked": ["rka_multi_hop_retrieval"],
        "expected_entities": [
            {"entity_id": "mis_01ABC0000000000000000000", "entity_type": "mission", "importance": "critical"},
            {"entity_id": "dec_01DEF0000000000000000000", "entity_type": "decision", "importance": "critical"},
        ],
    }
    await r.run_scenario(scenario)
    seeds = captured["body"].get("seeds")
    assert seeds == ["mis_01ABC0000000000000000000"], (
        f"R1 no-op: when critical[0] is already a mission, seeds stays as "
        f"single-element [critical[0]]. Got: {seeds!r}"
    )


@pytest.mark.asyncio
async def test_multi_hop_seeds_only_critical_when_no_first_mission():
    """When critical[0] is a decision but NO mission-type critical entity
    is present, the R1 fix doesn't trigger — single-seed BFS preserved."""
    captured: dict[str, dict] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/graph/multi-hop":
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"nodes": [], "edges": []})
        return httpx.Response(404, json={"detail": "no fixture"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler), base_url="http://test"
    )
    r = EvalV2Runner(rka_url="http://test", project_id="prj_test", http_client=client)

    scenario = {
        "scenario_id": "test-decision-no-mission",
        "actor": "brain",
        "trigger": "test scenario with decision but no mission",
        "tools_invoked": ["rka_multi_hop_retrieval"],
        "expected_entities": [
            {"entity_id": "dec_01ABC0000000000000000000", "entity_type": "decision", "importance": "critical"},
            {"entity_id": "jrn_01DEF0000000000000000000", "entity_type": "journal", "importance": "critical"},
        ],
    }
    await r.run_scenario(scenario)
    seeds = captured["body"].get("seeds")
    assert seeds == ["dec_01ABC0000000000000000000"], (
        f"R1 no-op: when critical[0] is decision but no mission in criticals, "
        f"seeds stays as single-element. Got: {seeds!r}"
    )
