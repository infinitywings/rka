"""Phase 2.1 (mis_01KRSTZVCTFGF91QZXTYK7ZGDD T1) — prompt-led structured
prefix tests.

The Phase 2 pilot revealed that Phase 1's `PilotSDK` returned hardcoded
strings (e.g., 'APPROVED\\n...') that satisfied downstream parsers verbatim;
real Claude returns free-form prose that doesn't carry those tokens. Phase
2.1 fixes this by extending node system_prompts with explicit format
requirements (option (a) from chk_01KRSTFD7203NWAR8MYD91KSFV; tool-use
option (b) deferred to a hypothetical Phase 2.2).

These tests lock the format-hint wiring at two load-bearing sites:

  - gate1_validation: must extend BRAIN_SYSTEM with _GATE1_FORMAT so
    Claude's first-line token (APPROVED:/REDIRECTED:) is parseable by
    _parse_gate1_verdict. Failure here routes to escalation_router and
    cascades into the v2.5.3+agentic-rc1 422.
  - strategy_node: must extend BRAIN_SYSTEM with _POSITION_FORMAT so
    state["brain_position"] (captured by _summarize_position) is a clean
    one-line summary instead of Claude's verbose preamble.

Tests use the existing FakeSDK pattern from test_brain.py — captures
prompt + system per call. No real SDK calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestrator import state as orchestrator_state
from orchestrator.nodes import brain


@dataclass
class _FakeSDK:
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
class _FakeMCP:
    workflow_thread_id: str = "thr_test_phase_2_1"
    note_id_counter: int = 0
    calls: list[dict] = field(default_factory=list)

    def _record(self, op: str, **kw: Any) -> None:
        self.calls.append({"op": op, **kw})

    def rka_get_status(self) -> dict:
        self._record("rka_get_status")
        return {"phase": "design"}

    def rka_get_context(self, topic: str | None = None, limit: int = 10) -> dict:
        self._record("rka_get_context", topic=topic, limit=limit)
        return {"recent": []}

    def rka_add_note(self, content: str, **kwargs: Any) -> str:
        self.note_id_counter += 1
        note_id = f"jrn_phase_2_1_{self.note_id_counter:03d}"
        self._record("rka_add_note", content=content, note_id=note_id, **kwargs)
        return note_id


def _initial_state() -> dict:
    return orchestrator_state.make_initial_state(
        workflow_thread_id="thr_test_phase_2_1",
        mission_id="mis_test_xyz",
        motivated_by_decision_id="dec_test_001",
    )


# ---------------------------------------------------------------------------
# Parser-level tests — _parse_gate1_verdict handles realistic prefix output
# ---------------------------------------------------------------------------


class TestParseGate1VerdictHandlesPrefixedClaudeProse:
    """The prefix parser's `"APPROVED" in first` substring check already
    handles both bare-token ('APPROVED') and prefixed ('APPROVED: ...').
    These tests lock that contract so future parser refactors don't lose
    the prefix-handling property."""

    def test_approved_colon_prefix_with_prose(self):
        verdict_text = (
            "APPROVED: The Backbrief covers all acceptance criteria, the "
            "assumptions are explicit and falsifiable, and the bookkeeper "
            "invariant is honored. No risks require escalation.\n\n"
            "Detail: ..."
        )
        assert brain._parse_gate1_verdict(verdict_text) == "approved"

    def test_redirected_colon_prefix_with_prose(self):
        verdict_text = (
            "REDIRECTED: Assumption A2 lacks a falsifiability criterion and "
            "Risk R1 doesn't name a mitigation. Recommend revisiting before "
            "proceeding to mission_execute.\n\n"
            "Detail: ..."
        )
        assert brain._parse_gate1_verdict(verdict_text) == "redirected"

    def test_approved_bare_token_legacy_path_still_works(self):
        """Phase 1 FakeSDK returned bare 'APPROVED'; the parser must
        keep accepting that shape so the inherited Phase 1 tests pass."""
        verdict_text = "APPROVED\nLooks good."
        assert brain._parse_gate1_verdict(verdict_text) == "approved"

    def test_no_approved_token_anywhere_routes_to_redirected(self):
        """Defensive: if Claude ignores the format requirement (or the
        format hint is dropped from system_prompt), the parser still
        gives a deterministic answer. 'Redirected' is the safe default
        — it routes to escalation_router instead of mission_execute."""
        verdict_text = (
            "I have reviewed the Backbrief carefully. The assumptions "
            "are partially specified but the risk register is complete.\n"
            "Recommendation: proceed."
        )
        assert brain._parse_gate1_verdict(verdict_text) == "redirected"


# ---------------------------------------------------------------------------
# Wiring tests — gate1_validation and strategy_node hand the format hint to sdk
# ---------------------------------------------------------------------------


class TestNodesPassFormatHintInSystemPrompt:
    """T1 wiring lock — the format-hint constants must actually reach the
    SDK's system_prompt arg at the relevant nodes. Phase 2.1 -> final tag."""

    def test_gate1_validation_extends_system_with_gate1_format(self):
        sdk = _FakeSDK(canned_reply="APPROVED: looks fine.")
        mcp = _FakeMCP()
        state = _initial_state()
        state["executor_backbrief"] = "Backbrief text."

        brain.gate1_validation(state, sdk, mcp)

        assert len(sdk.calls) == 1
        system = sdk.calls[0]["system"] or ""
        # Must contain both the base Brain identity AND the gate1 format hint.
        assert "Brain" in system, f"expected base BRAIN_SYSTEM; got {system!r}"
        assert "APPROVED:" in system, (
            "gate1_validation's system_prompt must extend BRAIN_SYSTEM with "
            "_GATE1_FORMAT so real Claude prefixes with APPROVED: or "
            "REDIRECTED: (the cascade-fix for v2.5.3+agentic-rc1)."
        )
        assert "REDIRECTED:" in system

    def test_strategy_node_extends_system_with_position_format(self):
        sdk = _FakeSDK(
            canned_reply=(
                "Strategy in one line: enumerate v2.5.x missions, surface "
                "Phase-3 gaps, propose Phase 2.1 closure.\n\n"
                "Detail follows..."
            )
        )
        mcp = _FakeMCP()
        state = _initial_state()

        brain.strategy_node(state, sdk, mcp)

        assert len(sdk.calls) == 1
        system = sdk.calls[0]["system"] or ""
        assert "Brain" in system
        assert "position summary" in system.lower() or "one-line" in system.lower(), (
            "strategy_node's system_prompt should extend BRAIN_SYSTEM with "
            "_POSITION_FORMAT so the first-line of Claude's reply is a "
            "clean one-line summary (consumed by _summarize_position)."
        )


# ---------------------------------------------------------------------------
# Soft-parser smoke — _summarize_position handles realistic claude output
# ---------------------------------------------------------------------------


class TestSummarizePositionHandlesRealisticClaudeOutput:
    """_summarize_position takes the first line. With _POSITION_FORMAT
    instructing Claude to lead with a one-line summary, the result is a
    clean position statement. Without it, it'd be a verbose preamble like
    'I will now synthesize a strategy for this mission...' which is unhelpful
    but doesn't crash. These tests lock the truncation contract."""

    def test_first_line_summary_passes_through(self):
        text = (
            "Strategy: enumerate v2.5.x missions, surface gaps, propose closure.\n"
            "\n"
            "Detail:\n"
            "1. ...\n"
        )
        result = brain._summarize_position(text)
        assert result == "Strategy: enumerate v2.5.x missions, surface gaps, propose closure."

    def test_long_first_line_truncated_with_ellipsis(self):
        text = "x" * 500
        result = brain._summarize_position(text, max_chars=100)
        assert len(result) == 100
        assert result.endswith("…")

    def test_empty_input_yields_empty_string(self):
        assert brain._summarize_position("") == ""
