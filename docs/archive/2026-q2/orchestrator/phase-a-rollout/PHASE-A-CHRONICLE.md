# Phase A operational-rollout chronicle (Phase 2.4 → 2.14)

**Period**: 2026-05-17 → 2026-05-19
**Target mission** (held constant across all attempts): `mis_01KRVF159FEHMYD55Q6EQ7BD18` — 3 cross-reference items
**Acceptance criterion** (deferred and carried forward across 6 retries):
> 1+ of 3 target journals receive `related_decisions` writes verified
> via `rka_get(<jrn_id>).related_decisions` non-empty AND matching the
> IDs ratified by PI at `pi_decision_select`.
**Final result**: 3/3 — chapter close at Phase 2.14 (workflow thread `thr_op_rollout_v6_1779199949`).

This chronicle synthesizes the six successive empirical-rollout retries that
ratified Phase A's autonomous Brain↔Executor↔PI loop. It exists as a single
navigable history; each retry's full per-run narrative is preserved in this
directory (`operational-rollout-v1..v6.md` + `phase-2-9-subprocess-context.md`
+ `phase-2-11-investigation.md`). The canonical architectural notes folded
out of these documents now live in repo `CLAUDE.md` (Phase D2, D2.1, D2.5,
Phase-X, Phase-X²) and `CHANGELOG.md`.

## Why six retries

Each rollout held the same target mission and the same acceptance criterion;
each surfaced a NEW blocker class one layer deeper than the previous. The
retry chain validated layers progressively from the driver string contract
at the bottom of the stack up through brain-quality framing discipline at
the top. Every retry shipped infrastructure (driver tests, fold work,
permissions plumbing) that the next retry then exercised. No retry was
wasted, but each closed a non-overlapping failure class:

| Phase | Layer surfaced | Closed by |
|---|---|---|
| 2.4 (v1) | Driver string contract | Phase 2.4 patch (same run) |
| 2.6 (v2) | Subprocess permission model | Phase 2.7 architecture |
| 2.8 (v3) | Subprocess MCP project scope | Phase 2.9 RKA_PROJECT propagation |
| 2.10 (v4) | Brain wrapper-vs-target framing + decision_present topology | Phase 2.11 (T1 + T2) |
| 2.12 (v5) | WRITE_TOOLS allowlist coverage | Phase 2.13 (rka_bulk_update + rka_update_note) |
| 2.14 (v6) | — (chapter close, 3/3) | n/a |

## v1 (Phase 2.4) — driver string-contract bug

The first run shipped the operational driver + 14 regression tests + two
diagnostic checkpoints. Both runs reached `pi_greenlight` and terminated
in `escalation_router` because the driver returned `"accept"` for `a` at
every interrupt type — but `_route_after_pi_greenlight` checks `"approve" in
response`. PI typed `a` at greenlight → driver returned `"accept"` →
substring match failed → routed to escalation (skipping `pi_decision_select`).
Resolution `chk_01KRVG6GE119ASG26QKXH0N5D2` Option A: type-aware
`_ACCEPT_TOKEN_BY_INTERRUPT_TYPE` table (`pi_greenlight: "approve"`,
`pi_decision_select: "accept"`, `pi_acceptance: "accept"`) — the same
pattern Phase 1's `pilot_t12.py` had used. The retry exposed the deeper
gap (no mission body in the strategy prompt) which became Phase 2.5 scope.

## v2 (Phase 2.6) — executor subprocess has no write permissions

Phase 2.5 folded 17 ratified skill-prompt deltas into `BRAIN_SYSTEM` /
`EXECUTOR_SYSTEM` and added `rka_get_mission(mission_id)` to the
prompt-builder chain. v2's single run rode the brain pipeline through
`backbrief_draft` → `gate1_validation` (APPROVED for the first time) →
`pi_decision_select` (fired for the first time). But the `mission_execute`
artifact reported verbatim: *"Tool execution is blocked. Without permission
to call MCP or bash, I cannot perform any of T0–T6."* The `claude-agent-sdk`
subprocess had READ permission but no write tools — it could think but not
act. Three architecture options were enumerated (A: grant full MCP scope
to subprocess; B: parent-side dispatcher; C: hybrid — read scope in the
subprocess + parent-side dispatch of writes after PI ratification). Phase
2.7 ratified Option C, which became the load-bearing invariant for the
rest of Phase A and the entire agentic distribution.

## v3 (Phase 2.8) — subprocess MCP session scope mismatch

Phase 2.7 implementations landed: `READ_TOOLS` allowlist (9 entries),
`disallowed_tools` for all 7 WRITE_TOOLS, structured `proposed_actions` JSON
contract, `decision_present` → `pi_decision_select` flow, parent-side
`execute_ratified_actions` dispatcher. v3 empirically validated all 5
integration paths (read → plan → parse → ratify → execute) end-to-end —
but with 0/3 items written, for a NEW infrastructure reason: the
subprocess MCP child inherited `Default Project` (proj_default), not the
parent's configured `prj_01KKQM9JFG67GT5FGWTAHD9YE4`. Seven of seven
expected entities returned 404. The brain LLM caught this cleanly, emitted
a well-formed empty `{"proposed_actions": []}` with structured rationale,
and escalated correctly. Phase 2.9 closed the gap in 4 atomic commits:
T1 `RKA_PROJECT` env propagation via `McpStdioServerConfig.env` (load-
bearing); T2 added `rka_list_projects` + `rka_set_project` to READ_TOOLS
for self-recovery; T3 env-gated real-RKA integration probe; T4 cosmetic
`pi_acceptance` summary helper. Suite: 233 → 244 passing + 2 skipped.

## v4 (Phase 2.10) — brain-quality + decision_present topology gap

v4 validated the project-propagation fix (banner log explicitly named the
inherited project) AND validated every prior architectural layer — yet still
landed 0/3, this time at the brain-quality layer. The `mission_execute`
brain LLM interpreted the wrapper mission's T0-T7 wrapper-task structure as
the work to execute (deferring "T1 file edits" to proposed_actions, which
rolled up to a single `rka_submit_report` stub). The PI never saw the actual
proposed cross-reference writes. Compounding this, `decision_present` called
the brain LLM with a strategic-meta-decision prompt — NOT with the
`proposed_actions` JSON — so even if the executor HAD proposed correctly,
the PI-facing decision packet wouldn't have surfaced those actions by
identity. EC8 set-identity (`ratified == proposed`) was unverifiable by PI.

Phase 2.11 closed both findings: T1 added `decision_present` early-bypass
on non-empty `state["proposed_actions"]` that surfaces actions by identity
(no LLM re-detour); T2 added the EXECUTOR_SYSTEM 10th delta with canonical
marker phrase *"work-target is the `mission_id` field"* explicitly
disambiguating wrapper scaffolding from target work. Suite: 252+2 → 259+2.

## v5 (Phase 2.12) — WRITE_TOOLS allowlist gap

v5 was a pure empirical retry — zero orchestrator code changes per the
Brain spec. T1 (`decision_present` early-bypass) and T2 (wrapper-vs-target
framing) both fired correctly. The brain emitted target-scoped per-item
proposals. PI ratified. But the brain chose `rka_bulk_update` — which was
not in the `WRITE_TOOLS` allowlist — and the dispatcher emitted the
expected `ratified_action_tool_not_allowed` ErrorRecord. Phase 2.13
expanded WRITE_TOOLS to include `rka_bulk_update` alongside the existing
`rka_update_note`.

## v6 (Phase 2.14) — chapter close (3/3)

Another pure empirical retry, zero code changes. The brain chose
`rka_update_note × 3` (cleaner per-item dispatch) rather than `rka_bulk_update`
— both now allowlisted. All 3 writes landed atomically (identical
`updated_at` timestamps to the second). The driver crashed at the FINAL
node (`final_synthesis`) with a transient `Claude Code returned an error
result: success` SDK flake, but this was cosmetic — all 3 writes had
already dispatched. Per-target verification:

| Journal | `related_decisions` (observed) | Floor |
|---|---|---|
| `jrn_01KQQ4K4GWFKHQBCQNC9F92JX4` | 4 IDs matching ratified | **3/3 at strict floor** |
| `jrn_01KMX18FDBEE9T8JNHHAP649TE` | 2 IDs matching ratified | |
| `jrn_01KP4QR4XFP0ZHKR14B9ET6CN2` | 2 IDs matching ratified | |

## What landed in the agentic distribution

The infrastructure ratified by the 6-retry chain became Phase A's permanent
contribution to agentic and the foundation for everything that followed:

- **Phase 2.4** — driver type-aware accept-token table; `_ACCEPT_TOKEN_BY_TYPE`
  later promoted into `runner.py:resume_token` for the Phase-A HTTP/MCP
  surface, locking the v1 string-contract regression at the contract level.
- **Phase 2.5** — 17 skill-prompt deltas folded into `BRAIN_SYSTEM` +
  `EXECUTOR_SYSTEM` Python constants; mission-body data flow into prompt
  builders; canonical structured-handoff markers ("anti-pattern #12",
  Delta #1 `info.version`, Delta #8 `ErrorRecord over raising`, Delta #14a
  expected/observed framing, Delta #17 integrity error vocabulary).
- **Phase 2.7 Option C** — the read-only subprocess + parent-side WRITE
  dispatch invariant. Subprocess gets READ_TOOLS allowlist; WRITE_TOOLS go
  on `disallowed_tools`. LLM emits structured `proposed_actions` JSON;
  parent parses, surfaces via `decision_present`, ratifies via
  `pi_decision_select` (TWO-TAP autonomy-licensing gate), dispatches via
  `execute_ratified_actions`. EC8 set-identity: `ratified == proposed`.
- **Phase 2.9** — `RKA_PROJECT` propagation through `McpStdioServerConfig.env`
  (later superseded by v2.6's `project_id` kwarg contract on every rka tool,
  but the dead env-var threading stays in `llm_client._build_mcp_servers_config`
  as a documented hint per CLAUDE.md Phase D2.5).
- **Phase 2.11** — `decision_present` early-bypass on non-empty
  `proposed_actions`; EXECUTOR_SYSTEM 10th delta wrapper-vs-target framing.
- **Phase 2.13** — `WRITE_TOOLS` expanded; the dispatcher's
  `ratified_action_tool_not_allowed` ErrorRecord pattern set the precedent
  for Phase-X² polish enum-value and Phase-X²' required-field validation.

The Phase A surface itself (FastAPI daemon + MCP stdio + parked-interrupt
store) was added separately on top of this infrastructure and is documented
in CLAUDE.md's "Phase-A: Claude-Code-native PI surface" section.

## Where the substantive content lives now

- **Architectural invariants** — repo `CLAUDE.md` (Phase D2 through
  Phase-X²' sections), `orchestrator/CLAUDE.md`, `orchestrator/AGENTS.md`.
- **WRITE_TOOLS allowlist + chain semantics** — `orchestrator/orchestrator/executor.py`
  + `nodes/executor.py:execute_ratified_actions`.
- **READ_TOOLS allowlist + subprocess scope** — `orchestrator/orchestrator/llm_client.py`.
- **Brain + Executor system prompts** — `orchestrator/orchestrator/nodes/brain.py:BRAIN_SYSTEM`
  + `orchestrator/orchestrator/nodes/executor.py:EXECUTOR_SYSTEM`.
- **Response-token contract** — `orchestrator/orchestrator/response_tokens.py`
  + `runner.resume_token` (Phase D2.1 sentinel-prefix lock).
- **Cross-run + in-run redirect channel** — Phase-X / Phase-X² in CLAUDE.md;
  see also archived design memos `../cross-run-correction-channel.md`,
  `../phase-x-prime-polish-design.md`, `../v2.6.x-roadmap.md`.

## Pointers to individual archived sources

For deep-history reproduction of any single retry's per-run state, see:

- `operational-rollout-v1.md` — Phase 2.4 narrative + driver patch
- `operational-rollout-v2.md` — Phase 2.6 narrative + executor-permission discovery
- `operational-rollout-v3.md` — Phase 2.8 narrative + Phase 2.7 architecture validation + subprocess project mismatch
- `operational-rollout-v4.md` — Phase 2.10 narrative + brain-quality finding
- `operational-rollout-v5.md` — Phase 2.12 narrative + WRITE_TOOLS gap surfacing
- `operational-rollout-v6.md` — Phase 2.14 chapter close (3/3)
- `phase-2-9-subprocess-context.md` — Phase 2.9 4-commit narrative (T1-T4)
- `phase-2-11-investigation.md` — Phase 2.11 2-fix narrative (decision_present + EXECUTOR_SYSTEM delta)

The skill-prompt deltas folded in Phase 2.5 are archived at
`../skill-prompt-deltas.md`. The chapter-close mission was
`mis_01KRZ1QRMM7HGPYVAQPMXQVK3P`; the originating Phase 2 program decision
that authorized the multi-retry chain was `dec_01KRVE1ZT6M8VN4PQM7W2HE8X6`.
