# Eval-v3 experiment handover — local session notes

**Written**: 2026-08-23, by the remote session that built this suite.
**Branch**: `claude/rka-performance-eval-mtyuqz` (draft PR #88, based on `main@3fb0cd7`).
**State**: all four eval components implemented and hermetically tested (155
eval-harness tests passing); **no real numbers exist yet** — every result in
`results/` directories is absent or placeholder. Your job is the experiment
runs against the live local RKA instance and the real knowledge projects.

## Goal (PI's framing, verbatim intent)

Make research with AI agents easier to manage; ensure important information —
**directives and evidence — does not fade away when context grows**; log
complex decisions and rationales and **retrieve them with related evidence,
literature, directives via back-tracing so research does not get lost after
significant pivoting**; and show the saved evidence/knowledge graph helps
draft better manuscripts. The paper (`docs/paper/RKA-paper.pdf` §7) is
high-level background, not a constraint.

## What exists (read `eval-harness/v3/README.md` first)

| Dir | Question | Runner | Needs live RKA? | Needs LLM? |
|---|---|---|---|---|
| `self_study/` | record health (§7.1 metrics) | `compute_metrics.py` | no — DB snapshot | no |
| `tracing/` | decision back-trace + pivot survival | `runner.py` | yes (:9712) | no |
| `retention/` | fade curve: rka vs full-context vs RAG | `runner.py` | yes (rka arm) | yes |
| `writer/` | draft grounding + evidence use A/B | `score_drafts.py` | via verify_provenance | drafting arms |

Each dir has its own `schema.md`/`protocol.md`/`README.md` with exact CLI
invocations and corpus formats. Example corpora contain **synthetic ids** —
replace with real ones before quoting any number.

## Suggested order of work

### 0. Preflight
- `git fetch && git checkout claude/rka-performance-eval-mtyuqz`
- `docker compose up -d` then check `curl localhost:9712/api/health`
- `pip install -e ".[embeddings,llm,academic,workspace,dev]"` in a venv (or use existing), then
  `python -m pytest eval-harness/v3/tests/ -q` — should be 34 passed.
- List the local projects: `curl localhost:9712/api/projects` — pick which
  knowledge projects to evaluate (per the PI there are several running ones).

### 1. Self-study (cheap, do first, per project)
```bash
docker compose exec rka sqlite3 /data/rka.db ".backup /data/rka-snapshot-$(date +%F).db"
docker compose cp rka:/data/rka-snapshot-$(date +%F).db eval-harness/v3/self_study/snapshots/
python eval-harness/v3/self_study/compute_metrics.py \
  --db eval-harness/v3/self_study/snapshots/rka-snapshot-<date>.db \
  --out eval-harness/v3/self_study/results/metrics.json \
  --csv eval-harness/v3/self_study/results/debt_trajectory.csv
# repeat with --project prj_... for each project of interest
```
Snapshots are `*.db` → already gitignored. Commit the `metrics.json` outputs.

### 2. Tracing corpus + run (the back-tracing question)
Author `eval-harness/v3/tracing/scenarios.jsonl` (format: `tracing/schema.md`)
from the real graph. Efficient method: query the snapshot for decision
candidates —
```sql
SELECT id, question, chosen, status, superseded_by FROM decisions
WHERE rationale IS NOT NULL AND (status = 'superseded' OR superseded_by IS NOT NULL
       OR length(rationale) > 200);
```
— draft scenarios mechanically (walk `entity_links` from each anchor for
candidate expected-trace entries), then have the PI ratify/prune each
scenario's `expected_trace` and mark pivots. 10–15 scenarios, several with
`pivot` blocks. Then:
```bash
python eval-harness/v3/tracing/runner.py \
  --corpus eval-harness/v3/tracing/scenarios.jsonl \
  --rka-url http://localhost:9712 [--project prj_...] \
  --out-dir eval-harness/v3/tracing/results
```
**Expect trouble here — that's the point.** Prior evals found: multi-hop
returned HTTP 422 everywhere (v2.5.x), ego-graph critical coverage 0.333,
cluster→parent traversal weak. Divergences land in the output instead of
crashing; a 422 today means the bug survived and is worth filing/fixing.

### 3. Retention (the fade curve — headline result)
- Create a **disposable project**; ingest each scenario's seeded directives as
  `pi_instruction`/`directive` journal entries and evidence as findings/claims
  (record the real entity ids back into `expected_citations`).
- Author `retention/scenarios.jsonl` (format: `retention/schema.md`): filler
  must be topically adjacent to the seeds or the RAG baseline wins too easily;
  probe at ~10k/50k/150k token distances.
- `export RKA_LLM_MODEL=...` (litellm id; same model serves all arms), then:
```bash
python eval-harness/v3/retention/runner.py \
  --corpus eval-harness/v3/retention/scenarios.jsonl \
  --arms full_context,rag,rka \
  --rka-url http://localhost:9712 --project prj_<disposable> \
  --out-dir eval-harness/v3/retention/results
```
Headline: `metrics.json` → `curve.by_arm` — rka flat vs baselines decaying,
if the thesis holds. Note: real fade needs real distances — canned filler is
fine but make it long.

### 4. Writer A/B (grounding + evidence use)
Per `writer/protocol.md`: pick 2–3 sections from a real project with a claim
spine; produce Arm A (Writer skill + live RKA), Arm B (same model, flat dump
of the same source material), optional Arm C (brief only). Then:
```bash
python rka/skills/writer/scripts/verify_provenance.py drafts/A.tex \
  --project prj_... --output reports/A.json     # repeat per arm
python eval-harness/v3/writer/score_drafts.py \
  --scenario scenario.json --out eval-harness/v3/writer/results/comparison.json
```
The `expected_evidence` set per scenario should be the spine's bindings for
that section, PI-ratified. `--support-backend llm` gives a better SUPPORTED
check than the lexical default.

## Gotchas (learned building this)

- **`writing/` is gitignored** repo-wide (local scratch) — that's why the
  writer eval lives in `writer/`. Don't create eval files under any
  `writing/` path or `storage/`; check `git status` shows your outputs.
- `*.db` is gitignored → snapshots can't leak; **but `results/*.json` should
  be committed** — that's the deliverable.
- Code changes under `rka/` need `docker compose up -d --build` (restart is
  NOT enough — see CLAUDE.md); the eval runners themselves talk REST only and
  need no rebuild.
- The self-study coverage numbers use a depth-3 **undirected** entity_links
  walk (documented limitation in `self_study/README.md`) — tighten before
  quoting in the paper if reviewers would press.
- CI collects `eval-harness/` tests in the main pytest run — keep new corpus
  files parseable (tests validate the example corpora).
- PR #88 is a **draft** on purpose: land experiment corpora + results on this
  same branch, then promote/merge when the PI is satisfied.

## Reporting back

The remote session that wrote this is watching PR #88 (CI + comments). When
runs produce `metrics.json` files, commit them to this branch; interpretation
and the results narrative (paper §7 or README claims) can be done in either
session. Open bugs discovered by the runners (e.g. a surviving multi-hop 422)
deserve their own issues, not silent fixes inside this PR.
