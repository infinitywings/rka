# Eval-v2 — Composed-Context Coverage Report

**Mission**: `mis_01KRPF3DERZS2W5VFDYE9E9GKM`
**Motivating decision**: `dec_01KRPF09AP1FE1CRR6YQBY2R5F`
**Date**: 2026-05-15
**Author**: Brain (this session)
**Branch**: `feat/eval-v2-composed-context` @ `fbcdbdb`
**Test counts**: T1 13 / T3 6 / T4 17 = 36/36 unit-integration tests
**Suite-scale data**: 16 scenarios × 6 pattern types × 11 distinct MCP tools

---

## TL;DR — metric-divergence-as-headline (skill rule #14)

**Critical-recall PASSES the 0.85 floor at 0.958. Ordering and efficiency are the real story.**

| Metric | Mean | Floor | Verdict |
|---|---|---|---|
| **Critical recall** | **0.958** | 0.85 | ✅ PASSED |
| Expanded recall | 0.887 | (informational) | strong |
| **Ordering score** | **0.251** | (none formal) | ⚠️ low — critical entities buried |
| Breadth | 3.25 of 5 | (none formal) | acceptable |
| **Efficiency** | **0.037** | (none formal) | 🔴 very low — bundles 96% noise |

The composed retrieval surface DOES surface critical entities (95.8% recall) but does so by returning ~170-entity bundles where ~5 are expected and the remaining ~165 are project-context noise. Skill rule #14 applies: **report the divergence, not the floor pass**.

---

## Headline findings

### Finding 1: composed retrieval is recall-good, ordering-bad, efficiency-bad

The current default — hybrid retrieval + importance-weighted + entity_links centrality + recency boost — surfaces 14 of 16 scenarios' critical entities at recall=1.0 and the other 2 at 0.67. That means **at the entity-presence level, the retrieval mostly works**.

What fails: **ordering** — critical entities are present but buried mid-bundle. NDCG-style ordering scores average 0.251, meaning critical entities are roughly mid-pack rather than top-3 across the typical Brain session-start bundle.

**Recommendation 1 — Phase 3 tuning candidate**: adjust importance-weight + centrality + recency-boost coefficients so critical-importance entities consistently land in the top-N (e.g., top-15) of the returned bundle. The current weighting surfaces them but doesn't prioritize them.

### Finding 2: efficiency 0.037 = bundles are 96% padding

Each scenario's bundle averages 170 entities; only ~5 are in the expected set. That's a 32:1 noise-to-signal ratio. Two interpretations:

- **(a)** the bundles ARE the right shape and the corpus's expected_entities sets are under-specified (ratify-and-grow per the spec's 30%-drift checkpoint trigger)
- **(b)** the bundles are over-fetching context that downstream consumers (Brain, Executor) actually filter on the consumer side

Per Brain skill rule #14, the headline is the divergence itself. **Whichever interpretation is correct, the bundle SHAPE is the next thing to evaluate.** A Phase 3 mission should A/B-test "narrow bundle (top-10 importance-ranked)" vs "broad bundle (current default)" and measure downstream LLM-consumer quality (token efficiency, answer correctness).

**Recommendation 2**: do NOT default-narrow the bundle now. Eval-v2 measures the bundle as currently shipped; choosing how to interpret 0.037 efficiency requires A/B data on downstream consumers, which is out of Eval-v2 scope per the upfront acceptance criteria.

### Finding 3: cluster-anchored scenarios are the recall failure mode

Both scenarios that scored below 1.0 critical-recall are cluster-anchored:

- `brain-contradiction-staleness-vs-validation` (rec 0.67): scenario anchors at `ecl_01KP4PK7VPN8YFR50PSFXPGTQ0` (Staleness Detection cluster) + `ecl_01KP4PKMN8XS0WXHXHN7GN4TG3` (Validation Gate Frameworks). The retrieval missed `dec_01KP4P4QSSNZCTEHVT6QR7ZRYD` (parent RQ).
- `brain-paper-scaffold-session-start-section` (rec 0.67): anchors at `ecl_01KP4PJGJKE9Q7X1W2X6SJJVZ3` (Session Start cluster). Missed `dec_01KP4P53MSKY3GKEXZKG9JMFKX` (parent RQ for that cluster).

**Pattern**: when the user/agent anchors at a cluster, the retrieval surface fails to traverse back up to the cluster's parent decision (the RQ). The `rka_get_ego_graph` per-tool critical-coverage is only 0.333 across the 6 scenarios that invoke it — confirming Eval-v1 finding #3 ("Cluster-level retrieval is weak"; eval-harness/report.md headline finding 3).

**Recommendation 3 — high-priority Phase 3 follow-up**: cluster-to-parent-RQ retrieval pathway. The current entity_links centrality boost may under-weight the parent-RQ direction from cluster anchors. Worth investigating whether the boost should be link-direction-aware (favor parent-of, supports, etc. over generic centrality).

### Finding 4: 5 of 11 tools contribute zero critical entities

Per-tool mean critical-coverage:

| Tool | Mean coverage | Notes |
|---|---|---|
| `rka_get_journal` | **1.000** | strongest — recent journals always include critical entries |
| `rka_get_context` | **0.867** | very strong |
| `rka_get_mission` | **0.800** | strong for mission-pickup pattern |
| `rka_get_checkpoints` | 0.333 | medium — surfaces critical only when checkpoints are central to the scenario |
| `rka_get_research_map` | 0.333 | medium |
| `rka_get_ego_graph` | 0.333 | medium (cluster-anchored variant is the failure case) |
| `rka_get_status` | 0.000 | **zero contribution** |
| `rka_get_pending_maintenance` | 0.000 | **zero contribution** |
| `rka_get_review_queue` | 0.000 | **zero contribution** |
| `rka_multi_hop_retrieval` | 0.000 | **422 across all invocations — REAL DIVERGENCE** |
| `rka_assemble_evidence` | 0.000 | **200 OK but no expected entities surfaced** |

Three categories of zero-contribution:

- **Real bug — rka_multi_hop_retrieval returns 422 Unprocessable Content** on every invocation (4 scenarios invoked it). Logged as a sister-uncertainty divergence per the T2-gate ratification. **Worth filing a follow-up bug-fix mission** — the tool is documented in MCP but the REST endpoint rejects the body shape the runner sends. May be a request-schema drift.
- **Conceptual zero-coverage — rka_get_status / rka_get_pending_maintenance / rka_get_review_queue** return status-level data (active phase, gap counts) that doesn't include entity references at the scenario-anchor level. They're not "broken"; they answer a different question. The composed-context bundle's value comes from get_context + get_journal + get_mission; the others are situational.
- **rka_assemble_evidence** returns 200 but the response shape didn't expose entity IDs the walker could find. T2-gate flagged this as a sister-uncertainty; confirmed empirically. Worth surfacing whether the response shape is what the eval expects.

**Recommendation 4**: investigate `rka_multi_hop_retrieval`'s 422 — this is the clearest actionable item from Eval-v2. Likely a 1-2 commit fix once the body-schema drift is identified.

### Finding 5: actor-split reveals executor scenarios are slightly easier

| Actor | n | Recall | Expanded | Ordering | Efficiency |
|---|---|---|---|---|---|
| executor | 6 | 1.000 | 0.933 | 0.246 | 0.027 |
| brain | 10 | 0.933 | 0.860 | 0.254 | 0.043 |

Executor scenarios use leaner tool sequences (4 tools each vs Brain's 6) and hit recall=1.0 perfectly. Brain's scenarios have the cluster-anchored failure mode (Finding 3) pulling recall down. Brain's efficiency is slightly better (0.043 vs 0.027) because Brain's 6-tool bundles include the same ~170 entities while Executor's 4-tool bundles include slightly fewer entities for the same ~5 expected — the absolute count of noise scales with tool count.

---

## Per-axis breakdown

### By pattern type

| Pattern | n | mean recall | mean ordering | mean efficiency |
|---|---|---|---|---|
| brain-session-start | 4 | 1.00 | 0.24 | 0.029 |
| brain-mission-creation | 2 | 1.00 | 0.27 | 0.032 |
| brain-contradiction | 2 | **0.83** | 0.18 | 0.021 |
| brain-paper-scaffold | 2 | **0.83** | 0.34 | 0.103 |
| executor-mission-pickup | 3 | 1.00 | 0.25 | 0.026 |
| executor-backbrief | 3 | 1.00 | 0.25 | 0.027 |

**brain-contradiction** and **brain-paper-scaffold** are the weak patterns — both predominantly cluster-anchored. **brain-paper-scaffold-multi-cluster-rq** (S10) is the outlier within paper-scaffold with rec=1.0 / ord=0.53 / eff=0.188 — best ordering + best efficiency of the whole corpus. That scenario uses `rka_get_research_map` first, which gives a structured RQ→clusters response — much denser per-entity than the importance-ranked context bundle.

### By tool category

Already covered in Finding 4. The headline is the binary split: 3 tools that work (`get_journal`, `get_context`, `get_mission`) account for substantially all the critical-recall; 3 tools contribute medium (`get_checkpoints`, `get_research_map`, `get_ego_graph`); 5 contribute zero — 1 due to a real bug and 4 due to either conceptual mismatch or shape mismatch.

---

## Methodological limitations

Per Brain skill rule #9d (caveats mandatory):

1. **PI-ratified ground truth, not derived post-hoc**. This is by design (A2 of the upfront Backbrief; shrinks labeling burden vs Eval-v1's full-corpus grading). But it means the expected sets reflect the Executor's mental model of what SHOULD be there + PI's ratification, not a downstream-consumer measurement of what was actually NEEDED. The 0.037 efficiency could be reframed if the expected sets were expanded by 5-10× to include "useful-but-not-must-have" context entries.

2. **Single-rater corpus authoring + single-pass PI ratification.** The corpus was drafted by Executor in this session and PI ratified 5 of 6 asks block-accept + 1 correction (S6 promotion). The single labeling pass is fast but doesn't surface ambiguity in marginal cases. Eval-v3 (if filed) could iterate the corpus with multi-rater agreement.

3. **16 scenarios is small.** Within-rater + within-corpus noise dominates over per-tool effect size at this corpus size. The per-tool critical-coverage table is the strongest signal because each tool is exercised across ~5-16 scenarios; per-scenario metrics carry more variance.

4. **Single config evaluation.** Per A4, only the current default (hybrid + importance + centrality + recency) is measured. The +9% NDCG@10 Eval-v1 finding for FTS+semantic vs FTS-only would not show here because the runner doesn't switch backends.

5. **Live container at v2.4.1 with vec_available=true.** Eval-v1's qwen3-8B backfill is NOT in effect on this container; the embedding backend is the v2.4.0 default (FastEmbed nomic-768). Eval-v2 measurements attribute to that backend; switching to qwen3 would re-run with potentially different ordering scores.

6. **Project scope: `prj_01KKQM9JFG67GT5FGWTAHD9YE4` (rka_development).** The runner's `--project-id` flag was set; live API observed responses scoped accordingly. Different projects (smaller corpora) may show very different efficiency numbers since the noise denominator scales with project size.

---

## Forward-looking recommendations

1. **Investigate `rka_multi_hop_retrieval` 422** (Finding 4) — likely a request-body-schema drift between the MCP-tool docs and the REST `/api/graph/multi-hop` endpoint. One commit fix candidate.

2. **A/B test importance-weighting + centrality coefficients** (Finding 1) to improve ordering_score from 0.25 to a target (≥0.50 would mean critical entities consistently in the top-third of the bundle). Phase 3 mission scope.

3. **Cluster→parent-RQ retrieval pathway** (Finding 3) — investigate whether entity_links direction should bias retrieval (e.g., "parent-of" link gets a boost from clusters). Phase 3 mission scope.

4. **Decide on bundle-narrowing policy** (Finding 2). Either (a) accept current bundles as the right shape and grow corpus expected_entities to match, or (b) A/B test narrower bundles. PI ratifies which interpretation drives Phase 3.

5. **`rka_get_ego_graph` cluster anchoring shape** — confirmed sister-uncertainty divergence. Worth a small probe to see whether the response shape changes when the anchor is a cluster vs decision/mission. May explain part of Finding 3.

6. **Expand corpus to 30+ scenarios for significance testing** — current 16 is directional. Phase 3 could double the count with focused cluster-anchored scenarios to confirm Finding 3's pattern.

---

## Reproducibility provenance (per Brain skill rule #8a)

- **corpus_hash**: see `eval-harness/v2/results/metrics.json` (sha256:... per `_provenance`)
- **rka_head**: see metrics.json
- **eval_run_timestamp**: see metrics.json
- **eval_version**: `v2`
- **container_version**: 2.4.1 with vec_available=true (FastEmbed default per v2.4.0)
- **project_id**: `prj_01KKQM9JFG67GT5FGWTAHD9YE4` (rka_development)
- **branch**: `feat/eval-v2-composed-context` @ `fbcdbdb`
- **runner command**: `python -m eval-harness.v2.runner --corpus eval-harness/v2/corpus/scenarios.jsonl --rka-url http://localhost:9712 --project-id prj_01KKQM9JFG67GT5FGWTAHD9YE4 --output-dir eval-harness/v2/results/raw`
- **metrics command**: `python -m eval-harness.v2.metrics --corpus ... --raw-dir ... --output eval-harness/v2/results/metrics.json`

---

## Decision-slate hook

Per Brain skill rule #9b: this report does NOT autoship final decisions on importance-weight tuning, bundle-narrowing policy, or cluster→parent-RQ pathway changes. The four named recommendations above are candidates for follow-up Brain `decision_options` slates the PI ratifies separately:

- **(D1)** Bug-fix Mission: `rka_multi_hop_retrieval` 422 (Finding 4) — **CLOSED in v2.5.1** (see addendum below)
- **(D2)** Tuning Mission: importance-weight/centrality/recency-boost coefficient sweep (Finding 1)
- **(D3)** Pathway Mission: cluster→parent-RQ retrieval (Finding 3)
- **(D4)** Policy Decision: bundle-narrowing vs corpus-expansion under 0.037 efficiency (Finding 2)

PI ratifies which subset becomes Phase 3 missions. The mission spec's checkpoint trigger fires here: critical recall is comfortably above floor (0.958 vs 0.85), so this is NOT a "corpus too easy + needs harder cases" outcome — it's a "retrieval surfaces critical entities but ordering and efficiency are the next bottleneck" outcome.

---

## v2.5.1 addendum — D1 closed (Mission v2.5.1-D1)

**Mission**: `mis_01KRRM8CJP34KTN8KJMZQH2PFP`
**Decision**: `dec_01KRRM5WKSSX7C3ZXZME0BMVQ9` (D1 sequencing ratified ahead of D2/D3/D4)
**Date**: 2026-05-16
**Container**: rebuilt from `feat/v2.5.1-multi-hop-fix` HEAD (commits 10cae50 + b6b7d06 + 5f786f0)

### What changed

Two-sided fix to the v2.5.0 baseline's `rka_multi_hop_retrieval` 422 wall:

1. **API schema** — [rka/api/routes/graph.py](../../rka/api/routes/graph.py) — `MultiHopRequest.query` relaxed from required `str` to `Optional[str] = None`; route handler returns an Affordance-G structured 422 (`{error, detail, hint}`) when neither `query` nor `seeds` is provided. Seeds-only invocations now accepted, matching what the service layer already supported.
2. **Runner body** — [eval-harness/v2/runner.py](runner.py) — `_call_multi_hop` now sends `seeds=[anchor]` (a list, not the v2.4-era singular `start_entity` key) and always populates `query` from `scenario.trigger[:200]`, so the schema's neither-set branch is unreachable from runner traffic.

### Headline impact — per-tool critical coverage

`per_tool_mean_critical_coverage[rka_multi_hop_retrieval]` is the directly-affected metric:

| Run | rka_multi_hop_retrieval | divergences across 16 bundles |
|---|---|---|
| v2.5.0 baseline | **0.0000** (every call 422 → empty response) | 16 (one per scenario, all multi-hop) |
| v2.5.1 | **0.6833** | 0 multi-hop divergences (2 unrelated scaffold ones unchanged) |

Δ = **+0.6833** absolute. Other 10 tools were already 2xx in the baseline; their critical-coverage is identical between runs.

### Aggregate impact

Aggregate recall doesn't move (multi_hop was contributing zero entities; the other 10 tools already cleared the 0.85 floor). The one aggregate that nudges is `mean_ordering_score`, since multi-hop now adds critical IDs into the discovery-order combined ranking:

| Metric | v2.5.0 | v2.5.1 | Δ |
|---|---|---|---|
| mean_recall (critical) | 0.9583 | 0.9583 | +0.0000 |
| mean_expanded_recall | 0.8875 | 0.8875 | +0.0000 |
| mean_ordering_score | 0.2510 | 0.2533 | **+0.0022** |
| mean_breadth | 3.25 | 3.25 | +0.0000 |
| mean_efficiency | 0.0368 | 0.0362 | -0.0005 |

Efficiency dipping by 0.0005 is the expected reflex of multi-hop now populating the bundle with non-critical neighbors as well — the BFS-expand is doing what it should. Critical-recall floor still **PASSES** at 0.85.

### Reproducibility — v2.5.1 run

- **rka_head**: `b6b7d063f4d3` (from `feat/v2.5.1-multi-hop-fix`; merged to main as v2.5.1)
- **corpus_hash**: `sha256:b6b586d71d940f6bb430f90dd2fe6cb68501fdd7f1095a9ff68b5f72bb7f9e16` (unchanged from v2.5.0 — same 16 scenarios)
- **timestamp**: 2026-05-16T15:09:48Z
- **raw bundles**: `eval-harness/v2/results/raw_v2.5.1/`
- **metrics**: `eval-harness/v2/results/metrics_v2.5.1.json`
- **baseline preserved**: `eval-harness/v2/results/raw/` + `metrics.json` (v2.5.0)
- **runner command**: `python eval-harness/v2/runner.py --output-dir eval-harness/v2/results/raw_v2.5.1`
- **metrics command**: `python eval-harness/v2/metrics.py --raw-dir eval-harness/v2/results/raw_v2.5.1 --output eval-harness/v2/results/metrics_v2.5.1.json`

D2/D3/D4 remain candidates for Phase 3 missions; their findings carry forward unchanged from the v2.5.0 baseline section above.

---

## v2.5.2 addendum — D3 closed (Mission v2.5.2-D3)

**Mission**: `mis_01KRS1D8C0E2FP52D0P6JNB3SX`
**Fix-shape decision**: `dec_01KRS1ADPD4W6AW2X54MKVXMCR`
**Sequencing decision**: `dec_01KRRM5WKSSX7C3ZXZME0BMVQ9`
**Date**: 2026-05-16
**Container**: rebuilt from `feat/v2.5.2-cluster-parent-rq` HEAD (commits 4ccd168 + ba9dd8e + 597f1b0 + cc8a1ca + e2db9b7)

### Root cause (Brain 2026-05-16 code-trace)

Finding 3 (S7 + S9 cluster-anchored 0.67 recall in v2.5.0/v2.5.1) was caused by a missing edge type, not a centrality-weighting miscalibration. Empirical evidence: `evidence_clusters.research_question_id` is a FOREIGN KEY column populated for 101/101 clusters across all 9 projects, but `GraphService.multi_hop_retrieval` and `GraphService.get_ego_graph` only walk `entity_links` + `claim_edges`. The FK column was invisible to traversal — every cluster anchor missed its parent RQ.

### Fix shape (v2.5.2)

1. **Migration 023** (`rka/db/migrations/023_cluster_answers_links.sql`):
   - Extends the `entity_links.link_type` CHECK enum (from migration 021) to include `'answers'`. Uses migration 021's documented table-swap pattern (rename → CREATE new CHECK → INSERT SELECT → DROP old → recreate indexes).
   - Backfills one row per `evidence_clusters` with non-null FK: `source=cluster`, `target=decision`, `link_type='answers'`, `link_weight=1.0`. INSERT OR IGNORE against the project-scoped UNIQUE triple from migration 020 → idempotent on re-runs.
2. **DEFAULT_EDGE_WEIGHTS['answers'] = 1.0** in `rka/services/graph.py` (high-signal tier alongside `justified_by` / `motivated` / `evidence_for` / `derived_from`).
3. **ClusterService hook** in `rka/services/clusters.py` — `.create` and `.update` write the `answers` link via `BaseService.add_link(...)` whenever a non-null `research_question_id` is set. INSERT OR IGNORE semantics keep parity going forward without re-running migrations.

### Headline impact — per-scenario critical recall

| Scenario | Anchor | v2.5.0 / v2.5.1 | v2.5.2 | Δ |
|---|---|---|---|---|
| S7 `brain-contradiction-staleness-vs-validation` | cluster `ecl_01KP4PK7VPN8YFR50PSFXPGTQ0` | 0.667 | **1.000** | +0.333 |
| S9 `brain-paper-scaffold-session-start-section` | cluster `ecl_01KP4PJGJKE9Q7X1W2X6SJJVZ3` | 0.667 | **1.000** | +0.333 |
| Other 14 scenarios | — | 1.000 | 1.000 | +0.000 |

**Every scenario in the 16-scenario corpus now scores critical-recall = 1.0**, so aggregate `mean_recall (critical)` is **1.000** flat.

### Headline impact — per-tool critical coverage

The directly-affected tools:

| Tool | v2.5.0 | v2.5.1 | v2.5.2 | Δ(.1→.2) |
|---|---|---|---|---|
| `rka_get_ego_graph` | 0.333 | 0.333 | **0.778** | **+0.444** |
| `rka_multi_hop_retrieval` | 0.000 | 0.683 | **0.817** | +0.133 |

ego_graph moved well past the spec target (≥0.5). multi_hop's bonus comes from the new edges populating BFS-expand neighborhoods.

### Aggregate impact

| Metric | v2.5.0 | v2.5.1 | v2.5.2 | Δ(.1→.2) |
|---|---|---|---|---|
| mean_recall (critical) | 0.9583 | 0.9583 | **1.0000** | **+0.0417** |
| mean_expanded_recall | 0.8875 | 0.8875 | 0.9375 | +0.0500 |
| mean_ordering_score | 0.2510 | 0.2533 | 0.2628 | +0.0096 |
| mean_breadth | 3.25 | 3.25 | 3.25 | +0.0000 |
| mean_efficiency | 0.0368 | 0.0362 | 0.0372 | +0.0010 |

`mean_efficiency` ticked back up (+0.0010 from v2.5.1) because the new edges add directly-relevant entities to the bundle rather than tangential ones — the ordering also nudged.

### Production data — migration 023 row count

Verified live against `/data/rka.db` post-rebuild:

| Project | `entity_links WHERE link_type='answers'` count |
|---|---|
| `prj_01KKQM9JFG67GT5FGWTAHD9YE4` (Eval-v2 project) | **16** |
| `prj_01KMJQZXPZW0VZV5483QEJPNRN` | 28 |
| `prj_01KMJTPHW2KR7JR9SP3GRB9210` | 11 |
| `prj_01KMKREC3JKSJVPYR6KHEKWVN7` | 18 |
| `prj_01KN51HD73DSY9ZR9C56JYRNYZ` | 7 |
| `prj_01KP4D83G1F0TN209J258RZ0D6` | 6 |
| `prj_01KPB91SAX28Z2KFE5EHPSGR01` | 6 |
| `prj_01KPVB7NHJ0N33C024TD0E6CZ6` | 5 |
| `proj_default` | 4 |
| **Total** | **101** |

Invariant verified: total equals `evidence_clusters WHERE research_question_id IS NOT NULL` count (101). The other 8 projects (85 clusters total) get the same fix collaterally — relevant if any of them are added to the Eval-v2 corpus later.

### Reproducibility — v2.5.2 run

- **rka_head**: e2db9b7 (`feat/v2.5.2-cluster-parent-rq` pre-merge)
- **corpus_hash**: `sha256:b6b586d71d940f6bb430f90dd2fe6cb68501fdd7f1095a9ff68b5f72bb7f9e16` (unchanged from v2.5.0 — same 16 scenarios)
- **raw bundles**: `eval-harness/v2/results/raw_v2.5.2/`
- **metrics**: `eval-harness/v2/results/metrics_v2.5.2.json`
- **baselines preserved**: v2.5.0 at `results/raw/` + `metrics.json`; v2.5.1 at `results/raw_v2.5.1/` + `metrics_v2.5.1.json`
- **runner command**: `python eval-harness/v2/runner.py --output-dir eval-harness/v2/results/raw_v2.5.2`
- **metrics command**: `python eval-harness/v2/metrics.py --raw-dir eval-harness/v2/results/raw_v2.5.2 --output eval-harness/v2/results/metrics_v2.5.2.json`

### Phase 3 status

D1 (v2.5.1) + D3 (v2.5.2) closed. Remaining Phase-3 hooks unchanged:
- **D2** — importance-weight / centrality / recency-boost coefficient sweep (Finding 1)
- **D4** — bundle-narrowing vs corpus-expansion under 0.037 efficiency (Finding 2)

Note that the aggregate `mean_recall (critical) = 1.000` "ceiling" outcome means D2/D4 work shifts the success signal: recall is no longer the place to look for improvement. `mean_ordering_score` (0.263) and `mean_efficiency` (0.037) are now the headline gaps. Either next mission may want to consider re-grading the corpus for harder critical-recall cases (separate decision; out of v2.5.2 scope).
