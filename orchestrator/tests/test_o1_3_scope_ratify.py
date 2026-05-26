"""Phase O, O1.3 — pi_scope_ratify (TWO-TAP) tests.

Covers:
  - pi_scope_ratify payload shape: items, title, rendered_markdown,
    two_tap_required, two_tap_label
  - markdown renderer: every PolishedIdea field appears; missing fields
    render "(unspecified)"; empty optional lists are omitted
  - accept path: scope_ratified=True, no brain_position write
  - reject path (literal 'reject'): scope_ratified=False, no
    brain_position write (loops back to capture_idea, not to polish)
  - correct path (freeform text): scope_ratified=False AND
    brain_position carries the redirection
  - InterruptRecord captures node_name + response + payload_size
  - parked_store accepts pi_scope_ratify type
  - runner _ACCEPT_TOKEN_BY_TYPE maps pi_scope_ratify → 'accept'
  - runner _ONBOARDING_INTERRUPT_TYPES contains pi_scope_ratify
  - graph.ONBOARDING_NODE_NAMES contains pi_scope_ratify
"""

from __future__ import annotations

import pytest

from orchestrator import graph
from orchestrator.nodes import pi
from orchestrator.nodes.pi import _render_polished_idea_markdown
from orchestrator.parked_store import ParkedStore
from orchestrator.runner import _ACCEPT_TOKEN_BY_TYPE, OrchestratorRunner

from tests._fakes import FakeMCP, FakeSDK


# ---------------------------------------------------------------------------
# _render_polished_idea_markdown
# ---------------------------------------------------------------------------


def test_render_polished_idea_includes_all_required_fields():
    p = {
        "research_question": "Can edge LLMs hit 5 tok/s?",
        "motivation": "Privacy matters.",
        "scope": "1-3B params on Pi 5.",
        "novelty_hypothesis": "No prior INT4 work on Pi 5.",
        "target_venue": "MLSys 2026",
        "open_assumptions": ["thermal headroom"],
        "ingested_sources": ["jrn_AA"],
    }
    md = _render_polished_idea_markdown(p)
    assert "Can edge LLMs hit 5 tok/s?" in md
    assert "Privacy matters" in md
    assert "Pi 5" in md
    assert "No prior INT4" in md
    assert "MLSys 2026" in md
    assert "thermal headroom" in md
    assert "jrn_AA" in md
    # Section headers present.
    assert "## Research question" in md
    assert "## Motivation" in md
    assert "## Scope" in md
    assert "## Novelty hypothesis" in md
    assert "## Open assumptions" in md
    assert "## Backed by ingested sources" in md


def test_render_polished_idea_missing_fields_fallback():
    md = _render_polished_idea_markdown({})
    assert "(unspecified)" in md
    # Optional sections skipped when empty.
    assert "Open assumptions" not in md
    assert "Backed by ingested sources" not in md


def test_render_polished_idea_handles_non_dict():
    assert "no polished idea" in _render_polished_idea_markdown(None).lower()
    assert "no polished idea" in _render_polished_idea_markdown("string").lower()


def test_render_polished_idea_target_venue_unspecified():
    p = {
        "research_question": "x",
        "motivation": "y",
        "scope": "z",
        "novelty_hypothesis": "w",
    }
    md = _render_polished_idea_markdown(p)
    assert "(none specified)" in md  # target_venue fallback


# ---------------------------------------------------------------------------
# pi_scope_ratify payload + TWO-TAP metadata
# ---------------------------------------------------------------------------


_POLISHED = {
    "research_question": "Can edge LLMs hit 5 tok/s on Pi 5?",
    "motivation": "On-device LLMs unlock private personalization.",
    "scope": "In: 1-3B. Out: GPUs.",
    "novelty_hypothesis": "INT4 quant on Pi 5 not measured before.",
    "target_venue": "MLSys 2026",
    "ingested_sources": ["jrn_A", "jrn_B"],
    "open_assumptions": ["thermal"],
}


def _state_with_polished() -> dict:
    return {
        "project_id": "prj_test_01",
        "current_phase": "init",
        "polished_idea": _POLISHED,
    }


def test_pi_scope_ratify_payload_shape():
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return "accept"

    pi.pi_scope_ratify(_state_with_polished(), FakeSDK(), FakeMCP(), fake_interrupt)

    p = captured["payload"]
    assert p["type"] == "pi_scope_ratify"
    assert "TWO-TAP" in p["title"]
    assert p["items"] == [_POLISHED]
    assert p["total_items"] == 1
    assert p["two_tap_required"] is True
    assert "Confirm" in p["two_tap_label"]
    # Pre-rendered markdown present.
    assert "Pi 5" in p["rendered_markdown"]
    assert "## Research question" in p["rendered_markdown"]


def test_pi_scope_ratify_empty_polished_idea_still_renders():
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return "reject"

    out = pi.pi_scope_ratify(
        {"project_id": "p1", "polished_idea": {}},
        FakeSDK(),
        FakeMCP(),
        fake_interrupt,
    )
    # Empty polish → items list is empty.
    assert captured["payload"]["items"] == []
    assert out["scope_ratified"] is False


# ---------------------------------------------------------------------------
# Accept / reject / correct routing
# ---------------------------------------------------------------------------


def test_pi_scope_ratify_accept_sets_scope_ratified_true():
    def fake_interrupt(_p):
        return "accept"

    out = pi.pi_scope_ratify(_state_with_polished(), FakeSDK(), FakeMCP(), fake_interrupt)
    assert out["scope_ratified"] is True
    assert out["current_node"] == "pi_scope_ratify"
    assert "brain_position" not in out


def test_pi_scope_ratify_bare_reject_clears_without_brain_position():
    def fake_interrupt(_p):
        return "reject"

    out = pi.pi_scope_ratify(_state_with_polished(), FakeSDK(), FakeMCP(), fake_interrupt)
    assert out["scope_ratified"] is False
    # No brain_position write — bare reject means "abandon this draft",
    # not "redirect to alternative framing".
    assert "brain_position" not in out


def test_pi_scope_ratify_correct_carries_redirect_text_to_brain_position():
    redirection = (
        "Reframe: instead of Pi 5, scope to NVIDIA Jetson — broader thermal "
        "headroom + better quantization support."
    )

    def fake_interrupt(_p):
        return redirection

    out = pi.pi_scope_ratify(_state_with_polished(), FakeSDK(), FakeMCP(), fake_interrupt)
    assert out["scope_ratified"] is False
    assert out["brain_position"] == redirection


def test_pi_scope_ratify_correct_truncates_long_redirection():
    long_text = "rewrite scope " * 1000
    out = pi.pi_scope_ratify(
        _state_with_polished(), FakeSDK(), FakeMCP(), lambda _p: long_text
    )
    assert len(out["brain_position"]) == 5000


def test_pi_scope_ratify_emits_interrupt_record():
    out = pi.pi_scope_ratify(
        _state_with_polished(), FakeSDK(), FakeMCP(), lambda _p: "accept"
    )
    assert len(out["interrupts"]) == 1
    rec = out["interrupts"][0]
    assert rec["node_name"] == "pi_scope_ratify"
    assert rec["response"] == "accept"
    assert rec["payload_size"] == 1


# ---------------------------------------------------------------------------
# Schema + registry wiring
# ---------------------------------------------------------------------------


def test_parked_store_accepts_pi_scope_ratify():
    store = ParkedStore(":memory:")
    thread_id = store.create_run(mission_id="prj_x", project_id="prj_x")
    iid = store.park_interrupt(
        workflow_thread_id=thread_id,
        mission_id="prj_x",
        interrupt_type="pi_scope_ratify",
        payload={"type": "pi_scope_ratify", "title": "x"},
    )
    assert iid.startswith("int_")
    store.close()


def test_runner_accept_token_for_scope_ratify_is_accept():
    assert _ACCEPT_TOKEN_BY_TYPE["pi_scope_ratify"] == "accept"


def test_runner_recognizes_pi_scope_ratify_as_onboarding():
    assert "pi_scope_ratify" in OrchestratorRunner._PHASE_O_INTERRUPT_TYPES


def test_graph_onboarding_node_names_include_pi_scope_ratify():
    assert "pi_scope_ratify" in graph.ONBOARDING_NODE_NAMES
