# Review State

Tracks the Revision Loop for the current PI review cycle (see Revision Loop
section in SKILL.md). Three-iteration cap; the third failed iteration auto-
escalates to a PI Style or Logical checkpoint with three resolution options.

## Current cycle

iteration: 0
max: 3
verdict: (none yet)

## Comment classifications for this cycle

(For each PI review comment, classify into R1, R2, R3, or R4 per the
Revision Loop section. R4 escalates via rka_create_mission.)

| Comment ID | Class | Section | Status |
|---|---|---|---|
| (PI fills in)            | R?  | §?    | pending |

## Procedure map

| Class | Comment type | Procedure |
|---|---|---|
| R1 | Factual (sentence-level) | inline auto-fix; re-render; bump iteration |
| R2 | Style or AI-tic | re-run ai_tic_lint at stricter threshold; auto-revise |
| R3 | Inconsistency (cross-section) | structural rewrite of all affected sections |
| R4 | Logical gap or unsupported claim | ESCALATE via rka_create_mission |

## History

(Each completed iteration leaves a record.)

### Iteration N (date)
- changes: ...
- verdict: CONTINUE | ESCALATE | COMPLETE
- next_action: ...
