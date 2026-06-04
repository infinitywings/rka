"""Phase 2.11 T3 — `decision_present` proposed_actions early-bypass regression tests.

Mission: `mis_01KRYT62XQK5NK3BY7G9BGRAPS` (Phase 2.11; Brain-ratified scope
per `dec_01KRYT1GCP5N9CJZ2YE2N3BTBH` Option A — two-item punch-list).

These tests lock the corrected contract for `brain.decision_present`:

- When `state["proposed_actions"]` is non-empty, the node MUST bypass the
  brain LLM call and build the PI-facing decision packet directly from
  the structured action list. Each action's `tool`, `args`, and `rationale`
  must appear in the packet content + a structured `proposed_actions`
  field on the `decisions_to_present` entry.
- When `state["proposed_actions"]` is empty or missing, the existing
  strategic-meta-decision flow (Phase 2.7 design) is preserved as the
  fall-through. Backward compatible.
- Phase 2.7 T3d mechanical copy `proposed_actions → ratified_actions` at
  `pi_decision_select` is unchanged and continues to work with the new
  packet shape.

This closes Phase 2.10 Finding 2 (decision_present decoupled from
state["proposed_actions"]; EC8 set-identity unverifiable by PI).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestrator.nodes import brain, pi
from orchestrator.state import make_initial_state


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _RecordingSDK:
    """SDKClient double that records every `complete()` call. T1's early-
    bypass path MUST NOT invoke complete() when proposed_actions is non-
    empty — we assert calls list is empty."""

    canned_reply: str = "strategic-meta-decision draft (should not appear)"
    calls: list[dict] = field(default_factory=list)

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        system: str | None = None,
        timeout_s: float | None = None,  # Phase S4 — accepted, ignored
    ) -> str:
        self.calls.append({"prompt": prompt, "max_tokens": max_tokens, "system": system})
        return self.canned_reply


@dataclass
class _RecordingMCP:
    """MCPClient double recording `rka_add_note` calls so tests can assert
    the journal entry contents include the proposed_actions verbatim."""

    workflow_thread_id: str = "thr_t3_test"
    add_note_calls: list[dict] = field(default_factory=list)
    add_decision_calls: list[dict] = field(default_factory=list)
    note_id_counter: int = 0

    def rka_add_note(self, content: str, **kwargs: Any) -> str:
        self.note_id_counter += 1
        rid = f"jrn_phase_2_11_t3_{self.note_id_counter:03d}"
        self.add_note_calls.append({"content": content, "id": rid, **kwargs})
        return rid

    def rka_add_decision(self, content: str, **kwargs: Any) -> str:
        rid = "dec_phase_2_11_t3_001"
        self.add_decision_calls.append({"content": content, "id": rid, **kwargs})
        return rid


def _state(proposed_actions: list[dict] | None = None) -> dict:
    s = make_initial_state(
        workflow_thread_id="thr_t3_test",
        mission_id="mis_t3_target",
        motivated_by_decision_id="dec_t3_motivator",
        project_id="prj_t3_test",
    )
    if proposed_actions is not None:
        s["proposed_actions"] = proposed_actions
    # Populate fields the strategic-meta-decision fall-through needs.
    s["brain_strategy"] = "strategy text (for fall-through path)"
    s["executor_position"] = "executor position summary"
    return s


def _sample_proposed_actions(n: int = 3) -> list[dict]:
    """3-item rka_update_note proposed_actions mirroring Phase 2.10's target
    mission's cross-reference items (jrn_01KQQ..., jrn_01KMX..., jrn_01KP4...)."""
    return [
        {
            "tool": "rka_update_note",
            "args": {
                "id": "jrn_01KQQ4K4GWFKHQBCQNC9F92JX4",
                "related_decisions": [
                    "dec_01KQNPC7A683HK0KRX1PAGNNED",
                    "dec_01KMX18FDAMN7T5YVZ7V8HV6RJ",
                    "dec_01KMX18FDAMN7T5YVZ7V8HV6RK",
                    "dec_01KP4P4QSSNZCTEHVT6QR7ZRYD",
                ],
            },
            "rationale": "4 IDs cited in Provenance section",
        },
        {
            "tool": "rka_update_note",
            "args": {
                "id": "jrn_01KMX18FDBEE9T8JNHHAP649TE",
                "related_decisions": ["dec_corpus_search_a", "dec_corpus_search_b"],
            },
            "rationale": "FTS5 brain-corpus search; project deletion feature",
        },
        {
            "tool": "rka_update_note",
            "args": {
                "id": "jrn_01KP4QR4XFP0ZHKR14B9ET6CN2",
                "related_decisions": ["dec_back_link_to_fix"],
            },
            "rationale": "Superseded bug; back-link to resolution",
        },
    ][:n]


# ---------------------------------------------------------------------------
# Test 1 — non-empty proposed_actions early-bypass
# ---------------------------------------------------------------------------


def test_decision_present_with_proposed_actions_builds_structured_packet():
    """Phase 2.11 T1 load-bearing assertion: when proposed_actions is
    non-empty, decision_present MUST (a) NOT invoke the brain LLM at all,
    (b) include each action's identity (tool, args.id, args.related_decisions,
    rationale) in the packet, (c) surface them structurally on the
    decisions_to_present entry so the driver / UI can render them."""
    sdk = _RecordingSDK()
    mcp = _RecordingMCP()
    proposed = _sample_proposed_actions(3)
    state = _state(proposed_actions=proposed)

    update = brain.decision_present(state, sdk, mcp)

    # (a) Brain LLM NOT invoked — Phase 2.11 T1 early-bypass.
    assert sdk.calls == [], (
        f"Phase 2.11 T1: brain LLM must NOT be invoked when "
        f"proposed_actions is non-empty; got {len(sdk.calls)} LLM call(s)"
    )

    # decisions_to_present has one entry; identity preserved.
    queued = update["decisions_to_present"]
    assert len(queued) == 1
    entry = queued[0]
    assert entry["source_node"] == "decision_present"
    assert entry["options"] == ["accept", "modify", "reject"]

    # (b) Packet content mentions all 3 tools + each args.id + each rationale.
    content = entry["context"]
    for action in proposed:
        assert action["tool"] in content, f"tool {action['tool']!r} missing from packet"
        assert action["args"]["id"] in content, f"args.id {action['args']['id']!r} missing"
        assert action["rationale"] in content, f"rationale missing from packet"

    # (c) Structured field surfaces the full proposed_actions list verbatim.
    assert entry.get("proposed_actions") == proposed, (
        "Phase 2.11 T1: decisions_to_present must carry the structured "
        "proposed_actions list for driver/UI rendering"
    )

    # Summary mentions the action count (test 4 explicit; included here too).
    assert "3 action" in entry["summary"]


# ---------------------------------------------------------------------------
# Test 2 — empty proposed_actions falls through to strategic path
# ---------------------------------------------------------------------------


def test_decision_present_without_proposed_actions_falls_through_to_strategic_path():
    """Phase 2.11 T1 backward compatibility: when proposed_actions is
    empty (Phase 2.10 mission_execute's actual emit) or missing, the
    existing strategic-meta-decision flow (Phase 2.7 design) is preserved.
    Brain LLM IS invoked; packet content is the LLM's strategic draft."""
    sdk = _RecordingSDK(canned_reply="Phase 2 Closure Threshold A/B/C/D meta-question")
    mcp = _RecordingMCP()

    # Case 2a: explicit empty list.
    state = _state(proposed_actions=[])
    update = brain.decision_present(state, sdk, mcp)
    assert len(sdk.calls) == 1, (
        "Phase 2.11 T1 fall-through: brain LLM MUST be invoked when "
        "proposed_actions is empty (strategic-meta-decision flow preserved)"
    )
    assert update["decisions_to_present"][0]["context"] == (
        "Phase 2 Closure Threshold A/B/C/D meta-question"
    )
    assert update["decisions_to_present"][0]["title"] == "Brain-drafted decision"
    # Strategic path has no `proposed_actions` field on the entry.
    assert "proposed_actions" not in update["decisions_to_present"][0]

    # Case 2b: proposed_actions key entirely missing from state.
    sdk2 = _RecordingSDK(canned_reply="another strategic draft")
    mcp2 = _RecordingMCP()
    state2 = _state()
    # Deliberately don't set proposed_actions at all.
    update2 = brain.decision_present(state2, sdk2, mcp2)
    assert len(sdk2.calls) == 1, (
        "Phase 2.11 T1 fall-through: missing proposed_actions key also "
        "routes to strategic-meta-decision flow"
    )


# ---------------------------------------------------------------------------
# Test 3 — pi_decision_select copies proposed → ratified on accept
#          (integration check with new packet shape)
# ---------------------------------------------------------------------------


def test_decision_present_then_pi_decision_select_copies_proposed_actions_to_ratified():
    """Phase 2.11 T1 × Phase 2.7 T3d integration check: the mechanical
    `proposed_actions → ratified_actions` copy at pi_decision_select MUST
    still work with the new packet shape from decision_present's early-
    bypass path. PI accepts; ratified_actions matches proposed exactly
    (EC8 set-identity guarantee)."""
    sdk = _RecordingSDK()
    mcp = _RecordingMCP()
    proposed = _sample_proposed_actions(3)
    state = _state(proposed_actions=proposed)

    # 1. decision_present builds the packet (early-bypass path).
    update_dp = brain.decision_present(state, sdk, mcp)
    # Merge update back into state to simulate workflow progression.
    state["decisions_to_present"] = update_dp["decisions_to_present"]

    # 2. pi_decision_select receives PI's "accept" response.
    class _AcceptInterrupt:
        captured_payloads: list[dict] = []

        def __call__(self, payload):
            self.captured_payloads.append(payload)
            return "accept"

    interrupt_fn = _AcceptInterrupt()
    update_pds = pi.pi_decision_select(state, sdk, mcp, interrupt_fn=interrupt_fn)

    # 3. EC8 set-identity: ratified_actions exactly equals proposed_actions.
    assert update_pds["ratified_actions"] == proposed, (
        f"Phase 2.11 T1 × Phase 2.7 T3d EC8 set-identity check: "
        f"ratified_actions must equal proposed_actions on accept; "
        f"got ratified={update_pds['ratified_actions']!r}"
    )

    # 4. The PI-facing payload contained the structured proposed_actions
    #    (driver can render them by identity).
    payload = interrupt_fn.captured_payloads[0]
    items = payload["items"]
    assert len(items) == 1
    # The decision packet entry has the structured proposed_actions field
    # from Phase 2.11 T1.
    assert items[0].get("proposed_actions") == proposed


# ---------------------------------------------------------------------------
# Test 4 — packet summary renders action count
# ---------------------------------------------------------------------------


def test_decision_present_packet_summary_renders_action_count():
    """Phase 2.11 T1: the packet summary mentions the action count so PI
    sees N at a glance without parsing items[]."""
    sdk = _RecordingSDK()
    mcp = _RecordingMCP()
    proposed = _sample_proposed_actions(2)
    state = _state(proposed_actions=proposed)

    update = brain.decision_present(state, sdk, mcp)
    entry = update["decisions_to_present"][0]
    summary = entry["summary"]

    assert "2 action" in summary, (
        f"summary must mention the action count; got {summary!r}"
    )
    # Title also mentions the count.
    assert "2 action" in entry["title"]
    # EC8 set-identity language present in the summary.
    assert "ratified" in summary.lower()


# ---------------------------------------------------------------------------
# Test 5 — early-bypass writes a journal note tagged for the workflow
# ---------------------------------------------------------------------------


def test_decision_present_early_bypass_writes_journal_with_proposed_actions_set_tag():
    """Phase 2.11 T1: the early-bypass path still journals the packet so
    workflow_thread_id tag lineage (Affordance F) is preserved. Tag set
    distinguishes the early-bypass packet from a strategic-meta-decision
    one (`decision-draft` + `proposed-actions-set`)."""
    sdk = _RecordingSDK()
    mcp = _RecordingMCP()
    proposed = _sample_proposed_actions(3)
    state = _state(proposed_actions=proposed)

    brain.decision_present(state, sdk, mcp)

    # One rka_add_note call (the packet body).
    assert len(mcp.add_note_calls) == 1
    call = mcp.add_note_calls[0]
    assert "decision-draft" in call["tags"]
    assert "proposed-actions-set" in call["tags"]
    assert call["source"] == "brain"
    assert call["type"] == "note"
    assert call["related_mission"] == "mis_t3_target"
