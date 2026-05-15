# Eval-v2 corpus schema — context-need scenarios

Mission: `mis_01KRPF3DERZS2W5VFDYE9E9GKM` (composed-context coverage eval).
Motivating decision: `dec_01KRPF09AP1FE1CRR6YQBY2R5F`.

This schema defines the JSONL corpus used by the Eval-v2 runner. Each
line of `eval-harness/v2/corpus/scenarios.jsonl` is one scenario — a
"context-need" stated as a session-start trigger plus the PI-ratified
ground-truth set of entities that **should** appear in the returned
context bundle.

The runner (T3) invokes a composed call sequence per scenario; the
metrics module (T4) compares the returned entities against
`expected_entities` to compute recall, ordering, breadth, efficiency.

## Field reference

| Field | Type | Required | Description |
|---|---|---|---|
| `scenario_id` | string (slug) | yes | Stable identifier, kebab-case. Used as the filename for raw-result serialization. |
| `actor` | enum: `brain` \| `executor` | yes | Which role's session-start pattern this scenario simulates. Drives the tool-sequence variant. |
| `trigger` | string | yes | Free-text description of the session-start context. Human-readable; not parsed by the runner. |
| `tools_invoked` | array of strings | yes | Ordered list of MCP tool names the runner will invoke for this scenario. Each name must be in the canonical Minimal Session Start sequence (or a documented variant). |
| `expected_entities` | array of `ExpectedEntity` | yes | PI-ratified ground-truth set. Minimum 5 total; minimum 3 with `importance="critical"`. |
| `context_length_budget_estimate` | integer | no | Informational; the eval does not enforce. Roughly the token budget the scenario is expected to fit in. |
| `notes` | string | no | Free-text notes — Brain's rationale, edge cases the scenario exercises, etc. Not used by metrics. |

### `ExpectedEntity` shape

| Field | Type | Required | Description |
|---|---|---|---|
| `entity_id` | string | yes | The full RKA entity ID, including prefix (e.g., `dec_01ABC...`, `jrn_01DEF...`, `mis_01GHI...`, `clm_01JKL...`, `ecl_01MNO...`, `lit_01PQR...`, `chk_01STU...`). |
| `entity_type` | enum | yes | Must be one of: `journal`, `decision`, `mission`, `claim`, `cluster`, `literature`, `checkpoint`. |
| `importance` | enum | yes | Must be one of: `critical`, `useful`, `nice-to-have`. The `recall` metric is computed over `critical`-tagged entities only; `expanded_recall` covers the full set. |

## Acceptance constraints (locked by validators in T1 tests)

- `scenario_id` must match `^[a-z0-9][a-z0-9-]{2,63}$` (kebab-case slug, 3-64 chars).
- Each scenario MUST have at least 5 entries in `expected_entities`.
- At least 3 of those entries MUST have `importance="critical"`.
- `entity_id` strings should start with the `entity_type`-implied prefix (e.g., `decision` entities start with `dec_`). The schema doesn't enforce this with a per-pair regex constraint at the JSON-Schema level, but a runtime validator in the runner spot-checks it.
- `tools_invoked` array must be non-empty.

## Diversity floor (locked by ratification at the T2 mid-mission gate)

The corpus must cover all six session-start pattern types, with at least
two scenarios per type:

1. Brain session-start (resume project after a break)
2. Brain mission-creation (drafting a new mission from a decision)
3. Brain contradiction-investigation (claims contradicting across clusters)
4. Brain paper-scaffold-assembly (evidence-cluster assembly for writing)
5. Executor mission-pickup (fresh Executor reads mission + context)
6. Executor backbrief-gate (Executor preparing Backbrief journal entry)

## Reproducibility

Per Eval-v1's pattern, the runner writes a SHA256 of
`eval-harness/v2/corpus/scenarios.jsonl` plus the RKA HEAD commit into
`eval-harness/v2/results/metrics.json` for reproducibility.
