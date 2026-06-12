# Synthetic-corpus stress harness

A self-grading retrieval/integrity stress test: `corpus.py` plants a fully
synthetic research arc ("lorawan_fw_security" — LoRaWAN smart-meter FUOTA
security, zero vocabulary overlap with rka_development) through the public
REST API, recording ground truth as it writes. The pytest module
`tests/test_synthetic_harness.py` then grades search, graph traversal,
report-context collection, and the session-context bundle mechanically
against that planted ground truth — no agents, no LLM, no live server.

Ported from `/tmp/rka-eval/synth/{generate.py,stress_test.py}` (eval-v3,
2026-06-12). The generator is transport-agnostic: `generate(post, put)`
takes two async callables, so the corpus can be planted through an
in-process ASGI client (CI) or a live server alike.

## What it plants

- needles (unique-fact entries with known answers, incl. unicode and
  FTS-hostile ones) + a near-miss distractor
- 2 supersede chains (decision + journal) — current-vs-overturned
- 1 contradiction (claim_edges `contradicts`)
- 1 retraction + corrected note
- known provenance chains (lit -> dec -> mis -> jrn; RQ -> cluster; hub note)
- tag cohorts incl. the curated `writeup-arc` report cohort
- an oversized log entry (~10k chars) and 30 low-signal filler notes

## What it catches

Regression classes this harness's ancestor surfaced on 2026-06-11/12
(eval-v3):

- **FTS OR/AND bug** — `_sanitize_fts_query` space-join made "or" mode
  behave as AND; multi-word natural-language queries failed closed.
- **Missing supersedes edges** — supersession recorded only in columns,
  invisible to graph traversal (ego/multi-hop/report-context).
- **Pack re-keying rot** — exported/re-imported packs leaking source-project
  IDs in prose (covered by the ancestor's round-trip test; not in the CI
  port, which has a single in-process app).
- **Writer trust gaps** — context bundles burying pinned PI directives
  (positions #58/#60 on a live corpus), report-context recall far below
  the curated cohort.

## How to run

```bash
# CI-safe, in-process (no Docker, no server):
pytest tests/test_synthetic_harness.py -q

# or inside the dev container:
docker compose exec rka pytest tests/test_synthetic_harness.py -q
```

The test builds a throwaway app via `create_app(RKAConfig(...))` with LLM and
embeddings disabled (FTS + tag + LIKE retrieval only), generates the corpus
once per module, runs `reindex_fts`, then asserts against the ground truth.
