# Retrieval-Quality Evaluation Report — v2.3.5 RKA

**Mission**: `mis_01KRKJ9G20EM5XMA147JTKQCFF`
**Date**: 2026-05-14
**Author**: Brain (this session, post-rehearsal)
**Status**: T6 narrative complete; T7 archive pending

---

## Recommendation thresholds (declared upfront per Brain skill rule #9a)

- **NDCG@10 delta ≥7.5% relative** = clear winner → recommend adopt as default
- **2.5–7.5%** = ambiguous → chain into `brain_generate_decision_slate` for PI ratification (skill rule #9b)
- **<2.5%** = no change → status quo holds
- **Metric-divergence rule (#14)**: if NDCG@10 is ambiguous but MRR or P@10 clearly ≥7.5%, the divergence IS the headline (and vice versa)

---

## Headline findings

### Finding 1: AND-fix has **zero effect on FTS-only retrieval** — DO NOT APPLY

| Comparison | P@10 Δ | MRR Δ | NDCG@10 Δ | Verdict |
|---|---|---|---|---|
| current_or vs and_fix (FTS-only) | 0.0000 (0%) | 0.0000 (0%) | 0.0000 (0%) | **No change** |
| current_or_hybrid vs and_fix_hybrid | 0.0000 (0%) | 0.0000 (0%) | +0.0050 (+0.78%) | **No change** |

**Both deltas are well below the <2.5% threshold across all three metrics.** The AND-fix's predicted effect (suppressing OR-over-recall on noise-friendly queries) did not materialize in this corpus.

**Hypothesis on why**: FTS5's default `MATCH` query parser may already apply implicit AND semantics, or the corpus's query patterns don't have the specific token-overlap structure that the AND-fix targets. Q19 (`distributed consensus algorithm Paxos Raft`), specifically designed as the AND-vs-OR diagnostic, returned only 1 self-referential hit (the rehearsal observations journal that lists Q19's query verbatim) — meaning OR didn't over-recall, so there was nothing for AND to suppress.

**Recommendation**: **Do NOT apply the AND-fix as default.** Leave `_sanitize_fts_query` with current OR semantics. The fix remains available via `RKA_FTS_QUERY_MODE=and` env var for future experimentation if a workload emerges that benefits from it.

### Finding 2: Semantic-hybrid retrieval improves NDCG@10 clearly; P@10/MRR gains are smaller — **METRIC DIVERGENCE IS THE HEADLINE**

| Comparison | P@10 Δ | MRR Δ | NDCG@10 Δ |
|---|---|---|---|
| FTS-only → semantic-hybrid (either OR or AND) | +0.0097 (+3.54%) | +0.0430 (+6.78%) | **+0.0524 to +0.0574 (+8.97% to +9.82%)** |

**NDCG@10 clears the 7.5% clear-winner threshold; P@10 and MRR sit in the 2.5–7.5% ambiguous band.**

Per the metric-divergence rule (#14), **this divergence is the headline finding**, not the average. What it means substantively:

- **Semantic-hybrid surfaces the same relevant results into the top-10** (P@10 mostly unchanged) and **finds the first relevant result at similar rank** (MRR similar) **but ranks them better within the top-10** (NDCG@10 improves clearly).
- This is consistent with semantic-hybrid acting as a **re-ranking layer** on top of FTS, where embedding similarity boosts the most-relevant items to higher ranks within the top-N rather than expanding what enters the top-N.

**Recommendation**: **CONDITIONAL YES on defaulting `RKA_EMBEDDINGS_ENABLED=true`.** Semantic-hybrid is a clear winner on ranking quality (NDCG@10). The case is strongest when retrieval consumers care about *which* result ranks first (Brain's context engine + research-map use the ranking signal), and weakest when they just need "is it in top-10" (any FTS-driven feature).

**Caveat for production rollout**: enabling embeddings has operational costs (FastEmbed model bundle size, GPU/CPU latency on backfill, vec table maintenance). This eval doesn't measure those costs — it only measures retrieval quality. PI should weigh the +9% NDCG@10 improvement against operational overhead before flipping the default.

---

## Per-axis breakdown

### AND-fix axis (OR vs AND `_sanitize_fts_query`)

**Outcome**: null finding. AND-fix produced identical metrics on FTS-only and a 0.78% NDCG@10 improvement only when combined with semantic-hybrid (still below the 2.5% threshold).

**Per-query illustrative case**: Q19 `distributed consensus algorithm Paxos Raft`. Designed explicitly to test OR-over-recall. With OR semantics, the expected failure mode was over-recall of unrelated content sharing single tokens (e.g., "consensus failure" detector entries). The eval shows OR returned only 1 result (the self-referential rehearsal observations journal). The corpus may not contain enough token-rich noise to exercise the OR failure mode the AND-fix is designed to cure.

### Semantic-hybrid axis (FTS-only vs FTS+semantic)

**Outcome**: clear winner on NDCG@10 (+8.97% to +9.82%); ambiguous on P@10 (+3.54%) and MRR (+6.78%).

**Per-query illustrative case**: Q2 `decisions about agentic workflow architecture`. Synthetic, designed as semantic-favored — the canonical decision (dec_01KRKE6ERDPQTFQS6ZGY9A3CK0) doesn't literally contain "agentic" or "architecture". Both FTS-only and semantic-hybrid returned the decision; semantic-hybrid ranked it higher.

---

## Notable retrieval failures (separate from the AND-fix and semantic-hybrid signal)

Four queries returned **NO canonical results** across any config. These are diagnostic for RKA's retrieval surface rather than for this specific 2×2 comparison:

1. **Q "decisions made today"**: 3 results returned, all irrelevant (paper-typesetting missions + Brain audit). The expected `dec_01KRKE6ERDPQTFQS6ZGY9A3CK0` and `dec_01KR7BJRHSC0G3TX6PSKY2X0V2` (both decisions from today) were not returned by any config. **Query-time temporal language ("today") is not interpreted** — RKA's retrieval treats "today" as a literal token rather than a recency filter signal. Worth Brain investigation: should the v2.3.5 recency boost combine with explicit-temporal query interpretation?

2. **Q "what's in the workflow improvements research question"**: 6 results, all irrelevant. The expected 3 clusters under `dec_01KP4P53MSKY3GKEXZKG9JMFKX` were not retrieved. **Structural-traversal queries fail** — "what's in" as a structural cue isn't understood; queries that ask for children/parents/siblings of an entity need a different retrieval path than FTS or semantic over content.

3. **Q "evidence clusters about staleness detection"**: 1 result (smoke test mission), irrelevant. Expected `ecl_01KP4PK7VPN8YFR50PSFXPGTQ0` not retrieved. **Cluster-level retrieval is weak** — clusters have rich synthesis text but may be under-weighted in the retrieval scoring.

4. **Q "PI directives this week about agentic branch and orchestrator"**: 2 results (design note + Brain synthesis), both topically adjacent but **neither is a PI directive**. The 3 expected PI-directive journals (`jrn_01KRKJTNB3MFB2H1SGD6T9E0Z0`, `jrn_01KRKGRXYB6A22JVKCS4R45JBP`, `jrn_01KR4JQTZNREMQV88YRBTT2RW4`) were not retrieved. **`source='pi'` filtering not happening** — actor-anchored queries fall back to FTS over content, ignoring entity metadata.

These four findings each merit a separate follow-up investigation. They're stronger signal for "what RKA retrieval needs next" than the AND-vs-OR comparison this eval was built around.

---

## Methodological limitations

Per Brain skill rule #9d (caveats mandatory in narrative reports):

1. **Single-rater eval** with a **methodological shift mid-mission**: 7 ratings by PI (out of 137), 130 by Brain assistant (this session) following Option A workflow per `jrn_01KRKGRXYB6A22JVKCS4R45JBP` extension and the labeling-fatigue rhythm observation (#16). Ratings reflect Brain's content-relevance read filtered by Mission C-style "production user preferences" inference, not PI's first-principles judgments on the full corpus.

2. **31-query corpus** is **directional, not significance-tested** (Q4 scope lock). Findings are reported as deltas, not as p-value-defensible claims. With ~30 queries, even a 5-point NDCG@10 delta is roughly within the noise margin of bootstrap confidence intervals — but Q4 rejected adding statistical analysis as scope creep.

3. **Q19 self-reference artifact**: The negative-example query `distributed consensus algorithm Paxos Raft` returned 1 result that is the rehearsal observations journal itself (which contains the query string in its corpus enumeration). This is self-referential and inflates apparent OR over-recall slightly. Brain rated 0 for the pair, so the artifact doesn't affect metrics directly, but the diagnostic finding (OR didn't over-recall on this corpus) should be tempered by this caveat.

4. **`vec_claims` was backfilled with qwen3-embedding-8b-dwq via LM Studio** (per PI directive 2026-05-14) for the eval-run duration, then container reverted to `RKA_EMBEDDINGS_ENABLED=false` defaults. The semantic-hybrid configs tested in this eval do NOT reflect the production-default state (FastEmbed nomic-embed-text-v1.5). The 9% NDCG@10 improvement attribution is to "semantic-hybrid with qwen3-8B" specifically — switching the production default to FastEmbed nomic would require a separate verification run before claiming the same delta holds. Recommendation #2 above (default embeddings on) is therefore **conditional on the embedding-backend choice**.

5. **Mode-C parallel scaffold context**: Mission ran in Mode C with Executor parallel work + PI+Brain validation rehearsal. The eval's procedural integrity is intact (PI verified raw results + dedup before labeling started), but rehearsal observations are folded into both this report and the orchestrator-pilot signal at `jrn_01KRKN3QD9EPTFHWRSSGQ8X7MY`.

---

## Forward-looking recommendations

1. **Do NOT apply the AND-fix as default** (Recommendation 1). Leave `RKA_FTS_QUERY_MODE` env-var available as opt-in.
2. **Conditionally apply `RKA_EMBEDDINGS_ENABLED=true` default**, with the operational-cost caveat (Recommendation 2). PI ratifies based on whether the +9% NDCG@10 improvement on ranking quality justifies the FastEmbed/qwen3 bundle + backfill cost. **Decision recommended: bring this back to PI as a separate `brain_generate_decision_slate` after this report lands** — it's a deployment decision, not just a metric decision.
3. **Open follow-up investigations** for the four retrieval failure modes surfaced:
   - Query-time temporal language ("today", "this week") interpretation
   - Structural-traversal queries ("what's in [RQ name]")
   - Cluster-level retrieval weighting
   - Actor-anchored queries (`source='pi'` filtering)
4. **Re-run this eval with the production embedding backend** (FastEmbed nomic) before committing to embedding-on-by-default. The current eval's qwen3 results may not transfer.
5. **Expand corpus** for any future eval that needs significance-test rigor. 100+ queries with bootstrap CIs would resolve the ambiguity in the 2.5–7.5% bands for P@10 and MRR.

---

## Decision-slate hook

Per Brain skill rule #9b: this report does not autoship a final decision on the embedding-default question. The metric divergence (NDCG@10 clear winner, P@10/MRR ambiguous) plus the qwen3-vs-FastEmbed backend uncertainty makes this a candidate for a follow-up Brain decision_options slate covering:

- (A) Default embeddings on with FastEmbed nomic
- (B) Default embeddings on with qwen3-8B (requires LM Studio dependency)
- (C) Leave embeddings off; expose explicit `--semantic` flag to retrieval CLI tools for opt-in
- (D) Re-run eval on production FastEmbed before deciding

PI ratifies. Brain recommends C with later re-eval on FastEmbed (D) as a follow-up — preserves backwards-compatibility while not blocking the FastEmbed-vs-qwen3 question.

---

## Reproducibility provenance (per Brain skill rule #8a)

- **corpus_hash**: `sha256:72e51af67ed3df16f3f41e961a2a6c4bac5fc4dd23ef0885cdf285d7a61edf54`
- **labels_hash**: `sha256:40ac5b6a6d16599c45e464a9e351261d13d3383ef7d710680bcca06709900a8a`
- **rka_head**: `c8d83f3`
- **eval_run_timestamp**: `2026-05-14T19:04:45Z`
- **config_fingerprints**: see `results/metrics.json`
- **embedding_backend_for_hybrid_configs**: `qwen3-embedding-8b-dwq` via LM Studio at `http://host.docker.internal:1234`

