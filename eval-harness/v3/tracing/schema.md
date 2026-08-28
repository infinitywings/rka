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
| `project_id` | `prj_…` id | for cold-session scoring | Frozen project binding. Every answer artifact must repeat this exact value. |
| `nl_query` | string | no | Backward-compatible single natural-language question for a flat trace scenario. |
| `anchor_decision` | `dec_…` id | yes | The canonical decision the trace starts from. |
| `expected_trace` | array of `ExpectedEntity` | conditional | PI-ratified ground truth for a legacy flat trace. Required unless `story` is present. |
| `pivot` | object | no | `{"superseded_decision_id": "dec_…", "superseding_decision_id": "dec_…"}`. Present when the scenario tests a pivot: retrieval must surface the superseding decision; surfacing only the superseded one is the stale-surfacing failure. |
| `query_variants` | array | conditional | Independent natural-language probes for a story scenario. Each has `variant_id`, `query`, and optional `style`. Required with `story`. Gold-author expansion terms are not accepted by the headline runner. |
| `required_roles` | array | no | Cold-session roles. Defaults to exactly `pi`, `brain`, and `executor`; each role must answer every query in a distinct session. |
| `story` | object | no | Gold causal-story contract described below. Its anchor is retained only for scoring and an explicitly labeled graph-ceiling diagnostic; query retrieval never receives it. |
| `retrieval` | object | no | Optional mechanical-runner caps (`search_limit`, `max_depth`, `multi_hop_max_nodes`, `report_max_nodes`, `seed_limit`). |
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

For a `story` scenario, every query variant instead runs the non-oracle
pipeline independently:

1. `/api/search` with the natural-language query.
2. Query-seeded `/api/graph/multi-hop` with **no explicit entity seed**.
3. `/api/graph/report-context` with the raw query only.
4. `/api/entities/resolve` over the candidate union, including induced edges,
   full stored facts, and currentness.

Only the formal result records (`entity_id`/`id` on search results and `id`
on graph nodes) count as candidates. IDs merely mentioned in snippets, labels,
edge endpoints, or inclusion metadata do not. Resolver-added source closure is
reported separately and may not satisfy roles, edges, facts, or currentness.

The runner also performs one separately reported oracle diagnostic using the
gold anchor. Oracle results never contribute to headline story metrics.

## Gold story contract

The smallest useful story is not a flat list. It identifies the functional
roles, causal edges, facts, and temporal status required to reconstruct why a
research direction exists and what followed:

```json
{
  "roles": {
    "literature_basis": {"any_of": ["lit_..."], "required": true},
    "rationale_journal": {"any_of": ["jrn_..."], "required": true},
    "current_decision": {"any_of": ["dec_new"], "required": true},
    "superseded_decision": {"any_of": ["dec_old"], "required": true},
    "execution_mission": {"any_of": ["mis_..."], "required": true},
    "result_journal": {"any_of": ["jrn_result"], "required": true}
  },
  "required_edges": [
    {"source": "lit_...", "target": "dec_new", "link_type": "informed_by"},
    {"source": "dec_new", "target": "mis_...", "link_type": "motivated"},
    {"source": "mis_...", "target": "jrn_result", "link_type": "produced"}
  ],
  "causal_edges": [
    ["dec_old", "jrn_rationale"],
    ["jrn_rationale", "dec_new"],
    ["dec_new", "mis_..."],
    ["mis_...", "jrn_result"]
  ],
  "required_facts": [
    {
      "fact_id": "current-choice",
      "any_of_entities": ["dec_new"],
      "contains": ["chosen value", "key rationale"]
    }
  ],
  "currentness": {
    "must_be_current": ["dec_new"],
    "must_be_not_current": ["dec_old"]
  },
  "current_entities": ["dec_new"],
  "historical_entities": ["dec_old"],
  "min_precision": 0.25,
  "forbidden_current_entities": ["jrn_draft_only"],
  "optional_entities": [],
  "distractors": [],
  "forbidden_entities": [],
  "foreign_must_exclude": [],
  "current_conclusion": {
    "verdict": "supported",
    "checks": [
      {"must_include": ["chosen value"]},
      {"numeric": {"value": 60, "tolerance": 1}}
    ]
  }
}
```

- A headline role is satisfied only when at least one `any_of` entity is
  returned by the project-bound resolver as `found: true` / `resolved`. Raw
  string-ID candidate coverage is reported separately as
  `raw_candidate_recall` and cannot make a scenario pass.
- `required_edges` are evaluated from returned graph payloads plus the induced
  edges of the resolved candidate set.
- `causal_edges` encode narrative cause-before-effect order for cold-agent
  answers; they are separate because stored provenance-edge direction is not
  always causal direction (`decision --justified_by--> journal`).
- `required_facts` are checked against full resolved records, never snippets.
- `must_be_current` entities must be retrieved and resolved as current.
  `must_be_not_current` is a rejection contract: absence passes; if such an
  entity is retrieved, the resolver must attest that it is not current.
- `min_precision` (default `0.2`) prevents a project dump from passing merely
  because all required roles are somewhere in the returned bundle.
- `distractors` reduce precision but are not automatically a hard failure;
  the downstream cold-agent scorer determines whether the agent rejected them.
- Missing, partial, or wrong-project resolver packets; foreign-project
  entities; explicitly forbidden entities; stale-only answers; and incorrect
  currentness are hard failures.

## Cold-session answer artifacts

The mechanical runner measures what Core retrieves. A real PI, Brain, or
Executor session is tested separately: give the fresh session only a project
id and one query variant, let it use normal RKA reads, and save one JSONL record
with its answer and citations. The evaluated session must not copy the hidden
gold manifest or attest its own retrieval trace:

```json
{
  "scenario_id": "signature-pivot-story",
  "query_variant": "colloquial",
  "role": "brain",
  "run_id": "run-signature-001",
  "session_id": "session-brain-colloquial-001",
  "project_id": "prj_...",
  "query": "What happened with the signature direction?",
  "answer": "The current choice is ... because ...",
  "verdict": "supported",
  "cited_entity_ids": ["jrn_...", "dec_new", "mis_...", "jrn_result"],
  "current_entity_ids": ["dec_new"],
  "causal_chain": ["dec_old", "jrn_...", "dec_new", "mis_...", "jrn_result"],
  "preview_evidence_ids": ["run_...", "obs_..."],
  "rejected_entity_ids": ["jrn_distractor"]
}
```

`cited_entity_ids`, `current_entity_ids`, `causal_chain`, and
`rejected_entity_ids` are flat arrays of unified graph/resolver entity IDs.
Experiment-preview records (`exp_`, `epv_`, `run_`, `rue_`, `obs_`, `elc_`,
and `evr_`) belong only in the optional `preview_evidence_ids` array. They must
be attested in the independently collected raw trace by an authoritative
same-project record returned from the matching typed experiment read:
`experiments` owns experiment, plan-version, and nested run records;
`experiment_runs` owns run, event, and nested observation records; and
`experiment_observations` owns observation, locator, and claim-relation
records. An ID mentioned in arbitrary successful output, relationship text,
or experiment config is not attestation. Preview evidence remains diagnostic
and does not satisfy graph citation, causal-order, or currentness scoring.

An independent collector saves a second JSONL file containing normalized raw
RKA tool calls. Bare `retrieved_entity_ids` or `resolved_entity_ids` are
rejected: the scorer extracts candidate IDs from call responses and recomputes
resolved IDs from the project-attested resolver packet.

The collector should preserve each raw response exactly. At ingestion, the
scorer can read a native JSON value, its exact JSON-string serialization, or a
single MCP `{\"content\":[{\"type\":\"text\",\"text\":...}]}` envelope whose text is
one exact JSON value. It does not guess through Markdown fences or merge
multiple content blocks, and normalization never rewrites the archived trace.
Preview attestation examines only typed record locations and requires both the
exact record `id` and the scenario's exact `project_id`; broad string-ID
extraction is retained for trace diagnostics but cannot attest preview evidence.

Trust boundary: the benchmark operator runs this collector outside the
evaluated PI/Brain/Executor sessions and archives the raw file plus its SHA-256.
The scorer detects stale, mismatched, or self-declared artifacts; like any
file-based benchmark, it cannot cryptographically prove who authored a
deliberately forged transcript.

```json
{
  "scenario_id": "signature-pivot-story",
  "query_variant": "colloquial",
  "role": "brain",
  "run_id": "run-signature-001",
  "session_id": "session-brain-colloquial-001",
  "response_sha256": "sha256-of-the-canonical-response-record",
  "project_id": "prj_...",
  "query": "What happened with the signature direction?",
  "collector_id": "local-tool-recorder-v1",
  "calls": [
    {
      "ordinal": 1,
      "operation": "search",
      "project_id": "prj_...",
      "request": {"project_id": "prj_...", "query": "What happened with the signature direction?"},
      "outcome": "ok",
      "response": [{"entity_id": "dec_new"}, {"entity_id": "jrn_..."}]
    },
    {
      "ordinal": 2,
      "operation": "resolve_entities",
      "project_id": "prj_...",
      "request": {"project_id": "prj_...", "ids": ["dec_new", "jrn_..."]},
      "outcome": "ok",
      "response": {
        "project_id": "prj_...",
        "entities": {
          "dec_new": {"found": true, "outcome": "resolved", "project_id": "prj_..."},
          "jrn_...": {"found": true, "outcome": "resolved", "project_id": "prj_..."}
        }
      }
    }
  ]
}
```

After reading the answer without access to the gold manifest, an independent
reviewer may save a third JSONL artifact:

```json
{
  "scenario_id": "signature-pivot-story",
  "query_variant": "colloquial",
  "role": "brain",
  "run_id": "run-signature-001",
  "session_id": "session-brain-colloquial-001",
  "project_id": "prj_...",
  "query": "What happened with the signature direction?",
  "reviewer_id": "reviewer-1",
  "response_sha256": "sha256-of-the-canonical-response-record",
  "human_scores": {
    "current_conclusion": 4,
    "mandatory_coverage": 4,
    "causal_reconstruction": 3,
    "provenance_currentness": 4,
    "distractor_rejection": 4
  }
}
```

Score a complete frozen response set without adding an LLM or orchestrator to
the harness:

```bash
python eval-harness/v3/tracing/score_story_responses.py \
  --corpus eval-harness/v3/tracing/scenarios.story.jsonl \
  --run-id run-signature-001 \
  --responses responses.story.jsonl \
  --traces traces.story.jsonl \
  --ratings ratings.story.jsonl \
  --out results/story-responses.json
```

The scorer requires exactly one response and trace per
`(scenario_id, query_variant, role)`, with the same frozen run, unique cold
session, exact response hash, exact project, and exact query. A response containing `retrieved_entity_ids`,
`resolved_entity_ids`, or `human_scores` is rejected. Citations and
causal/current declarations must be subsets of the separate trace's resolved
entities. Trace call ordinals must be contiguous, each request must repeat the
project binding, and the resolver packet must attest that same project. The
gold manifest is kept hidden from evaluated sessions.

The mechanical gate checks role coverage, cause-before-effect order, current
verdict, required answer facts, foreign/forbidden citations, and stale entities
presented as current. It is deliberately called `mechanical_pass`, not semantic
success: string and numeric probes cannot reliably detect negation or judge
whether the explanation is coherent. Overall status remains
`pending_human_review` until all five independent rubric dimensions are present
and each meets the scenario threshold (3 by default). A low or invalid review
cannot pass, and a high review cannot override a mechanical hard failure.
Use the same 0–4 scale for every dimension: 4 = complete and correct, 3 =
correct with only minor omissions, 2 = mixed or materially incomplete, 1 =
mostly incorrect, and 0 = absent or unusable.
The rating repeats the run/session/role/project/query binding and the canonical
SHA-256 reported for that exact response. Run once without `--ratings` to get
the hashes and `pending_human_review`, then add independent reviews and rerun.
Collectors use `canonical_record_sha256` from `score_story_responses.py` when
creating the trace binding.

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

Story scenarios additionally report:

- `story_success` — all required roles, edges, facts, and currentness checks
  pass with no hard failure.
- `raw_candidate_recall` — diagnostic recall before resolution; never a
  headline success signal.
- `role_coverage` and `required_edge_coverage` — completeness and causal
  connectivity, separately.
- `fact_coverage` — load-bearing facts present in full resolved records.
- `precision` / `noise_ratio` and `distractors_found` — whether enough story
  was recovered without returning a project dump.
- `anchor_hit_rate` at the scenario's configured `search_limit`, `anchor_mrr`,
  plus by-style and by-role rollups — robustness across
  exact, paraphrased, colloquial, and underspecified questions.

## Corpus authoring

Ground truth comes from the real knowledge graph (project-A or
edge-cloud-agent): pick decisions with recorded rationale — especially ones
that superseded an earlier plan — and enumerate what a colleague would need
to reconstruct the decision. The included `scenarios.example.jsonl` shows the
shape with synthetic ids; replace it with a ratified corpus before quoting
numbers.
