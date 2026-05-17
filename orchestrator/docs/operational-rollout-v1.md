# Operational rollout v1 — autonomous Brain↔Executor loop, first real-data runs

**Mission**: `mis_01KRVE4J71T6M6XWPDVPXMFJ49` (Phase 2.4-operational-rollout)
**Decision**: `dec_01KRVE1ZT6M8VN4PQM7W2HE8X6` (narrow first run; interactive PI review)
**Branch**: `agentic` at HEAD post-this-commit
**Date**: 2026-05-17

## Headline

**Two diagnostic runs against `mis_01KRVF159FEHMYD55Q6EQ7BD18`** (the autonomous-target mission carrying 3 ratified cross-reference items) shipped the operational driver + tests + two valuable checkpoints, but **did not meet Phase 2.4's acceptance criterion** (1+ items complete the Brain→PI→Executor cycle with `rka_update_note` write). PI ratified Option C on `chk_01KRVH890GKYCY9A28TM02STQ1`: combine the surfaced orchestrator gaps into a single Phase 2.5 mission (data-flow fix + deltas-into-Python-constants fold), then retry the operational rollout as Phase 2.6.

The driver + 14 regression tests land on agentic regardless — they're real infrastructure that Phase 2.6 will reuse.

## What was chosen + why (T0 picks)

Out of 18 cross-reference candidates, 3 were ratified by PI at the upfront Backbrief (`jrn_01KRVEGJGRCQWJ9PBH039H0JDP`):

| Pick | Journal ID | Difficulty | Why |
|---|---|---|---|
| 1 | `jrn_01KQQ4K4GWFKHQBCQNC9F92JX4` | HIGH | Maintenance-pass note that **explicitly cites 4 decision IDs in its Provenance section** — smoothest path to clean first-item cycle |
| 2 | `jrn_01KMX18FDBEE9T8JNHHAP649TE` | MEDIUM | "Project Deletion" feature request; no decisions cited — tests brain's content→corpus search |
| 3 | `jrn_01KP4QR4XFP0ZHKR14B9ET6CN2` | MEDIUM | "Research Map claim-count bug" log, status `superseded` — tests brain's ability to find back-link to a historical fix decision |

Difficulty gradient was deliberate: HIGH first so the run had the smoothest path to first-item success before the harder cases.

## Run 1 — first run, all 3 items via driver (`thr_op_rollout_v1_1779039051`)

### Outcome
- `terminal_state: complete` (misleadingly clean)
- `artifacts: 2` (strategy_node + confirmation_brief only)
- `interrupts: 2` (pi_greenlight + pi_acceptance; **no pi_decision_select**)
- `checkpoints: 1` (escalation_router fired)
- `errors: 0`
- `final_report_id: None`
- **No `rka_update_note` calls; no per-item work reached.**

### Root cause
**Driver-side string-contract bug.** `orchestrator/scripts/driver.py:interactive_interrupt` returned `"accept"` for the `a` shortcut on all interrupt types. But `graph.py:_route_after_pi_greenlight` checks `"approve" in response` (not `"accept"`). PI typed `a` at greenlight → driver returned `"accept"` → `"approve" in "accept"` is False → routed to escalation_router (skipping 7 nodes including the critical `pi_decision_select` interrupt).

Phase 1's `pilot_t12.py:pilot_interrupt` already had the type-aware pattern (returns `"approve"` for non-decision interrupts, `"accept"` for decision/acceptance). My new driver standardized on `"accept"` for everything — regression.

### Resolution: `chk_01KRVG6GE119ASG26QKXH0N5D2` Option A (PI-ratified)

Patched the driver:

```python
_ACCEPT_TOKEN_BY_INTERRUPT_TYPE: dict[str, str] = {
    "pi_greenlight": "approve",
    "pi_decision_select": "accept",
    "pi_acceptance": "accept",
}

def _default_accept_token(interrupt_type: str) -> str:
    return _ACCEPT_TOKEN_BY_INTERRUPT_TYPE.get(interrupt_type, "approve")
```

`a` shortcut, EOFError fallback, and empty-input fallback all route through `_default_accept_token(kind)`. Mirrors `pilot_interrupt` semantics exactly.

Added 6 regression tests:
- `test_accept_shortcut_returns_approve_for_pi_greenlight` (explicit lock, references the resolved checkpoint ID)
- `test_accept_shortcut_returns_accept_for_pi_decision_select`
- `test_accept_shortcut_returns_accept_for_pi_acceptance`
- `test_closed_stdin_defaults_to_type_aware_token_and_warns` (covers both greenlight + acceptance)
- `test_empty_response_defaults_to_type_aware_accept_token`
- `TestDefaultAcceptTokenTable` (4 tests locking the table mapping)

Suite count: 199 → 205 tests passing.

## Run 2 — retry with patched driver (`thr_op_rollout_v1_retry_1779039758`)

### Outcome
- `terminal_state: complete`
- `artifacts: 4` (strategy_node + confirmation_brief + **backbrief_draft + gate1_validation**) — +2 vs run 1
- `interrupts: 2` (pi_greenlight + pi_acceptance; **still no pi_decision_select**)
- `checkpoints: 1` (escalation_router still fired)
- `errors: 0`
- `final_report_id: None`
- `pi_acceptance` summary: `"REDIRECTED:"` (vs run 1's "Mission body unread")

### Diagnosis — orchestrator code data-flow gap

Driver routing is now correct: PI's `a` at greenlight → `"approve"` → routed to `backbrief_draft` (verified by the new artifacts). The graph then progressed through `backbrief_draft` → `gate1_validation` → **escalation_router** because gate1 returned `REDIRECTED`.

**Why did gate1 REDIRECT?** Because the Backbrief had no substance. Code-trace of `orchestrator/orchestrator/nodes/brain.py:strategy_node`:

```python
def strategy_node(state, sdk, mcp):
    context = mcp.rka_get_context(topic=state.get("mission_id", ""))
    status  = mcp.rka_get_status()
    prompt  = _build_strategy_prompt(state, context, status)
    #         ^^^ Does NOT include the mission body
    strategy_text = sdk.complete(prompt=prompt, ...)
```

`_build_strategy_prompt` injects only the bare `mission_id` string — never the mission's `objective`, `tasks`, `acceptance_criteria`, or `scope_boundaries`. The LLM literally never sees what the mission is asking for. Same gap in `_build_confirmation_prompt` and `_build_backbrief_prompt`.

Phase 1's PilotSDK masked this — its hardcoded canned responses didn't depend on prompt content. With real Claude, the brain correctly identifies the data-flow gap and refuses to fabricate a substantive Backbrief.

The brain's pi_greenlight Backbrief text (from the retry transcript) explicitly stated:

> *"Status: SKELETON. Mission body (mis_01KRVF159FEHMYD55Q6EQ7BD18) and motivating decision (dec_01KRVE1ZT6M8VN4PQM7W2HE8X6) remain permission-blocked this turn. Scope below is scaffolded from status payload + parked items, not from mission text. ... What this run will attempt: Cannot state substantively without mission body."*

This is **exemplary conservative behavior** — the brain is using Phase 2.3's updated skill prompts (it references "anti-pattern #12" verbatim, which is the structured-handoff rule from `skills/brain/SKILL.md`'s post-fold content) and correctly refuses to commit without ground-truth data. gate1_validation then correctly REDIRECTS the skeleton.

### Resolution: `chk_01KRVH890GKYCY9A28TM02STQ1` Option C (PI-ratified)

Combine BOTH layers into a single Phase 2.5 mission:
- (a) Fold the 17 ratified deltas from `orchestrator/docs/skill-prompt-deltas.md` into `orchestrator/orchestrator/nodes/brain.py:BRAIN_SYSTEM` and `orchestrator/orchestrator/nodes/executor.py:EXECUTOR_SYSTEM` Python constants. Closes the gap where Phase 2.3's marketplace-plugin fold doesn't reach the orchestrator's hardcoded prompts.
- (b) Add mission-body data flow: `strategy_node`, `confirmation_brief`, `backbrief_draft` (+ any other prompt-builder that lacks the context) call `mcp.rka_get_mission(mission_id)` at top and include the body in the LLM prompt.

Acceptance: 208+ orchestrator tests passing; brain_node prompts demonstrably include mission body via new regression tests.

Phase 2.4's original acceptance criterion (1+ items complete the full cycle with `rka_update_note`) transfers to **Phase 2.6** — a retry against the same `mis_01KRVF159FEHMYD55Q6EQ7BD18` target after Phase 2.5 ships.

## Per-item brain_node proposal quality

Run 1 + Run 2 both reached `pi_greenlight` but **never reached `pi_decision_select`** — the per-item cross-reference proposal interrupt never fired. So none of the 3 items had a brain_node proposal to assess. Phase 2.6's retry will produce that data.

Both runs DID confirm:
- Brain understands the structured-handoff format from the Phase 2.3 deltas (`anti-pattern #12` reference)
- Brain is correctly conservative when data is missing (skeleton Backbrief, refuses to fabricate)
- Brain knows about Affordances F + G, gate cadence, budget framing — all from the updated marketplace plugin skills

This is encouraging: the prompt-discipline uplift is REAL and working. The blocker is data flow, not prompt quality.

## PI's ratification rate

N/A — no per-item proposals were surfaced for ratification across either run. PI typed `a` twice per run (pi_greenlight + pi_acceptance), both procedural rather than substantive.

## Telemetry-zero compliance check

✓ PASSED. Across both runs:
- No third-party network calls detected (orchestrator's notifications.py defaults to bell + osascript per Phase 2.3 delta #9).
- `ANTHROPIC_API_KEY` was set in env (per the Phase 2 anomaly inventory) but `make_sdk()` scrubbed it; auth routed via macOS Keychain.
- All MCP traffic was to `http://localhost:9712` (the local RKA instance). All SDK traffic was to the local `claude` CLI subprocess.

## Recommendations for follow-up missions

### Phase 2.5 (Brain to file separately) — orchestrator prompt-and-flow uplift

Combined scope per the resolved checkpoint:
- (a) Fold 17 deltas into Python BRAIN_SYSTEM / EXECUTOR_SYSTEM constants.
- (b) Add `rka_get_mission(mission_id)` call + body inclusion in:
  - `brain.py:strategy_node` + `_build_strategy_prompt`
  - `brain.py:confirmation_brief` + `_build_confirmation_prompt`
  - `executor.py:backbrief_draft` + `_build_backbrief_prompt`
  - Optionally: `brain.py:gate1_validation` + `_build_gate1_prompt` (gate1 reviews against acceptance criteria, so it benefits from seeing them)
- 3+ regression tests asserting mission body lands in the prompt for each affected node.

Estimated effort: 2-3 hr.

### Phase 2.6 — retry the operational rollout (post-Phase-2.5)

Same target mission (`mis_01KRVF159FEHMYD55Q6EQ7BD18`), new workflow_thread_id. Expected outcome: `pi_decision_select` interrupt fires; brain_node proposes related_decisions per item; PI ratifies; `rka_update_note` writes. Acceptance: 1+ items complete the full cycle.

If Phase 2.6's retry still fails for a new reason: another mandatory-pause checkpoint with the actual diagnostic data.

## Branch state at Phase 2.4 close-out

- `agentic` HEAD: post-this-commit. Includes:
  - `orchestrator/scripts/driver.py` (T1 deliverable; 14 unit tests)
  - `orchestrator/tests/test_driver.py` (new)
  - `orchestrator/docs/operational-rollout-v1.md` (this file)
- `main`: UNCHANGED at `c063673`. Hub-and-spoke isolation preserved.
- No new tag. `v2.5.3+agentic` final tag stands.
- Phase 2.4 mission `mis_01KRVE4J71T6M6XWPDVPXMFJ49`: closes with findings; acceptance deferred to Phase 2.6.
- Autonomous-target mission `mis_01KRVF159FEHMYD55Q6EQ7BD18`: status `pending`; awaits Phase 2.6 retry.

## Bookkeeper + agentic-branch invariants

✓ `git diff main -- rka/services/worker.py = 0` throughout Phase 2.4.
✓ `git diff HEAD -- rka/ = 0` for every commit on agentic in Phase 2.4 (all changes under `orchestrator/`).
