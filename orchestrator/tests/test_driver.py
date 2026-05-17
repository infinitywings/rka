"""Unit tests for `orchestrator.scripts.driver` (Phase 2.4 T1).

3 tests covering: (a) argv parsing rejects missing --mission-id; (b) mission
load surfaces a clean error if the mission doesn't exist (returns exit 2,
not a traceback); (c) `interactive_interrupt` translates the canonical
PI responses ("a", "r", "c <text>", freeform) into the correct return values
without prompting (stdin redirected for tests).
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import driver as driver_module  # noqa: E402


# ---------------------------------------------------------------------------
# (a) argv parsing — missing required --mission-id surfaces SystemExit(2)
# ---------------------------------------------------------------------------


def test_main_without_mission_id_exits_with_argparse_error(capsys):
    """argparse fires SystemExit(2) when a required arg is missing. The
    driver's main() lets that propagate cleanly — no traceback into
    sys.excepthook."""
    with pytest.raises(SystemExit) as exc_info:
        driver_module.main([])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "--mission-id" in captured.err


# ---------------------------------------------------------------------------
# (b) mission load — missing mission exits 2 with a clear message, not a crash
# ---------------------------------------------------------------------------


def test_main_returns_2_when_mission_load_fails(capsys, monkeypatch):
    """If `rka_get_mission` returns an empty/None result, the driver exits 2
    with a stderr message naming the missing mission ID — no SDK construction,
    no graph build."""

    class _FakeMCP:
        def __init__(self, *args, **kwargs):
            self.workflow_thread_id = kwargs.get("workflow_thread_id", "thr_test")

        def rka_get_status(self):
            return {"current_phase": "design"}

        def rka_get_mission(self, id=None):
            return None  # mission not found

    monkeypatch.setattr(driver_module, "make_client", _FakeMCP)
    # make_sdk should NOT be called — guard it so any accidental call surfaces
    monkeypatch.setattr(
        driver_module,
        "make_sdk",
        lambda: pytest.fail("make_sdk() must not be called when mission load fails"),
    )

    rc = driver_module.main(
        ["--mission-id", "mis_does_not_exist", "--checkpoint-db", ":memory:"]
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "mis_does_not_exist" in captured.err
    assert "not found" in captured.err.lower()


# ---------------------------------------------------------------------------
# (c) interactive_interrupt — response-string translation contract
# ---------------------------------------------------------------------------


class TestInteractiveInterrupt:
    """The interrupt handler must accept the canonical operator inputs AND
    return a token that matches the orchestrator's routing contract for the
    given interrupt type (chk_01KRVG6GE119ASG26QKXH0N5D2 root cause)."""

    def _run_with_input(self, monkeypatch, input_text: str, payload: dict | None = None) -> str:
        monkeypatch.setattr("builtins.input", lambda _prompt="": input_text)
        return driver_module.interactive_interrupt(payload or {"type": "pi_greenlight"})

    def test_accept_shortcut_returns_approve_for_pi_greenlight(self, monkeypatch, capsys):
        """REGRESSION-LOCK (chk_01KRVG6GE119ASG26QKXH0N5D2): pi_greenlight is
        routed via `"approve" in response` in graph.py:_route_after_pi_greenlight.
        The `a` shortcut MUST return "approve" (NOT "accept") for greenlight,
        or the graph short-circuits to escalation_router and skips 7 nodes
        including pi_decision_select."""
        result = self._run_with_input(
            monkeypatch, "a", payload={"type": "pi_greenlight"}
        )
        assert result == "approve", (
            f"pi_greenlight + `a` MUST return 'approve' (graph.py routes via "
            f"\"approve\" in response); got {result!r}. This is the "
            f"first-run-short-circuit root cause."
        )

    def test_accept_shortcut_returns_accept_for_pi_decision_select(self, monkeypatch, capsys):
        """pi_decision_select is routed via `"accept" in response`. The `a`
        shortcut returns "accept" for this type."""
        result = self._run_with_input(
            monkeypatch, "a", payload={"type": "pi_decision_select"}
        )
        assert result == "accept"

    def test_accept_shortcut_returns_accept_for_pi_acceptance(self, monkeypatch, capsys):
        """pi_acceptance is a terminal node — response is recorded but doesn't
        drive routing. "accept" is the conventional token."""
        result = self._run_with_input(
            monkeypatch, "a", payload={"type": "pi_acceptance"}
        )
        assert result == "accept"

    def test_reject_shorthand_returns_reject(self, monkeypatch, capsys):
        result = self._run_with_input(monkeypatch, "r")
        assert result == "reject"

    def test_correct_prefix_strips_to_payload_text(self, monkeypatch, capsys):
        result = self._run_with_input(
            monkeypatch, "c please use dec_01ABC instead of dec_01XYZ"
        )
        assert result == "please use dec_01ABC instead of dec_01XYZ"

    def test_freeform_response_passes_through(self, monkeypatch, capsys):
        result = self._run_with_input(monkeypatch, "looks ok but flag for review later")
        assert result == "looks ok but flag for review later"

    def test_empty_response_defaults_to_type_aware_accept_token(self, monkeypatch, capsys):
        """Empty line for pi_greenlight defaults to "approve" (the type-aware
        accept token), not the bare string "accept"."""
        result = self._run_with_input(
            monkeypatch, "", payload={"type": "pi_greenlight"}
        )
        assert result == "approve"

    def test_closed_stdin_defaults_to_type_aware_token_and_warns(self, monkeypatch, capsys):
        """Non-interactive runs (CI, piped input) get EOFError. The fallback
        token MUST also be type-aware — "approve" for greenlight, "accept"
        for decision/acceptance."""

        def _eof_input(_prompt=""):
            raise EOFError

        monkeypatch.setattr("builtins.input", _eof_input)
        # pi_greenlight → approve
        result_greenlight = driver_module.interactive_interrupt(
            {"type": "pi_greenlight"}
        )
        assert result_greenlight == "approve"
        # pi_acceptance → accept
        result_acceptance = driver_module.interactive_interrupt(
            {"type": "pi_acceptance"}
        )
        assert result_acceptance == "accept"
        captured = capsys.readouterr()
        # Both warnings present (one per call).
        assert "stdin closed" in captured.err


class TestDefaultAcceptTokenTable:
    """Lock the per-interrupt-type token table — the contract that fixes
    chk_01KRVG6GE119ASG26QKXH0N5D2. Mirrors graph.py's routing functions."""

    def test_pi_greenlight_maps_to_approve(self):
        assert driver_module._default_accept_token("pi_greenlight") == "approve"

    def test_pi_decision_select_maps_to_accept(self):
        assert driver_module._default_accept_token("pi_decision_select") == "accept"

    def test_pi_acceptance_maps_to_accept(self):
        assert driver_module._default_accept_token("pi_acceptance") == "accept"

    def test_unknown_interrupt_type_defaults_to_approve(self):
        """Unknown types default to 'approve' — matches pre-decision gate
        semantics (greenlight, gate-style verdicts) which the orchestrator
        routes via 'approve in response'."""
        assert driver_module._default_accept_token("pi_unknown_future_type") == "approve"
