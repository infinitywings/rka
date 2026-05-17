# Pilot v2.5.3+agentic (final) — T3 evidence

Mission: `mis_01KRSTZVCTFGF91QZXTYK7ZGDD` (Phase 2.1 shakedown)
Date: 2026-05-17
Branch: `agentic` at HEAD `3d4d0fd` (T1+T2 fixes applied)

## Acceptance-criteria readout

| Criterion | Status | Evidence |
|---|---|---|
| (a) Pilot completes without parse-cascade or unhandled exception | ✓ PASSED | `terminal_state: complete`, exit 0 |
| (b) ≥1 Brain↔Executor↔PI cycle advances cleanly | ✓ PASSED | All 10 happy-path nodes fired in order; 3 PI interrupts honored (greenlight → decision_select → acceptance) |
| (c) Any `rka_submit_checkpoint` calls return 200 (not 422) | ✓ PASSED | 0 checkpoints raised in pilot (happy path); **live smoke** with new payload returned HTTP 201 |
| (d) Keychain auth still resolves correctly (Phase 2 T2 regression check) | ✓ PASSED | `ANTHROPIC_API_KEY` WARNING fired + auth path = keychain (per log header) |

## Pilot run summary

Thread ID: `thr_pilot_v2_5_3_agentic_final_1778985733`

```
terminal_state:  complete
current_phase:   pi_acceptance
interrupts:      3
artifacts:       10
checkpoints:     0
errors:          0
final_report_id: mis_01KRKG9K1SSDZNDH90K2Z7ZM92
```

## Artifacts created (all retrievable via `tags=[thr_pilot_v2_5_3_agentic_final_1778985733]`)

| Node | Entity | RKA ID |
|---|---|---|
| strategy_node | journal | jrn_01KRSX1R765J0KMGAPBD05Q4X4 |
| confirmation_brief | journal | jrn_01KRSX3EQ63ZXTRASEQDXWDZ20 |
| backbrief_draft | journal | jrn_01KRSX7S2RT0H3DW247G5DY1TR |
| gate1_validation | journal | jrn_01KRSX8CAJNP1TZR2115NVCYR2 |
| mission_execute | journal | jrn_01KRSXD5JQ2ZT7B13QYA1EXMB7 |
| submit_report | mission report | mis_01KRKG9K1SSDZNDH90K2Z7ZM92 |
| cluster_review | journal | jrn_01KRSXG9267C3XENKNE7843BZR |
| decision_present | journal | jrn_01KRSXJ5R2QQ8EVY73MS455D2M |
| pi_decision_select | decision | dec_01KRSXJ5S1DRFNJN1NB1J2F2RG |
| final_synthesis | journal | jrn_01KRSXN0WBB9TTNWQSMDHN5TH9 |

## Headline finding

**The v2.5.3+agentic-rc1 → final transition is mechanically validated.**

T1 (prompt-led structured prefixes) closed the gate1 cascade — gate1_validation now produces an APPROVED verdict on real Claude output, routing to mission_execute instead of escalation_router.

T2 (rka_submit_checkpoint payload alignment) was not exercised by the pilot's happy path (no escalation fired), but a separate live smoke against `/api/checkpoints` with the new payload returned HTTP 201 (vs the previous 422), confirming the schema fix end-to-end.

Auth thesis (Phase 2's T1+T2 deliverable) preserved without regression: WARNING fired; auth path = keychain; no API billing event.

## Files

- `thr_pilot_v2_5_3_agentic_final_1778985733.json` — structured pilot summary
- `run_log_1778985733.txt` — full stdout/stderr of the pilot run
- `README.md` — this file

## Disposition

T3 acceptance criteria met. Branch is ready for T4 tag transition (`v2.5.3+agentic-rc1` deleted from origin; final `v2.5.3+agentic` tag created at the new HEAD).
