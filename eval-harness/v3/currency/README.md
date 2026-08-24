# Eval-v3 Track 5 — pivot currency ("does the agent chase its own tail?")

Track 2 asks: *given the right decision, can the graph reconstruct it and
surface its replacement?* Answer: yes, 14/14 pivots, 0 stale-only.

This track asks the operational question that actually bites during research:

> A researcher remembers the **old** framing and asks about it. Does the agent
> get the decision in force **now**, or the superseded one — and can it even
> tell which is which?

For every supersede chain in a project, the runner issues the *old* decision's
question as the query (the realistic "I remember we decided X" case, and the
one most favourable to the stale record), then measures two surfaces:

- **entry** — `/api/search`: rank of superseded vs current, and whether any
  staleness signal is present in the payload at all.
- **graph** — `/api/graph/ego` at depth 2, seeded from whatever the entry
  surface actually returned (not from an oracle anchor): is the current
  decision reachable, and is the stale one marked?

Verdicts: `current_first` | `stale_first` | `stale_only` | `neither`.

Headline metric — **`blind_stale_exposure`**: the fraction of pivots where an
agent doing entry-retrieval alone is handed the superseded decision with no
signal that it has been replaced.

No LLM required; pure retrieval, so it is fast and fully reproducible.

```bash
python eval-harness/v3/currency/runner.py \
  --db eval-harness/v3/self_study/snapshots/<snapshot>.db \
  --project prj_... --rka-url http://localhost:9712 \
  --out eval-harness/v3/currency/results/<name>.json
```

Note: a project with 0 % embedding coverage measures a keyword-only index —
check coverage before interpreting (see RESULTS.md).
