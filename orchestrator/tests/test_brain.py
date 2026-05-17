"""Unit tests for the 6 Brain nodes (T3).

Each test injects fake SDK + MCP clients so no real LLM or MCP call
happens. The fakes record the call history so tests can assert what
prompts were issued and what MCP writes occurred.

Coverage per node:

  - state-update shape (returns dict with the documented keys)
  - MCP write was attempted with the right `tags` floor
  - Artifact record landed in the append-only `artifacts` collection
  - phase / current_node / position fields populated
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestrator.nodes import brain
from orchestrator.state import make_initial_state


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class FakeSDK:
    """Records every `complete()` call; returns a canned reply."""

    canned_reply: str = "fake LLM reply"
    calls: list[dict] = field(default_factory=list)

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> str:
        self.calls.append({"prompt": prompt, "max_tokens": max_tokens, "system": system})
        return self.canned_reply


@dataclass
class FakeMCP:
    """Captures every RKA call. `workflow_thread_id` is the auto-tag
    contract the real client honors."""

    workflow_thread_id: str = "thr_test_abc"
    note_id_counter: int = 0
    calls: list[dict] = field(default_factory=list)
    status_response: dict = field(default_factory=lambda: {"phase": "design"})
    context_response: dict = field(default_factory=lambda: {"recent": []})
    research_map_response: dict = field(default_factory=lambda: {"clusters": []})
    # Phase 2.5 T4: strategy_node + confirmation_brief now fetch the mission
    # body via rka_get_mission. Tests can override `mission_response` to
    # inject objective/tasks/AC/scope into the LLM prompt.
    mission_response: dict = field(default_factory=lambda: {"id": "mis_test_xyz"})

    def _record(self, op: str, **kw: Any) -> None:
        self.calls.append({"op": op, **kw})

    # --- reads ---
    def rka_get_status(self) -> dict:
        self._record("rka_get_status")
        return self.status_response

    def rka_get_context(self, topic: str | None = None, limit: int = 10) -> dict:
        self._record("rka_get_context", topic=topic, limit=limit)
        return self.context_response

    def rka_get_research_map(self) -> dict:
        self._record("rka_get_research_map")
        return self.research_map_response

    def rka_get_mission(self, id: str | None = None) -> dict:
        self._record("rka_get_mission", id=id)
        return self.mission_response

    # --- writes ---
    def rka_add_note(self, content: str, **kwargs: Any) -> str:
        self.note_id_counter += 1
        note_id = f"jrn_fake_{self.note_id_counter:03d}"
        self._record("rka_add_note", content=content, note_id=note_id, **kwargs)
        return note_id


def _initial_state() -> dict:
    return make_initial_state(
        workflow_thread_id="thr_test_abc",
        mission_id="mis_test_xyz",
        motivated_by_decision_id="dec_test_001",
    )


# ---------------------------------------------------------------------------
# 1. strategy_node
# ---------------------------------------------------------------------------


def test_strategy_node_returns_documented_state_update():
    sdk = FakeSDK(canned_reply="Strategy: do X, then Y.")
    mcp = FakeMCP()
    state = _initial_state()

    update = brain.strategy_node(state, sdk, mcp)

    assert update["current_phase"] == "brain_strategy"
    assert update["current_node"] == "strategy_node"
    assert update["brain_strategy"] == "Strategy: do X, then Y."
    assert update["brain_position"]  # populated, non-empty
    assert len(update["artifacts"]) == 1
    assert update["artifacts"][0]["rka_id"].startswith("jrn_")
    assert update["artifacts"][0]["entity_type"] == "journal"
    assert update["artifacts"][0]["node_name"] == "strategy_node"


def test_strategy_node_reads_context_and_status():
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = _initial_state()

    brain.strategy_node(state, sdk, mcp)

    ops = [c["op"] for c in mcp.calls]
    assert "rka_get_context" in ops
    assert "rka_get_status" in ops
    assert "rka_add_note" in ops


def test_strategy_node_tags_include_brain_strategy():
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = _initial_state()

    brain.strategy_node(state, sdk, mcp)
    note_call = next(c for c in mcp.calls if c["op"] == "rka_add_note")
    assert "brain-strategy" in note_call["tags"]


def test_strategy_node_sdk_prompt_references_mission_id():
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = _initial_state()

    brain.strategy_node(state, sdk, mcp)
    assert "mis_test_xyz" in sdk.calls[0]["prompt"]


# ---------------------------------------------------------------------------
# 2. confirmation_brief
# ---------------------------------------------------------------------------


def test_confirmation_brief_queues_decision_for_pi():
    sdk = FakeSDK(canned_reply="Confirmation brief draft.")
    mcp = FakeMCP()
    state = _initial_state()
    state["brain_strategy"] = "Some strategy"

    update = brain.confirmation_brief(state, sdk, mcp)

    assert update["current_phase"] == "brain_confirmation"
    assert update["current_node"] == "confirmation_brief"
    queued = update["decisions_to_present"]
    assert len(queued) == 1
    assert queued[0]["title"] == "Confirmation Brief"
    assert "approve" in queued[0]["options"]
    assert "redirect" in queued[0]["options"]


def test_confirmation_brief_writes_journal_with_confirmation_tag():
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = _initial_state()

    brain.confirmation_brief(state, sdk, mcp)
    note_call = next(c for c in mcp.calls if c["op"] == "rka_add_note")
    assert "confirmation-brief" in note_call["tags"]


def test_confirmation_brief_prompt_includes_existing_strategy():
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = _initial_state()
    state["brain_strategy"] = "Previously synthesized strategy text."

    brain.confirmation_brief(state, sdk, mcp)
    assert "Previously synthesized strategy text." in sdk.calls[0]["prompt"]


def test_strategy_node_includes_mission_body():
    """Phase 2.5 (mis_01KRVJ240VXH7NQ0PMSHXHK888 T4): strategy_node must
    fetch the mission via rka_get_mission and include objective + tasks +
    acceptance_criteria + scope_boundaries in the LLM prompt. Phase 2.4
    retry confirmed that without this, the brain produces a SKELETON
    Backbrief and gate1_validation correctly REDIRECTS."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    mcp.mission_response = {
        "id": "mis_test_xyz",
        "objective": "PROBE_OBJECTIVE_MARKER",
        "tasks": [
            {"description": "PROBE_TASK_ALPHA", "status": "pending"},
            {"description": "PROBE_TASK_BETA", "status": "pending"},
        ],
        "acceptance_criteria": "PROBE_ACCEPTANCE_MARKER",
        "scope_boundaries": "PROBE_SCOPE_MARKER",
    }
    state = _initial_state()

    brain.strategy_node(state, sdk, mcp)

    # rka_get_mission must have been called with the state's mission_id.
    mission_calls = [c for c in mcp.calls if c["op"] == "rka_get_mission"]
    assert mission_calls, "strategy_node must call rka_get_mission"
    assert mission_calls[0]["id"] == "mis_test_xyz"

    prompt = sdk.calls[0]["prompt"]
    for marker in (
        "PROBE_OBJECTIVE_MARKER",
        "PROBE_TASK_ALPHA",
        "PROBE_TASK_BETA",
        "PROBE_ACCEPTANCE_MARKER",
        "PROBE_SCOPE_MARKER",
    ):
        assert marker in prompt, f"strategy_node prompt missing mission body marker: {marker}"


def test_confirmation_brief_includes_mission_body():
    """Phase 2.5 T4 — same data-flow fix as strategy_node, applied to
    confirmation_brief so the PI-facing brief is grounded in mission body."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    mcp.mission_response = {
        "id": "mis_test_xyz",
        "objective": "CB_OBJECTIVE_MARKER",
        "tasks": [{"description": "CB_TASK_ALPHA", "status": "active"}],
        "acceptance_criteria": "CB_ACCEPTANCE_MARKER",
        "scope_boundaries": "CB_SCOPE_MARKER",
    }
    state = _initial_state()
    state["brain_strategy"] = "Prior strategy text."

    brain.confirmation_brief(state, sdk, mcp)

    mission_calls = [c for c in mcp.calls if c["op"] == "rka_get_mission"]
    assert mission_calls, "confirmation_brief must call rka_get_mission"
    assert mission_calls[0]["id"] == "mis_test_xyz"

    prompt = sdk.calls[0]["prompt"]
    for marker in (
        "CB_OBJECTIVE_MARKER",
        "CB_TASK_ALPHA",
        "CB_ACCEPTANCE_MARKER",
        "CB_SCOPE_MARKER",
    ):
        assert marker in prompt, f"confirmation_brief prompt missing mission body marker: {marker}"


# ---------------------------------------------------------------------------
# 3. decision_present
# ---------------------------------------------------------------------------


def test_decision_present_queues_three_option_decision():
    sdk = FakeSDK(canned_reply="Q: should we do X? Options: A | B | C.")
    mcp = FakeMCP()
    state = _initial_state()

    update = brain.decision_present(state, sdk, mcp)
    assert update["current_node"] == "decision_present"
    queued = update["decisions_to_present"]
    assert len(queued) == 1
    assert set(queued[0]["options"]) == {"accept", "modify", "reject"}
    assert queued[0]["source_node"] == "decision_present"


def test_decision_present_journals_draft_with_decision_draft_tag():
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = _initial_state()

    brain.decision_present(state, sdk, mcp)
    note_call = next(c for c in mcp.calls if c["op"] == "rka_add_note")
    assert "decision-draft" in note_call["tags"]


# ---------------------------------------------------------------------------
# 4. cluster_review
# ---------------------------------------------------------------------------


def test_cluster_review_reads_research_map():
    sdk = FakeSDK()
    mcp = FakeMCP(research_map_response={"clusters": [{"id": "ecl_1"}]})
    state = _initial_state()

    brain.cluster_review(state, sdk, mcp)
    ops = [c["op"] for c in mcp.calls]
    assert "rka_get_research_map" in ops
    # Research map content should land in the prompt
    assert "ecl_1" in sdk.calls[0]["prompt"]


def test_cluster_review_journals_with_cluster_review_tag():
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = _initial_state()

    update = brain.cluster_review(state, sdk, mcp)
    note_call = next(c for c in mcp.calls if c["op"] == "rka_add_note")
    assert "cluster-review" in note_call["tags"]
    assert update["current_phase"] == "brain_review"


# ---------------------------------------------------------------------------
# 5. gate1_validation
# ---------------------------------------------------------------------------


def test_gate1_validation_parses_approved_verdict():
    sdk = FakeSDK(canned_reply="APPROVED\n\nBackbrief covers all criteria.")
    mcp = FakeMCP()
    state = _initial_state()
    state["executor_backbrief"] = "Some backbrief"

    update = brain.gate1_validation(state, sdk, mcp)
    assert update["gate1_verdict"] == "approved"
    assert update["current_phase"] == "brain_review"


def test_gate1_validation_parses_redirected_verdict():
    sdk = FakeSDK(canned_reply="REDIRECTED\n\nMissing acceptance criterion #3.")
    mcp = FakeMCP()
    state = _initial_state()
    state["executor_backbrief"] = "Incomplete backbrief"

    update = brain.gate1_validation(state, sdk, mcp)
    assert update["gate1_verdict"] == "redirected"


def test_gate1_validation_default_falls_back_to_redirected():
    # Malformed first line → conservative default = redirected.
    sdk = FakeSDK(canned_reply="hmm I'm not sure")
    mcp = FakeMCP()
    state = _initial_state()

    update = brain.gate1_validation(state, sdk, mcp)
    assert update["gate1_verdict"] == "redirected"


def test_gate1_validation_tags_journal_with_verdict():
    sdk = FakeSDK(canned_reply="APPROVED — looks fine.")
    mcp = FakeMCP()
    state = _initial_state()

    brain.gate1_validation(state, sdk, mcp)
    note_call = next(c for c in mcp.calls if c["op"] == "rka_add_note")
    assert "gate1" in note_call["tags"]
    assert "verdict-approved" in note_call["tags"]


# ---------------------------------------------------------------------------
# 6. final_synthesis
# ---------------------------------------------------------------------------


def test_final_synthesis_sets_complete_terminal_state():
    sdk = FakeSDK(canned_reply="Final writeup.")
    mcp = FakeMCP()
    state = _initial_state()

    update = brain.final_synthesis(state, sdk, mcp)
    assert update["current_phase"] == "complete"
    assert update["terminal_state"] == "complete"
    assert update["current_node"] == "final_synthesis"


def test_final_synthesis_tags_journal_as_final_synthesis():
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = _initial_state()
    state["artifacts"] = [
        {"rka_id": "jrn_a", "entity_type": "journal", "node_name": "strategy_node"}
    ]

    brain.final_synthesis(state, sdk, mcp)
    note_call = next(c for c in mcp.calls if c["op"] == "rka_add_note")
    assert "final-synthesis" in note_call["tags"]
    assert note_call["importance"] == "critical"


def test_final_synthesis_prompt_references_accumulated_artifacts():
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = _initial_state()
    state["artifacts"] = [
        {"rka_id": "jrn_a", "entity_type": "journal", "node_name": "strategy_node"},
        {"rka_id": "jrn_b", "entity_type": "journal", "node_name": "cluster_review"},
    ]

    brain.final_synthesis(state, sdk, mcp)
    prompt = sdk.calls[0]["prompt"]
    assert "jrn_a" in prompt
    assert "jrn_b" in prompt


# ---------------------------------------------------------------------------
# Cross-cutting: all 6 nodes append exactly one artifact
# ---------------------------------------------------------------------------


def test_every_brain_node_appends_at_least_one_artifact():
    nodes = [
        brain.strategy_node,
        brain.confirmation_brief,
        brain.decision_present,
        brain.cluster_review,
        brain.gate1_validation,
        brain.final_synthesis,
    ]
    for fn in nodes:
        sdk = FakeSDK()
        mcp = FakeMCP()
        state = _initial_state()
        update = fn(state, sdk, mcp)
        assert update["artifacts"], f"{fn.__name__} did not append an artifact"
        assert update["artifacts"][0]["rka_id"].startswith("jrn_")


def test_every_brain_node_sets_current_node_name():
    nodes_and_names = [
        (brain.strategy_node, "strategy_node"),
        (brain.confirmation_brief, "confirmation_brief"),
        (brain.decision_present, "decision_present"),
        (brain.cluster_review, "cluster_review"),
        (brain.gate1_validation, "gate1_validation"),
        (brain.final_synthesis, "final_synthesis"),
    ]
    for fn, expected_name in nodes_and_names:
        sdk = FakeSDK()
        mcp = FakeMCP()
        state = _initial_state()
        update = fn(state, sdk, mcp)
        assert update["current_node"] == expected_name


def test_brain_system_prompt_present_on_every_call():
    nodes = [
        brain.strategy_node,
        brain.confirmation_brief,
        brain.decision_present,
        brain.cluster_review,
        brain.gate1_validation,
        brain.final_synthesis,
    ]
    for fn in nodes:
        sdk = FakeSDK()
        mcp = FakeMCP()
        state = _initial_state()
        fn(state, sdk, mcp)
        # Every Brain LLM call must carry the Brain system message.
        # Phase 2.1 (mis_01KRSTZVCTFGF91QZXTYK7ZGDD T1) extends BRAIN_SYSTEM
        # with per-node format hints at some call sites (gate1_validation
        # gets _GATE1_FORMAT; strategy_node gets _POSITION_FORMAT) — the
        # substring check honors both bare and extended forms.
        system = sdk.calls[0]["system"] or ""
        assert brain.BRAIN_SYSTEM in system, (
            f"{fn.__name__}: system_prompt must contain BRAIN_SYSTEM "
            f"(possibly extended with a format hint). Got: {system!r}"
        )


def test_BRAIN_SYSTEM_includes_phase_2_5_deltas():
    """Phase 2.5 (mis_01KRVJ240VXH7NQ0PMSHXHK888 T2): BRAIN_SYSTEM is
    extended with prose from 5 runtime-relevant deltas per the Brain-
    ratified Option-C scope (dec_01KRVHZ4P3F1GXE75RRAQX3BTP +
    chk_01KRVH890GKYCY9A28TM02STQ1):

      Delta #2  — Mid-mission Backbrief gate (token: "Gate cadence")
      Delta #7  — Conservative malformed-input defaults (token: "redirect, not approve")
      Delta #14a — Metric divergence-as-headline (token: "expected X, observed Y")
      Delta #15 — PI batch-review affordance (token: "batched=True")
      Delta #16 — Affordance F propagation (token: "workflow_thread_id")

    7 other deltas are SKIPPED-PYTHON (already enforced in orchestrator
    source code; tracked in skill-prompt-deltas.md with code-path
    references — see Phase 2.5 T6 metadata commit).
    """
    text = brain.BRAIN_SYSTEM
    # Base identity preserved (Phase 2.1 substring guarantee).
    assert "You are the Brain" in text

    # Phase 2.5 delta markers — each from a runtime-relevant delta.
    expected_markers = [
        ("delta #2 Gate cadence",       "Gate cadence"),
        ("delta #7 Conservative",       "redirect, not approve"),
        ("delta #14a Divergence",       "expected X, observed Y"),
        ("delta #15 PI batch-review",   "batched=True"),
        ("delta #16 Affordance F",      "workflow_thread_id"),
    ]
    missing = [label for label, marker in expected_markers if marker not in text]
    assert not missing, (
        f"BRAIN_SYSTEM missing Phase 2.5 delta markers: {missing}. "
        f"Each runtime-relevant delta's prose must include the substring "
        f"locked by this test so future refactors can't silently drop them."
    )
