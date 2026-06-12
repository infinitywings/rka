# Addendum — the AND-vs-OR question, finally tested (2026-06-11)

**Context**: Eval-v1 (`report.md`, 2026-05-14) reported a null finding for the
AND-fix: "AND-fix has zero effect on FTS-only retrieval." The OR-semantics fix
(PR #34, `56c92d9`) revealed why: `_sanitize_fts_query`'s default `or` mode
space-joined quoted terms, and FTS5's implicit operator for space-separated
terms is AND — **the "OR" baseline was AND all along**, so Eval-v1 compared
AND against AND. The mode comparison was never actually run.

## What was measured after the fix

Live corpus: `rka_development` pack (2026-06-11 export; 1,621 journal / 140
decisions / 154 literature / 113 missions / 2,663 links), imported into RKA
at this branch, FTS-only (no embeddings available in the eval environment).

### Query-robustness probes (pre-fix vs post-fix, same corpus)

| Probe | AND (pre-fix "or" mode) | OR (fixed) |
|---|---|---|
| 7-term descriptive query, fts_journal rows matched | 1 | 499 (bm25-ranked) |
| 40 ground-truthed NL questions, search recall@10 | 0.000 | functional |
| 40 questions, stopword-stripped keyword queries, recall@10 | 0.026 | functional |

### Report-scope cohort recall (3 tag-cohort scopes, paragraph queries)

| Surface | AND (pre-fix) | OR only | OR + stopwords + tag-RRF + seed protection |
|---|---|---|---|
| `POST /api/search` (one-shot paragraph) | 0.00 | 0.32 | **0.45** |
| `POST /api/graph/multi-hop` (one-shot paragraph) | 0.00 | 0.16 | **0.40** |
| `collect_report_context` (with angle queries) | n/a | 0.68 | **0.84** |

(The 0.84 single-call mean exceeds the 30–59-call agent-loop baseline of
0.80 measured in eval-v3.)

## Verdict on the original Eval-v1 question

- **AND as default is untenable**: it fails closed on any query over ~4
  words, which silently crippled every search-seeded consumer
  (`/api/context` topic path, `/api/graph/multi-hop`).
- **OR (with bm25 ranking + stopword stripping) is the correct default.**
  `RKA_FTS_QUERY_MODE=and` remains available for precision-first workloads.

## What still requires a production re-run

Eval-v1's PI-labeled corpus covers the result lists produced by the May runs;
re-running its 2×2 (query-mode × FTS/hybrid) with the **real** OR mode and
the production FastEmbed backend will produce new result lists requiring
incremental labeling. The hybrid (semantic) axis could not be re-measured in
this environment (network policy blocks embedding-model downloads); the
+8.97–9.82% NDCG@10 hybrid finding from Eval-v1 is unaffected by the OR fix
in its hybrid-vs-FTS comparison, but its absolute numbers were computed on
an AND-only keyword axis and will shift under OR.
