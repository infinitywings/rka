# Operational rollout v4 — Phase 2.9 architecture validated; brain-quality + topology gap surfaced at mission_execute layer

**Mission**: `mis_01KRYBZ0W4Z9F1GXKP96ERKGKK` (Phase 2.10 — bundled retry + Phase 2.9 T3 debt discharge)
**Decision**: `dec_01KRYBR8APM187YJXQG2Q455EM` (Option A — bundled retry + bug fix; Brain-recommended; PI-handed-off)
**Branch**: `agentic` at HEAD post-this-commit
**Date**: 2026-05-18
**Target mission**: `mis_01KRVF159FEHMYD55Q6EQ7BD18` (same as v1, v2, v3; 3 cross-reference items)
**Workflow thread**: `thr_op_rollout_v4_1779136376` (no collision with v1/v2/v3)

## Headline

**Phase 2 chapter status: NEEDS DEEPER INVESTIGATION.** 0/3 cross-reference items completed despite all Phase 2.7+2.9 architectural pieces working at their intended layers. The blocker is now at the **brain-quality / decision_present-topology** layer, NOT the read/dispatch/permission/auth layers (all of which were validated in this run). One narrow architectural gap and one brain-framing-discipline gap are the Phase 2.11-investigation scope.

## What Phase 2.10 DID validate (significant positive signal)

### T1 — Phase 2.9 T3 debt discharge (`RestMCPClient.rka_get_journal`) — shipped

Commit `93dde3c`: URL `/api/journal`→`/api/notes`, return shape `dict`→`list[dict[str, Any]]`, client-side tag filter, Protocol updated, FakeMCP aligned, 6 new locking tests in `tests/test_rest_mcp_client_get_journal.py`, restored the Phase 2.9 T3 worked-around bypass-detection assertion. Suite: 244+2 → 252+2 (+8 net tests). Phase 2.9's `jrn_01KRY908A3RYX1TBH6CKKPJRGC` punch-list entry closed.

### T2 — Driver banner confirms Phase 2.9 T1 propagation LIVE in production

Driver header shows verbatim:

> *"SDK: REAL claude-agent-sdk (Claude Max routing; subprocess RKA_PROJECT=prj_01KKQM9JFG67GT5FGWTAHD9YE4)"*

The subprocess MCP child inherited the parent's `project_id` via `McpStdioServerConfig.env["RKA_PROJECT"]`. The 8th mandatory-pause trigger (subprocess-MCP-project-mismatch surfaced in Phase 2.8) is structurally closed and visibly confirmed in the runtime banner. No 404s on subprocess MCP reads this run.

### Phase 2.9 T4 cosmetic fix VALIDATED end-to-end

The pi_acceptance summary shows verbatim:

> *"Mission escalated via 1 checkpoint(s); 8 artifacts produced; see checkpoint detail."*

Composed from counts via `_compose_acceptance_summary(state)` — no longer the "APPROVED:" gate1 verdict leak from Phase 2.8. The Phase 2.9 T4 helper is empirically validated.

### Architectural inventory — all working at their intended layers

| Layer | Mechanism | Phase 2.10 evidence | Verdict |
|---|---|---|---|
| Subprocess MCP read scope | Phase 2.7 READ_TOOLS allowlist + Phase 2.9 T1 RKA_PROJECT env | Banner log; subprocess fetched mission body + journals via mcp__rka__rka_get | ✅ |
| Subprocess WRITE deny | Phase 2.7 disallowed_tools + permission_mode="dontAsk" | Phase 2.9 T3 integration test passed pre-flight; no bypass writes during this run | ✅ |
| Auth thesis | Phase 2 ANTHROPIC_API_KEY scrub via make_sdk() | Banner log shows scrub + Claude Max routing; usd_spent=0.0 end-to-end | ✅ |
| Mission body data flow | Phase 2.5 T4/T5 mission body in prompts | Banner shows full mission body loaded; Backbrief was substantive | ✅ |
| Structured output parser | Phase 2.7 T3c `_parse_proposed_actions` (fenced + brace-counted) | Extracted `{"proposed_actions": [...]}` from mission_execute reply cleanly | ✅ |
| Ratification copy | Phase 2.7 T3d pi_decision_select copies proposed→ratified on accept | (Not exercised; PI rejected at decision_select for cause) | (unexercised this run) |
| Parent-side WRITE dispatch | Phase 2.7 T3e execute_ratified_actions | (Not exercised; rejected before reaching this node) | (unexercised this run) |
| Driver re-prompt on empty Enter | Phase 2.7 T4 | PI typed explicit `a`/`r`/`a` at the 3 interrupts (no buffered-newline auto-accepts) | ✅ |
| pi_acceptance summary | Phase 2.9 T4 composed-from-counts | Banner log shows clean "Mission escalated via..." summary; no gate1 verdict leak | ✅ |
| `rka_get_journal` REST contract | Phase 2.10 T1 `/api/notes` + list[dict] + client-side tag filter | Restored Phase 2.9 T3 assertion passing pre-flight (integration probe) | ✅ |

10 of 10 architectural layers held. The blocker is upstream — in the brain LLM's interpretation of the mission, not in the orchestrator's execution machinery.

## What Phase 2.10 did NOT validate — and the two findings

### Finding 1 (brain-quality at mission_execute) — wrapper-vs-target misframing

The brain's `mission_execute` LLM **interpreted the Phase 2.10 wrapper mission's T0-T7 task structure as the work to execute**, rather than the target mission's 3 cross-reference items. The Confirmation Brief earlier in the run correctly distinguished wrapper from target (per Phase 2.8 carryforward discipline), but by the time `mission_execute` ran, the Backbrief had drifted to wrapper-task language ("T1 implemented the approved Backbrief as file edits only — no write-side RKA calls were made directly").

Concrete evidence (mission_execute artifact `jrn_01KRYE6GNFR0XD4B3F5H3SR6N9`):

> *"Mission executed through the standard orchestrator trajectory... T0 read-side pre-flight loaded mission... T1 implemented the approved Backbrief as file edits only — no write-side RKA calls were made directly, deferring all knowledge-base writes to the `proposed_actions` channel for PI selection."*

The emitted `proposed_actions` block contained **exactly ONE action**:

```json
{
  "tool": "rka_submit_report",
  "args": {summary, findings, anomalies, ..., related_journal: [5 run artifacts]},
  "rationale": "Submit the structured mission report so the orchestrator can advance to pi_acceptance."
}
```

**Not 3× `rka_update_note` against the target journals.** Zero proposals for any of `jrn_01KQQ4K4GWFKHQBCQNC9F92JX4`, `jrn_01KMX18FDBEE9T8JNHHAP649TE`, or `jrn_01KP4QR4XFP0ZHKR14B9ET6CN2`.

The brain treated the orchestrator's mission_execute as "execute the wrapper Backbrief's T0-T7 plan" (including a "T1 file edits" subtask that can't actually run because the subprocess has no Bash/file-edit tools). The "deferred to proposed_actions" framing then rolled up to a mission-report submission rather than the actual cross-reference writes.

**Same pattern as Phase 2.8** (meta-decision-instead-of-per-item-proposals) but **different cause**. Phase 2.8 was brain-over-cautious about an A1 cosmetic framing inconsistency. Phase 2.10 is brain-mis-leveling on what "execute" means.

### Finding 2 (architectural — decision_present ⊥ proposed_actions decoupling) — Phase 2.11 punch-list

A real Phase 2.7 design gap surfaced empirically: **decision_present's PI-facing decision packet is completely decoupled from `state["proposed_actions"]`**.

Look at the orchestrator's existing code:

```python
# brain.py:decision_present
def _build_decision_prompt(state: ResearchWorkflowState) -> str:
    return (
        "Draft a decision packet for PI selection. Provide:\n"
        "  - The question being decided.\n"
        "  - 2-4 options with trade-offs.\n"
        "  - The Brain's recommendation (option index + 1-sentence reason).\n\n"
        f"Current strategy:\n{state.get('brain_strategy', '(empty)')}\n"
        f"Executor's most recent position:\n{state.get('executor_position', '(empty)')}\n"
    )
```

`decision_present` doesn't read `state["proposed_actions"]`. It generates its own strategic decision packet from `brain_strategy` text. Meanwhile, Phase 2.7 T3d's `pi_decision_select` copies `proposed_actions → ratified_actions` on accept:

```python
# pi.py:pi_decision_select
ratified = list(state.get("proposed_actions", []) or []) if is_accept else []
```

**These two halves of the architecture are independent**:
- The PI-facing decision packet (decision_present output) is a strategic question the brain generated
- The mechanical accept/reject (pi_decision_select COPY semantics) acts on `proposed_actions` regardless of what the PI thinks they're approving

This is a **real architectural gap**, not just a brain-quality issue. The Brain explicitly relied on **EC8 set-identity** (proposed_actions = ratified_actions; verifiable by PI at the gate) in the Phase 2.10 Confirmation Brief — but the orchestrator's implementation makes EC8 *unverifiable* by the PI because they never see the proposed_actions in the decision packet.

In this run, PI was shown a "Phase 2 Closure Threshold" meta-decision (A/B/C/D options about set-identity strictness), not the actual `proposed_actions` block. The accept/reject signal would have copied an `rka_submit_report` stub action that PI couldn't have known about — leading to a malformed dispatch (`related_mission` kwarg missing) had PI accepted.

PI correctly typed `r` (reject); workflow routed cleanly to escalation_router; no malformed dispatch ran; error_count=0. The right call given the meta-decision didn't represent the actual work.

## 8 mandatory-pause triggers — none fired

| # | Trigger | Verdict |
|---|---|---|
| 1 | Brain proposes unrelated decisions on item 1 | N/A — no per-item proposals were emitted at all |
| 2 | Executor LLM bypasses disallowed_tools | DID NOT FIRE — subprocess held scope; no direct write attempts |
| 3 | `_parse_proposed_actions` fails | DID NOT FIRE — parser cleanly extracted the JSON (just wrong content) |
| 4 | pi_decision_select doesn't copy on accept | DID NOT FIRE — PI rejected, so the copy-on-accept path wasn't exercised |
| 5 | rka_update_note 422 from parent | DID NOT FIRE — no rka_update_note calls attempted |
| 6 | ANTHROPIC_API_KEY surfaces in subprocess env | DID NOT FIRE — Phase 2 auth thesis held end-to-end (usd_spent=0.0) |
| 7 | workflow_thread_id collides | DID NOT FIRE — `thr_op_rollout_v4_1779136376` unique |
| 8 | Subprocess 404 on target journal reads (CATASTROPHIC Phase 2.9 regression check) | DID NOT FIRE — Phase 2.9 T1 propagation worked |

**The actual blocker is a 9th trigger** that wasn't anticipated in the upfront 8-trigger list: brain misframes wrapper-vs-target at the mission_execute output layer, and decision_present surfaces a strategic meta-decision instead of proposed_actions. These are now the Phase 2.11-investigation scope.

## T0 → pi_acceptance timing

| Event | Time |
|---|---|
| Driver invoked | ~21:08 UTC |
| pi_greenlight interrupt | ~21:09 UTC (Confirmation Brief substantive) |
| PI typed `a` | T+0s |
| backbrief_draft → gate1 (APPROVED first pass) | jrn_01KRYDY29S3HP2J1B432PAD8AC at 21:09 |
| mission_execute | jrn_01KRYE6GNFR0XD4B3F5H3SR6N9 at 21:09 |
| pi_decision_select (meta-decision) | ~21:10 UTC |
| PI typed `r` | T+0s |
| pi_acceptance | ~21:10 UTC |
| PI typed `a` | T+0s |
| Driver exit | ~21:10 UTC |

Total wall-clock: ~2 minutes (well under the 8-15 min brain estimate; reject-at-decision_select short-circuited the full keystone path).

## 8 artifacts produced (workflow_thread_id `thr_op_rollout_v4_1779136376`)

| # | Artifact ID | Node | Reading |
|---|---|---|---|
| 1 | `jrn_01KRYDA1RSWJT6FYWXF0F2RY64` | `strategy_node` | Substantive; wrapper-vs-target framing correct at this layer |
| 2 | `jrn_01KRYDBNC604WFR4B4GGE68XZK` | `confirmation_brief` | Substantive; A1-A6 with explicit false-cases; EC8 set-identity discipline named |
| 3 | `jrn_01KRYDXKVJ8VMJW218RHAKKSDT` | `backbrief_draft` | Drift toward wrapper-task language ("T0 pre-flight (7 checks)") — this is where the misframing started |
| 4 | `jrn_01KRYDY29S3HP2J1B432PAD8AC` | `gate1_validation` | **APPROVED** first pass — gate1 validates plan coherence, not plan↔world correspondence |
| 5 | `jrn_01KRYE4V7A3R251TA1MCHF4YYC` | `mission_execute` log | "T1 implemented the approved Backbrief as file edits only" — the misframing in action |
| 6 | `mis_01KRVF159FEHMYD55Q6EQ7BD18` | `submit_report` (report) | Mission_id as report identity (Phase 2.7 T5 contract correct) |
| 7 | `jrn_01KRYE8R0A9NH8J06E7SD7RNGB` | `cluster_review` | Substantive research-map review (clean surface; 3 structural issues noted) |
| 8 | `jrn_01KRYEA1F5BYMWKYMANC88DSTG` | `decision_present` | The meta-decision packet that didn't surface proposed_actions |

Plus 1 escalation_router checkpoint (correct routing on `r` at pi_decision_select).

## Phase 2 chapter close-out: NEEDS DEEPER INVESTIGATION

0/3 cross-reference items completed for a NEW reason (combined brain-quality + topology gap), not for any of the 8 enumerated mandatory-pause triggers. Phase 2.11-investigation is the mandatory next mission.

## Recommendations for Phase 2.11-investigation

Two punch-list items, both narrow:

### Item 1 (architectural; ~2-3 hr): `decision_present` surfaces `state["proposed_actions"]`

Modify `orchestrator/orchestrator/nodes/brain.py:decision_present`:
- `_build_decision_prompt` reads `state["proposed_actions"]` and includes it verbatim in the prompt to the brain LLM, instructing the LLM to draft a decision packet that:
  - Lists the proposed actions (1 per row) with rationale + tool + args
  - Asks PI to verify the set
  - Single recommended option: "accept the proposed_actions as drafted"
  - Alternative options for partial-accept / reject

OR (simpler alternative): bypass the brain LLM at `decision_present` entirely when `state["proposed_actions"]` is non-empty — directly build the decision packet from the structured data with no LLM intermediation. Surfaces the actual proposed actions to PI for ratification; preserves EC8 set-identity guarantee.

Add 2-3 regression tests in `tests/test_brain.py` asserting decision_present's output includes proposed_actions when present.

### Item 2 (brain-prompt discipline; ~1-2 hr): EXECUTOR_SYSTEM prose addition for wrapper-vs-target framing at mission_execute

Phase 2.7 EXECUTOR_SYSTEM already has 9 deltas folded in (Phase 2.5 + 2.7). Add a 10th delta covering wrapper-vs-target discipline:

> *"Wrapper-vs-target framing. When mission_execute runs, the work-target is the mission_id in state, NOT the wrapper mission whose Backbrief you're reading. If the Backbrief says 'T1 fix RestMCPClient.rka_get_journal', that's wrapper-mission scaffolding describing what the PI/Brain did to PREPARE for this run — not work you should re-do. Your work is on the target mission's actual tasks (e.g., 'Add related_decisions to 3 ratified journal entries'), not on the wrapper's planning structure."*

Add 1 regression test in `tests/test_executor.py` asserting EXECUTOR_SYSTEM contains the wrapper-vs-target delta marker.

### Item 3 (optional; only if 1+2 don't suffice): per-item iteration in graph topology

Phase 2.6 finding (decision_present fires once per workflow). Phase 2.7+2.9+2.10 deferred this. If Phase 2.11 fixes 1+2 and the resulting Phase 2.12 retry still shows brain confusion at 3-item batch, consider per-item iteration. But probably not needed — the issue isn't batching, it's the brain mis-leveling on what "execute" means.

Estimated total: 3-5 hr for items 1+2 combined. Item 3 is optional.

### After Phase 2.11 ships, Phase 2.12 retries the operational rollout

Same target `mis_01KRVF159FEHMYD55Q6EQ7BD18`, fresh `thr_op_rollout_v5_<unix_ts>`. With decision_present surfacing proposed_actions AND EXECUTOR_SYSTEM having clearer wrapper-vs-target framing, brain should emit 3× rka_update_note proposed_actions, PI sees them, ratifies, parent dispatches.

If Phase 2.12 retry still produces 0/3 items, the issue is deeper than these two fixes — file a Phase 2.13-deep-investigation.

## Telemetry-zero compliance

✓ PASSED. Across this run:
- No third-party network calls (`notifications.py` defaults to bell + osascript per Phase 2.3 Delta #9)
- `ANTHROPIC_API_KEY` was set but scrubbed by `make_sdk()` before subprocess invocation
- All MCP traffic to `http://localhost:9712` (local RKA)
- All SDK traffic to bundled `claude` subprocess
- `usd_spent: 0.0` — Claude Max routing held end-to-end

## Branch state at Phase 2.10 close-out

- `agentic` HEAD: post-this-commit. 2 new commits: `93dde3c` (T1 rka_get_journal fix) and this commit (T5 narrative).
- `main`: unchanged at `c063673`.
- No new release tag. `v2.5.3+agentic` final tag stands.
- Suite at 252 passing + 2 skipped (T3 integration tests env-gated).
- Bookkeeper + agentic-branch + grep-gate invariants verified at every commit.

## Run summary statistics

| Metric | Value |
|---|---|
| `terminal_state` | complete |
| Total artifacts | 8 |
| Interrupts | 3 (pi_greenlight + pi_decision_select + pi_acceptance) |
| Errors | 0 ✓ |
| Checkpoints | 1 (escalation_router fired on `r` at pi_decision_select — expected) |
| USD spent | 0.0 ✓ (Claude Max routing held) |
| PI explicit input rate | 3/3 (driver re-prompt on empty Enter prevented buffered-newline auto-accepts) |
| Target journal `related_decisions` populated | 0/3 (floor breached) |
| Phase 2.10 acceptance criterion met | NO |
| Phase 2 chapter status | NEEDS DEEPER INVESTIGATION |

## Lineage chain at close

- Phase 2.4 (`mis_01KRVE4J71T6M6XWPDVPXMFJ49`): driver-string-contract bug found; acceptance deferred
- Phase 2.6 (`mis_01KRVM7BDCX0ATBERR6DAFTXZV`): subprocess permissions blocker surfaced; acceptance deferred
- Phase 2.8 (`mis_01KRXRF6VRFAAV1T8XKZ3RHJXJ`): subprocess project mismatch surfaced; acceptance deferred
- Phase 2.10 (`mis_01KRYBZ0W4Z9F1GXKP96ERKGKK`, this mission): brain-quality + decision_present-topology surfaced; **acceptance deferred to Phase 2.12**
- Phase 2.11-investigation: file as new mission; 2 narrow punch-list items above
- Phase 2.12-retry: target unchanged; fresh `thr_op_rollout_v5_<unix_ts>`; same minimum-1-of-3 criterion

The pattern across 2.4 → 2.6 → 2.8 → 2.10 is consistent: each retry surfaces a new layer of the stack as the dominant blocker once the previous layer is closed. Phase 2.10's combined finding is now the last layer (brain quality + decision_present topology); Phase 2.11 should close it.

## Bookkeeper + agentic-branch + grep-gate invariants

✓ `git diff main -- rka/services/worker.py = 0` throughout Phase 2.10.
✓ `git diff main -- rka/ = 0` for both Phase 2.10 commits.
✓ `grep -rn 'from rka\|import rka' orchestrator/` returns no production-code matches.
