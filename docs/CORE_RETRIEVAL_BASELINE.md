# RKA Core retrieval baseline

This benchmark is the deterministic release gate for RKA Core retrieval. It
measures whether a clean Core instance can recover the right records and their
linked evidence without leaking another project's records or treating retired
knowledge as current.

It is intentionally small. It is not an embedding-model comparison, a live
database audit, or a Writer-quality evaluation.

## What is measured

The runner plants the fixed synthetic FUOTA research corpus in a temporary
database and exercises the public REST API through an in-process ASGI
transport. The task set contains two researcher-style queries for each direct
entity type:

- journal;
- claim;
- decision;
- literature.

A separate explicit-seed neighborhood task must recover the current signature
decision, informing literature, motivated mission, result journal, derived
claim, and their four provenance edges. Graph nodes must carry the canonical
currentness projection produced by the entity resolver.

The same run also checks:

- an overlapping-vocabulary shadow project never appears in direct or graph
  results;
- even a malformed edge stamped as local but pointing to a shadow-project
  entity cannot expose that entity ID or the dangling edge;
- a foreign explicit graph anchor resolves to an empty result rather than a
  plausible-looking placeholder;
- the current decision ranks no lower than its superseded predecessor and the
  predecessor carries a non-null supersession signal;
- an unfiltered read first confirms both journal revisions and both claims,
  including their stored lifecycle state; then `hide_superseded=true` removes
  the superseded journal and `stale=false` removes the stale claim while each
  current replacement remains visible.

Only IDs in formal search-result or graph-node fields count as retrieved.
Identifiers merely mentioned in snippets, labels, or edge text do not improve
recall.

For claims, the stored signals named `stale` and `staleness` are not aliases.
`stale=true` is a hard structural invalidation, such as a superseded source.
`staleness` is the freshness-review state; `green` means there is no open
freshness warning and does not make a structurally stale claim current. Clients
must use the entity resolver's derived `currentness` result when deciding
whether knowledge is current.

## Gate and thresholds

Quality and isolation are strict:

| Check | Threshold |
|---|---:|
| Direct types / linked tasks present | all 4 types / at least 1 task |
| Recall@10 for every direct task | 1.00 |
| Linked-neighborhood node recall | 1.00 |
| Linked-neighborhood edge recall | 1.00 |
| Currentness coverage for expected linked nodes | 1.00 |
| Foreign-project hits | 0 |
| Foreign-anchor placeholder nodes | 0 |
| Current/superseded and stale projections | all pass |

Latency is a broad regression tripwire, not a performance SLA. Corpus setup,
migrations, and FTS rebuilding are excluded from timing. After one warm-up,
the default run records seven requests per task and requires:

| Timed surface | p95 ceiling |
|---|---:|
| Direct search | 500 ms |
| Explicit-seed linked neighborhood | 1,000 ms |

These ceilings are deliberately far above the recorded local baseline. They
are intended to detect accidental external-service calls, severe N+1 behavior,
or similar regressions without making CI depend on runner speed. Exact p50,
p95, and maximum values remain observational.

The Core pytest integration test uses three repetitions to keep routine CI
bounded while exercising the same task coverage and hard gates. The committed
standalone baseline uses the seven-repetition protocol above.

## Reproduce

From a clean development environment:

```bash
python eval-harness/v3/core_retrieval/runner.py \
  --check \
  --repeats 7 \
  --warmups 1 \
  --output /tmp/rka-core-retrieval.json
```

The unmarked integration test is included automatically in the Core pytest
profile:

```bash
python -m pytest -q tests/test_synthetic_harness.py
```

The committed result under `eval-harness/v3/core_retrieval/results/` records
the source commit, corpus-source SHA-256, Python, SQLite, operating system,
architecture, transport, task protocol, thresholds, and measured values.

## Interpretation boundary

This gate uses keyword retrieval with embeddings and server-side LLM features
disabled. It therefore supports claims about deterministic Core storage,
project-scoped FTS/tag retrieval, graph expansion, lifecycle signals, and
in-process latency. It does not characterize semantic-retrieval quality,
Docker/network latency, LM Studio, real-project data distributions, or human
research-story reconstruction. Those remain separate diagnostic profiles and
cannot replace this release gate.
