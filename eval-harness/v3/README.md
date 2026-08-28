# Eval-v3 — RKA performance & research-quality evaluation suite

Plan: [`docs/superpowers/plans/2026-08-23-rka-research-quality-evaluation-plan.md`](../../docs/superpowers/plans/2026-08-23-rka-research-quality-evaluation-plan.md),
recentered on the project's operational goal: **make AI-agent research easier
to manage, and make sure important information — directives and evidence —
does not fade away as context grows.**

| Component | Question | Entry point |
|---|---|---|
| [`core_retrieval/`](core_retrieval/) | Does provider-free Core retrieval recover journals, claims, decisions, literature, and linked evidence within a stable latency tripwire while preserving project and currency boundaries? | `runner.py --check --output …` |
| [`self_study/`](self_study/README.md) | Is the record itself healthy? Provenance coverage, research-debt trajectory, mission-cycle friction, pipeline-stage flow. | `compute_metrics.py --db <snapshot>` |
| [`tracing/`](tracing/schema.md) | Can complex decisions be retrieved as complete, current research stories — rationale, evidence, literature, execution, results, and pivots? | `runner.py --corpus … --rka-url …`; `score_story_responses.py --corpus … --run-id … --responses … --traces …` |
| [`retention/`](retention/schema.md) | Do planted directives and evidence survive context growth? Retention curve per arm: RKA retrieval vs plain long-context vs naive RAG. | `runner.py --corpus … --arms …` |
| [`writer/`](writer/protocol.md) | Do the saved evidence and knowledge graph produce better-grounded manuscript drafts? Grounding + evidence-utilization deltas vs a flat-dump baseline. | `score_drafts.py --scenario …` |

## Suggested run order

1. **core_retrieval** in a clean temporary database — the Core release gate;
   it does not require Docker, an embedding provider, an LLM, or Writer.
2. **self_study** against a DB snapshot — establishes whether the store is a
   trustworthy substrate before measuring retrieval over it.
3. **tracing** against the live instance with a PI-ratified scenario corpus —
   its per-relation recall findings tell the retention benchmark which paths
   to stress.
4. **retention** with a real completer (`RKA_LLM_MODEL`) — the headline
   fade-curve result.
5. **writer** A/B drafting runs, audited with
   `rka/skills/writer/scripts/verify_provenance.py` and scored here.

All runners record non-2xx responses as divergences instead of crashing, and
embed corpus/snapshot SHA256s in their outputs (Eval-v1/v2 reproducibility
convention). Example corpora ship with synthetic ids — author real, ratified
corpora from the live knowledge graph before quoting numbers.

Tests: `pytest eval-harness/v3/tests/ -q` (hermetic; collected by the main CI
suite).
