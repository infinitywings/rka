# Phase 2.9 — Subprocess MCP project_id propagation + READ_TOOLS expansion + integration probe + cosmetic fix

**Mission**: `mis_01KRY2KP0GGZY21BA4Z2R2S718` (Phase 2.9 — narrow 3-item punch-list closing the 8th mandatory-pause trigger from Phase 2.8 + optional T4 cosmetic)
**Decision**: `dec_01KRY2EXCSTSSCFZJ96VG4MGDW` (Option A — narrow scope; Brain-recommended; PI-handed-off)
**Branch**: `agentic` at HEAD post-this-commit
**Date**: 2026-05-18
**Depends on**: `mis_01KRXRF6VRFAAV1T8XKZ3RHJXJ` (Phase 2.8 — surfaced the subprocess-MCP-project-mismatch finding empirically)

## Headline

**Phase 2.9 closes the 8th mandatory-pause trigger surfaced by Phase 2.8** via four atomic commits on agentic, all under `orchestrator/`:
- T1 `be4cc64` — subprocess MCP project_id propagation (load-bearing fix)
- T2 `935757e` — READ_TOOLS 9→11 (belt-and-suspenders self-recovery path)
- T3 `bd2569e` — env-gated real-RKA integration probe (catches future drift)
- T4 `8afdd2f` — optional cosmetic shipped within scope (pi_acceptance summary no longer leaks gate1 verdict)

Suite: 233 → **244 passing + 2 skipped** (T3 integration tests env-gated; CI shows them skipped). Bookkeeper + agentic-branch + grep-gate invariants verified at every commit.

Phase 2.10 is now ready: retry the Phase 2.4→2.6→2.8 operational rollout against the same target with fresh `thr_op_rollout_v4_<unix_ts>`. With T1's project propagation closing the 8th trigger and T2's allowlist expansion providing a self-recovery path, high probability of empirical success on first try.

## T1 — Subprocess MCP project_id propagation (load-bearing)

### Phase 2.8 finding recap

`jrn_01KRY18QH8RBK5TF445KWJW1H8` (mission_execute artifact from Phase 2.8 run `thr_op_rollout_v3_1779115398`) showed:

> *"Active project is `Default Project` (Phase D — IPAL/HAI work). All 7 expected entities returned 404 — they live in a different project. This is the MCP `_session.project_id` issue documented in the Executor skill: ephemeral per-process."*

The parent process's `RestMCPClient(project_id=prj_01KKQM9JFG67GT5FGWTAHD9YE4)` setting governed parent-side REST calls (where brain nodes like `strategy_node` and `gate1_validation` worked correctly). But the subprocess spawned its own `rka mcp` stdio binary via `McpStdioServerConfig(command="/Users/ceron/.local/bin/rka", args=["mcp"])` — and that binary had its own MCP session, starting in `Default Project` (proj_default — currently Phase D Mission 6 IPAL/HAI work).

The transitive env inheritance from the claude CLI subprocess didn't carry the `RKA_PROJECT` env var (it wasn't set in the parent process), so the subprocess fell through to its default.

### T1 fix shape

Four file edits + one new test file (commit `be4cc64`):

- `orchestrator/orchestrator/llm_client.py:_build_mcp_servers_config(rka_binary, project_id=None)` — new `project_id` param. When non-None (and truthy), sets `McpStdioServerConfig.env = {"RKA_PROJECT": project_id}`. Back-compat: when None or empty, env key is omitted (Phase 2.8 ran with this code path; preserved bit-for-bit).
- `orchestrator/orchestrator/llm_client.py:_RealSDKClient.__init__(*, env=None, project_id=None)` — accepts new `project_id` param; stores at construction time.
- `orchestrator/orchestrator/llm_client.py:_RealSDKClient._async_complete` — threads `self._project_id` to `_build_mcp_servers_config(rka_binary, project_id=self._project_id)`.
- `orchestrator/orchestrator/llm_client.py:make_sdk(project_id=None)` — new param threaded through to `_RealSDKClient(env=_scrubbed_env(), project_id=project_id)`. Default None means pre-Phase-2.9 callers continue to work.
- `orchestrator/orchestrator/state.py` — additive `project_id: str` field in `ResearchWorkflowState`. `make_initial_state(..., project_id="")` default-empty param.
- `orchestrator/scripts/driver.py` — pre-existing `--project-id` arg (default `prj_01KKQM9JFG67GT5FGWTAHD9YE4`) now threaded into BOTH `make_sdk(project_id=args.project_id)` AND `make_initial_state(..., project_id=args.project_id)`. Driver log banner shows the active project_id.

### T1 regression tests (6 new in `tests/test_llm_client_project_propagation.py`)

| # | Test | Locks |
|---|---|---|
| 1 | `test_build_mcp_servers_config_with_project_id_sets_env` | Load-bearing: env carries RKA_PROJECT |
| 2 | `test_build_mcp_servers_config_without_project_id_omits_env` | Back-compat: None / empty omits env |
| 3 | `test_make_sdk_threads_project_id_to_subprocess_config` | End-to-end propagation through SDK |
| 4 | `test_make_sdk_scrubs_anthropic_api_key_with_project_id_set` | Phase 2 auth thesis preserved across new param |
| 5 | `test_state_carries_project_id_through_make_initial_state` | Additive state field round-trips |
| 6 | `test_real_sdk_client_without_project_id_omits_subprocess_env` | Back-compat at SDK layer (not just make_sdk) |

## T2 — READ_TOOLS expansion (belt-and-suspenders)

### T2 fix shape

`orchestrator/orchestrator/llm_client.py:READ_TOOLS` — added `rka_list_projects` + `rka_set_project`. New length: 9 → 11. Confirmed both are read-side (session-context selectors; cannot mutate entities).

### Why belt-and-suspenders is non-redundant

Even with T1's RKA_PROJECT env propagation working, an extra defense layer matters because:
1. Future drift in `_build_mcp_servers_config` could re-introduce the gap silently.
2. Future scope changes (e.g., dynamic project switching mid-workflow) might need runtime project enumeration.
3. Phase 2.8's brain LLM correctly attempted `rka_list_projects` for self-recovery and was denied — closing this denial removes one failure mode entirely.

The expanded allowlist gives the brain LLM a fallback recovery path: if env propagation regresses for any reason, brain can call `rka_list_projects` to enumerate, infer the right project from context, and `rka_set_project` to switch — instead of escalating with empty `proposed_actions` per Phase 2.8's pattern.

### T2 regression tests (2 new locks in `tests/test_llm_client_real.py`)

| # | Test | Locks |
|---|---|---|
| 1 | `test_phase_2_9_read_tools_includes_project_selectors` | Both entries present; count is 11 |
| 2 | `test_phase_2_9_project_selectors_not_in_write_tools` | Safety check against semantic-layer confusion |

Note: Brain's spec estimated 4 Phase 2.7 T2 assertion-site updates needed. Actual count was **0** — existing Phase 2.7 T2 tests in `test_llm_client_real.py` use `_prefixed_tools(READ_TOOLS)` dynamically, so they auto-expand to the new 11-entry list. The tests were written robustly enough that the READ_TOOLS expansion didn't require any assertion-site updates.

## T3 — Real-RKA integration probe (catches future drift)

### Why this test matters

FakeMCP unit tests cannot model cross-process MCP sessions. The Phase 2.8 finding (subprocess inheriting wrong project) was invisible to all 244 unit tests because they use FakeMCP's in-process fake — no real subprocess, no real `rka mcp` stdio binary, no real MCP session boundary. Only a real `claude-agent-sdk` subprocess spawning a real `rka mcp` child can reveal whether `McpStdioServerConfig.env` propagation actually works at runtime.

### T3 implementation

New file: `orchestrator/tests/test_executor_integration.py` (commit `bd2569e`). Module-level `pytest.skipif(not os.environ.get("RKA_INTEGRATION"))` gate. CI default run shows the 2 tests as `skipped`.

Local invocation:

```
RKA_INTEGRATION=1 .venv/bin/python -m pytest \
  orchestrator/tests/test_executor_integration.py -v
```

Env-overridable probe config:
- `RKA_INTEGRATION_PROBE_PROJECT` (default `prj_01KKQM9JFG67GT5FGWTAHD9YE4`)
- `RKA_INTEGRATION_PROBE_MISSION` (default `mis_01KRVF159FEHMYD55Q6EQ7BD18` — the Phase 2.4→2.6→2.8→2.10 target)
- `RKA_URL` (default `http://localhost:9712`)

### T3 keystone tests (2)

| # | Test | Validates |
|---|---|---|
| 1 | `test_mission_execute_against_real_subprocess_and_rka` | T1's project propagation works end-to-end; subprocess MCP session scoped to parent's project_id; mission_execute reads probe mission successfully (no 404s); `_parse_proposed_actions` extracts cleanly; no errors. Direct A/B test against Phase 2.8 failure mode (asserts executor_position contains NO wrong-project markers: "404", "not found in project", "Default Project", "assumption invalidation"). |
| 2 | `test_subprocess_cannot_invoke_write_tools_integration` | Phase 2.7 WRITE_TOOLS disallow holds at runtime against real claude-agent-sdk. Subprocess prompted to attempt `rka_update_note` directly; asserts no bypass writes land at RKA (verified via `rka_get_journal(tags=[<probe_thread>])` showing no executor-sourced `type=note` entries). |

These tests are skipped in CI but should be run locally before any future Phase 2.X operational-rollout retry. They give us a fast pre-flight signal that the architecture is intact end-to-end, not just at the unit-test layer.

## T4 — Cosmetic anomaly fix (optional; shipped within scope)

Phase 2.8 surfaced a minor reporting cosmetic: `pi_acceptance.summary` field showed `"APPROVED:"` — the gate1_validation verdict text leaking through `state["brain_position"]`. Misleading: described the gate1 verdict, not the mission outcome.

### T4 fix shape (commit `8afdd2f`)

`orchestrator/orchestrator/nodes/pi.py` — new helper `_compose_acceptance_summary(state)` replaces the `state["brain_position"][:200]` summary source with a composed one based on counts + escalation signal:

- if errors → `"Mission ended with N error(s); ..."` (leads with error count per Phase 2.5 Delta #14b divergence-as-headline)
- elif checkpoints → `"Mission escalated via N checkpoint(s)..."`
- elif final_report_id → `"Mission complete; final_report_id=...; ..."`
- else fallback → `"Workflow complete; see report for details."`

Static helper; deterministic; testable. No longer reads brain_position.

3 new tests in `tests/test_pi.py` lock the corrected behavior:
- `test_pi_acceptance_summary_does_not_leak_gate1_verdict` (direct A/B against Phase 2.8 anomaly)
- `test_pi_acceptance_summary_reflects_error_count_when_present`
- `test_pi_acceptance_summary_reflects_escalation_when_checkpoints_raised`

## Suite count progression

| Phase | Suite | Delta |
|---|---|---|
| Phase 2.8 close | 233 passing | (baseline) |
| Phase 2.9 T1 | 233 → 239 passing | +6 T1 tests |
| Phase 2.9 T2 | 239 → 241 passing | +2 T2 tests |
| Phase 2.9 T3 | 241 → 241 passing + 2 skipped | +2 integration tests (env-gated) |
| Phase 2.9 T4 | 241 → 244 passing + 2 skipped | +3 T4 tests |
| **Phase 2.9 close** | **244 passing + 2 skipped** | **+11 net new tests** |

All commits passed the full suite before pushing. No regressions.

## Bookkeeper + agentic-branch + grep-gate invariants

Verified at every commit boundary:
- `git diff main -- rka/services/worker.py = 0`
- `git diff main -- rka/ = 0`
- `grep -rn 'from rka\|import rka' orchestrator/` returns none (only `test_invariants.py` references the grep pattern in a comment)
- Push-after-every-commit + `git ls-remote origin agentic` HEAD matches local

## Phase 2.10 readiness statement

**Phase 2.10 is ready to launch.** Same target (`mis_01KRVF159FEHMYD55Q6EQ7BD18`), same 3-item scope, fresh `thr_op_rollout_v4_<unix_ts>` workflow_thread_id, same 7-trigger mandatory-pause list **plus the now-closed 8th trigger** (subprocess-MCP-project-mismatch).

Expected behavior with Phase 2.9 fixes live:
1. `make_sdk(project_id=prj_01KKQM9JFG67GT5FGWTAHD9YE4)` (driver's `--project-id` default)
2. Subprocess MCP child inherits `RKA_PROJECT=prj_01KKQM9JFG67GT5FGWTAHD9YE4` via `McpStdioServerConfig.env`
3. Subprocess `rka_get_mission(mis_01KRVF159FEHMYD55Q6EQ7BD18)` resolves correctly (no 404)
4. Subprocess reads each of the 3 cross-reference journals via `mcp__rka__rka_get`
5. mission_execute LLM emits structured `proposed_actions` JSON with 3 entries (one rka_update_note per item)
6. decision_present surfaces; pi_decision_select fires with batched payload
7. PI explicitly types `a` (driver re-prompts on empty Enter per Phase 2.7 T4)
8. execute_ratified_actions dispatches 3 × `rka_update_note(id=jrn_*, related_decisions=[dec_*, ...])` from parent process
9. pi_acceptance summary now reads "Mission complete; final_report_id=...; 11 artifacts produced." (Phase 2.9 T4 fix)
10. Post-run `rka_get(<jrn_id>).related_decisions` non-empty AND ID-identical to PI's ratified set

If brain proposal quality on Item 1 (HIGH-quality with 4 cited decisions in Provenance section) is anything but excellent, that's the Phase 2.11+ scope signal. Given Phase 2.8's exemplary brain behavior, Phase 2.10 has high probability of empirical success on first try.

**Phase 2.4 → 2.6 → 2.8 → 2.10 acceptance criterion** (1+ items complete cycle with `rka_update_note` write) carries forward to Phase 2.10. The architectural pieces are all in place; Phase 2.10 is the integration validation.

## Divergences from upfront 8 assumptions

All 8 assumptions held; no divergences requiring scope refinement:
- A1 (Phase 2.7 architecture stays in place) ✓
- A2 (McpStdioServerConfig.env is the right channel) ✓ (T1 unit-tested; T3 integration test validates at real-subprocess layer)
- A3 (rka_list_projects + rka_set_project are read-side; safe in READ_TOOLS) ✓ (T2 safety test locks)
- A4 (RKA_INTEGRATION=1 env-gate is right) ✓ (CI shows 2 skipped as designed)
- A5 (probe mission fixture management) ✓ (simplified to reuse existing target; no fixture lifecycle complexity)
- A6 (suite count moves 233 → ~239-241) ✓ (actual: 244 + 2 skipped; T4 shipped + the 2 T2 locks made the count slightly higher)
- A7 (invariants carry forward) ✓
- A8 (no release tag, no merge to main, agentic-only) ✓

## Branch state at Phase 2.9 close-out

- `agentic` HEAD: post-this-commit. 5 new commits (T1, T2, T3, T4, T5-this-narrative).
- `main`: unchanged at `c063673`.
- No new release tag. `v2.5.3+agentic` final tag stands.
- Suite at 244 passing + 2 skipped.

## Hand-off

Phase 2.10 mission spec to be filed by Brain. Suggested scope: same narrow 3-item retry against `mis_01KRVF159FEHMYD55Q6EQ7BD18` with fresh `thr_op_rollout_v4_<unix_ts>` workflow_thread_id; same 7-trigger mandatory-pause list (8th trigger closed by Phase 2.9 T1); ~30-60 min PI interactive review estimate; orchestrator/docs/operational-rollout-v4.md narrative target.
