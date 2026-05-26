"""Phase D, D5a — onboarding PI interrupt-node tests.

Covers the 3 new PI interrupt nodes added to nodes/pi.py:
  - pi_onboarding_topic
  - pi_toolkit_ratify
  - pi_credentials_ready

Each test exercises the node's interrupt payload assembly + state-
update shape. The runner-level response-token mapping is tested
separately in test_runner_resume.py (those tests will be extended in
D5c when the interrupts are wired into the onboarding subgraph).
"""

from __future__ import annotations

from typing import Any

from orchestrator.nodes import pi


# ---------------------------------------------------------------------------
# Stub SDK + MCP — these interrupts don't use them, but the signature
# requires them.
# ---------------------------------------------------------------------------


class _StubSDK:
    def complete(self, **kw) -> str:
        return ""


class _StubMCP:
    workflow_thread_id = "thr_test"


def _capturing_interrupt(captured: list[dict]):
    """Return an interrupt_fn that records every payload + returns
    a deterministic "approve" so the node assigns the documented
    follow-up state shape."""
    def _fn(payload: dict) -> str:
        captured.append(payload)
        return "approve"
    return _fn


# ---------------------------------------------------------------------------
# pi_onboarding_topic
# ---------------------------------------------------------------------------


def test_pi_onboarding_topic_payload_shape():
    """The interrupt payload must include the canonical 'type',
    'title', and a prompt the PI's Claude session can render."""
    captured: list[dict] = []
    state = {"workflow_thread_id": "thr_t", "mission_id": "mis_t"}
    update = pi.pi_onboarding_topic(
        state, _StubSDK(), _StubMCP(), _capturing_interrupt(captured)
    )
    assert len(captured) == 1
    p = captured[0]
    assert p["type"] == "pi_onboarding_topic"
    assert "title" in p
    assert "prompt" in p
    # Body of the prompt mentions the things PI should answer.
    assert "summary" in p["prompt"].lower()
    assert "field" in p["prompt"].lower()
    assert "venue" in p["prompt"].lower()


def test_pi_onboarding_topic_captures_response_as_topic_summary():
    """PI's response string lands in topic_metadata.summary (Brain's
    research_toolkit_node reads it from there)."""
    captured: list[dict] = []
    def custom_interrupt(payload):
        captured.append(payload)
        return "IoT edge LLM hosting for smart-home intents; MLSys 2026"

    update = pi.pi_onboarding_topic(
        {}, _StubSDK(), _StubMCP(), custom_interrupt
    )
    assert "topic_metadata" in update
    assert update["topic_metadata"]["summary"] == (
        "IoT edge LLM hosting for smart-home intents; MLSys 2026"
    )


def test_pi_onboarding_topic_records_interrupt():
    captured: list[dict] = []
    update = pi.pi_onboarding_topic(
        {}, _StubSDK(), _StubMCP(), _capturing_interrupt(captured)
    )
    interrupts = update["interrupts"]
    assert len(interrupts) == 1
    assert interrupts[0]["node_name"] == "pi_onboarding_topic"


def test_pi_onboarding_topic_marks_current_node():
    captured: list[dict] = []
    update = pi.pi_onboarding_topic(
        {}, _StubSDK(), _StubMCP(), _capturing_interrupt(captured)
    )
    assert update["current_node"] == "pi_onboarding_topic"


# ---------------------------------------------------------------------------
# pi_toolkit_ratify
# ---------------------------------------------------------------------------


def test_pi_toolkit_ratify_surfaces_proposed_toolkit_in_payload():
    captured: list[dict] = []
    state = {
        "proposed_toolkit": [
            {"name": "rka", "type": "mcp_stdio"},
            {"name": "context7", "type": "mcp_stdio"},
            {"name": "sec-edgar", "type": "mcp_stdio"},
        ],
    }
    pi.pi_toolkit_ratify(
        state, _StubSDK(), _StubMCP(), _capturing_interrupt(captured)
    )
    payload = captured[0]
    assert payload["type"] == "pi_toolkit_ratify"
    assert payload["total_items"] == 3
    names = [t["name"] for t in payload["items"]]
    assert names == ["rka", "context7", "sec-edgar"]


def test_pi_toolkit_ratify_accept_copies_to_ratified_toolkit():
    """Set-identity semantics: on accept, every proposed tool moves
    to ratified_toolkit verbatim (mirrors Phase 2.7 T3d for
    proposed_actions → ratified_actions). The runner's response-token
    contract emits "accept" for pi_toolkit_ratify."""
    captured: list[dict] = []
    state = {
        "proposed_toolkit": [
            {"name": "rka"}, {"name": "context7"}, {"name": "sec-edgar"},
        ],
    }
    def accept_interrupt(payload):
        captured.append(payload)
        return "accept"
    update = pi.pi_toolkit_ratify(state, _StubSDK(), _StubMCP(), accept_interrupt)
    assert update["ratified_toolkit"] == state["proposed_toolkit"]


def test_pi_toolkit_ratify_reject_yields_empty_ratified_toolkit():
    captured: list[dict] = []
    state = {"proposed_toolkit": [{"name": "rka"}]}

    def reject(payload):
        captured.append(payload)
        return "reject"

    update = pi.pi_toolkit_ratify(state, _StubSDK(), _StubMCP(), reject)
    assert update["ratified_toolkit"] == []


def test_pi_toolkit_ratify_includes_brain_notes_when_present():
    """If state has a brain_position (set by research_toolkit_node when
    Brain emits notes_for_pi), the payload surfaces those notes so the
    PI can read the Brain's reasoning before deciding."""
    captured: list[dict] = []
    state = {
        "proposed_toolkit": [{"name": "rka"}],
        "brain_position": "I recommend skipping sec-edgar; this project is ML systems, not finance.",
    }
    pi.pi_toolkit_ratify(
        state, _StubSDK(), _StubMCP(), _capturing_interrupt(captured)
    )
    assert "brain_notes" in captured[0]
    assert "ML systems" in captured[0]["brain_notes"]


def test_pi_toolkit_ratify_batched_marker_when_over_threshold():
    """11+ proposed tools triggers the batched-review affordance
    (obs #15) just like pi_decision_select does."""
    captured: list[dict] = []
    state = {"proposed_toolkit": [{"name": f"t{i}"} for i in range(15)]}
    update = pi.pi_toolkit_ratify(
        state, _StubSDK(), _StubMCP(), _capturing_interrupt(captured)
    )
    assert update["batch_review_active"] is True
    assert update["batch_review_payload_size"] == 15
    assert captured[0].get("batched") is True


# ---------------------------------------------------------------------------
# pi_credentials_ready
# ---------------------------------------------------------------------------


def test_pi_credentials_ready_emits_path_and_secret_list_in_payload():
    captured: list[dict] = []
    state = {
        "project_id": "prj_test_abc",
        "proposed_toolkit": [
            {
                "name": "sec-edgar",
                "secrets": [
                    {
                        "name": "SEC_EDGAR_API_KEY",
                        "criticality": "required",
                        "description": "API key from sec.gov",
                    }
                ],
            },
            {
                "name": "context7",
                "secrets": [],  # no secrets — shouldn't appear in expected_secrets
            },
        ],
    }
    pi.pi_credentials_ready(
        state, _StubSDK(), _StubMCP(), _capturing_interrupt(captured)
    )
    payload = captured[0]
    assert payload["type"] == "pi_credentials_ready"
    # Project-id-derived path appears so the PI knows where to edit.
    assert "prj_test_abc" in payload["env_file_path"]
    # Expected-secrets list has one entry (the sec-edgar key); context7
    # contributes no secrets.
    secrets = payload["expected_secrets"]
    assert len(secrets) == 1
    assert secrets[0]["name"] == "SEC_EDGAR_API_KEY"
    assert secrets[0]["tool"] == "sec-edgar"
    assert secrets[0]["criticality"] == "required"


def test_pi_credentials_ready_payload_never_includes_secret_values():
    """Critical safety check: the interrupt payload (which lands in
    the Claude Code transcript) must never include actual credential
    values. The expected_secrets list carries names + metadata only.

    We DON'T pass env values into pi_credentials_ready (the .env file
    lives on disk; the node never reads it). This test confirms the
    payload doesn't accidentally surface anything that LOOKS like a
    value."""
    captured: list[dict] = []
    state = {
        "project_id": "prj_x",
        "proposed_toolkit": [
            {
                "name": "tool_x",
                "secrets": [{"name": "MY_KEY", "criticality": "required"}],
            }
        ],
    }
    pi.pi_credentials_ready(
        state, _StubSDK(), _StubMCP(), _capturing_interrupt(captured)
    )
    payload = captured[0]
    # No "value" key on any expected_secret entry.
    for s in payload["expected_secrets"]:
        assert "value" not in s
        # And no key with a name suggesting a value (defense in depth).
        for k in s.keys():
            assert "secret" not in k.lower() or k == "name"


def test_pi_credentials_ready_records_interrupt():
    captured: list[dict] = []
    state = {"project_id": "prj_x", "proposed_toolkit": []}
    update = pi.pi_credentials_ready(
        state, _StubSDK(), _StubMCP(), _capturing_interrupt(captured)
    )
    interrupts = update["interrupts"]
    assert interrupts[0]["node_name"] == "pi_credentials_ready"


def test_pi_credentials_ready_marks_current_node():
    captured: list[dict] = []
    update = pi.pi_credentials_ready(
        {"project_id": "p", "proposed_toolkit": []},
        _StubSDK(), _StubMCP(),
        _capturing_interrupt(captured),
    )
    assert update["current_node"] == "pi_credentials_ready"
