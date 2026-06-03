# Pilot v2.5.3+agentic — T3 evidence

Mission: `mis_01KRSRZX2P3BN4ZAP70ZM7YXGC`
Date: 2026-05-17
Branch: `feat/v2.5.3-context-ordering` / `agentic` at HEAD (commit `27ba9cd` + this folder).

## Acceptance-criteria readout

| Criterion | Status | Evidence |
|---|---|---|
| (a) Pilot completes without unhandled exception | ✗ FAILED | `escalation_router` raised `CheckpointError` after upstream node failure (see log) |
| (b) ≥1 real LLM call succeeds | ✓ PARTIAL — call was made, response returned, but downstream parsing/handoff failed | First run hit `max_turns=1` (fixed); second run got past SDK call into the graph |
| (c) No `ANTHROPIC_API_KEY` billing event | ✓ PASSED | log line 1 confirms WARNING + scrub fired; SDK env-arg excluded the var |
| (d) State machine advances ≥3 nodes | ⚠ INDETERMINATE | escalation_router fired (node #N), implying ≥1 upstream node ran first; no terminal state to inspect because exception escaped |

## Headline finding

**Auth routing WORKS** (the headline capability of Phase 2):

- WARNING emitted: *"ANTHROPIC_API_KEY is set in env (would route to API billing). make_sdk() scrubs it before SDK invocation so auth falls through to Claude Max (credentials.json / Keychain)."*
- Auth-path label logged: `keychain` (via `security find-generic-password -s 'Claude Code-credentials'`).
- SDK constructed without raising; first `complete()` call reached Claude Max (the first run's failure was the SDK's own `max_turns=1` error, which only fires AFTER auth succeeded and a turn was assigned).

**Downstream orchestrator-RKA contract issues surface when real SDK swaps in for PilotSDK** (Phase 2 shakedown territory):

- After fixing `max_turns=1` to default-unlimited, the graph advances past `strategy_node` but raises somewhere downstream.
- `escalation_router` catches the upstream exception and submits a checkpoint via `mcp.rka_submit_checkpoint(...)`. This call gets HTTP 422 *"knowledge-pack integrity"* from RKA at /api/checkpoints.
- Likely cause: orchestrator's checkpoint-submission payload doesn't include fields that RKA v2.5.3's `check_integrity` gate requires (Mission B hardened structured-body 422 contracts during v2.3.5; orchestrator was designed pre-v2.4 and inherited that contract drift via the T0 merge).

## Files

- `run_log_1778982590.txt` — full stdout/stderr of the failing pilot run.
- `README.md` — this file.

## Disposition

Per mission checkpoint trigger #5 (*"T3 pilot fails to complete for any reason other than missing credentials: surface; could indicate orchestrator state-machine regression after the merge OR SDK incompatibility"*): filing as a checkpoint to PI before tagging v2.5.3+agentic. The auth-routing headline capability ships; the integration-shakedown is real work that needs a follow-up Phase 2.1 mission.
