---
name: orchestrator-pi
description: PI cockpit for the RKA LangGraph orchestrator. Renders parked PI interrupts (greenlight / decision_select / acceptance), guides the human through them, and dispatches the PI's response back to the workflow. Load when supervising a running orchestrator workflow.
version: 0.1.0
---

# Orchestrator PI Skill

You are the PI's cockpit for the RKA orchestrator. The orchestrator
runs Brain ⇄ Executor ⇄ PI workflows against RKA missions as a
LangGraph. At three points the graph parks for PI input:

## Tool Surface note (v2.7.0+)

The rka MCP server (separate from this orchestrator MCP server) ships
a **discriminated-union dispatch architecture** as of v2.7.0:
**3 always-on dispatch tools** — `rka_query` (read operations),
`rka_execute` (write/lifecycle operations), `rka_describe` (schema
lookup) — **plus 2 escape hatches** (`rka_load_tools` and `rka_help`,
the latter now a deprecated alias of `rka_describe`). All 87 RKA
operations live as discriminated-union branches under `rka_execute` /
`rka_query`; per-branch enum + required-field constraints are
enforced at the FastMCP inputSchema layer (so e.g.
`confidence='confirmed'` is rejected BEFORE the call goes out). See
`/Volumes/base/workspace/rka/docs/v2.6.x-v2.7.0-tool-surface-arc.md`
for the full v2.6.3 → v2.7.0 architectural arc.

Most cockpit work in this skill uses the `orchestrator_*` tools
(`orchestrator_health`, `orchestrator_inbox`, `orchestrator_run_start`,
`orchestrator_accept`, etc.) — those are this MCP server's own surface
and are unaffected by the RKA-side v2.7.0 redesign. If the PI asks you
to inspect RKA directly during a parked interrupt (e.g. "show me
dec_01XYZ", "list pending missions"), call via the dispatch surface:

- `rka_query(operation='get', entity_id='dec_01XYZ', project_id='prj_...')`
- `rka_query(operation='get_journal', project_id='prj_...', limit=20)`
- `rka_query(operation='get_decision_tree', project_id='prj_...')`

If the PI specifically asks to bank PI guidance verbatim during a
session, use:

- `rka_execute(operation='record_note', content='...', source='pi',
  verbatim_input='<exact PI words>', project_id='prj_...')`

`rka_describe(operation='record_note')` will show you the exact
required + optional fields for any operation; `rka_describe('')`
(empty string) lists all available operations at low token cost.

**Orchestrator subprocess compatibility note.** Inside the
orchestrator workflow itself, the daemon's SDK subprocess (Brain /
Executor LLM) deliberately runs against the v2.7.0a2 legacy verb
surface via `RKA_LEGACY_TOOLS=1` set in
`orchestrator/docker-compose.yml`. This preserves the parent-side
TWO-TAP gate granularity at `pi_decision_select` — per-operation
WRITE_TOOLS allowlist and the `proposed_actions → ratified_actions`
dispatch contract are anchored to individual tool names like
`rka_add_decision`, `rka_create_mission`, etc., NOT to a single
`rka_execute(operation=...)` call. The full re-anchoring to the
discriminated-union surface (and corresponding Brain / Executor
prompt rewrites) lands in a separate `v2.7.0+agentic.X` release;
until then, the cockpit sees v2.7.0 but the daemon subprocess sees
the v2.7.0a2 verb surface.

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

### Per-run PI overrides — `run_instructions=...`

`orchestrator_run_start` accepts an optional `run_instructions: str`
kwarg (Phase-X — Cross-Run Correction Channel). Use it when the PI
wants to scope or correct THIS run without polluting the mission body:

- Per-run budget scoping ("this run only does T1–T4 at $25; T5–T8 are
  future runs requiring separate authorization")
- Surfacing prior session context ("attempt-2 surfaced a $100 misframing;
  authorized cap is $25")
- Explicit assumption overrides ("treat Bash as available — EROFS was
  resolved in jrn_…")

The orchestrator stores it in `workflow_runs.run_overrides.pi_instructions`
and Brain's `strategy_node` reads it under a delimited "PI OVERRIDES
(highest priority)" block at the top of the strategy prompt. The block
explicitly tells Brain to treat the text as PI directive and prefer it
over contradicting mission-body wording.

The response from `orchestrator_run_start` redacts the actual text to
`"<set>"` to avoid logging PI prose — the canonical record lives in
`workflow_runs.run_overrides` accessible via `orchestrator_get_run`.

### Cross-run auto-rehydration

`pi_greenlight` redirects on previous attempts of the same mission are
auto-rehydrated into the next `orchestrator_run_start`'s `run_overrides`
under `prior_redirects`. The PI does NOT need to re-type a redirect that
they already submitted on an earlier (now-terminal) run of the same
mission — Brain will see it again at the next strategy_node.

Auto-rehydration is filtered by:
- Most-recent 3 redirects (corrects) for this mission
- Excludes redirects from runs that subsequently reached
  `terminal_state="complete"` (those corrections are assumed absorbed)
- Excludes redirects with `responded_at <= mission_metadata.overrides_cleared_at`
  (PI explicit "I've absorbed everything" affordance — see next section)

### `orchestrator_cancel_overrides(mission_id)`

PI escape valve when the prior-redirect auto-rehydration is no longer
desired. Stamps `mission_metadata.overrides_cleared_at = now()`. Future
runs of this mission will not surface any prior redirects whose
`responded_at <= cleared_at`. Manual `run_instructions=` kwarg is
unaffected; only the auto-rehydration channel is cleared.

When to call:
- The PI just inspected the latest brief and verified all prior
  corrections were correctly absorbed.
- A mission has gone through multiple iteration cycles and the
  `prior_redirects` block is becoming noise.
- An incorrect or now-irrelevant prior redirect needs to be retired.

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

When the run accumulated errors or checkpoints, the Phase-X²' polish
also surfaces three top-level diagnostic hints on the same item:
`latest_error_type` (e.g.
`ratified_action_arg_missing_required_field`), `latest_failed_tool`
(e.g. `rka_submit_checkpoint`), and `latest_checkpoint_reason`
(free-text from the most recent checkpoint). Render these in the
acceptance prompt so the PI sees the specific escalation cause
before drilling into `errors[]` / `checkpoints[]`. Absent (null)
when the run had no errors/checkpoints — the happy-path payload is
unchanged in shape.

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
    {label: "Reject", description: "Hard reject (escalation_router → terminal pi_acceptance)"},
    {label: "Correct", description: "Redirect with freeform direction. At pi_greenlight: triggers Brain redraft (Phase-X²); at pi_acceptance: marks run escalated and ends. See gate semantics below."},
])
```

Then call:

- **Accept** → `orchestrator_accept(interrupt_id)`
- **Reject** → `orchestrator_reject(interrupt_id, reason="...")`
- **Correct** → ask the PI for the redirection text, then
  `orchestrator_correct(interrupt_id, response_text="<their text>")`

#### What `correct` does at each gate (Phase-X² semantic)

The redirect destination depends on the gate type — the PI should
understand this BEFORE picking "Correct":

- **`pi_greenlight` (Confirmation Brief, first-look)** — `correct`
  loops back to a Brain redraft of the brief: the sanitized redirect
  text is prepended to the next strategy prompt as an "IN-RUN PI
  REDIRECT" block (top priority, supersedes mission body + cross-run
  history), Brain re-generates the Confirmation Brief, and a fresh
  `pi_greenlight` parks for ratification. Bounded at
  `MAX_GREENLIGHT_REDRAFTS` (=3) in-run redrafts; the 4th `correct`
  escalates with a real `greenlight_redraft_budget_exceeded` error so
  the PI can adjudicate rather than spiral.
- **`pi_decision_select` (TWO-TAP ratification, brain-proposed writes)**
  — `correct` escalates the run via `escalation_router` → terminal
  `pi_acceptance`. This is the autonomy-licensing gate; redrafting
  write proposals mid-run is OUT of scope for this surface (file as
  a follow-up if needed).
- **`pi_acceptance` (terminal mission review)** — `correct` (or
  `reject`) marks `terminal_state="escalated"` and ends the run.
  There is no meaningful loopback target after `final_synthesis`.
- **`pi_credentials_ready` / `pi_bootstrap_fill_ack` (onboarding /
  Phase B)** — `correct`/`reject` ends the subgraph cleanly; the
  PI re-enters via the slash command (state on disk persists where
  applicable).

If the PI wants their correction to survive across runs of the same
mission (e.g. cancel + relaunch later), use `correct` on
`pi_greenlight` — Phase-X also auto-rehydrates `pi_greenlight`
redirects into the NEXT run's `prior_redirects` block. The in-run
redraft channel (this PR, Phase-X²) and the cross-run channel
(Phase-X, shipped earlier) compose: a redirect at `pi_greenlight`
ALWAYS becomes part of the audit-tracked PI-overrides chain, whether
the current run completes the redraft or terminates and a future
run picks it up.

### For pi_decision_select (TWO-TAP — REQUIRED):

`orchestrator_accept` on a `pi_decision_select` interrupt is a
**privileged ratification**: it transfers `proposed_actions` →
`ratified_actions` and the graph's `execute_ratified_actions` node then
dispatches them as RKA writes via WRITE_TOOLS (rka_add_note,
rka_add_decision, rka_update_note, rka_submit_checkpoint,
rka_submit_report, rka_create_mission, rka_bulk_update). These are
real, irreversible writes. (Per the v2.7.0 surface-change note above,
the orchestrator daemon's subprocess runs against the v2.7.0a2 verb
surface via `RKA_LEGACY_TOOLS=1`, so these per-tool WRITE_TOOLS names
remain authoritative for the autonomy contract until the next
`v2.7.0+agentic.X` release rewires them to the dispatch surface.)

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
- `orchestrator_run_start(mission_id, project_id, budget_usd?, run_instructions?)` — start;
  Phase-X `run_instructions` is the manual per-run PI override channel
- `orchestrator_list_runs(status?, limit?)` — runs list
- `orchestrator_get_run(workflow_thread_id)` — run detail (includes
  `run_overrides` showing what overrides were active for the run)
- `orchestrator_cancel(workflow_thread_id)` — abort
- `orchestrator_cancel_overrides(mission_id)` — Phase-X PI escape valve;
  clears auto-rehydration of prior pi_greenlight redirects for this
  mission's next run
- `orchestrator_inbox(workflow_thread_id?)` — pending interrupts
- `orchestrator_get_interrupt(interrupt_id)` — one interrupt detail
- `orchestrator_accept(interrupt_id)` — accept (server emits type-correct token)
- `orchestrator_reject(interrupt_id, reason?)` — reject → escalation
- `orchestrator_correct(interrupt_id, response_text)` — freeform redirect.
  On `pi_greenlight`, the response text auto-rehydrates into the NEXT
  run's `prior_redirects` block (per Phase-X). Useful when the PI wants
  the correction to survive across run boundaries without re-typing.

## Notes for the PI's RKA writes (separate surface)

RKA-side work (recording verbatim PI guidance, resolving rka
checkpoints, updating decisions) goes through the `rka_*` tools as
usual — the `rka:pi` skill at `plugin/skills/pi/SKILL.md` still
applies. The orchestrator inbox is an ADDITIONAL surface for
workflow-driven interrupts, not a replacement for normal PI work.
