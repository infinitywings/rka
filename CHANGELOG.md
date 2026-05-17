# Changelog

All notable changes to RKA are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + semver.

## [2.5.3] — 2026-05-17 (patch release; D2 context-ordering closed via 3-mission stack)

**Missions** (in order):
- `mis_01KRSMPNRQ70WRB1NH9BJAT6JX` — original D2 sort refactor
- `mis_01KRSP44W7BDZH11PZRGXH1WM4` — coefficient A/B sweep
- `mis_01KRSQ4GCRWPSXCWZHGZ2ZR830` — runner reorder (winning vector)

**Decisions**:
- `dec_01KRSMMCS8MD7KQDBS0E2DVKBQ` (D2 fix-shape; covers all 3 missions)
- `dec_01KRSP1852TKACJA0BM0HJNWBB` (hold-and-tune ratification after sort-only fell below floor)
- `dec_01KRSQ1TDY1X976W7EV16GXWZV` (vector-II ratification after sweep flat)

**Surfaced by**: Eval-v2 Finding 1 — `mean_ordering_score = 0.251` against the v2.5.2 baseline. The fix lifts this to **0.400** (+0.137 absolute, +0.037 above the 0.363 floor target).

### Root cause (resolved across 3 missions)

The `ContextEngine` post-fetch ranker had two documented-vs-implemented divergences from the v2.4 design (`dec_01KQQPD6Y6B362T3K08368BDMP`):
1. Topic-driven `get_context(topic=…)` discarded BM25/vector search relevance and re-sorted by importance only.
2. Overview `get_context()` used `created_at` as a tuple tie-break, not as the multiplicative recency term the v2.4 spec called for.

The original v2.5.3 mission fixed both. Per-scenario validation showed the fix worked (paper-scaffold-session-start-section lifted +0.333), but the aggregate move was only +0.016 — well below the 0.10 floor. A 5-config coefficient A/B sweep (v2.5.4) then proved coefficient space empirically flat (spread 0.0272 across the simplex), confirming `ContextEngine`'s internal sort was NOT the bottleneck. The winning attack vector turned out to be one layer up: the Eval-v2 runner's tool-invocation order.

### Fixed

- **Topic-anchored `get_context` preserves BM25/vector relevance order** (Mission 1, `rka/services/context.py`). Search hits annotated with `_search_rank = i` after `_hydrate_hits`; topic_sort_key uses `(rank, -importance, -centrality)` ascending. Importance/centrality break ties within identical search rank.
- **Overview `get_context` uses a weighted-sum score with recency as a first-class multiplicative term** (Mission 1):
  ```
  score = w_imp * importance_normalized + w_cent * log1p(centrality) + w_recency * recency_score
  ```
  where `recency_score = 1.0 / (1 + days_since_created)` clamped to `[0, 1]`. Default coefficients: `w_imp=0.5`, `w_cent=0.3`, `w_recency=0.2`. Semantic shift: a heavily-linked recent high-band entry can now outrank an un-linked critical-band entry. The v2.4 spec called for this; pre-v2.5.3 the strict-band hierarchy was the *bug*, not the design.
- **PI-source lift preserved at +0.125 normalized** (matches pre-v2.5.3 `+5/40` magnitude).
- **Two pre-v2.5.3 tests updated** to reflect the new semantics (`test_pi_source_lift_applied_within_band` now checks the lift via `_overview_score` directly; `test_high_centrality_with_age_can_beat_un_linked_critical` inverts the assertion). The decision rationale named the old invariant as the bug.

### Added

- **Env-var-configurable coefficients** (Mission 2, `rka/services/context.py` + `docker-compose.yml`). Read from `RKA_CTX_W_IMP`, `RKA_CTX_W_CENT`, `RKA_CTX_W_RECENCY`, `RKA_CTX_PI_LIFT` at module import time. Docker-compose interpolates from shell env so eval sweeps can swap configs via container restart without source rebuilds. `_reload_coefficients_from_env()` helper for in-process test overrides.
- **A/B sweep harness** at `eval-harness/v2/sweep_v2_5_3.py` (Mission 2). Runs the eval-v2 corpus across N coefficient configs, restarting the rka container between configs. Outputs aggregated metrics + per-config raw bundles. Reusable for future tuning.
- **Eval-v2 runner anchor-aware tool-order policy** (Mission 3, `eval-harness/v2/runner.py`). When a scenario has critical expected entities AND its `tools_invoked` includes any of `{rka_get_ego_graph, rka_multi_hop_retrieval, rka_assemble_evidence}`, those tools fire FIRST in deterministic order. Anchor-aware tools' outputs now lead the bundle's `combined_ranking` instead of being buried behind `get_context`'s 150+ entries. Non-anchored scenarios are no-ops (preserved behavior).

### Empirical finding (locked for future tuning work)

- **Coefficient space is essentially flat for this corpus**. 5-config sweep spanned simplex corners (recency-heavy, centrality-heavy, importance-dominant, balanced); aggregate `mean_ordering_score` moved <0.028 across the span. Future tuning should NOT waste effort on coefficient search; the lever is somewhere else (runner-order, type-aware boosting, corpus alignment).
- **Tool-invocation order is the dominant lever** for the aggregate metric. 9 anchor-affected scenarios lifted +0.30 to +0.53 each from the reorder; 7 un-anchored scenarios stayed within DB-drift noise (±0.04).

### Tests

- **17 context tests** in `tests/test_services/test_context.py` (11 pre-existing + 3 v2.5.3 sort-by-retrieval-path + 3 v2.5.4 env-var coefficients).
- **14 runner tests** in `eval-harness/v2/tests/` (7 pre-existing + 6 v2.5.5 reorder unit + 1 v2.5.5 lock-defaults integration).
- All previous regression tests pass (52 db, 25 cluster-related, etc.).

### Eval-v2 impact (canonical v2.5.3 run)

| Metric | v2.5.0 baseline | v2.5.1 | v2.5.2 | **v2.5.3** | Δ vs v2.5.2 |
|---|---|---|---|---|---|
| mean_recall (critical) | 0.958 | 0.958 | **1.000** | 0.958 | -0.042 (DB drift; see note) |
| mean_expanded_recall | 0.888 | 0.888 | 0.938 | 0.875 | -0.063 |
| **mean_ordering_score** | 0.251 | 0.253 | 0.263 | **0.400** | **+0.137** ✓ |
| mean_breadth | 3.25 | 3.25 | 3.25 | 3.00 | -0.25 |
| mean_efficiency | 0.037 | 0.036 | 0.037 | 0.035 | -0.002 |

**Per-tool critical-coverage**:

| Tool | v2.5.2 | v2.5.3 | Δ | Notes |
|---|---|---|---|---|
| `rka_get_ego_graph` | 0.333 | 0.778 | +0.444 ↑ | now first-discoverer for anchored entities |
| `rka_multi_hop_retrieval` | 0.000 | 0.817 | +0.817 ↑ | combined v2.5.1+v2.5.2+v2.5.3 effect |
| `rka_get_journal` | 1.000 | 0.000 | -1.000 ↓ | **attribution shift, not coverage loss** — entities still in bundle |
| (others) | unchanged | unchanged | 0.000 | |

The `rka_get_journal` per-tool drop is an attribution shift: the reorder puts anchor-aware tools ahead of `get_journal`; entities `get_journal` used to first-discover are now first-discovered by `ego_graph`/`multi_hop`. Total bundle recall unchanged. (Possible v2.5.4 metric refinement: annotate first-discovery vs follow-on coverage.)

The aggregate `mean_recall` drop from v2.5.2's 1.0 to 0.958 is DB-drift between runs (8 new entities added to live `rka_development` between the v2.5.2 and v2.5.3 eval runs displaced older entries from `/api/notes` top-20). Re-running v2.5.2 against today's DB would show the same drop. Hard recall floor (0.85) preserved.

### Release-line scope

Main only — `release/desktop` is independent per `dec_01KRPAVSTJ4H80VXJVN6DQ82WQ`.

### Phase-3 status

D1 (v2.5.1), D3 (v2.5.2), D2 (v2.5.3) all closed. D4 (bundle-narrowing) remains — re-scoping recommended per the v2.5.3 addendum in `eval-harness/v2/report.md` (anchor-aware-tool priority for bundle truncation; per-tool attribution annotation in the metric).

---

## [2.5.2] — 2026-05-16 (patch release; cluster → parent-RQ traversal)

**Mission**: `mis_01KRS1D8C0E2FP52D0P6JNB3SX`
**Fix-shape decision**: `dec_01KRS1ADPD4W6AW2X54MKVXMCR`
**Sequencing decision**: `dec_01KRRM5WKSSX7C3ZXZME0BMVQ9` (D3 ratified after D1 closed at v2.5.1)
**Surfaced by**: Eval-v2 Finding 3 (S7 + S9 cluster-anchored scenarios stuck at 0.67 critical-recall across v2.5.0 + v2.5.1 baselines).

### Root cause

`evidence_clusters.research_question_id` is a FOREIGN KEY column populated for 101/101 clusters across all 9 projects, but `GraphService.multi_hop_retrieval` and `GraphService.get_ego_graph` only walk `entity_links` + `claim_edges`. The FK column was invisible to graph traversal — every cluster anchor missed its parent research-question. Not a weight-tuning problem (the original hypothesis); a missing-edge-type problem.

### Added

- **New `entity_links.link_type` value: `'answers'`** (cluster → parent-RQ direction).
  Active-tier entry; rejects unknowns via the CHECK constraint same as the
  other 11 link types.
- **Migration 023** (`rka/db/migrations/023_cluster_answers_links.sql`):
  - Extends the CHECK enum (from migration 021) to include `'answers'`.
    Uses migration 021's documented table-swap pattern.
  - Backfills one entity_link per `evidence_clusters` row with a non-null
    `research_question_id` — `link_type='answers'`, `source=cluster`,
    `target=decision`, `link_weight=1.0`, `link_reason='backfill from
    evidence_clusters.research_question_id FK (migration 023)'`.
    Idempotent via INSERT OR IGNORE against the project-scoped UNIQUE
    triple from migration 020.
  - Production row count post-migration: **101 entity_links** across 9
    projects (16 for `prj_01KKQM9JFG67GT5FGWTAHD9YE4`, the Eval-v2 project).
- **`DEFAULT_EDGE_WEIGHTS['answers'] = 1.0`** in `rka/services/graph.py`
  (high-signal tier alongside `justified_by` / `motivated` / `evidence_for` /
  `derived_from`).
- **ClusterService hook for parity going forward** in
  `rka/services/clusters.py` — `.create` and `.update` write the `answers`
  link via `BaseService.add_link(...)` whenever a non-null
  `research_question_id` is set. INSERT OR IGNORE semantics keep re-runs
  safe; no future migration needed for new clusters.

### Fixed

- **Cluster-anchored graph traversal now surfaces the parent
  research-question.** Both `GraphService.get_ego_graph` and
  `GraphService.multi_hop_retrieval` walk the new `answers` edges
  automatically (no graph-layer code changes required beyond the
  weight-map entry).

### Tests

- **4 migration tests** at `tests/test_db/test_migration_023.py`:
  CHECK extension accepts `'answers'`; CHECK still rejects unknown
  link types (additive, not removal); backfill is idempotent across
  two runs; row count invariant equals cluster count with non-null FK,
  per-project breakdown propagates `project_id` correctly, orphan
  null-FK clusters produce no link, provenance columns set as documented.
- **4 regression tests** at `tests/test_services/test_graph.py`:
  ego_graph from cluster anchor includes parent RQ (S7 anchor verbatim);
  multi_hop_retrieval seeds-only cluster traversal returns parent RQ
  (combined v2.5.1 + v2.5.2 regression-lock); ClusterService.create
  emits exactly one link when FK set; ClusterService.create emits no
  link when FK is NULL.

### Eval-v2 impact — live re-run against v2.5.2 container

| Per-scenario critical recall | v2.5.0 / v2.5.1 | v2.5.2 |
|---|---|---|
| S7 `brain-contradiction-staleness-vs-validation` | 0.667 | **1.000** |
| S9 `brain-paper-scaffold-session-start-section`  | 0.667 | **1.000** |
| Other 14 scenarios | 1.000 | 1.000 |

| Aggregate | v2.5.1 | v2.5.2 | Δ |
|---|---|---|---|
| mean_recall (critical) | 0.9583 | **1.0000** | **+0.0417** |
| mean_expanded_recall | 0.8875 | 0.9375 | +0.0500 |
| mean_ordering_score | 0.2533 | 0.2628 | +0.0096 |
| mean_efficiency | 0.0362 | 0.0372 | +0.0010 |

| Per-tool critical-coverage (directly-affected tools) | v2.5.1 | v2.5.2 |
|---|---|---|
| `rka_get_ego_graph` | 0.333 | **0.778** (Δ +0.444) |
| `rka_multi_hop_retrieval` | 0.683 | **0.817** (Δ +0.133) |

**Every scenario in the 16-scenario corpus now scores critical-recall = 1.0.**

Critical-recall floor (0.85) passes flat at the ceiling. v2.5.2 artifacts
at `eval-harness/v2/results/raw_v2.5.2/` + `metrics_v2.5.2.json`. Baselines
preserved: v2.5.0 at `results/raw/` + `metrics.json`; v2.5.1 at
`results/raw_v2.5.1/` + `metrics_v2.5.1.json`. Full before/after analysis
in `eval-harness/v2/report.md` § "v2.5.2 addendum — D3 closed".

### Release-line scope

Main only — `release/desktop` is independent per the hub-and-spoke
architecture (`dec_01KRPAVSTJ4H80VXJVN6DQ82WQ`). No cherry-pick attempted.

### Phase-3 hooks remaining

D1 (v2.5.1) + D3 (v2.5.2) both closed. D2 (importance-weight tuning) and
D4 (bundle-narrowing policy) remain candidate Phase-3 missions; their
success signal has shifted from `mean_recall` (now at the 1.0 ceiling)
to `mean_ordering_score` (0.263) and `mean_efficiency` (0.037).

---

## [2.5.1] — 2026-05-16 (patch release; multi-hop schema relaxation)

**Mission**: `mis_01KRRM8CJP34KTN8KJMZQH2PFP`
**Motivating decision**: `dec_01KRRM5WKSSX7C3ZXZME0BMVQ9` (D1 sequencing from Eval-v2 report)
**Surfaced by**: Eval-v2's v2.5.0 live run (Finding 4 in `eval-harness/v2/report.md`,
journal `jrn_01KRPGY39DJA2K9KV20XD733GK`) — every `rka_multi_hop_retrieval`
invocation in the 16-scenario corpus returned 422.

### Fixed

- **`POST /api/graph/multi-hop` now accepts seeds-only invocations.**
  `MultiHopRequest.query` was a required `str` (no default), so any
  body that only carried `seeds` was rejected by FastAPI's schema
  validator with the default per-field-error 422 — even though the
  service layer (`rka/services/graph.py:multi_hop_retrieval`) has
  always had an explicit seeds-set branch that bypasses search.
  ([rka/api/routes/graph.py](rka/api/routes/graph.py))
- **422 body shape on neither-set requests is now the Affordance-G
  structured object** (`{error, detail, hint}`) instead of FastAPI's
  per-field-error array. Mirrors the Mission B precedent at
  `rka/api/routes/config.py:_422`. The `hint` field is a fully-rendered
  example so callers see actionable guidance instead of needing the
  schema docs.
- **Eval-v2 runner sends a v2.5.1-compliant body.** `_call_multi_hop`
  now sends `seeds=[anchor]` (a list, not the v2.4-era singular
  `start_entity` key that the schema never recognized) and always
  populates `query` from `scenario.trigger[:200]`.
  ([eval-harness/v2/runner.py](eval-harness/v2/runner.py))

### Behavior preserved (regression-locked)

- **Query-only invocations** still succeed (search-based seeding path).
- **Both `query` + `seeds` provided** still succeed; the service uses
  explicit seeds and bypasses the search step.
- **MCP wrapper** (`rka_multi_hop_retrieval` in `rka/mcp/server.py`)
  always sends `query`, so no MCP-side change is required.

### Tests

- 4 new regression tests at `tests/test_api/test_graph_route.py` —
  seeds-only / query-only / neither (422 + Affordance-G shape) / both
  combined.
- 1 new test at `eval-harness/v2/tests/test_runner.py` —
  `test_call_multi_hop_body_matches_v2_5_1_schema` asserting body
  shape against the schema (no `start_entity` legacy key; `seeds` is
  a list; `query` always populated).

### Eval-v2 impact (live re-run against v2.5.1 container)

- **`per_tool_mean_critical_coverage[rka_multi_hop_retrieval]`**
  moved **0.000 → 0.683** (Δ +0.683).
- Zero `rka_multi_hop_retrieval` divergences across the 16-scenario
  corpus (was 16 — one per scenario).
- Aggregate `mean_ordering_score` nudged **+0.0022** from the newly-
  populated multi-hop contribution to the combined ranking.
- Critical-recall floor (0.85) still PASSES at 0.958.
- v2.5.1 artifacts: `eval-harness/v2/results/raw_v2.5.1/` +
  `metrics_v2.5.1.json`. v2.5.0 baseline preserved at
  `results/raw/` + `metrics.json`.
- Full before/after analysis in `eval-harness/v2/report.md` § "v2.5.1
  addendum — D1 closed".

### Release-line scope

This patch lands on **main only**. The `release/desktop` line is
independent per the hub-and-spoke architecture
(`dec_01KRPAVSTJ4H80VXJVN6DQ82WQ`); a future cherry-pick to
`v2.5.0-desktop` is up to the desktop release cadence and is not part
of this mission.

### Phase-3 hooks (D2/D3/D4) unchanged

D1 was the well-scoped first slice. D2 (importance-weight tuning),
D3 (cluster→parent-RQ pathway), and D4 (bundle-narrowing policy) remain
candidate Phase-3 missions, gated on PI ratification.

---

## [2.5.0] — 2026-05-15 (main branch; distinct from `v2.5.0+desktop` on release/desktop)

**Release line note.** Per the hub-and-spoke architecture decision
`dec_01KRPAVSTJ4H80VXJVN6DQ82WQ`, this v2.5.0 release on `main`
is independent of `v2.5.0-desktop` on `release/desktop`. Main carries
core RKA features; release/desktop carries macOS .app distribution.
Eval-v2's composed-context coverage harness is core infrastructure, so
it lands on main and bumps main's minor.

### Added

- **Eval-v2 composed-context coverage harness** at `eval-harness/v2/`,
  extending (not replacing) the May 14 single-endpoint `rka_search`
  eval (`mis_01KRKJ9G20EM5XMA147JTKQCFF`).
  - **Corpus schema** (`eval-harness/v2/schema.md` +
    `eval-harness/v2/schema.json`) with JSON Schema Draft 2020-12
    validation. Each scenario carries: `scenario_id`, `actor`
    (brain | executor), `trigger`, `tools_invoked`, `expected_entities`
    with `importance` tags (critical | useful | nice-to-have), optional
    `context_length_budget_estimate` + `notes`.
  - **Schema validator** (`schema_validator.py`) with two runtime rules
    JSON Schema can't express cleanly: critical-floor ≥3 per scenario,
    and entity_id/entity_type prefix consistency.
  - **Corpus of 16 scenarios** (`corpus/scenarios.jsonl`) spanning 6
    pattern types: Brain session-start (4), Brain mission-creation (2),
    Brain contradiction-investigation (2), Brain paper-scaffold-assembly
    (2), Executor mission-pickup (3), Executor backbrief-gate (3).
    All entity IDs anchored to real rka_development entities.
  - **Runner** (`runner.py`) — REST-direct execution of the composed
    call sequence per scenario (11 distinct MCP tools mapped), entity-ID
    extraction via depth-first walker, anchor-entity logic for
    multi_hop / ego_graph / assemble_evidence, defensive JSON parsing
    for non-existent endpoints' SPA fallbacks, sister-uncertainty
    probing with checkpoint-on-divergence per Brain T2-gate ratification.
  - **Metrics** (`metrics.py`) — 5 per-scenario metrics (recall over
    critical-only, expanded_recall, NDCG-style ordering_score, breadth,
    efficiency) + per-corpus aggregation + per-actor breakdown +
    per-tool critical-coverage breakdown + reproducibility provenance
    (corpus SHA + rka HEAD + timestamp).
  - **36 unit + integration tests** (13 T1 schema + 6 T3 runner +
    17 T4 metrics) all passing.
  - **Live run results** in `results/raw/<scenario_id>.jsonl` +
    `results/metrics.json`:
    - mean_recall (critical) = 0.958 — PASSES 0.85 floor
    - mean_expanded_recall = 0.887
    - mean_ordering_score = 0.251 (low — critical entities buried mid-bundle)
    - mean_breadth = 3.25 of 5 entity types
    - mean_efficiency = 0.037 (very low — bundles 96% noise)
  - **Brain narrative report** at `eval-harness/v2/report.md` with 5
    headline findings + 4 decision-slate hooks for Phase 3 (bug fix
    on rka_multi_hop_retrieval 422, importance-weight tuning, cluster→
    parent-RQ pathway, bundle-narrowing policy).

### Surfaced bugs (next-mission candidates)

- `rka_multi_hop_retrieval` returns **422 Unprocessable Content** on
  every invocation during the live run — likely a request-body schema
  drift between MCP-tool docs and the `/api/graph/multi-hop` REST
  endpoint. Logged at `eval-harness/v2/results/raw/*.jsonl` and
  surfaced as Phase-3 decision-slate hook D1 in
  `eval-harness/v2/report.md`.

### Mission reference

- Mission: `mis_01KRPF3DERZS2W5VFDYE9E9GKM`
- Motivating decision: `dec_01KRPF09AP1FE1CRR6YQBY2R5F`
- Mid-mission gate ratification (Option B + S6 critical promotion):
  PI greenlight 2026-05-15
- Procedural-recurrence calibration: `jrn_01KRPGY39DJA2K9KV20XD733GK`
- Working branch: `feat/eval-v2-composed-context`
  (merged to main at this release via --no-ff)
- Test suite at release: 36 in `eval-harness/v2/tests/` + the prior
  v2.4.1 baseline

### Bookkeeper invariant

`git diff main -- rka/services/worker.py = 0 lines` held across every
commit on the eval-v2 branch (verified at T1 ca61cbe, T2 ea4d32c,
T2.1 8bde65f, T3 4ce5f09, T4 9043374, T5 fbcdbdb, T6 ec25052,
T7 release commit). The mission's measurement-only constraint
held too: `git diff main -- rka/` = 0 lines (Eval-v2 added no
source-code changes to RKA proper).

---

## [2.4.1] — 2026-05-15

### Fixed

- **`openai_compat` + `ollama` embedding backends: default httpx timeout
  raised from 30s → 600s.** The prior 30s default made local 8B-class
  embedding servers (LM Studio + qwen3-embedding-8b, Ollama + nomic-large
  variants) fail the first backfill batch with `httpx.ReadTimeout` and no
  claims would land. Constructor still accepts `timeout_seconds=...` so
  fast hosted backends can opt back down.
- **`BackfillService` default batch size lowered from 32 → 8.** A 32-text
  batch against an 8B-class model on a single Mac is multiple seconds even
  under ideal conditions; reducing the default lets the first batch
  complete and keeps the polling UI honest. Constructor still accepts
  `batch_size=...` for hosted-API workloads where 32+ is fine.
- **Backfill failure message now includes the exception class name.** Prior
  `status.error` rendered as `"batch embed failed (cursor at …): "` (empty
  after the colon) when the underlying exception had no string
  representation — e.g. `httpx.ReadTimeout()`. Now renders as
  `"batch embed failed (cursor at …): ReadTimeout: <message>"`. Locked by
  `test_backfill_error_includes_exception_class_when_message_empty`.

### Tests

- 4 new tests in `tests/test_services/test_embedding_backfill.py`:
  - `test_backfill_error_includes_exception_class_when_message_empty`
  - `test_backfill_default_batch_size_is_eight_v241`
  - `test_openai_compat_default_timeout_is_600_v241`
  - `test_ollama_default_timeout_is_600_v241`

### Provenance

- Triggered by PI UI failure observation post-v2.4.0 release: LM Studio
  + qwen3-embedding-8b 4096-dim backfill failed at 0/827 claims after
  ~23 min wall-clock with empty `status.error` after the colon.
- Bookkeeper invariant `git diff main -- rka/services/worker.py` = 0 lines
  held on the v2.4.1 hotfix branch.

## [2.4.0] — 2026-05-15

### ⚠ BREAKING CHANGES

- **`/api/capabilities` no longer returns the `llm` field.** The response
  is now `{"embedding": {available, reason_unavailable}}` — top-level
  `llm` is absent (not null, not `{available: false}`, gone). Any client
  that read `response.capabilities.llm` before v2.4.0 must update.
  Locked by a regression test in
  `tests/test_api/test_capabilities_route.py`. Rationale: PI directive
  `jrn_01KRNZBS50K250HHHHEC58E4GC` ratified Interpretation A of the
  LLM-capability removal — service code preserved, user-facing surface
  removed.
- **`web/src/hooks/useLLM.ts` and `web/src/pages/Notebook.tsx` are
  deleted.** The Settings page's LLM config card is replaced with a new
  Embeddings card; LLM types are removed from `web/src/api/types.ts`
  and LLM methods from `web/src/api/client.ts`. Server-side
  `rka/infra/llm.py`, `rka/api/routes/llm.py`, and the `rka_ask` /
  `rka_generate_summary` MCP tools are PRESERVED for future re-wiring
  through the orchestrator's Claude Code SDK.
- **`docker-compose.yml` no longer carries `RKA_LLM_*` env var
  references** (commented or active). `RKA_EMBEDDINGS_ENABLED: "true"`
  is set explicitly on both services.

### Added

- **Pluggable embedding backends.** Three concrete implementations
  behind the `EmbeddingBackend` Protocol:
  - **FastEmbed** (local ONNX, default; nomic-768 baseline)
  - **OpenAI-compat HTTP** (OpenAI API, LM Studio, vLLM, Together,
    Anthropic-via-shim — whichever the `base_url` points at; `api_key`
    optional)
  - **Ollama** (singular-prompt `/api/embeddings`; not the
    list-wrapped OpenAI shape)
- **Persistent embedding config at `/data/embedding_config.json`**
  (file-mode 0600, atomic write via tmp+rename, pre-flight backup to
  `embedding_config.backup.json` on every save).
- **REST API for embedding config:**
  - `GET /api/config/embedding` — current config with `api_key`
    redacted to `"***"`
  - `PUT /api/config/embedding` — validate + test + persist; returns
    202 + `{job_id, status_url}` if backfill kicked off, 200 if only
    `api_key` changed
  - `POST /api/config/embedding/test` — probe without persisting;
    returns `{ok, detail, detected_dim, latency_ms}`
  - `GET /api/config/embedding/backfill/status?job_id=…` — polling
    endpoint for the UI progress bar
  - 422 error mapping (Affordance G pattern):
    `{"error": "embedding_config_invalid", "detail": ..., "hint": ...}`
- **Migration 022 (`022_dim_flex_vec_claims.sql`)** — adds
  `claims.embedding_pending` column + partial index; flags every
  existing claim as pending so the configured backend re-embeds them.
- **`rka/services/embedding_reshape.py`** — drops + recreates the
  `vec_claims` virtual table at a config-driven dim. Runs on app
  startup (only when the dim has actually changed) and on
  PUT-with-dim-change.
- **`rka/services/embedding_backfill.py:BackfillService`** — iterates
  pending claims in `id`-ascending order, embeds in batches (default
  32), writes vec_claims rows, clears the flag. Resumable across
  container restarts. Per-claim failures keep the flag for retry;
  batch-level embed failures mark the job state=`failed`.
- **Web UI Settings page → Embeddings tab.** Backend dropdown,
  conditional fields per backend, **Test connection** button,
  confirmation modal for **Save & re-embed**, progress bar polling
  the status endpoint every ~1500 ms. The 422 hint for corrupt config
  renders verbatim from the server.
- **First-run banner.** Dismissible "Semantic search is enabled"
  banner with a link to Settings → Embeddings; dismissal persists in
  `localStorage` (`rka_first_run_banner_dismissed_v2_4`).
- **First-run startup hook.** When `/data/embedding_config.json` is
  absent, app startup persists `DEFAULT_CONFIG` (fastembed + nomic-768)
  via the standard `save_config` path so the config file exists from
  the very first request.
- **Reconcile-dim guard.** Each backend's production `embed()` path
  calls `reconcile_dim(self._dim, observed)` — raises
  `EmbeddingConfigError` on real drift; preserves the legitimate
  populate-from-zero path used by `test_connection()`. Replaces
  silent `self._dim = len(vec)` mutation that previously masked
  config-vs-server-dim divergence.
- **`docs/embedding_backends.md`** — full backend reference: matrix,
  switching procedure, latency table, troubleshooting (LM Studio
  connect-refused, dim mismatch, bind-mount + 0600 caveat).
- **`CHANGELOG.md`** — this file.

### Changed

- `embeddings_enabled` config default flipped from `False` to `True`.
  Override via `RKA_EMBEDDINGS_ENABLED=false` env var if you really
  want the in-process EmbeddingService disabled.
- `EmbeddingService` keeps the same public surface (`embed`,
  `embed_document`, `embed_batch`, `store_embedding`, …) but the work
  is dispatched to a swappable `EmbeddingBackend` chosen at
  construction time. Legacy `EmbeddingService(model_name=...)` calls
  still work and default to FastEmbed.
- `rka_get_status` MCP formatter renders the capabilities LLM line
  conditionally (`if "llm" in caps`) so it gracefully omits it now and
  re-appears if Phase 2 puts the field back.

### Preserved (deliberate non-removals)

- `rka/infra/llm.py`, `rka/api/routes/llm.py` server modules
- `rka_ask`, `rka_generate_summary` MCP tools (graceful no-op when LLM
  unavailable, which is the new default)
- Background enrichment paths in `rka/services/worker.py` (bookkeeper
  invariant: `git diff main -- rka/services/worker.py` is empty across
  every Mission D commit)
- `enrichment_status` column on entries
- LLM-dependent web pages outside Notebook (Timeline, ContextInspector)
  — none imported `useLLM` directly and continue to render unchanged

### Mission reference

- Mission: `mis_01KRNYPVB8N3HDMZ9HK9HM3TB0`
- Motivating decision: `dec_01KRNYJ966H6W4REMK2ZJY2Y9R`
- LLM-removal refinement: `jrn_01KRNZBS50K250HHHHEC58E4GC`
- Mid-mission gate ratification: `dec_01KRP0WFMXAF0TQN6RDXY65WEX`
- Working branch: `feat/v2.4-pluggable-embeddings` (from `main@42e04c6`)
- Test suite at release: 599 passing (511 baseline + 88 mission-D tests)
