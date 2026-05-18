"""Phase 2.9 T3 — real-RKA integration probe tests (env-gated).

Mission: `mis_01KRY2KP0GGZY21BA4Z2R2S718` (Phase 2.9; PI-handed-off scope
per `dec_01KRY2EXCSTSSCFZJ96VG4MGDW` Option A).

These tests catch subprocess-MCP-session-not-scoped drift that FakeMCP
unit tests cannot model. FakeMCP's in-process fake has no cross-process
session boundary; only a real `claude-agent-sdk` subprocess spawning a
real `rka mcp` stdio child can reveal whether `McpStdioServerConfig.env`
propagation actually works at runtime.

## CI behavior

Default CI runs SKIP these tests (the entire module is gated by the
`RKA_INTEGRATION=1` env var). `pytest -q` in CI shows them as `skipped`.

## Local invocation

To run the full integration suite locally (requires a running v2.5.3+
RKA container at `http://localhost:9712`, Claude Max credentials in
`~/.claude/.credentials.json` or macOS Keychain, AND the `rka` MCP stdio
binary on PATH):

    RKA_INTEGRATION=1 .venv/bin/python -m pytest \\
        orchestrator/tests/test_executor_integration.py -v

To target a different probe mission/project (defaults are the Phase 2.4
→2.6→2.8→2.10 target mission in rka_development):

    RKA_INTEGRATION=1 \\
    RKA_INTEGRATION_PROBE_PROJECT=prj_01KKQM9JFG67GT5FGWTAHD9YE4 \\
    RKA_INTEGRATION_PROBE_MISSION=mis_01KRVF159FEHMYD55Q6EQ7BD18 \\
    .venv/bin/python -m pytest orchestrator/tests/test_executor_integration.py -v

## What these tests validate

1. `test_mission_execute_against_real_subprocess_and_rka` — the load-
   bearing integration test. Validates that Phase 2.9 T1's RKA_PROJECT
   env propagation works end-to-end: subprocess MCP session is scoped to
   the parent's project_id (NOT proj_default), `mission_execute` LLM
   reads the probe mission successfully (no 404s), emits structured
   `proposed_actions` JSON, `_parse_proposed_actions` extracts cleanly.
   This is the cross-process A/B test the unit tests cannot perform.

2. `test_subprocess_cannot_invoke_write_tools_integration` — the
   security invariant test. Verifies the Phase 2.7 WRITE_TOOLS disallow
   holds at runtime, not just in unit tests. Subprocess attempts to
   reach a write tool; SDK refuses per `permission_mode="dontAsk"`.

Both tests catch failures that would otherwise only surface at the next
Phase 2.X operational rollout — i.e., when wall-clock cost is highest.
"""

from __future__ import annotations

import os
import pytest

from orchestrator.nodes import executor
from orchestrator.state import make_initial_state


# ---------------------------------------------------------------------------
# Module-level skip gate
# ---------------------------------------------------------------------------


pytestmark = pytest.mark.skipif(
    not os.environ.get("RKA_INTEGRATION"),
    reason=(
        "integration test (real RKA + real claude-agent-sdk subprocess); "
        "set RKA_INTEGRATION=1 to enable. See module docstring for full "
        "run command."
    ),
)


# ---------------------------------------------------------------------------
# Probe configuration (env-overridable)
# ---------------------------------------------------------------------------


def _probe_project_id() -> str:
    """RKA project_id the probe runs against. Defaults to the
    rka_development project where the Phase 2.4→2.6→2.8→2.10 target
    mission lives."""
    return os.environ.get(
        "RKA_INTEGRATION_PROBE_PROJECT", "prj_01KKQM9JFG67GT5FGWTAHD9YE4"
    )


def _probe_mission_id() -> str:
    """RKA mission_id the probe runs against. Defaults to the Phase
    2.4→2.6→2.8→2.10 target mission — a real, intact mission with 3
    cross-reference tasks. The probe doesn't write; it just verifies
    the subprocess can READ this mission successfully (which it
    couldn't in Phase 2.8 due to the project-mismatch bug)."""
    return os.environ.get(
        "RKA_INTEGRATION_PROBE_MISSION", "mis_01KRVF159FEHMYD55Q6EQ7BD18"
    )


def _rka_url() -> str:
    return os.environ.get("RKA_URL", "http://localhost:9712")


# ---------------------------------------------------------------------------
# Real-client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def real_mcp_client():
    """Real RestMCPClient pointed at the local v2.5.3+ container, scoped
    to the probe project. NOT a fake — talks to the live REST API."""
    from orchestrator.mcp_client import make_client

    return make_client(
        workflow_thread_id="thr_phase_2_9_integration_probe",
        base_url=_rka_url(),
        project_id=_probe_project_id(),
    )


@pytest.fixture
def real_sdk_client():
    """Real `_RealSDKClient` (Phase 2.9 T1 project_id-aware) spawning a
    real claude-agent-sdk subprocess. Requires Claude Max credentials.
    Skips with a clear message if no auth path is available."""
    from orchestrator.llm_client import make_sdk

    try:
        return make_sdk(project_id=_probe_project_id())
    except RuntimeError as e:
        pytest.skip(f"Claude Max credentials not available: {e}")


# ---------------------------------------------------------------------------
# Test 1 — load-bearing project-propagation integration test
# ---------------------------------------------------------------------------


def test_mission_execute_against_real_subprocess_and_rka(
    real_sdk_client, real_mcp_client
):
    """Phase 2.9 T3 load-bearing integration test: validates that the
    subprocess MCP session inherits the parent's project_id at runtime
    (Phase 2.9 T1's `McpStdioServerConfig.env["RKA_PROJECT"]` channel).

    Procedure:
      1. Build initial state pointing at the probe mission in the
         configured probe project.
      2. Invoke `executor.mission_execute(state, real_sdk_client, real_mcp_client)`
         — this spawns the real claude-agent-sdk subprocess with the
         project_id propagated via env, then makes the real LLM call.
      3. Assert: `state["proposed_actions"]` is a list (parse succeeded).
      4. Assert: the executor's reply text does NOT contain "404",
         "not found", "Default Project", or other markers indicating
         the subprocess reads landed in the wrong project. This is the
         direct A/B test against the Phase 2.8 failure mode.
      5. Assert: no entries in `state["errors"]` (no auth regressions,
         no MCP unreachable, no parser failures).

    If this test passes, Phase 2.10's operational rollout retry has high
    probability of empirical success on the first try.
    """
    state = make_initial_state(
        workflow_thread_id="thr_phase_2_9_integration_probe",
        mission_id=_probe_mission_id(),
        motivated_by_decision_id="",
        project_id=_probe_project_id(),
    )
    # Provide a minimal Backbrief so mission_execute has context to plan
    # against; we expect proposed_actions=[] from a read-only smoke test.
    state["executor_backbrief"] = (
        "Phase 2.9 T3 integration probe. Read the probe mission body via "
        "rka_get_mission and emit `{\"proposed_actions\": []}` to confirm "
        "subprocess MCP session is scoped to the correct project. Do NOT "
        "attempt any write-side tool calls."
    )
    state["gate1_verdict"] = "approved"

    update = executor.mission_execute(state, real_sdk_client, real_mcp_client)

    # The structured output parser ran (proposed_actions key present in update).
    assert "proposed_actions" in update, (
        "Phase 2.9 T3: mission_execute should populate state['proposed_actions'] "
        "via _parse_proposed_actions regardless of empty/non-empty list"
    )
    assert isinstance(update["proposed_actions"], list), (
        f"proposed_actions should be a list; got {type(update['proposed_actions']).__name__}"
    )

    # The subprocess's work_log was journaled.
    assert "artifacts" in update
    assert len(update["artifacts"]) >= 1

    # Direct A/B test against Phase 2.8 failure mode: the executor's reply
    # should NOT contain wrong-project markers. We check the position
    # summary (first line of LLM reply) and the parsed errors list.
    position = update.get("executor_position", "").lower()
    wrong_project_markers = [
        "404",
        "not found in project",
        "default project",
        "wrong project",
        "assumption invalidation",  # Phase 2.8 brain's escalation marker
    ]
    found_markers = [m for m in wrong_project_markers if m in position]
    assert not found_markers, (
        f"Phase 2.9 T3 A/B test FAILED: executor_position contains wrong-"
        f"project markers {found_markers!r} — Phase 2.8 failure mode still "
        f"present. Full position summary: {update.get('executor_position', '')!r}"
    )

    # No errors should surface for a successful integration probe.
    errors = update.get("errors", []) or []
    assert not errors, (
        f"Phase 2.9 T3: unexpected errors during integration probe: "
        f"{[e.get('error_type') for e in errors]!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — WRITE_TOOLS disallow holds at runtime
# ---------------------------------------------------------------------------


def test_subprocess_cannot_invoke_write_tools_integration(
    real_sdk_client, real_mcp_client
):
    """Phase 2.9 T3 security invariant test: validates Phase 2.7's
    WRITE_TOOLS disallow holds at the real-subprocess layer, not just in
    unit tests.

    Procedure:
      1. Build initial state pointing at the probe mission.
      2. Provide a Backbrief explicitly instructing the LLM to attempt
         a write-side tool call (rka_update_note).
      3. Invoke `mission_execute` against the real subprocess.
      4. Assert: state["proposed_actions"] is still a list (LLM emitted
         the structured block); the LLM either (a) refused the write
         per `permission_mode="dontAsk"`, (b) only emitted a write in
         `proposed_actions` (which is the ratification-gated path — fine),
         OR (c) escalated via empty proposed_actions per Phase 2.5 Delta #7.
      5. Assert: no rka_update_note call landed at RKA directly from the
         subprocess (verified by checking the workflow_thread_id-tagged
         journal entries — only `mission-execution` log should appear,
         no `rka_update_note` artifact tagged from execute_ratified_actions
         or anywhere outside the parent process).

    If this test passes, Phase 2.7's read-only subprocess invariant holds
    end-to-end against real claude-agent-sdk.
    """
    state = make_initial_state(
        workflow_thread_id="thr_phase_2_9_write_invariant_probe",
        mission_id=_probe_mission_id(),
        motivated_by_decision_id="",
        project_id=_probe_project_id(),
    )
    state["executor_backbrief"] = (
        "Phase 2.9 T3 WRITE_TOOLS invariant probe. ATTEMPT to call "
        "rka_update_note directly to verify the subprocess refuses. "
        "If the subprocess SDK refuses, emit `{\"proposed_actions\": "
        "[{\"tool\": \"rka_update_note\", \"args\": {...}, \"rationale\": "
        "\"would need PI ratification anyway\"}]}` to demonstrate that the "
        "write path is correctly routed through ratification. Do NOT "
        "actually mutate anything."
    )
    state["gate1_verdict"] = "approved"

    update = executor.mission_execute(state, real_sdk_client, real_mcp_client)

    assert "proposed_actions" in update
    assert isinstance(update["proposed_actions"], list)

    # The KEY assertion: even though the prompt encouraged a direct write
    # attempt, no rka_update_note call should have landed via the
    # subprocess. Check the RKA-side state for any new journal entries
    # tagged with this probe's workflow_thread_id that have type "note"
    # AND came from an executor source (would indicate the subprocess
    # somehow bypassed scope).
    #
    # The probe's own journal write from mission_execute (type="log") is
    # expected and fine; what we want to NOT see is a type="note" write
    # from this same workflow_thread_id, which would only happen if the
    # subprocess called rka_update_note directly (bypassing the parent
    # process gating).
    probe_journal = real_mcp_client.rka_get_journal(
        tags=["thr_phase_2_9_write_invariant_probe"]
    )
    entries = probe_journal.get("entries", []) or []
    bypass_writes = [
        e for e in entries
        if e.get("type") == "note" and e.get("source") == "executor"
    ]
    assert not bypass_writes, (
        f"Phase 2.9 T3 WRITE_TOOLS invariant VIOLATED: subprocess "
        f"appears to have invoked write-side tool directly. Bypass "
        f"writes detected: {[e.get('id') for e in bypass_writes]!r}. "
        f"This is a CATASTROPHIC Phase 2.7 regression."
    )
