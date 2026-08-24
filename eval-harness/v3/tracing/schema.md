# Eval-v3 Track — decision back-tracing scenarios

Goal: measure whether a **complex decision and its rationale**, once logged,
can be effectively retrieved together with its related evidence, literature,
directives, and superseded alternatives — so the research record survives
significant pivoting. This targets the failure modes Eval v1/v2 already
flagged (structural-traversal queries fail; `rka_get_ego_graph` critical
coverage 0.333; `rka_multi_hop_retrieval` 422s).

Each line of `scenarios.jsonl` is one scenario:

| Field | Type | Required | Description |
|---|---|---|---|
| `scenario_id` | slug | yes | Stable kebab-case identifier; used for raw-result filenames. |
| `nl_query` | string | no | Natural-language question a researcher would ask ("why did we choose X over Y"). When present, the runner first hits `/api/search` and scores the anchor decision's rank. |
| `anchor_decision` | `dec_…` id | yes | The canonical decision the trace starts from. |
| `expected_trace` | array of `ExpectedEntity` | yes | PI-ratified ground truth: what a complete back-trace from the anchor must surface. Minimum 3 entries, at least 1 `critical`. |
| `pivot` | object | no | `{"superseded_decision_id": "dec_…", "superseding_decision_id": "dec_…"}`. Present when the scenario tests a pivot: retrieval must surface the superseding decision; surfacing only the superseded one is the stale-surfacing failure. |
| `notes` | string | no | Rationale / edge cases. Not scored. |

`ExpectedEntity`:

| Field | Type | Description |
|---|---|---|
| `entity_id` | prefixed id | `jrn_` / `lit_` / `clm_` / `ecl_` / `dec_` / `mis_` / `chk_` |
| `entity_type` | enum | `journal` \| `literature` \| `claim` \| `cluster` \| `decision` \| `mission` \| `checkpoint` |
| `relation` | enum | Why it belongs in the trace: `evidence` \| `literature` \| `directive` \| `parent_decision` \| `superseded_alternative` \| `mission` \| `checkpoint` |
| `importance` | enum | `critical` \| `useful` — `trace_recall` is computed over critical only; `expanded_recall` over all. |

## Scored surfaces (per scenario)

1. **NL anchoring** (`/api/search`, only when `nl_query` present): reciprocal
   rank of `anchor_decision` in the result list.
2. **Ego trace** (`/api/graph/ego/{anchor}` at depth 2).
3. **Multi-hop trace** (`/api/graph/multi-hop`, seeds `[anchor]`, depth 2).
4. **Union trace**: entities surfaced by any traversal surface — the headline
   recall, since a Brain session can compose calls.

## Metrics

- `anchor_mrr` — mean reciprocal rank of the anchor decision for NL queries.
- `trace_recall` / `expanded_recall` — critical / all expected entities found
  in the union trace; also reported per traversal surface and per `relation`
  (so "directives get lost" vs "literature gets lost" is visible directly).
- `precision` — |expected ∩ returned| / |returned| for the union trace
  (bundle-noise measure, comparable to Eval v2's efficiency).
- `pivot_correctness` — fraction of pivot scenarios where the superseding
  decision is surfaced; `stale_surfacing` counts scenarios where only the
  superseded decision appeared.
- Non-2xx responses are recorded as divergences per surface, never crashes —
  a repeat of the v2.5.x multi-hop 422 shows up as data.

## Corpus authoring

Ground truth comes from the real knowledge graph (project-A or
edge-cloud-agent): pick decisions with recorded rationale — especially ones
that superseded an earlier plan — and enumerate what a colleague would need
to reconstruct the decision. The included `scenarios.example.jsonl` shows the
shape with synthetic ids; replace it with a ratified corpus before quoting
numbers.
