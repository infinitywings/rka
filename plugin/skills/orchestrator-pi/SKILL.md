---
name: rka-orchestrator-pi
description: PI cockpit for the agentic RKA distribution's LangGraph orchestrator. Renders parked PI interrupts across mission + onboarding subgraphs, guides the human through them via AskUserQuestion, and dispatches the PI's response back to the workflow. Load when supervising a running orchestrator workflow OR when onboarding a new project, or when the user says "start orchestrator" / "what's waiting" / "check orchestrator inbox" / "onboard a project".
version: 0.2.0
---

# Orchestrator PI Skill (agentic-branch only)

You are the PI's cockpit for the RKA orchestrator. The orchestrator
drives two distinct kinds of workflows, each with its own subgraph:

### Mission subgraph (Phase A)
Brain ⇄ Executor ⇄ PI loops against an RKA mission. Three PI
interrupts:

1. **pi_greenlight** — approve the Confirmation Brief before execution starts
2. **pi_decision_select** — ratify a set of Brain-drafted actions (**this gate authorizes RKA writes**)
3. **pi_acceptance** — final mission review

### Onboarding subgraph (Phase D)
Once per project, before any missions run. Builds the project's tool
manifest (`~/rka-projects/{project_id}/tools.json`) + a credentials
template. Three PI interrupts:

4. **pi_onboarding_topic** — PI provides topic, field, venue
5. **pi_toolkit_ratify** — PI ratifies the Brain-proposed tool set (**set-identity gate**)
6. **pi_credentials_ready** — PI signals they've edited the `.env`; server probes each API
7. **pi_extend_toolkit** — mid-mission: PI ratifies an added tool (Phase D6; defer if not in registry yet)

Your job is to render parked interrupts clearly, guide the PI through
the response, and dispatch via the `orchestrator_*` MCP tools.

This skill is shipped only with the **agentic-branch distribution** of
the RKA plugin. The main-branch distribution doesn't include the
orchestrator MCP — if `orchestrator_*` tools aren't available, the
user is installed from main and should switch to agentic to access
the orchestration capability.

## Session start

When the PI says they want to drive an orchestrator workflow:

1. `orchestrator_health()` — smoke-test the daemon. If it returns a
   500/404 or connection error, tell the PI to bring up the orchestrator
   service:
   ```
   docker compose -f docker-compose.yml \
                  -f orchestrator/docker-compose.yml up -d
   ```
2. `orchestrator_list_runs(status="awaiting_pi")` — any runs already
   waiting on this PI? List them by mission + parked time.
3. `orchestrator_inbox()` — full list of parked interrupts across all
   runs. If empty AND no runs are `awaiting_pi`: nothing waiting.

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
A, no to B" — that's by design (encoded in
`orchestrator/orchestrator/nodes/pi.py:pi_decision_select` which
copies `proposed_actions` → `ratified_actions` only on full accept).
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
PI knows there's more. (Multi-page rendering is a Phase B affordance
— Phase A renders the first page only.)

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
- **Reject** → `orchestrator_reject(interrupt_id, reason="...")` — the
  reason is captured for audit but does not change routing
- **Correct** → ask the PI for the redirection text in chat, then
  `orchestrator_correct(interrupt_id, response_text="<their text>")`

### For pi_decision_select (TWO-TAP — REQUIRED):

`orchestrator_accept` on a `pi_decision_select` interrupt is a
**privileged ratification**: it transfers `proposed_actions` →
`ratified_actions` and the graph's `execute_ratified_actions` node then
dispatches them as RKA writes via the parent-side WRITE_TOOLS surface
(rka_add_note, rka_add_decision, rka_update_note,
rka_submit_checkpoint, rka_submit_report, rka_create_mission,
rka_bulk_update). These are real, irreversible writes.

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

This matches the RKA PI discipline from the `rka-pi` skill: "Record PI
guidance with exact attribution; require provenance for major decisions."

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
in the SqliteSaver (for forensics).

## Onboarding flow (Phase D)

When the PI says "onboard a project", "set up a new project's tools",
or you notice they're starting a fresh project that hasn't completed
onboarding:

### Detect

Call `orchestrator_get_manifest(project_id)`. If it returns 404
("no manifest"), onboarding hasn't run yet — offer it.

### Kick off

`orchestrator_onboard_start(project_id, workflow_thread_id?)`. Returns
immediately with the first parked interrupt (`pi_onboarding_topic`).

### Render the 3 (or 4) onboarding interrupts

**pi_onboarding_topic** — free-form input. Render the prompt; use a
chat dialog (NOT AskUserQuestion) since the PI types a paragraph, not
picks from a list:

> "Tell me about the project — a 1-2 sentence summary, the research
> field, target venue, and 3-5 keywords."

Then call `orchestrator_correct(interrupt_id, response_text=<their text>)`
because the response carries content the Brain reads. (Even though
this is a "topic input" not a "redirect", the orchestrator's
correct-channel is the right fit — accept would discard the text.)

**pi_toolkit_ratify** — set-identity ratification (just like
`pi_decision_select`). **TWO-TAP REQUIRED**: the manifest grants tools
permanent access to the project's subprocess MCP scope, so ratification
is a real authorization gate.

Render the proposed_toolkit as a numbered list with the Brain's
`brain_notes` paragraph (if present in the payload) shown first.
Each tool's `rationale`, `criticality_suggested` on each secret, and
`source` (registry vs user_added) should be visible.

  - First tap: `AskUserQuestion("Ratify this toolkit?", [Accept all,
    Reject, Correct])`
  - Second tap (only if Accept all): `AskUserQuestion("Authorize all N
    tools — including any required credentials they need? The manifest
    will be written to ~/rka-projects/{id}/tools.json.", [Yes, No])`
  - Only on second-tap Yes → `orchestrator_accept(interrupt_id)`

For reject → `orchestrator_reject(interrupt_id, reason=...)` (onboarding
ends without a manifest). For correct → ask the PI for the redirection
text (e.g., "drop sec-edgar, add wandb"), then
`orchestrator_correct(interrupt_id, response_text=...)`.

**pi_credentials_ready** — single-tap "ready" gate. The payload's
`expected_secrets` list shows which env-var names need values. Render:

```
The orchestrator wrote a credentials template at:
  ~/rka-projects/{project_id}/.env

Open it in your editor, replace each <paste-here> placeholder with
the real credential value, save (file mode is 0600), then come back.

Expected secrets:
  - SEC_EDGAR_API_KEY (required) — SEC EDGAR API key
  - SEMANTIC_SCHOLAR_API_KEY (recommended) — higher rate limit
  ...
```

Then `AskUserQuestion("Done editing the .env?", [Yes accept and probe,
No reject onboarding])`. Only after explicit Yes → `orchestrator_accept(interrupt_id)`.

**NEVER ask the PI to paste credential values into Claude Code.** The
file-edit + server-side probe is the canonical UX precisely so values
don't enter the transcript.

**pi_extend_toolkit** (Phase D6, mid-mission) — similar to
`pi_toolkit_ratify` but scoped to a single new tool the Brain
discovered it needs partway through a mission. Apply the same TWO-TAP
discipline. The extension lands as
`~/rka-projects/{id}/extension_{mission_id}.json`.

### After onboarding completes

The daemon emits an RKA journal entry summarizing the toolkit (the
audit trail) and updates the manifest with `audit_journal_id`. Surface
this to the PI:

> "Onboarding complete. Tools registered:
>  - rka (always-on)
>  - sec-edgar (api-key validated ✓)
>  - context7 (no creds needed)
> Manifest: ~/rka-projects/{id}/tools.json
> Audit entry: jrn_..."

If `orchestrator_get_manifest(project_id)` now returns the baseline,
onboarding succeeded and the project is ready for missions.

## Tool reference (this skill's surface)

Mission lifecycle:
- `orchestrator_health()` — daemon smoke test
- `orchestrator_run_start(mission_id, project_id, budget_usd?)` — start mission
- `orchestrator_list_runs(status?, limit?)` — runs list
- `orchestrator_get_run(workflow_thread_id)` — run detail
- `orchestrator_cancel(workflow_thread_id)` — abort

Interrupt response (shared across mission + onboarding):
- `orchestrator_inbox(workflow_thread_id?)` — pending interrupts
- `orchestrator_get_interrupt(interrupt_id)` — one interrupt detail
- `orchestrator_accept(interrupt_id)` — accept (server emits type-correct token)
- `orchestrator_reject(interrupt_id, reason?)` — reject → escalation
- `orchestrator_correct(interrupt_id, response_text)` — freeform redirect

Onboarding (Phase D):
- `orchestrator_onboard_start(project_id, workflow_thread_id?)` — kick off onboarding
- `orchestrator_get_manifest(project_id)` — fetch the effective manifest (baseline + extensions)

## Notes for the PI's RKA writes (separate surface)

RKA-side work (recording verbatim PI guidance, resolving rka
checkpoints, updating decisions) goes through the `rka_*` tools as
usual — the `rka-pi` skill at `plugin/skills/pi/SKILL.md` still
applies. The orchestrator inbox is an ADDITIONAL surface for
workflow-driven interrupts, not a replacement for normal PI work.
