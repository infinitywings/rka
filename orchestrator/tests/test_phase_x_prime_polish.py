"""Phase-X²' polish — schema-divergence validation chain tests.

Companion file to test_rka_enums.py (helper unit tests) and the
test_executor.py / test_mcp_client.py additions (dispatcher + adapter
integration). This file covers the prompt-layer (Layer 3) and PI
diagnostic surface (Layer 4) corners that don't fit in either of those.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Layer 3 — Canonical field NAME block in BRAIN_SYSTEM + EXECUTOR_SYSTEM
# ---------------------------------------------------------------------------


def test_brain_system_includes_canonical_field_names_block() -> None:
    from orchestrator.nodes.brain import BRAIN_SYSTEM

    # The block must mention the load-bearing canonical names for the
    # 9 WRITE_TOOLS so Brain's prompt-time learning anchors correctly.
    assert "canonical field names" in BRAIN_SYSTEM
    # Per-tool canonical names that are NOT `content`.
    assert "rka_submit_checkpoint" in BRAIN_SYSTEM
    assert "rka_submit_report" in BRAIN_SYSTEM
    assert "`description`" in BRAIN_SYSTEM
    assert "`summary`" in BRAIN_SYSTEM
    assert "`objective`" in BRAIN_SYSTEM
    # Explicit negative callout for the empirical bug shape.
    assert "common Brain hallucination" in BRAIN_SYSTEM.lower() or (
        "common brain hallucination" in BRAIN_SYSTEM.lower()
    )
    assert "content" in BRAIN_SYSTEM  # mentioned in negative callout context


def test_executor_system_includes_canonical_field_names_block() -> None:
    from orchestrator.nodes.executor import EXECUTOR_SYSTEM

    assert "canonical field names" in EXECUTOR_SYSTEM
    assert "rka_submit_checkpoint" in EXECUTOR_SYSTEM
    assert "`description`" in EXECUTOR_SYSTEM
    assert "`summary`" in EXECUTOR_SYSTEM
    # Negative callout symmetric with BRAIN_SYSTEM.
    assert (
        "common Brain hallucination" in EXECUTOR_SYSTEM.lower()
        or "NOT `content`" in EXECUTOR_SYSTEM
    )


def test_brain_and_executor_prompts_mention_all_nine_write_tools() -> None:
    """Drift check — the canonical-name block should reference each of
    the 9 WRITE_TOOLS at least once. If a future PR adds a new
    WRITE_TOOL without updating the prompt block, this fails loudly.
    """
    from orchestrator.llm_client import WRITE_TOOLS
    from orchestrator.nodes.brain import BRAIN_SYSTEM
    from orchestrator.nodes.executor import EXECUTOR_SYSTEM

    for tool in WRITE_TOOLS:
        assert tool in BRAIN_SYSTEM, (
            f"BRAIN_SYSTEM missing canonical-name reference for "
            f"{tool}; update the Phase-X²' polish block"
        )
        assert tool in EXECUTOR_SYSTEM, (
            f"EXECUTOR_SYSTEM missing canonical-name reference for "
            f"{tool}; update the Phase-X²' polish block"
        )


# ---------------------------------------------------------------------------
# Layer 4 — PI diagnostic surface on pi_acceptance payload
# ---------------------------------------------------------------------------


class _RecordingInterrupt:
    """Records the payload passed to interrupt_fn so tests can inspect
    the shape of what the PI would see."""

    def __init__(self, response: str = "accept"):
        self.calls: list[dict] = []
        self._response = response

    def __call__(self, payload: dict) -> str:
        self.calls.append(payload)
        return self._response


def _minimal_state(**overrides) -> dict:
    """Construct a minimal ResearchWorkflowState dict for pi_acceptance."""
    base = {
        "artifacts": [],
        "errors": [],
        "checkpoints": [],
        "interrupts": [],
        "final_report_id": None,
        "usd_spent": 0.0,
    }
    base.update(overrides)
    return base


def test_pi_acceptance_surfaces_latest_error_type_when_errors_present() -> None:
    """When the run accumulated errors, pi_acceptance's payload must
    surface latest_error_type so the PI sees the specific escalation
    cause without drilling into errors[]. The ErrorRecord shape uses
    the canonical `detail` field (state.py:94) — adversarial-review
    HIGH fix made pi_acceptance read this canonical key."""
    from orchestrator.nodes.executor import _make_error
    from orchestrator.nodes.pi import pi_acceptance

    # Build the error via the SAME constructor the dispatcher uses, so
    # the test exercises the production ErrorRecord shape (not a
    # synthetic dict that could mask field-name drift).
    production_error = _make_error(
        "execute_ratified_actions",
        "ratified_action_arg_missing_required_field",
        "PA-1: tool='rka_submit_checkpoint' missing required field(s): "
        "description-alias-set missing",
    )
    state = _minimal_state(
        errors=[production_error],
        checkpoints=[
            {
                "id": "chk_test",
                "reason": "Schema mismatch on PA-2; description required.",
            }
        ],
    )
    interrupt_fn = _RecordingInterrupt(response="accept")
    pi_acceptance(state, sdk=None, mcp=None, interrupt_fn=interrupt_fn)

    assert len(interrupt_fn.calls) == 1
    payload = interrupt_fn.calls[0]
    item = payload["items"][0]
    assert item["latest_error_type"] == (
        "ratified_action_arg_missing_required_field"
    )
    assert item["latest_failed_tool"] == "rka_submit_checkpoint"
    assert "Schema mismatch" in item["latest_checkpoint_reason"]


def test_pi_acceptance_falls_back_to_reason_for_legacy_dicts() -> None:
    """Hand-constructed error dicts using the legacy `reason` field
    must still work — the extractor reads `detail` first then falls
    back to `reason`. Pins the back-compat fallback so future PRs
    can't silently drop it."""
    from orchestrator.nodes.pi import pi_acceptance

    state = _minimal_state(
        errors=[
            {
                "error_type": "some_legacy_error",
                "reason": "PA-2: tool='rka_add_note' failed via legacy path",
            }
        ],
    )
    interrupt_fn = _RecordingInterrupt(response="accept")
    pi_acceptance(state, sdk=None, mcp=None, interrupt_fn=interrupt_fn)

    item = interrupt_fn.calls[0]["items"][0]
    assert item["latest_failed_tool"] == "rka_add_note"


def test_pi_acceptance_fields_are_none_when_no_errors() -> None:
    """Happy-path: no errors, no checkpoints → top-level fields are
    None (NOT absent — keeps the payload shape stable for PI cockpit
    code that reads them unconditionally)."""
    from orchestrator.nodes.pi import pi_acceptance

    state = _minimal_state(final_report_id="rep_clean")
    interrupt_fn = _RecordingInterrupt(response="accept")
    pi_acceptance(state, sdk=None, mcp=None, interrupt_fn=interrupt_fn)

    item = interrupt_fn.calls[0]["items"][0]
    assert item["latest_error_type"] is None
    assert item["latest_failed_tool"] is None
    assert item["latest_checkpoint_reason"] is None


def test_pi_acceptance_failed_tool_extraction_handles_unrecognised_detail_shape() -> None:
    """If the error's detail text doesn't carry the canonical
    `tool='...'` substring, latest_failed_tool stays None — does NOT
    raise."""
    from orchestrator.nodes.pi import pi_acceptance

    state = _minimal_state(
        errors=[
            {
                "error_type": "some_other_error",
                "detail": "Free-form text without the canonical "
                          "tool= substring",
            }
        ],
    )
    interrupt_fn = _RecordingInterrupt(response="accept")
    pi_acceptance(state, sdk=None, mcp=None, interrupt_fn=interrupt_fn)

    item = interrupt_fn.calls[0]["items"][0]
    assert item["latest_error_type"] == "some_other_error"
    assert item["latest_failed_tool"] is None
