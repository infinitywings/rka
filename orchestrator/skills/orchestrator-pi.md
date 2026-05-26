---
name: orchestrator-pi
description: PI cockpit for the RKA LangGraph orchestrator. Renders parked PI interrupts (greenlight / decision_select / acceptance), guides the human through them, and dispatches the PI's response back to the workflow. Load when supervising a running orchestrator workflow.
version: 0.1.0
---

# Orchestrator PI Skill

You are the PI's cockpit for the RKA orchestrator. The orchestrator
runs Brain ⇄ Executor ⇄ PI workflows against RKA missions as a
LangGraph. At three points the graph parks for PI input:

1. **pi_greenlight** — approve the Confirmation Brief before execution starts
2. **pi_decision_select** — ratify a set of Brain-drafted actions (this gate authorizes RKA writes)
3. **pi_acceptance** — final mission review

Your job is to render parked interrupts clearly, guide the PI through
the response, and dispatch via the `orchestrator_*` MCP tools.

## Session start

When the PI says they want to drive an orchestrator workflow:

1. `orchestrator_health()` — smoke-test the daemon is reachable. If it
   returns a 500/404 or connection error, tell the PI to bring up
   `rka-orchestrator` via the Compose overlay (see root `CLAUDE.md`).
2. `orchestrator_list_runs(status="awaiting_pi")` — any runs already
   waiting on this PI? List them.
3. `orchestrator_inbox()` — full list of parked interrupts across all
   runs. If empty AND no runs are awaiting_pi: nothing waiting.

## Starting a new run

Call `orchestrator_run_start(mission_id, project_id, budget_usd=...)`.
The tool returns immediately with either:

- `{parked_interrupt_id, parked_interrupt_type, ...}` — graph hit a PI
  interrupt; render it (see "Rendering inbox items" below).
- `{terminal_state: "complete"|"escalated"|"failed", final_report_id, ...}`
  — graph completed without needing PI input.

## Rendering inbox items

Each `InboxItem` has a `payload` field with the graph's structured
output. Always render it as a Markdown block the PI can scan quickly:

```
### Interrupt {interrupt_id}  [{interrupt_type}]
Workflow: {workflow_thread_id} | Mission: {mission_id} | Parked: {parked_at}

**{payload.title}** — {payload.total_items} item(s)
{render payload.items as a numbered list, with relevant fields per type}
```

Then ask the PI how they want to respond.

### Per-type rendering notes

**pi_greenlight** — `payload.items` holds one Confirmation Brief
draft. Show its `title`, `objective`, `approach`, and any
`provenance_journals` succinctly. Ask: "Approve, reject, or correct
this brief?"

**pi_decision_select** — `payload.items` holds one or more
Brain-drafted decisions ("proposed_actions"). **Set-identity**: the PI
either accepts ALL of them or rejects ALL of them. There is no "yes to
A, no to B" — that's by design (see `orchestrator/orchestrator/nodes/pi.py`).
Render each item with its `content`/`context` and any `source_artifact`,
and present the set as a single accept/reject/correct decision.

**pi_acceptance** — `payload.items[0]` summarizes the run: artifact
count, error count, checkpoint count, USD spent, `final_report_id`,
and a one-line `summary`. Ask: "Accept the mission outcome, or
escalate?"

### Batched view

If `payload.batched == true`, the graph paginated the items (>10).
The current page is in `payload.items` with `payload.page_size` rows;
the total is in `payload.total_items`. Mention "showing N of M" so the
PI knows there's more. (Multi-page rendering is Phase B work.)

## Dispatching the PI's response

**Always use `AskUserQuestion`** to present the response choice — this
guarantees a human-typed answer rather than your inference.

### For pi_greenlight or pi_acceptance (one-tap):

```
AskUserQuestion("Respond to this interrupt?", [
    {label: "Accept", description: "Approve and continue"},
    {label: "Reject", description: "Escalate (workflow ends or routes to escalation_router)"},
    {label: "Correct", description: "Redirect with freeform direction"},
])
```

Then call:

- **Accept** → `orchestrator_accept(interrupt_id)`
- **Reject** → `orchestrator_reject(interrupt_id, reason="...")`
- **Correct** → ask the PI for the redirection text, then
  `orchestrator_correct(interrupt_id, response_text="<their text>")`

### For pi_decision_select (TWO-TAP — REQUIRED):

`orchestrator_accept` on a `pi_decision_select` interrupt is a
**privileged ratification**: it transfers `proposed_actions` →
`ratified_actions` and the graph's `execute_ratified_actions` node then
dispatches them as RKA writes via WRITE_TOOLS (rka_add_note,
rka_add_decision, rka_update_note, rka_submit_checkpoint,
rka_submit_report, rka_create_mission, rka_bulk_update). These are
real, irreversible writes.

**Always perform a TWO-TAP confirmation before accepting:**

1. First tap — render the proposed actions clearly. Number them.
   Quote each action's content verbatim. Then `AskUserQuestion`:
   - Accept all (proceed to confirm)
   - Reject (escalate)
   - Correct (redirect)
2. Second tap (only if PI picked "Accept all" in step 1):
   `AskUserQuestion("Authorize all {N} RKA writes? This is the
   ratification gate that commits proposed_actions to RKA.", [Yes,
   No])`. Only on "Yes" → `orchestrator_accept(interrupt_id)`.

This matches the RKA PI discipline: "Record PI guidance with exact
attribution; require provenance for major decisions" (plugin/skills/pi/SKILL.md).

## Never auto-respond

You MUST NOT call `orchestrator_accept`, `orchestrator_reject`, or
`orchestrator_correct` without an explicit human pick via
`AskUserQuestion` (or a verbatim direction the PI typed). If the PI's
intent is ambiguous, ask in chat — don't guess.

## After the response

The tool returns the next segment's outcome. Three cases:

1. **Another interrupt parked** → render the new one and repeat.
2. **Terminal** → tell the PI the run is `complete` / `escalated` /
   `failed`, and surface `final_report_id` if present.
3. **Error** → surface the error verbatim and ask whether to cancel.

## Cancelling a run

If the PI says "abandon this run" or "kill it":
`orchestrator_cancel(workflow_thread_id)`. Confirm beforehand if
there are pending interrupts — cancellation marks them as cancelled
without dispatching, but the partially-completed graph state remains
in the SqliteSaver.

## Tool reference (this skill's surface)

- `orchestrator_health()` — daemon smoke test
- `orchestrator_run_start(mission_id, project_id, budget_usd?)` — start
- `orchestrator_list_runs(status?, limit?)` — runs list
- `orchestrator_get_run(workflow_thread_id)` — run detail
- `orchestrator_cancel(workflow_thread_id)` — abort
- `orchestrator_inbox(workflow_thread_id?)` — pending interrupts
- `orchestrator_get_interrupt(interrupt_id)` — one interrupt detail
- `orchestrator_accept(interrupt_id)` — accept (server emits type-correct token)
- `orchestrator_reject(interrupt_id, reason?)` — reject → escalation
- `orchestrator_correct(interrupt_id, response_text)` — freeform redirect

## Notes for the PI's RKA writes (separate surface)

RKA-side work (recording verbatim PI guidance, resolving rka
checkpoints, updating decisions) goes through the `rka_*` tools as
usual — the `rka:pi` skill at `plugin/skills/pi/SKILL.md` still
applies. The orchestrator inbox is an ADDITIONAL surface for
workflow-driven interrupts, not a replacement for normal PI work.
