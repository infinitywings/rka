"""Phase D, D5c — onboarding subgraph wiring + runner.start_onboarding.

Covers:
  - build_onboarding_graph compiles cleanly with the LangGraph runtime
  - Topology: every node from ONBOARDING_NODE_NAMES (sans research_toolkit's
    sibling pi_extend_toolkit which is D6) is registered
  - Routing: pi_toolkit_ratify reject → END; accept → draft_manifest
  - Routing: pi_credentials_ready reject → END; accept → finalize
  - runner.start_onboarding creates a workflow_runs row + runs first
    segment; parks at pi_onboarding_topic (the first interrupt)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from orchestrator import onboarding_graph as OG
from orchestrator.parked_store import ParkedStore
from orchestrator.runner import OrchestratorRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    os.environ["RKA_PROJECTS_ROOT"] = str(tmp_path)
    yield tmp_path
    os.environ.pop("RKA_PROJECTS_ROOT", None)


@pytest.fixture
def store():
    s = ParkedStore(":memory:")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Compile + topology
# ---------------------------------------------------------------------------


def test_build_onboarding_graph_compiles_with_real_langgraph():
    """The onboarding subgraph compiles via the real LangGraph runtime
    without errors — catches missing nodes, broken edges, or invalid
    routing functions."""
    pytest.importorskip("langgraph")

    class _StubSDK:
        def complete(self, **kw):
            return ""

    class _StubMCP:
        workflow_thread_id = "thr_t"

        def rka_add_note(self, **kw):
            return "jrn_x"

    compiled = OG.build_onboarding_graph(sdk=_StubSDK(), mcp=_StubMCP())
    # Compiled is a Runnable-shaped object — no obvious smoke check
    # other than "it exists and has .invoke".
    assert hasattr(compiled, "invoke")


def test_onboarding_graph_registers_all_six_nodes():
    """The compiled graph should register: pi_onboarding_topic,
    research_toolkit, pi_toolkit_ratify, draft_manifest,
    pi_credentials_ready, finalize."""
    pytest.importorskip("langgraph")

    class _StubSDK:
        def complete(self, **kw):
            return ""

    class _StubMCP:
        workflow_thread_id = "thr_t"

        def rka_add_note(self, **kw):
            return "jrn_x"

    compiled = OG.build_onboarding_graph(sdk=_StubSDK(), mcp=_StubMCP())
    # LangGraph exposes `nodes` on the compiled object (a dict-like).
    node_names = set(compiled.nodes)
    for expected in (
        "pi_onboarding_topic",
        "research_toolkit",
        "pi_toolkit_ratify",
        "draft_manifest",
        "pi_credentials_ready",
        "finalize",
    ):
        assert expected in node_names, f"missing node {expected!r}"


# ---------------------------------------------------------------------------
# Routing functions (direct unit tests; don't need the graph compiled)
# ---------------------------------------------------------------------------


def test_route_after_toolkit_ratify_to_draft_when_ratified_nonempty():
    state = {"ratified_toolkit": [{"name": "rka"}]}
    assert OG._route_after_toolkit_ratify(state) == "draft_manifest"


def test_route_after_toolkit_ratify_to_end_when_ratified_empty():
    from langgraph.graph import END
    state = {"ratified_toolkit": []}
    assert OG._route_after_toolkit_ratify(state) == END


def test_route_after_toolkit_ratify_to_end_when_field_missing():
    from langgraph.graph import END
    assert OG._route_after_toolkit_ratify({}) == END


def test_route_after_credentials_ready_to_finalize_on_accept():
    state = {"interrupts": [{"response": "accept"}]}
    assert OG._route_after_credentials_ready(state) == "finalize"


def test_route_after_credentials_ready_to_end_on_reject():
    from langgraph.graph import END
    state = {"interrupts": [{"response": "reject"}]}
    assert OG._route_after_credentials_ready(state) == END


def test_route_after_credentials_ready_to_end_when_no_interrupts():
    from langgraph.graph import END
    assert OG._route_after_credentials_ready({"interrupts": []}) == END


# ---------------------------------------------------------------------------
# runner.start_onboarding
# ---------------------------------------------------------------------------


class _ScriptedGraph:
    """Reused from runner tests: a compiled-graph fake that scripts
    each invoke() call's output."""

    def __init__(self, outputs: list[dict]):
        self.outputs = list(outputs)
        self.invocations: list[tuple[Any, dict]] = []

    def invoke(self, input_or_command, config):
        self.invocations.append((input_or_command, config))
        return self.outputs.pop(0)


class _FakeInterrupt:
    def __init__(self, value):
        self.value = value


def test_start_onboarding_creates_workflow_row_and_invokes_subgraph(
    store: ParkedStore, tmp_root: Path
):
    """start_onboarding should mint a workflow_thread_id, register a
    workflow_runs row, and invoke the onboarding compile factory (not
    the mission compile factory)."""
    scripted = _ScriptedGraph(
        [
            {
                "current_node": "pi_onboarding_topic",
                "__interrupt__": [
                    _FakeInterrupt(
                        value={
                            "type": "pi_onboarding_topic",
                            "title": "Topic?",
                            "prompt": "tell me about your project",
                        }
                    )
                ],
            }
        ]
    )

    class _FakeMCP:
        workflow_thread_id = "thr_t"

    runner = OrchestratorRunner(
        store=store,
        sdk_factory=lambda pid: object(),
        mcp_factory=lambda tid, pid: _FakeMCP(),
        saver_factory=lambda tid: None,
        compile_factory=lambda **kw: object(),  # mission factory not used
        onboarding_compile_factory=lambda **kw: scripted,
    )
    out = runner.start_onboarding(project_id="prj_onboard_test")
    # Run row created.
    run = store.get_run(out.workflow_thread_id)
    assert run is not None
    assert run["project_id"] == "prj_onboard_test"
    # First interrupt parked.
    assert out.parked_interrupt_type == "pi_onboarding_topic"
    assert out.parked_interrupt_id is not None
    # The onboarding compile factory (NOT the mission one) was invoked.
    assert len(scripted.invocations) == 1


def test_start_onboarding_initial_state_includes_onboarding_fields(
    store: ParkedStore, tmp_root: Path
):
    """Initial state passed into the subgraph must include the Phase-D
    onboarding fields (topic_metadata, proposed_toolkit,
    ratified_toolkit) so the nodes' .get() lookups don't break."""
    scripted = _ScriptedGraph([
        {"current_node": "pi_onboarding_topic", "__interrupt__": [
            _FakeInterrupt(value={"type": "pi_onboarding_topic"})
        ]},
    ])

    class _FakeMCP:
        workflow_thread_id = "thr_t"

    runner = OrchestratorRunner(
        store=store,
        sdk_factory=lambda pid: object(),
        mcp_factory=lambda tid, pid: _FakeMCP(),
        saver_factory=lambda tid: None,
        compile_factory=lambda **kw: object(),
        onboarding_compile_factory=lambda **kw: scripted,
    )
    runner.start_onboarding(project_id="prj_state_check")
    # The first arg to invoke() is the initial state dict.
    initial_state = scripted.invocations[0][0]
    assert "topic_metadata" in initial_state
    assert "proposed_toolkit" in initial_state
    assert "ratified_toolkit" in initial_state
    assert initial_state["project_id"] == "prj_state_check"
    # mission_id is placeholder = project_id (per the runner contract
    # documented in start_onboarding's docstring).
    assert initial_state["mission_id"] == "prj_state_check"


def test_start_onboarding_does_not_call_rka_get_mission(
    store: ParkedStore, tmp_root: Path
):
    """Unlike start_run, onboarding does NOT load a mission spec — it's
    project-scoped only. Verify rka_get_mission is never called."""
    scripted = _ScriptedGraph([
        {"current_node": "pi_onboarding_topic", "__interrupt__": [
            _FakeInterrupt(value={"type": "pi_onboarding_topic"})
        ]},
    ])

    class _FakeMCP:
        workflow_thread_id = "thr_t"
        get_mission_calls: list = []

        def rka_get_mission(self, *args, **kw):
            _FakeMCP.get_mission_calls.append((args, kw))
            return {"id": "should_not_be_called"}

    _FakeMCP.get_mission_calls.clear()

    runner = OrchestratorRunner(
        store=store,
        sdk_factory=lambda pid: object(),
        mcp_factory=lambda tid, pid: _FakeMCP(),
        saver_factory=lambda tid: None,
        compile_factory=lambda **kw: object(),
        onboarding_compile_factory=lambda **kw: scripted,
    )
    runner.start_onboarding(project_id="prj_no_mission")
    assert _FakeMCP.get_mission_calls == []
