# RKA retrieval-quality eval harness

Mission: `mis_01KRKJ9G20EM5XMA147JTKQCFF` (eval-harness)
Branch: `feat/eval-harness` from `main@d2a9388`
Motivating decision: `dec_01KRKE6ERDPQTFQS6ZGY9A3CK0` (orchestrator Option B pilot)

A 2×2 factorial evaluation of RKA retrieval quality:

|                    | FTS-only            | FTS + semantic-hybrid     |
|--------------------|---------------------|----------------------------|
| **current OR**     | `current_or.yaml`   | `current_or_hybrid.yaml`   |
| **AND-fix**        | `and_fix.yaml`      | `and_fix_hybrid.yaml`      |

Run against a ~30–35-query labeled corpus (~20 synthetic + ~10–15 replayed from session history). Each unique result graded 0/1/2 by the PI ONCE; rating reused across configs that returned the same result. Metrics: **Precision@10, MRR, NDCG@10**. Output: per-config metrics tables + ~2-page Brain narrative with actionable recommendations.

## Status

This directory currently holds **Mode-C scaffolding only** (see the parallel-work clearance from PI 2026-05-14):

- ✓ `eval_harness/replay_extractor.py` — scans recent journal entries for retrieval invocations, surfaces candidate queries with original context.
- ✓ Directory tree + 4 empty config YAML placeholders.
- ✗ T2 implementations (`runner.py`, `metrics.py`, `labeler.py`, configs, tests) — held until the manual-first-validation observation journal lands.
- ✗ T3 eval run, T4 PI labeling, T5 metrics, T6 narrative report, T7 archive — downstream of T2.

The upfront Backbrief is filed AFTER the manual-first-validation observation journal lands (tagged `["manual-first-validation", "agentic-pilot", "conductor-rhythm"]`) so rhythm observations fold into the Executor's plan.

## Layout (when complete)

```
eval-harness/
├── README.md                       ← this file
├── corpus/
│   ├── synthetic_queries.jsonl     ← T1: Brain + PI co-author (~20)
│   ├── replayed_queries.jsonl      ← T1: replay_extractor + curation (~10–15)
│   └── queries.jsonl               ← union; canonical eval corpus
├── configs/
│   ├── current_or.yaml             ← baseline: OR sanitize + FTS-only
│   ├── and_fix.yaml                ← AND sanitize + FTS-only
│   ├── current_or_hybrid.yaml      ← OR sanitize + FTS + semantic
│   └── and_fix_hybrid.yaml         ← AND sanitize + FTS + semantic
├── eval_harness/                   ← runner package
│   ├── __init__.py
│   ├── replay_extractor.py         ← Mode C ✓
│   ├── runner.py                   ← T2
│   ├── metrics.py                  ← T2
│   └── labeler.py                  ← T2 (with dedup logic)
├── results/
│   ├── raw/                        ← T3 output: per-config × per-query result lists
│   ├── labels/                     ← T4 output: PI graded 0/1/2 ratings
│   └── metrics.json                ← T5 output: P@10, MRR, NDCG@10 per config
├── report.md                       ← T6: Brain narrative + recommendations
└── tests/                          ← T2: unit + integration tests
```

## Permitted `rka/` change

Exactly one (mission spec ratified): `RKA_FTS_QUERY_MODE` env var on `_sanitize_fts_query` in `rka/services/`. Default `or` preserves current behavior; setting `and` applies the Mission A revision-report fix. The eval toggles per config invocation.

**Bookkeeper invariant**: `git diff main -- rka/services/worker.py` must remain empty across every commit on this branch.

## Forward-compatibility note

The graded 0/1/2 labels live in `results/labels/` and key on `(query, unique_result_id)`, not on config name. Future eval extensions (configurations D–G: multi-hop, top_k sweep, entity_types, weight sweep) can reuse the same labeled corpus without re-labeling — any new config returning the same result set composes against the existing ratings.
