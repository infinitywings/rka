"""Gap 3B — Brain proposes capabilities, PI ratifies at pi_greenlight.

The Brain's strategy_node reply may include a ```json fenced block of
the form `{"capabilities": ["record_knowledge", ...]}` declaring the
smallest write-capability set the run needs. pi_greenlight on accept
copies this into state["allowed_capabilities"], overriding any
mission-set value from Gap 3A. The orchestrator's
execute_ratified_actions then enforces the narrowed scope.
"""

from __future__ import annotations

from orchestrator.nodes import brain as brain_module
from orchestrator.nodes import pi as pi_module
from orchestrator.state import make_initial_state
from tests._fakes import FakeMCP, FakeSDK


# ---------------------------------------------------------------------------
# _parse_proposed_capabilities
# ---------------------------------------------------------------------------


def test_parse_no_fenced_block_returns_empty():
    assert brain_module._parse_proposed_capabilities("just prose") == []


def test_parse_extracts_known_capabilities():
    reply = """
position summary

Detail.

```json
{"capabilities": ["record_knowledge", "execution_gates"]}
```
"""
    assert brain_module._parse_proposed_capabilities(reply) == [
        "record_knowledge",
        "execution_gates",
    ]


def test_parse_filters_unknown_capabilities():
    reply = '```json\n{"capabilities": ["record_knowledge", "fake_cap"]}\n```'
    assert brain_module._parse_proposed_capabilities(reply) == ["record_knowledge"]


def test_parse_dedupes_preserving_order():
    reply = (
        '```json\n{"capabilities": '
        '["record_knowledge", "execution_gates", "record_knowledge"]}\n```'
    )
    assert brain_module._parse_proposed_capabilities(reply) == [
        "record_knowledge",
        "execution_gates",
    ]


def test_parse_ignores_non_list_value():
    reply = '```json\n{"capabilities": "record_knowledge"}\n```'
    assert brain_module._parse_proposed_capabilities(reply) == []


def test_parse_ignores_missing_key():
    reply = '```json\n{"other_field": "x"}\n```'
    assert brain_module._parse_proposed_capabilities(reply) == []


def test_parse_handles_malformed_json():
    reply = '```json\n{capabilities: bad json}\n```'
    assert brain_module._parse_proposed_capabilities(reply) == []


def test_parse_ignores_top_level_non_object():
    reply = '```json\n["record_knowledge"]\n```'
    assert brain_module._parse_proposed_capabilities(reply) == []


def test_parse_ignores_non_string_entries():
    reply = '```json\n{"capabilities": ["record_knowledge", 123, null]}\n```'
    assert brain_module._parse_proposed_capabilities(reply) == ["record_knowledge"]


# ---------------------------------------------------------------------------
# strategy_node writes proposed_capabilities to state
# ---------------------------------------------------------------------------


def test_strategy_node_writes_proposed_capabilities():
    """When Brain's reply contains a capabilities block, strategy_node
    writes proposed_capabilities into the state update."""
    sdk = FakeSDK(
        canned_reply=(
            "Strategy summary line\n\n"
            'Some detail.\n\n```json\n'
            '{"capabilities": ["record_knowledge", "execution_gates"]}\n```'
        )
    )
    mcp = FakeMCP()
    state = make_initial_state(
        workflow_thread_id="thr_t",
        mission_id="mis_t",
        motivated_by_decision_id="dec_t",
    )

    update = brain_module.strategy_node(state, sdk, mcp)

    assert update["proposed_capabilities"] == [
        "record_knowledge",
        "execution_gates",
    ]


def test_strategy_node_omits_key_when_no_proposal():
    """Brain may omit the capabilities block — backward compat. State
    update should not even contain the key (leaves prior value
    untouched if any)."""
    sdk = FakeSDK(canned_reply="Just plain strategy text, no JSON")
    mcp = FakeMCP()
    state = make_initial_state(
        workflow_thread_id="thr_t",
        mission_id="mis_t",
        motivated_by_decision_id="dec_t",
    )

    update = brain_module.strategy_node(state, sdk, mcp)

    assert "proposed_capabilities" not in update


# ---------------------------------------------------------------------------
# pi_greenlight on accept copies proposed_capabilities → allowed_capabilities
# ---------------------------------------------------------------------------


def _state_with_proposal(proposed: list[str], pending_items: int = 1) -> dict:
    state = make_initial_state(
        workflow_thread_id="thr_t",
        mission_id="mis_t",
        motivated_by_decision_id="dec_t",
    )
    state["proposed_capabilities"] = proposed
    state["decisions_to_present"] = [
        {"source_node": "confirmation_brief", "content": "test"}
        for _ in range(pending_items)
    ]
    return state


def test_pi_greenlight_accept_copies_capabilities_to_allowed():
    state = _state_with_proposal(["record_knowledge", "execution_gates"])

    update = pi_module.pi_greenlight(
        state, FakeSDK(), FakeMCP(), lambda payload: "accept"
    )

    assert update["allowed_capabilities"] == ["record_knowledge", "execution_gates"]


def test_pi_greenlight_accept_with_empty_proposal_does_not_set_allowed():
    """Empty proposal = no override — leaves mission-set allowed_caps
    intact. Key isn't written to update so the workflow state preserves
    whatever Gap 3A set."""
    state = _state_with_proposal([])

    update = pi_module.pi_greenlight(
        state, FakeSDK(), FakeMCP(), lambda payload: "accept"
    )

    assert "allowed_capabilities" not in update


def test_pi_greenlight_reject_does_not_copy_capabilities():
    """Reject leaves allowed_capabilities alone. Brain's proposed_caps
    stays in state for re-runs."""
    state = _state_with_proposal(["record_knowledge"])

    update = pi_module.pi_greenlight(
        state, FakeSDK(), FakeMCP(), lambda payload: "reject"
    )

    assert "allowed_capabilities" not in update


def test_pi_greenlight_correct_does_not_copy_capabilities():
    """Correct (redirect) leaves allowed_caps untouched. Brain will
    re-propose on the next strategy pass."""
    from orchestrator.response_tokens import REDIRECT_SENTINEL

    state = _state_with_proposal(["record_knowledge"])

    redirect = REDIRECT_SENTINEL + "Narrow further to execution_gates only"
    update = pi_module.pi_greenlight(
        state, FakeSDK(), FakeMCP(), lambda payload: redirect
    )

    assert "allowed_capabilities" not in update


def test_pi_greenlight_payload_surfaces_proposed_capabilities():
    """The interrupt payload includes proposed_capabilities so the PI's
    Claude session can render them for ratification."""
    captured: list[dict] = []
    state = _state_with_proposal(["record_knowledge"])

    pi_module.pi_greenlight(
        state, FakeSDK(), FakeMCP(),
        lambda payload: (captured.append(payload), "accept")[1],
    )

    assert captured[0]["proposed_capabilities"] == ["record_knowledge"]


def test_pi_greenlight_payload_omits_empty_proposed_capabilities():
    """No Brain proposal = no key in payload (cleaner PI UX)."""
    captured: list[dict] = []
    state = _state_with_proposal([])

    pi_module.pi_greenlight(
        state, FakeSDK(), FakeMCP(),
        lambda payload: (captured.append(payload), "accept")[1],
    )

    assert "proposed_capabilities" not in captured[0]


# ---------------------------------------------------------------------------
# Substring-routing exploit: redirect-with-"accept"-substring is NOT accept
# ---------------------------------------------------------------------------


def test_pi_greenlight_redirect_with_accept_substring_does_not_grant_capabilities():
    """REDIRECT_SENTINEL prefix means redirect — even if the message
    contains 'accept' (e.g., 'I cannot accept this'). The Phase D2.1
    sentinel routing applies here too: allowed_capabilities must NOT be
    copied on a redirect."""
    from orchestrator.response_tokens import REDIRECT_SENTINEL

    state = _state_with_proposal(["record_knowledge"])
    update = pi_module.pi_greenlight(
        state, FakeSDK(), FakeMCP(),
        lambda payload: REDIRECT_SENTINEL + "I cannot accept this scope",
    )
    assert "allowed_capabilities" not in update
