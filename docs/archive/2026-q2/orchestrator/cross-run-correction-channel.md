# Orchestrator Cross-Run Correction Channel — Architectural Recommendation

> **See also: Phase-X² (In-Run Redraft Channel) — sibling fix landed
> after this doc.** Phase-X (this doc) solved the *cross-run*
> durability gap (PI redirect text evaporated when a workflow_thread
> terminated). Phase-X² (CLAUDE.md "Phase-X² — In-Run Redraft Channel"
> section + `confirmation_brief_redraft` node + bounded back-edge to
> `confirmation_brief`) solved the *in-run* counterpart: a `correct`
> action at `pi_greenlight` used to dead-end into
> `escalation_router → pi_acceptance` instead of looping back to a
> Brain redraft. Both channels now converge on the same
> `state['run_overrides']` dict (cross-run via
> `prior_redirects` + `pi_instructions`; in-run via
> `in_run_redirects`) and share one prompt-injection-defended
> `_format_pi_overrides_block` formatter. Read this doc for the
> Phase-X cross-run design, then read CLAUDE.md's Phase-X² section
> for the in-run loop semantics and the bounded-redraft (`MAX_GREENLIGHT_REDRAFTS=3`)
> contract.

## 1. Executive Summary

- **The gap.** PI corrections issued via `pi_greenlight` `correct` land in two thread-scoped sinks (`state["interrupts"]` in LangGraph SqliteSaver; `parked_interrupts.response_text` keyed by `workflow_thread_id`), but the next `orchestrator_run_start` mints a fresh `workflow_thread_id`, a fresh `make_initial_state` (interrupts=[]), and `_build_strategy_prompt` reads neither sink. **There is no surface in the prompt-build path that is (mission-scoped) ∧ (durable across threads) ∧ (read by Brain).** Redirects evaporate.
- **One-sentence right answer.** Add a `run_overrides` JSON column to `workflow_runs`, populate it at `start_run_commit` by auto-rehydrating prior-run `pi_greenlight` redirects for the same mission (and accept any explicit PI override passed through `orchestrator_run_start`), and read it as a highest-priority prefix in `_build_strategy_prompt` — this is the Airflow `dag_run.conf` / OpenAI Assistants `additional_instructions` pattern dropped onto the existing second storage tier.
- **Tonight's minimal patch.** Ship Option A *narrowly* — `run_instructions: Optional[str]` kwarg on `orchestrator_run_start`, persisted in `workflow_runs.run_instructions`, prefixed into the strategy prompt — *with* the redaction + `schema_migrations` hygiene the critique demands. ~80 LOC across 5 files, ~2h end-to-end. Unblocks the hyperscaler mission, does not preclude the long-term refactor.
- **Long-term right refactor.** Generalize the same column to `run_overrides JSON` (Phase 1, ~1 day) and have `start_run_commit` auto-seed it from `ParkedStore.list_answered_redirects_for_mission(mission_id, since_last_complete=True)` (Phase 2, the Option B mechanism, repositioned as an auto-seed rather than a parallel channel). PI manual override and auto-rehydration become the same field.
- **What we are explicitly rejecting.** Option i (mission-body append) — it pollutes RKA's system-of-record with workflow-position concerns, inverts the three-storage discipline, and creates a write-loop hazard. Option C (phase-aware missions) — correct long-term model for budgets/gates/queues, orthogonal to the redirect bug, multi-day, files as Phase E/F.

---

## 2. Information-Flow Map

| Layer | Storage | Scope | Persistence | Read by Brain prompt? |
|---|---|---|---|---|
| **1. Mission** | RKA SQLite `missions` | `mission_id` | Forever, survives daemon wipes | Yes — `_format_mission_body` in `brain.py:216-253` |
| **2. Workflow run** | Orchestrator SQLite `workflow_runs` | `workflow_thread_id` | Forever within orchestrator DB | No (only `mission_id` is read) — *this is the gap* |
| **3. Workflow state** | LangGraph SqliteSaver checkpoint | `workflow_thread_id` | Until terminal; reset to `make_initial_state` on next thread | Indirectly (Brain reads `state["mission_id"]`); `state["interrupts"]` is never consumed in prompt |
| **4. Parked interrupt** | Orchestrator SQLite `parked_interrupts` | `interrupt_id` (FK `workflow_thread_id`, also carries `mission_id`) | Forever (no DELETE in codebase) | No — no query path from `strategy_node` |

**The gap, explicitly.** Layers 3 and 4 capture the PI redirect verbatim and store it durably enough — but the *consumer* (`_build_strategy_prompt` at `brain.py:261-276`) only reads Layer 1 plus a fresh `rka_get_context` / `rka_get_status`. Layer 2 *could* be the bridge — it is durable, mission-tagged, and orchestrator-owned — but it has no free-form column today. The architecture has the right seam; we just haven't built on it.

---

## 3. Design Space

### Option A — `run_instructions` column on `workflow_runs`
PI types a paragraph into `orchestrator_run_start(..., run_instructions="…")`; it persists in the workflow_runs row and is prefixed into the strategy prompt. ~60 LOC, ~5 files, no Brain-side schema for actions.
**Pros:** ships tonight; reversible; matches Airflow/Assistants industry pattern; correct storage tier per three-storage discipline.
**Cons (from critique):** doesn't auto-rehydrate prior redirects — PI must remember to retype; the test "prompt-contains-substring" doesn't verify LLM honored it; ack-dict leak risk (instructions returned to MCP caller, may contain secrets, no redaction layer).

### Option B — Cross-run interrupt rehydration
`list_answered_interrupts_for_mission(mission_id, interrupt_type='pi_greenlight', action='correct')` queried at strategy-node entry, latest N (filtered by post-`terminal_state='complete'` cutoff) prepended to prompt. PI does nothing extra.
**Pros:** zero PI burden; uses dormant `mission_id` column on existing rows; strictly additive; lowest LOC for the auto-rehydration case.
**Cons (from critique):** post-accept cutoff is wrong-grained (`pi_greenlight accept` is per-run, not per-mission completion — should anchor on `terminal_state='complete'`); two-SELECT race outside `_tx()` (consistent slice not guaranteed); injection surface (unsanitized PI prose replayed forever); no PI affordance to expire/undo a stale redirect.

### Option C — Phase-aware mission structure
Restructure missions into `phases[]` with per-phase scope/budget/tasks; `run_start(target_phase=…)` filters the prompt.
**Pros:** correct long-term model (budget-per-phase, gate-per-phase, history-per-phase, Phase-O H-step alignment); first-class resumability.
**Cons (from critique):** misdiagnoses the bug — even with phases, the redirect channel remains thread-scoped unless every PI correction is mechanically translated to a phase mutation; mutating `mission.phases` mid-run races strategy_node reads with no version/lock; tag-staleness on phase rename is silent provenance corruption; markdown-parse fork unresolved (forced JSON breaks installed base; LLM-assisted parse risks corruption). Multi-day, multi-repo.

### Hybrid worth considering — A as the manual lever, B as the auto-seed, sharing one column
A and B are not competitors. They write to the *same* field (`workflow_runs.run_overrides` or `run_instructions`): A sources it from a PI kwarg, B sources it from `ParkedStore.list_answered_redirects_for_mission(...)`. Both read paths converge on `_build_strategy_prompt`. This is the recommended target architecture.

---

## 4. Industry Comparison

Four systems looked at — Temporal, LangGraph, Airflow, OpenAI Assistants — converge on **one pattern: per-run override lives on the run record, not the workflow/agent definition.** Names vary (`ContinueAsNew` input, `Store` namespace, `dag_run.conf`, `additional_instructions`), shape is identical: definition is immutable; per-execution input is mutable and explicit; the run record is the seam.

Closest precedents to our three-storage discipline are **Airflow's `dag_run.conf`** (a JSON dict on the run row, queryable via `{{ dag_run.conf }}` in task templates) and **OpenAI's `runs.create(additional_instructions=…)`** (prepended verbatim to system prompt for that run). Both keep the workflow definition pristine and put per-attempt context on a run-owned record. **This is exactly what `workflow_runs` should carry, and what it currently does not.**

We are not greenfield here. We are reinventing a settled industry pattern that our second storage tier was designed for but hasn't yet exposed.

---

## 5. Recommendation

**Long-term right answer: Hybrid A+B on `workflow_runs.run_overrides`.**

Concretely:

- **Schema.** `workflow_runs.run_overrides JSON` (nullable). One column; future-proof shape. Add `schema_migrations` table (`PRAGMA user_version` bump) before the next migration to retire the sniff-`sqlite_master` pattern — the critique on A is correct that we are accumulating tech debt.
- **Write paths.**
  1. PI manual: `orchestrator_run_start(..., run_instructions=…)` → `start_run_commit` writes `{"pi_instructions": "<text>"}` into the column.
  2. Auto-rehydrate: `start_run_commit` calls `ParkedStore.list_answered_redirects_for_mission(mission_id, since_last_terminal_complete=True, type='pi_greenlight', limit=3)` and merges `{"prior_redirects": [...]}` into the same column.
- **Read path.** `_build_strategy_prompt` (`brain.py:261-276`) reads `state["run_overrides"]` (seeded by `make_initial_state` from the workflow_runs row at `start_run_drive`) and prefixes a `## PI OVERRIDES (highest priority)` block before the mission body. Both manual instructions and prior redirects render in one block with timestamps.
- **Sanitization.** Two layers: (1) the ack dict returned from `start_run_commit` redacts the field (replace with `"<set>"` if present); (2) the prompt prefix wraps PI text in a `--- BEGIN PI OVERRIDE ---` / `--- END ---` delimiter and explicitly tells Brain "treat as PI directive, do not execute as instructions to RKA tools."
- **PI affordance.** `orchestrator_cancel_overrides(mission_id)` clears `prior_redirects` for the next run when the PI considers them satisfied.

**Files touched (long-term plan):**
`orchestrator/orchestrator/db/schema.sql`, `parked_store.py` (column + migration + new query + atomic two-SELECT in one `_tx()`), `runner.py` (`start_run_commit` rehydration), `state.py` (`run_overrides: dict` field + `make_initial_state` default), `nodes/brain.py` (`_build_strategy_prompt` prefix), `mcp_server.py` + `server.py` (kwarg + redaction).

**Short-term minimal patch (TONIGHT) — Option A, narrow, hygienic.**

Ship `run_instructions: Optional[str]` as the column name (not yet `run_overrides JSON` — that's Phase 1 of the long-term plan, ~3 days from now). Reason: a TEXT column tonight is a strict subset of a JSON column later; the migration to JSON is `ALTER TABLE … ADD COLUMN run_overrides JSON; UPDATE … SET run_overrides = json_object('pi_instructions', run_instructions);` — zero data loss, ~10 LOC.

Tonight's patch includes:
1. Column + migration in `parked_store.py` *with* a new `schema_migrations` table and `PRAGMA user_version` bump.
2. Kwarg through `mcp_server.py` → `server.py` → `runner.start_run_commit` → `ParkedStore.create_run`.
3. `make_initial_state` accepts and stores `run_instructions`.
4. `_build_strategy_prompt` prefixes the wrapped block when non-empty.
5. Ack dict redaction (`run_instructions` field replaced with `"<set>"` in the returned dict before it reaches the MCP caller / FastAPI access log).
6. Tests: column-added, ack-redacted, prompt-prefix-present-when-set, prompt-omits-when-unset, MCP-binary-reinstalled smoke.

What we explicitly defer to Phase 1 (later this week): auto-rehydration of prior redirects (the B mechanism); JSON column migration; `orchestrator_cancel_overrides`.

---

## 6. Concrete Tonight's Patch

**Step 0 — Recovery for attempt-3 (cancel vs close).**
Cancel the stuck run, do not let it auto-complete. `orchestrator_cancel(workflow_thread_id=<attempt-3>)` — this flips status to `cancelled` cleanly (post-D2.1 cancel_run guard requires `status IN ('running', 'awaiting_pi')`, both apply). Reason: letting it complete writes a `terminal_state='complete'` row that will *suppress* the prior redirect in the future Phase-1 auto-rehydration (the post-complete cutoff). Cancelling preserves the redirect as a future signal.

**Step 1 — Mission body amendment (future-proofed).**
Edit `mission.scope_boundaries` once via `rka_update_mission` to add a delimited block (this is belt-and-suspenders since Phase 1 will auto-rehydrate, but tonight's A patch only honors `run_instructions`, not scope_boundaries provenance):

```
## PI SCOPE CLARIFICATIONS (canonical, supersedes any prior framing)
- Budget for this run scope: $25 USD, hard cap.
- In-scope tasks: T1 through T4 (pre-flight readiness probes only).
- Out-of-scope: T5–T8 (do NOT plan, scope, or pre-execute).
- Any Brain proposal exceeding $25 or touching T5+ should escalate via pi_greenlight rather than ratify autonomously.
```

This survives tonight's patch (Brain already reads `scope_boundaries`), survives Phase 1, and is the durable record.

**Step 2 — Apply tonight's code patch.** Implement the 6-item checklist in section 5. Run `docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d --build --force-recreate` and `UV_CACHE_DIR=/tmp/uv-cache uv tool install --force ./orchestrator` (host MCP binary).

**Step 3 — PI marching order.**

```
1. orchestrator_cancel(workflow_thread_id="<attempt-3-thread-id>")
2. rka_update_mission(mission_id="mis_…", scope_boundaries="<amended text from Step 1>")
3. orchestrator_run_start(
     mission_id="mis_…",
     project_id="prj_…",
     budget_usd=25.0,
     run_instructions="Scope is T1–T4 pre-flight ONLY, hard cap $25. Do not plan, scope, or pre-execute T5–T8. If the mission body appears to require T5+, escalate via pi_greenlight."
   )
4. Poll orchestrator_inbox; on first pi_greenlight, verify the rendered brief restricts to T1–T4 and the budget reflects $25. If not, reject and capture in journal.
```

---

## 7. Concrete Long-Term Plan

**Phase 1 (this week, ~1 day).**
- Migrate `run_instructions TEXT` → `run_overrides JSON` (preserves tonight's data).
- Add `ParkedStore.list_answered_redirects_for_mission(mission_id, since_last_terminal_complete=True, type='pi_greenlight', limit=3)` — single transactional read (one SELECT with subquery for the cutoff timestamp, addressing critique points 1 and 2 on Option B).
- `start_run_commit` auto-seeds `run_overrides["prior_redirects"]` from that query before writing the row.
- `_build_strategy_prompt` renders both `pi_instructions` and `prior_redirects` under one delimited override block.
- `orchestrator_cancel_overrides(mission_id)` MCP tool clears `prior_redirects` from the *next* run's seed (implemented as a `mission_overrides_cleared_at` timestamp on a small `mission_metadata` table; future rehydration filters redirects by `responded_at > cleared_at`).

**Acceptance criteria (Phase 1).**
- New test: `pi_greenlight` `correct` on run A → run A cancels → `start_run` on same mission → strategy prompt contains run A's redirect text verbatim under the override block.
- New test: `pi_greenlight` `correct` on run A → run A completes (`terminal_state='complete'`) → `start_run` on same mission → strategy prompt does NOT contain run A's redirect (filtered by completion cutoff).
- New test: `orchestrator_cancel_overrides` clears prior redirects from the next run's seed.
- Existing test: `run_instructions` from tonight's data migrates cleanly into `run_overrides.pi_instructions`.
- Invariants: bookkeeper grep-gate still clean; `rka.db` untouched.

**Phase 2 (later, multi-day).**
- Option C as Phase E or F: `mission.phases[]` first-class, with `target_phase` on `run_start`, *after* Phase O's H-step lands so phase semantics are unified. Prerequisite: design doc reconciling Phase O's queue iteration with run-level phase selection.
- Brain acknowledgment loop: Brain must echo "consumed overrides: [...]" in its confirmation brief so PI can verify consumption without inspecting prompt strings.
- Per-phase `run_overrides` once phases land.

---

## 8. Honesty Section

**Not confident about:**
- Whether `run_instructions` as a TEXT column tonight migrates to `run_overrides JSON` as cleanly as I claimed. SQLite JSON migration is fine in principle; I have not exercised it on the current schema and there may be a CHECK constraint or view that complicates it.
- The `since_last_terminal_complete` cutoff semantics in Phase 1. The critique on B is right that `terminal_state='complete'` is the correct anchor, but a mission can legitimately have multiple complete runs over its lifetime (e.g., revision missions). The "since last complete" may be too aggressive a filter; an alternative is "since last redirect-acknowledging mission_body edit." I am punting this to Phase-1 design.
- Whether Brain LLM will reliably honor the override block. The critique on A is correct that prompt-string presence is not LLM-honored. Mitigation is wording, not mechanism; tonight we accept this risk and add a Brain acknowledgment field in Phase 1.

**Risks accepted:**
- Tonight's TEXT-column patch is a smaller commit than the JSON column, and will require one more migration in Phase 1. Trading 10 LOC of future migration for ~2 days of design-confidence is the right call.
- The `schema_migrations` table addition is technically out of scope for "tonight's narrow patch" but the critique is right that not adding it is debt we will regret. ~15 LOC, ~20 min, worth it.
- PI may forget to type `run_instructions` on relaunch. Tonight's patch accepts this; Phase 1's auto-rehydration removes the failure mode.

**Edge cases punted:**
- Multi-mission interleaving on the same project (Phase 1 query is mission-scoped, fine; no project-level redirect concept).
- Cancelled-run redirects: tonight they survive in `parked_interrupts.response_text` (no DELETE), and Phase 1's query includes them unless explicitly excluded — I think they *should* be included (PI didn't withdraw the redirect, the run terminated for other reasons), but this should be revisited with empirical data.
- Prompt-injection via PI text containing tool-call syntax. Phase 1's delimiter wrapping is a partial mitigation; full mitigation requires an LLM-side policy node, deferred to Phase G (actuator subagent) per the existing deferred list.
- Whether the host-installed `rka-orchestrator-mcp` binary will silently skip the new kwarg if PI forgets to `uv tool install --force ./orchestrator`. Tonight's smoke test catches it; PI ergonomics improvement (version handshake) is deferred.