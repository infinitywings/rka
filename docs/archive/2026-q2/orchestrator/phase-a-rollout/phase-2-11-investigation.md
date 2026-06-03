# Phase 2.11-investigation — decision_present surfaces proposed_actions + EXECUTOR_SYSTEM wrapper-vs-target delta

**Mission**: `mis_01KRYT62XQK5NK3BY7G9BGRAPS` (Phase 2.11 — two-item punch-list closing Phase 2.10's two findings)
**Decision**: `dec_01KRYT1GCP5N9CJZ2YE2N3BTBH` (Option A — two-item punch-list; Brain-recommended; PI-handed-off)
**Branch**: `agentic` at HEAD post-this-commit
**Date**: 2026-05-19
**Depends on**: `mis_01KRYBZ0W4Z9F1GXKP96ERKGKK` (Phase 2.10 — surfaced both findings empirically; NEEDS DEEPER INVESTIGATION)

## Headline

**Phase 2.11 closes both findings from Phase 2.10's NEEDS DEEPER INVESTIGATION close-out** via three atomic commits on agentic, all under `orchestrator/`:
- T1 `151065c` — `decision_present` early-bypass on non-empty `state["proposed_actions"]` (architectural fix; ~95 LOC)
- T2 `3d74a1f` — `EXECUTOR_SYSTEM` 10th delta: wrapper-vs-target distinction (brain prompt discipline; ~22 LOC)
- T3 `025fda1` — 7 new regression tests (5 decision_present + 2 EXECUTOR_SYSTEM); suite 252+2 → 259+2 skipped

Phase 2.12 is now **CHAPTER-CLOSE-READY**: retry the operational rollout against the same target `mis_01KRVF159FEHMYD55Q6EQ7BD18` with a fresh `thr_op_rollout_v5_<unix_ts>` workflow_thread_id. With both Phase 2.11 fixes live, brain `mission_execute` should emit 3× `rka_update_note` proposed_actions (not a wrapper-scaffolding stub), `decision_present` should surface those actions by identity in the PI-facing decision packet (not a strategic meta-question), and the PI's accept routes through the existing Phase 2.7 T3d copy semantics to `execute_ratified_actions` for parent-process dispatch.

## Finding 1 (Phase 2.10 brain-quality at mission_execute) → Phase 2.11 T2 fix

### Phase 2.10 evidence

The Phase 2.10 mission_execute artifact (`jrn_01KRYE6GNFR0XD4B3F5H3SR6N9`) showed the brain LLM emitting a single `rka_submit_report` stub:

```json
{"proposed_actions": [
  {"tool": "rka_submit_report", "args": {summary, findings, ...}, "rationale": "..."}
]}
```

NOT 3× `rka_update_note` for the target mission's 3 cross-reference items. Verbatim mission_execute language: *"T1 implemented the approved Backbrief as file edits only — no write-side RKA calls were made directly, deferring all knowledge-base writes to the proposed_actions channel for PI selection."*

The brain interpreted my Phase 2.10 upfront Backbrief's T0-T7 wrapper-task structure as the work to execute, including a "T1 file edits" subtask (which can't run; subprocess has no Bash/file-edit tools). The "deferred to proposed_actions" framing then rolled up to a mission-report submission rather than the actual cross-reference writes.

### T2 fix (commit `3d74a1f`)

Added a 10th delta to `EXECUTOR_SYSTEM` (after Phase 2.5 deltas #1, #8, #14b, #17 and Phase 2.7 "Action proposals" prose). Canonical marker phrase: **"work-target is the `mission_id` field"**. Full text:

> *"Wrapper-vs-target distinction. When `mission_execute` runs, your work-target is the `mission_id` field in the workflow state, NOT the wrapper mission whose Backbrief you may be reading. If the Backbrief outlines T0-T7 plan structure (pre-flight, debt discharge, driver invocation, keystone test, narrative, commits, mission report), that is wrapper scaffolding the orchestrator already executes via graph topology — your job is to execute against the target mission's actual tasks (typically cross-reference work, content extraction, decision linkage, etc.). Read the target mission via `rka_get_mission(mission_id_in_state)` before planning `proposed_actions`; ground every action item in the target mission's task list, not the wrapper's planning structure. A wrapper Backbrief's T1-T7 are framework metadata describing what the PI/Brain did to PREPARE this run — they are not your work to re-do."*

### T2 regression tests (2 in `test_executor.py`)

- `test_EXECUTOR_SYSTEM_includes_phase_2_11_wrapper_vs_target_delta` — asserts the canonical marker phrase + heading + T0-T7 wrapper-scaffolding callout + `rka_get_mission` instruction all present.
- `test_EXECUTOR_SYSTEM_delta_count_advances_through_phase_2_11` — soft assertion guarding against accidental deletion of earlier deltas during future folds. Counts 6 distinct section markers (4 Phase 2.5 + 1 Phase 2.7 + 1 Phase 2.11).

## Finding 2 (Phase 2.10 architectural — decision_present ⊥ proposed_actions) → Phase 2.11 T1 fix

### Phase 2.10 evidence

`decision_present` (Phase 2.7 design) called the brain LLM with a `_build_decision_prompt(state)` that read only `state["brain_strategy"]` + `state["executor_position"]` — NOT `state["proposed_actions"]`. The PI-facing decision packet was a brain-generated strategic meta-decision (Phase 2.10 emitted "Phase 2 Closure Threshold A/B/C/D" options), while `pi_decision_select` (Phase 2.7 T3d) mechanically copies `proposed_actions → ratified_actions` on accept regardless of what the PI thought they were approving.

**EC8 set-identity** (which the Brain explicitly relied on at the Phase 2.10 Confirmation Brief: *"ratified must equal proposed"*) was **unverifiable by PI** because the proposed_actions were never surfaced in the decision packet.

### T1 fix (commit `151065c`)

Added two helpers + early-bypass to `orchestrator/orchestrator/nodes/brain.py`:

```python
def _render_proposed_actions_packet(proposed_actions: list[dict]) -> str:
    """Render proposed_actions as a PI-facing decision packet body.
    Each action's identity (tool, args, rationale) appears so PI can
    verify the set before ratifying."""

def _decision_present_from_proposed_actions(
    state, mcp, proposed_actions
) -> dict:
    """Early-bypass path: builds decision packet directly from structured
    data; NO brain LLM call. Restores EC8 set-identity verifiability."""

def decision_present(state, sdk, mcp) -> dict:
    proposed_actions = list(state.get("proposed_actions") or [])
    if proposed_actions:
        return _decision_present_from_proposed_actions(state, mcp, proposed_actions)
    # Fall-through: existing strategic-meta-decision flow preserved
    # (backward compatible for workflows where mission_execute emits no
    # proposed_actions, e.g., open strategic questions).
    ...
```

Packet structure:
- `title`: `f"Brain proposes {n} action(s) — ratify the set?"`
- `context`: markdown rendering with each action's tool, args, rationale
- `proposed_actions`: structured list (for driver/UI rendering by identity)
- `summary`: `f"Brain proposes {n} action item(s); ratify the set or surface objections (EC8: ratified must equal proposed)"`

Journal entry tagged `decision-draft` + `proposed-actions-set` (distinguishes from strategic-meta-decision journal).

### T1 regression tests (5 in new `test_decision_present_proposed_actions.py`)

1. `test_decision_present_with_proposed_actions_builds_structured_packet` — load-bearing: brain LLM NOT invoked (zero `complete()` calls); each action's identity present in packet; structured `proposed_actions` field on entry.
2. `test_decision_present_without_proposed_actions_falls_through_to_strategic_path` — backward compat for both explicit-empty and missing-key cases; existing flow preserved.
3. `test_decision_present_then_pi_decision_select_copies_proposed_actions_to_ratified` — Phase 2.11 T1 × Phase 2.7 T3d integration check. EC8 set-identity: after decision_present (early-bypass) → pi_decision_select (accept), `ratified_actions == proposed_actions` exactly.
4. `test_decision_present_packet_summary_renders_action_count` — summary + title mention N; EC8 set-identity language present.
5. `test_decision_present_early_bypass_writes_journal_with_proposed_actions_set_tag` — workflow_thread_id tag lineage + `proposed-actions-set` tag distinguishes packet type.

## Phase 2.7 T3d mechanical copy — unchanged and validated

The mechanical `proposed_actions → ratified_actions` copy at `pi_decision_select` (Phase 2.7 T3d):

```python
ratified = list(state.get("proposed_actions", []) or []) if is_accept else []
```

is **unchanged**. Phase 2.11 T1 only changes the PI-visible packet shape, not the copy semantics. Test 3 above explicitly validates that the copy still works correctly with the new packet shape.

## Suite count progression

| Phase | Suite | Delta |
|---|---|---|
| Phase 2.10 close | 252 passing + 2 skipped | (baseline) |
| Phase 2.11 T1 | 252 + 2 skipped (unchanged; source change only) | +0 |
| Phase 2.11 T2 | 252 + 2 skipped (unchanged; constant prose addition only) | +0 |
| Phase 2.11 T3 | 259 + 2 skipped | **+7 regression tests** |
| **Phase 2.11 close** | **259 + 2 skipped** | **+7 net new** |

Slightly above Brain's upfront estimate (~258). All passing. No regressions in existing Phase 2.7+2.9 tests.

## Bookkeeper + agentic-branch + grep-gate invariants

Verified at every commit boundary:
- `git diff main -- rka/services/worker.py = 0` throughout Phase 2.11
- `git diff main -- rka/ = 0` for all 3 Phase 2.11 commits + this T4 commit
- `grep -rn 'from rka\|import rka' orchestrator/` — clean (no production code references)
- Push-after-every-commit + `git ls-remote origin agentic` verified

## Phase 2.12 readiness statement

**🟢 CHAPTER-CLOSE-READY**

Both Phase 2.10 findings closed:
1. ✅ Finding 1 (brain wrapper-vs-target misframing at mission_execute) — Phase 2.11 T2 EXECUTOR_SYSTEM 10th delta lands the discipline at the prompt layer. Canonical marker phrase locked by regression test.
2. ✅ Finding 2 (decision_present decoupled from proposed_actions) — Phase 2.11 T1 early-bypass surfaces the structured action list directly to PI. EC8 set-identity verifiability restored.

Both fixes are orthogonal (separate modules: `brain.py:decision_present` for #1, `executor.py:EXECUTOR_SYSTEM` for #2) and individually load-bearing. No coupling; either can ship independently. Phase 2.11 ships both atomically (3 source commits + 1 narrative commit = 4 atomic commits total per spec).

### Recommended Phase 2.12 mission shape

- **Target**: `mis_01KRVF159FEHMYD55Q6EQ7BD18` (same Phase 2.4→2.6→2.8→2.10 target; 3 cross-reference items intact; all 3 target journals' `related_decisions=null` per Phase 2.10 T4 verification)
- **Workflow thread**: fresh `thr_op_rollout_v5_<unix_ts>` (no collision with v1/v2/v3/v4)
- **Acceptance criterion** (deferred from Phase 2.4 → 2.6 → 2.8 → 2.10): 1+ of 3 cross-reference items has non-empty `related_decisions` post-run, matching the IDs ratified by PI at the keystone interrupt. Ideally all 3.
- **Mandatory-pause triggers**: original 8 from Phase 2.10 + the now-closed "9th trigger" (brain wrapper-vs-target misframing + decision_present meta-instead-of-proposed_actions) as CATASTROPHIC regression check. If the 9th trigger fires at Phase 2.12 (brain still misframes OR decision_present still surfaces meta-decision when proposed_actions non-empty), file Phase 2.13-deep-investigation.
- **Pre-flight in Phase 2.12 T0**: explicit verification that Phase 2.11 T1+T2 are present (1 keystone test per fix: `test_decision_present_with_proposed_actions_builds_structured_packet` + `test_EXECUTOR_SYSTEM_includes_phase_2_11_wrapper_vs_target_delta`). Both pass at Phase 2.11 close.
- **Estimated**: ~30-60 min PI deliberation for the keystone interrupt; ~$0.50-2.00 in API credits (Claude Max routing should keep `usd_spent=0`).

### Expected behavior with Phase 2.11 fixes live

Step-by-step prediction (the "happy path" Phase 2.12 should follow):

1. Driver invokes with fresh `thr_op_rollout_v5_<unix_ts>` + project_id propagation (Phase 2.9 T1) — banner shows `subprocess RKA_PROJECT=prj_01KKQM9JFG67GT5FGWTAHD9YE4`.
2. `strategy_node` + `confirmation_brief` produce substantive output (Phase 2.5+2.7+2.9 deltas all in EXECUTOR_SYSTEM + BRAIN_SYSTEM).
3. PI types `a` at `pi_greenlight`.
4. `backbrief_draft` produces a substantive Backbrief; `gate1_validation` APPROVES on first pass (Phase 2.10 already showed this works).
5. `mission_execute` LLM — **with the new Phase 2.11 T2 delta in EXECUTOR_SYSTEM** — reads the target mission via `rka_get_mission(mission_id_in_state)` and grounds its proposed_actions in the target mission's task list (3 cross-reference items), NOT the wrapper's T0-T7 structure. Emits 3× `rka_update_note` proposed_actions (one per target journal).
6. `_parse_proposed_actions` extracts the JSON cleanly; `state["proposed_actions"]` populated with 3 entries.
7. `decision_present` — **with the new Phase 2.11 T1 early-bypass** — sees non-empty `proposed_actions`, bypasses brain LLM, builds packet directly from structured data. PI-facing payload carries each action by identity (tool=rka_update_note, args.id=jrn_*, args.related_decisions=[dec_*, ...], rationale).
8. `pi_decision_select` fires; PI inspects the 3 proposed_actions in the decision packet (they ARE visible now, per T1). PI verifies item 1's proposal cites the 4 in-Provenance IDs. If clean, PI types `a`.
9. `pi_decision_select` mechanical copy: `ratified_actions = proposed_actions` (EC8 set-identity holds).
10. `execute_ratified_actions` (Phase 2.7 T3e) iterates `ratified_actions` and dispatches 3× `mcp.rka_update_note(id=jrn_*, related_decisions=[dec_*, ...])` from parent process.
11. `final_synthesis` + `pi_acceptance` close the workflow cleanly. PI types `a`.
12. Post-run: `rka_get(<jrn>).related_decisions` non-empty AND ID-identical to PI-ratified set on all 3 target journals. **Acceptance criterion satisfied; Phase 2 chapter EMPIRICALLY CLOSED.**

If step 5 still emits wrapper-scaffolding actions instead of cross-reference actions, the T2 delta wasn't enough — file Phase 2.13 for further prompt tuning. If step 7 still surfaces a strategic meta-decision, the T1 early-bypass has a bug — surface immediately.

## Pattern across the retry chain (lineage)

| Phase | Blocker surfaced | Closed in |
|---|---|---|
| 2.4 | Executor permission scope (subprocess couldn't read) | Phase 2.5 |
| 2.6 | Subprocess permission scope (couldn't write) | Phase 2.7 Option C |
| 2.8 | Subprocess MCP project propagation (8th trigger) | Phase 2.9 T1 |
| 2.10 | Brain-quality + decision_present topology | Phase 2.11 (this) |
| 2.12 | — (expected: chapter close on first try given the orthogonal fixes) | TBD |

Each retry has closed one layer and uncovered the next. Phase 2.11's two findings are plausibly the LAST load-bearing layer — Finding 2 (decision_present ⊥ proposed_actions) was structural rather than behavioral, so once fixed it shouldn't have a layer behind it. Finding 1 (brain framing discipline) is prompt-level, also structural-ish.

**Confidence: moderate.** The pattern has surprised us 4 times already. Phase 2.12 either confirms the chapter close or surfaces a Phase 2.13 candidate.

## Brain-side discipline carryforward (PI/Brain — me — at Phase 2.12 Backbrief)

Phase 2.10's failure had two layers:
- Brain LLM at `mission_execute` misframed wrapper-vs-target (closed by T2 delta)
- **Brain-side framing discipline (mine)**: my Phase 2.10 upfront Backbrief over-detailed the wrapper's T0-T7 plan structure, which the brain LLM read as work-target. Complementary to the T2 delta — I need to keep wrapper-scaffolding visually distinct from target-work in the Phase 2.12 Backbrief.

Phase 2.12 Backbrief discipline:
1. **Header section** explicitly names the target mission and the 3 cross-reference items as "the work"
2. **Wrapper scaffolding** (T0-T7 plan) lives in a separately-labeled section with explicit framing: "what I/the orchestrator do to PREPARE the run" — never mixed with "the work" section
3. **Acceptance criterion** measured at target-journal level (`related_decisions` non-empty + ID-identical to ratified set), not wrapper-mission status

This is the Brain-side complement to the T2 LLM-side discipline. Both layers should reinforce.

## Branch state at Phase 2.11 close-out

- `agentic` HEAD: post-this-commit. 4 new commits: `151065c` (T1), `3d74a1f` (T2), `025fda1` (T3), this commit (T4 narrative).
- `main`: unchanged at `c063673`.
- No new release tag. `v2.5.3+agentic` final tag stands.
- Suite at 259 passing + 2 skipped (T3 integration tests env-gated).
- All invariants verified at every commit.

## Bookkeeper + agentic-branch + grep-gate invariants

✓ `git diff main -- rka/services/worker.py = 0` throughout Phase 2.11.
✓ `git diff main -- rka/ = 0` for all Phase 2.11 commits.
✓ `grep -rn 'from rka\|import rka' orchestrator/` — clean (no production-code matches).
✓ Push-after-every-commit + `git ls-remote origin agentic` verified after each commit.
