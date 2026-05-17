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
