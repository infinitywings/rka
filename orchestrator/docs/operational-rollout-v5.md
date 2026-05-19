# Operational Rollout v5 — Phase 2.12 empirical retry

**Mission**: `mis_01KRYVYZ42H0ETXMYRE7318KM4`
**Decision**: `dec_01KRYVSQEWT4FPGVSK2WACSYBK` (Option A — pure empirical retry; zero
orchestrator code changes)
**Workflow thread**: `thr_op_rollout_v5_1779152656`
**Target mission**: `mis_01KRVF159FEHMYD55Q6EQ7BD18` (the deferred Phase 2
cross-reference acceptance criterion)
**Date**: 2026-05-19

---

## 1. Frame

Phase 2.11 closed two architectural debts surfaced by Phase 2.10:

- **T1** — `decision_present` early-bypass: when `state["proposed_actions"]`
  is non-empty, surface the executor's proposals to PI by identity rather than
  re-routing through a strategic-meta-decision LLM call. EC8 set-identity
  contract: `ratified_actions == proposed_actions` on `accept`.
- **T2** — `EXECUTOR_SYSTEM` 10th delta: the canonical marker phrase
  "work-target is the `mission_id` field" tells the brain LLM that T0–T7 in
  the Backbrief is **wrapper scaffolding** and the target work is whatever
  `rka_get_mission(state.mission_id)` returns.

Phase 2.12 is the empirical validation run. **No orchestrator code edits**:
Brain spec ratified Option A; only an `orchestrator/docs/` narrative file
(this one) and the run-artifact JSON are written by this phase.

The standing Phase 2 acceptance criterion remains:

> 1+ of 3 cross-reference items completes the full cycle with `rka_update_note`
> write verified via `rka_get(<jrn_id>).related_decisions` non-empty AND
> matching PI-ratified IDs.

---

## 2. Run outcome

```
terminal_state:      complete
current_phase:       pi_acceptance
interrupts:          3
artifacts:           10
checkpoints:         0
errors:              3
final_report_id:     mis_01KRVF159FEHMYD55Q6EQ7BD18
workflow_thread_id:  thr_op_rollout_v5_1779152656
```

All 10 artifacts landed in RKA. The run ended cleanly (no exceptions, no
hangs, no manual intervention beyond the 3 PI interrupts: greenlight,
backbrief accept, decision ratification).

Per-target verification (T3, executed post-run via direct `rka_get`):

| Target journal | `related_decisions` (observed) | Item floor |
|---|---|---|
| `jrn_01KQQ4K4GWFKHQBCQNC9F92JX4` | `null` | not met |
| `jrn_01KMX18FDBEE9T8JNHHAP649TE` | `null` | not met |
| `jrn_01KP4QR4XFP0ZHKR14B9ET6CN2` | `null` | not met |

**Expected 3/3, observed 0/3 — 3/3·100% off the floor.** Phase 2 acceptance
criterion is **not** met this run. Cause: 10th trigger (§4 below).

---

## 3. What worked (empirical validation of Phase 2.11)

### 3.1 T1 — `decision_present` early-bypass FIRED

The `decision_present` node received `state["proposed_actions"]` with 3
entries from `mission_execute`. The new early-bypass path activated:
`jrn_01KRYXYE3N8QZMJCBV0VCT4NYQ` is tagged `decision-draft` +
`proposed-actions-set` and renders as:

> "# Brain proposes 3 action(s) for PI ratification"
> "PI must verify the set below; on `accept`, these actions are copied to
> `ratified_actions` for parent-process dispatch via `execute_ratified_actions`.
> EC8 set-identity: ratified == proposed."

The PI interrupt at `pi_decision_select` surfaced the 3 entries verbatim
with their `tool`, `args`, and `rationale` fields — not via a re-LLM-call
strategic detour. Expected behavior; first time validated at runtime.

### 3.2 T2 — `EXECUTOR_SYSTEM` wrapper-vs-target framing WORKED

The brain executor produced **3 target-scoped proposals** (one per cross-
reference item) — not a single wrapper-scoped `rka_submit_report` stub
(the Phase 2.10 failure mode). The `mission_execute` journal
(`jrn_01KRYXP8MVD3MR15BPQSPH0J1W`) opens with:

> "I'll execute this mission per the approved Backbrief. Per the
> wrapper-vs-target rule, my work-target is the 3 cross-reference items."

The 10th delta's canonical marker took hold. The brain correctly grounded
in the target mission and produced an A-1 anomaly entry that itself
attributes the prior-run divergence to the very condition T2 was added to
prevent:

> "A-1 (target-state drift, observed): … Expected proposed_actions in
> that prior report: 3× `rka_update_note` on target journals. Observed:
> 1× `rka_submit_report` (wrapper-scoped close-out). Divergence: 100%
> off — zero target-scoped writes were proposed in the prior run."

Item 1's 4 decision IDs match the target journal's Provenance section
**exactly** (HIGH-quality candidate):

- `dec_01KQNPC7A683HK0KRX1PAGNNED` (Option B wrapper)
- `dec_01KMX18FDAMN7T5YVZ7V8HV6RJ` (agent-roles RQ)
- `dec_01KMX18FDAMN7T5YVZ7V8HV6RK` (system-architecture RQ)
- `dec_01KP4P4QSSNZCTEHVT6QR7ZRYD` (knowledge-freshness RQ)

Items 2 and 3 are MEDIUM-quality (FTS5 surfaced adjacent candidates with
clear inference paths, not direct-citation parents) — the brain
documented this as A-2 and A-3 anomalies with appropriate hedging.

### 3.3 Phase 2.7 T3e defense-in-depth FIRED CLEANLY

The brain proposed `rka_bulk_update` for all 3 items. `rka_bulk_update`
is **not** in the orchestrator's `WRITE_TOOLS` registry (`llm_client.py`:
`rka_add_note`, `rka_add_decision`, `rka_submit_checkpoint`,
`rka_submit_report`, `rka_create_mission`, `rka_update_note` — 6
entries). The parent-side `execute_ratified_actions` rejected all 3:

```
error_type:  ratified_action_tool_not_allowed
detail:      tool 'rka_bulk_update' is not in WRITE_TOOLS registry —
             the executor LLM proposed an action the orchestrator
             refuses to execute. Phase 2.7 Option C invariant.
```

3 `ErrorRecord` entries captured, run continued cleanly, no exceptions
leaked. The Phase 2.7 Option C invariant (parent-side mediation of all
write-tool dispatch) held at runtime — first empirical demonstration of
the rejection path firing.

### 3.4 Phase 2.9 T4 summary composition VALIDATED

`final_synthesis` (`jrn_01KRYY8448KAAD7PZ9Z09NVQBR`) composed the
end-of-run summary correctly with `errors_count=3`. Pipeline emitted
clean terminal output despite the rejection path firing 3× in
`execute_ratified_actions`. No silent failures, no partial-state
artifacts.

---

## 4. What didn't work — the 10th trigger

**WRITE_TOOLS registry gap.** Brain chose `rka_bulk_update` as the
write-side method for all 3 items. The brain's reasoning is documented
in `jrn_01KRYXP8MVD3MR15BPQSPH0J1W` and is, on its own merits, **sound
research methodology**:

> "Surfaced as the canonical write-side method rka_bulk_update with
> entity_type=note (the same method jrn_01KQQ4K4GWFKHQBCQNC9F92JX4
> itself documents using for the 2026-05-03 cross-reference hygiene pass
> on Items 2 and 3)."

The target journal `jrn_01KQQ4K4GWFKHQBCQNC9F92JX4` (the 2026-05-03
maintenance pass log) literally documents using `rka_bulk_update` for
cross-reference hygiene on the same target journals. The brain followed
precedent. The mission spec mentions `rka_update_note` as a tool name
but the brain treated this as the **logical operation** (update a note's
fields), which `rka_bulk_update` supports.

The blocker is mechanical, not methodological: the orchestrator's
WRITE_TOOLS registry only allowlists 6 specific tools, and
`rka_bulk_update` is not among them. The brain's tool choice was
**plausible and well-grounded**; the orchestrator's reaction was
**correct per Phase 2.7 Option C** (any tool outside the allowlist is
rejected, not silently routed through).

This is the **narrowest possible Phase 2 blocker** yet observed:

- Phase 2.4–2.6: workflow-position bugs, retry storms, decision-routing
  corruptions — broad architectural surface.
- Phase 2.7: parent-side mediation gap — broad architectural surface.
- Phase 2.8–2.9: subprocess env/auth/project-id propagation — moderate
  surface.
- Phase 2.10–2.11: framing discipline (wrapper-vs-target) and packet
  decoupling — narrow architectural surface.
- **Phase 2.12: registry membership of one specific tool name** — the
  smallest possible diff between "this run lands the writes" and "this
  run captures 3 ErrorRecords."

---

## 5. Phase 2 chapter status

**Status: NEEDS DEEPER INVESTIGATION.**

Phase 2 acceptance criterion (1+/3 of cross-reference items completes
the full cycle) is **not** met this run. The blocker is now mechanical
and narrow enough that Phase 2.13 can plausibly be a single-PR change
(~30–60 min): expand `WRITE_TOOLS` to include `rka_bulk_update` and add
a thin `RestMCPClient.rka_bulk_update(updates)` adapter on the parent
side.

The empirical validations are load-bearing:

1. The Phase 2.11 T1 + T2 fixes hold at runtime in the absence of the
   10th trigger. (Brain produced rigorous target-scoped proposals; PI
   saw them by identity in the decision packet.)
2. The Phase 2.7 Option C defense-in-depth fires cleanly on a malformed
   proposal. (No silent failures, no leaked exceptions.)
3. The full LangGraph → subprocess → REST API stack ran 10 artifacts to
   completion with 3 PI interrupts and 0 checkpoints.

The Phase 2 architectural surface is now empirically tight. The
remaining blocker is a **registry membership** question, not a
**workflow-correctness** question.

---

## 6. Phase 2.13 scope recommendation

Two complementary paths, ordered by preference:

### 6a. Expand WRITE_TOOLS to include `rka_bulk_update` (RECOMMENDED)

Add `"rka_bulk_update"` to the WRITE_TOOLS tuple in
`orchestrator/orchestrator/llm_client.py` and add a thin adapter on
`orchestrator/orchestrator/mcp_client.py::RestMCPClient`. The brain's
methodology was correct; the mechanical gap is the only blocker. This
also subsumes future cross-reference hygiene work that legitimately
needs the bulk-update endpoint.

Tests to add:

- `test_WRITE_TOOLS_includes_rka_bulk_update` — registry membership.
- `test_RestMCPClient_rka_bulk_update_dispatches_to_correct_endpoint` —
  adapter shape.
- `test_execute_ratified_actions_dispatches_rka_bulk_update` —
  end-to-end parent-side dispatch.

### 6b. Add `EXECUTOR_SYSTEM` 11th delta steering brain to allowlisted tools

Complementary to 6a. The brain currently has no allowlist signal in its
system prompt; it discovers the orchestrator's WRITE_TOOLS only by
empirical rejection. An 11th delta would surface the registry as a
ground-truth constraint at proposal time, reducing wasted-proposal
errors when the brain's natural tool choice falls outside the
allowlist.

Phase 2.13 mission spec should pick 6a as primary scope (the
methodological correctness path); 6b is optional polish.

---

## 7. PI Backbrief discipline finding (for Phase 2.13+)

The Phase 2.12 Backbrief explicitly framed T0–T7 wrapper scaffolding
with a "⚠️ WRAPPER SCAFFOLDING vs TARGET WORK" section, complementing
the Phase 2.11 T2 LLM-side delta. The brain LLM correctly applied the
framing (§3.2). This is a load-bearing discipline that should persist:

- LLM side (Phase 2.11 T2): canonical marker `"work-target is the
  mission_id field"` in `EXECUTOR_SYSTEM`.
- Brain side (Phase 2.12+ Backbriefs): explicit wrapper-vs-target
  section call-outs whenever the Backbrief itself enumerates wrapper
  steps that could be confused for target work.

Together these two-sided disciplines closed the Phase 2.10 failure mode
in this run.

---

## 8. Artifact ledger (10 artifacts)

| Phase | RKA ID | Type |
|---|---|---|
| `strategy_node` | `jrn_01KRYWVY6TZZSCH8M2SMTNQ0GH` | journal |
| `confirmation_brief` | `jrn_01KRYWXN8RHPAK6ECHP1628MCV` | journal |
| `backbrief_draft` | `jrn_01KRYXEH7VW9XR4CB0MEBT54J4` | journal |
| `gate1_validation` | `jrn_01KRYXF03YQ2ZJ10PVXWQ1P2FR` | journal |
| `mission_execute` | `jrn_01KRYXP8MVD3MR15BPQSPH0J1W` | journal |
| `submit_report` | `mis_01KRVF159FEHMYD55Q6EQ7BD18` | report |
| `cluster_review` | `jrn_01KRYXYE2X9Y7WQH8EVW3EPC0H` | journal |
| `decision_present` | `jrn_01KRYXYE3N8QZMJCBV0VCT4NYQ` | journal |
| `pi_decision_select` | `dec_01KRYY4DDTX4YEFR62F0E47EH9` | decision |
| `final_synthesis` | `jrn_01KRYY8448KAAD7PZ9Z09NVQBR` | journal |

Run-artifact JSON (errors + artifact metadata):
`orchestrator/results/op_rollout_v5/thr_op_rollout_v5_1779152656.json`

---

## 9. Invariants

- `git diff main -- rka/`: empty (this phase writes only
  `orchestrator/docs/operational-rollout-v5.md` and
  `orchestrator/results/op_rollout_v5/thr_op_rollout_v5_1779152656.json`).
- `git diff main -- rka/services/worker.py`: empty.
- `grep -rn 'from rka\|import rka' orchestrator/`: returns none.
- `orchestrator/tests/test_invariants.py`: unchanged from Phase 2.11.

Authentication: Claude Max keychain routing held (ANTHROPIC_API_KEY
scrub via `make_sdk()`'s `_scrubbed_env`); no API-key leak in any
artifact.
