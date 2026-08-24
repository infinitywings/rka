# Eval-v3 — experiment results (run 2026-08-23)

Runs against the PI's live local RKA instance (v2.9.0, `rka-server`), against
a `.backup` snapshot `rka-snapshot-2026-08-23.db`
(sha256 `85fd69bd…1bf1e2e4`, 133 MB, 11 projects).

**Status of each track**

| Track | State | Blocker |
|---|---|---|
| 1 self-study | **complete** — 11 projects | — |
| 2 tracing | **complete** — 20 scenarios, 2 projects | corpus awaits PI ratification |
| 3 retention | **complete** — 2 scenarios, 6 probes/arm | n is small; 150k distances untested |
| 4 writer A/B | **not run** | no claim spine exists in any project (0 manuscript units/claims/bindings) |

---

## Track 1 — self-study (record health)

Whole store: **976 claims, 97.7 % provenance coverage**, 84.0 % strict
(coverage ∧ not stale). 134 stale claims, 106 verified.

Coverage arrives overwhelmingly through decisions, not literature:

| Covering path | Claims |
|---|---|
| PI-decision link | 496 |
| source entry cites literature | 266 |
| researcher-journal link | 115 |
| researcher-authored source entry | 69 |
| literature link (graph walk) | 8 |

Per project (`self_study/results/metrics-<project>.json`):

| Project | Claims | Coverage | Strict | Stale | Missions | Open chk |
|---|---|---|---|---|---|---|
| project-A | 142 | 98.6 % | 93.0 % | 8 | 116 | 2 |
| project-C | 121 | 100 % | 28.1 % | 87 | 1 | 0 |
| project-B | 179 | 100 % | 100 % | 0 | 43 | 0 |
| project-D | 134 | 100 % | 100 % | 0 | 5 | 2 |
| project-G | 118 | 100 % | 100 % | 0 | 0 | 0 |
| project-H | 81 | 82.7 % | 82.7 % | 0 | 2 | 0 |
| project-F | 70 | 100 % | 44.3 % | 39 | 3 | 0 |
| project-E | 69 | 100 % | 100 % | 0 | 0 | 0 |
| project-I | 49 | 100 % | 100 % | 0 | 2 | 0 |
| default | 13 | 53.8 % | 53.8 % | 0 | 13 | 1 |
| project-J | 0 | — | — | — | 1 | 0 |

**Research debt is small but no longer strictly retired.** Cumulative
uncovered claims sat at 8 from April through July and rose to 22 in August
(14 new uncovered claims in the current month). Coverage, when it arrives,
arrives immediately: median time-to-coverage 0 days, mean 2.25, max 62.5 —
i.e. claims are almost always born covered, and the debt is a thin tail
rather than a backlog.

**Strict coverage is where the two writing-heavy projects diverge.**
project-C (28.1 %) and project-F (44.3 %) are dragged down purely by
staleness — 87 and 39 stale claims respectively, on 100 % raw coverage. That
is the pivot signature: the evidence is still attached, it has just been
superseded and not re-verified.

**Mission cycle.** 186 missions: 135 complete, 26 pending, 20 cancelled, 3
partial, 2 active. Median duration 0.77 h (mean 59.5 h, max 2213 h — a long
tail of missions left open rather than closed). 130 of 186 carry a report.
Checkpoints are rare: 0.34 per mission, median 0; resolution median 0.16 h.

**The epistemic pipeline is unused.** Interpretation candidates: 0. Claim
scope coverage: 0 % (0 of 976 claims carry `scope_revision ≥ 1`). Semantic
patch proposals: 0. Manuscript claims: 0. Every v2.7+ epistemic-qualification
surface is shipped but has no production traffic in this store.

### Referential-integrity observations

- **40 dangling `entity_links` endpoints** — references to entities that no
  longer exist (16 `decision`, 23 `literature`, 1 `journal`).
- **50 cross-project links** out of 8 564.
- **56 links with `project_id IS NULL`** — legacy rows predating the column;
  all 56 join two same-project entities.

### Extractor bug found and fixed

Running per project surfaced that `--project` was not applied to checkpoints,
the `entity_links` coverage walk, the researcher/PI anchor sets, or the
`claim_scope`/`semantic_patch`/`manuscript_*` counts: every project reported
the whole-store `open_checkpoints` value of 5, including projects with zero
checkpoints. Fixed in `compute_metrics.py`, with three regression tests that
fail against the previous version. True distribution is 2/2/1/0.

The link walk is now scoped **by endpoint** rather than by
`entity_links.project_id`, because scoping on the stamp alone discards the 56
legacy NULL rows and spuriously dropped project-C from 100 % to 95.9 %.
Per-project coverage numbers are unchanged by the fix; only the checkpoint
counts move.

---

## Track 2 — decision back-tracing

Corpora derived mechanically by `tracing/build_corpus.py` (derivation rule
documented in that file), `nl_query` hand-written as researcher paraphrases.
**PI ratification pending.**

| | project-F | project-A |
|---|---|---|
| Scenarios | 8 | 12 |
| Pivot scenarios | 8 | 6 |
| `trace_recall` (critical) | **1.000** | **1.000** |
| `expanded_recall` (all) | **1.000** | **1.000** |
| `precision` | 0.209 | 0.213 |
| `pivot_correct` | **8 / 8** | **6 / 6** |
| `stale_surfacing` | **0** | **0** |
| `anchor_mrr` (semantic) | 0.500 | 0.144 |
| `anchor_mrr` (keyword-only) | 0.200 | 0.024 |
| divergences | 0 | 0 |

Per-relation recall is 1.000 for every relation across both corpora —
directive (14), evidence (75), literature (30), mission (18),
parent_decision (6), superseded_alternative (15).

### The headline: pivots survive

**14 of 14 pivot scenarios surfaced the superseding decision; zero surfaced
only the stale one.** This is the question the PI posed — "research does not
get lost after significant pivoting" — and on this corpus the graph answers
it cleanly.

### Depth-2 is doing real work

Recall of 1.000 at depth 2 would be uninteresting if everything expected were
a direct neighbour. It is not:

| | depth-1 recall (all) | depth-1 recall (critical) | depth-2 |
|---|---|---|---|
| project-F | 0.592 | 0.947 | 1.000 |
| project-A | 0.695 | 0.861 | 1.000 |

**A depth-1 back-trace loses 30–41 % of the expected context.** All 6 parent
decisions sit at hop 2 — decision-tree parents are never directly linked —
and 41 of 75 evidence entities are 2-hop (claims extracted from the journal
entries that justify the decision). Depth 2 recovers all of it.

### The cost: bundle noise

Precision ≈ 0.21 on both corpora — roughly **four irrelevant entities for
every relevant one**. Ego-graph output size varies wildly with the anchor's
connectivity: 8 to 355 entities (median ≈ 34). `multi-hop` caps around 50;
`/api/graph/ego` applies no cap, so a hub decision returns a 355-node bundle.
Recall is free; the reader pays in noise.

### Finding the anchor is the weak link, not tracing from it

Graph traversal from a known decision is near-perfect. *Reaching* that
decision from a natural-language question is not. With semantic search
working, the anchor appears in the top 20 for only:

- **project-F: 3 of 5** NL scenarios (ranks 1, 1, 2)
- **project-A: 3 of 9** (ranks 1, 4, 20)

Decisions are crowded out by journal entries and missions, and the effect is
worse in the larger project (2 271 nodes vs 213). The asymmetry is the
practical finding: **once you have the anchor, RKA reconstructs the full
rationale; getting to the anchor from a question you'd actually ask is where
retrieval loses you.**

### The embedding outage, and what it cost

The first pass of this track was run with semantic search silently dead, and
the fix chain is itself a result. Three distinct defects stacked:

1. **Wrong host.** The instance pointed at `http://<embedding-host-A>:1234` — a
   machine that is not the one running LM Studio. The models actually live on
   this Mac at `localhost:1234`; corrected to `http://host.docker.internal:1234`
   (the container's route to the host). The configured model,
   `text-embedding-qwen3-embedding-4b`, was already downloaded and serves the
   matching 2 560 dimensions, so **no re-embedding was needed**.
2. **Config changes need a process restart.** After `PUT /api/config/embedding`
   the GET reflected the new value and `POST /api/config/embedding/test`
   succeeded (it builds a fresh client), yet search kept failing — the search
   path holds a provider client cached from startup. Only `docker restart
   rka-server` made the new URL take effect.
3. **Memory pressure on a 32 GB machine.** With `qwen3.8-27b-mlx` (29.53 GB)
   resident, JIT-loading the 2.50 GB embedding model thrashed: the first
   embedding call after idle exceeded 90 s. Unloading the 27 B dropped
   embedding latency to **0.195 s**.

With all three fixed, search runs in 0.22–0.48 s with zero divergences.
Graph-traversal metrics are byte-identical before and after, confirming they
never depended on embeddings.

> **Correction.** An earlier draft read the `anchor_mrr` change (0.024 → 0.144
> on project-A, 0.200 → 0.500 on project-F) as a "semantic lift". That was
> wrong. In the keyword-only runs 4 of 9 and 2 of 5 NL searches *timed out* and
> scored 0; after the fix none did, and the recovered scenarios account for the
> change. Per scenario the picture is mixed rather than uniformly better — on
> project-A one improved 0.125 → 1.000 while another regressed
> 0.091 → 0.000. And per the backfill gap below, **project-F has no vector
> coverage at all**, so semantic matching cannot have contributed to its
> number. These runs support no claim about semantic-vs-keyword retrieval
> quality; they show only that removing the timeouts made measurement
> possible.

Both keyword-only and semantic runs are kept in `tracing/results/` so the
degradation is measurable rather than merely asserted.

### The vector index has a three-month hole

The outage was not only a latency problem — it left a permanent gap in the
index. Across every entity type, **the last record carrying an embedding was
created 2026-05-23**, and nothing since has one (verified against the live
database, not the snapshot):

| table | rows | embedded | coverage | missing |
|---|---|---|---|---|
| journal | 3 129 | 2 647 | 84.6 % | 482 |
| literature | 481 | 327 | 68.0 % | 154 |
| decisions | 394 | 240 | 60.9 % | 154 |
| claims | 976 | 565 | 57.9 % | 411 |

Per project the split follows project age:

| project | entities | embedded | coverage |
|---|---|---|---|
| project-A | 2 093 | 1 997 | 95.4 % |
| project-B | 1 087 | 1 024 | 94.2 % |
| project-D | 317 | 282 | 89.0 % |
| **project-F** | **205** | **0** | **0.0 %** |
| **project-E** | **257** | **0** | **0.0 %** |
| **project-H** | **118** | **0** | **0.0 %** |

Every project created after 2026-05-23 is **entirely invisible to vector
search**; for those projects `/api/search` is keyword-only FTS however healthy
the embedding backend is. Repointing the backend fixed new queries but did
**not** backfill: `GET /api/config/embedding/backfill/status` still reports
`idle` and the live index is unchanged. No documented endpoint triggers one.

This is the most consequential finding in the evaluation. 1 201 entities —
three months of research across six projects — are reachable only by exact
keyword, and it invalidates any semantic-retrieval measurement taken against
those projects, including this suite's own project-F numbers.

### Backfill experiment: fixing the gap, and what it did not fix

With the PI's approval the gap was closed for one project. `BackfillService`
could not be used as-is: it is store-wide, and for claims it gates on
`claims.embedding_pending`, which is 0 for all 976 claims even though 411 lack
vectors — so it would have skipped every one of them. `PUT /api/config/embedding`
was also avoided: it calls `reshape_all_vec_tables_if_needed`, which rebuilds
every `vec_*` table and would have discarded project-A's 1 997 existing
vectors. Instead a scoped script reused RKA's own `compose_text` functions and
`EmbeddingService.embed_and_store` (vec row + metadata written atomically),
selecting pending rows by the `embedding_metadata` test the other entity types
already use.

Result: **project-F 208/208 = 100 %** embedded, 0 failures, ~2 minutes. A
pre-backfill snapshot was taken first.

**What it fixed.** Claims went from unreachable to reachable: the targeted
query "budget total direct costs F&A MTDC base" returned nothing before and
ranks the target claim 7th after. Querying the figure itself ranks it 2nd.

**What it did not fix — the important part.** Seed retrievability for the
retention probes is *unchanged* at 1 of 3, and `anchor_mrr` on the tracing
corpus did not improve; it fell from 0.500 to 0.272 (per scenario: one
improved − → r4, one regressed r2 → −, one regressed r1 → r9, two unchanged).
With 5 NL scenarios this is well inside noise and should not be read as
"embeddings made retrieval worse" — but it is solid evidence that **the
missing index was not what made the entry point weak.**

### The entry point fails on paragraph-style queries, and RKA documents this

The probe prompts are full sentences. RKA's own `collect_report_context`
docstring states the rule directly: *"ALWAYS provide `filters.angle_queries` —
3-5 short (1-4 word) queries… Paragraph-only seeding measured 0.32 mean cohort
recall vs 0.80 for angle-decomposed retrieval (eval-v3)."* The retention `rka`
arm issues exactly one paragraph-long query — the documented anti-pattern.

Decomposing the same probes into short angle queries recovers the targets the
long query misses entirely:

| query | budget claim | measurement decision |
|---|---|---|
| full probe sentence | not found | not found |
| `"direct costs"` | **rank 3** | — |
| `"budget total"` | rank 8 | — |
| `"measurement object"` | — | **rank 10** |
| `"robustness profile"` | — | rank 9 |

A union over three short queries surfaces both targets; the single long query
surfaces neither. This is the concrete, testable explanation for the `rka`
arm's 0.17, and it is a usage/plumbing defect in the eval arm rather than a
retrieval-design failure in RKA.

### Three RKA bugs worth filing

1. **`/api/capabilities` reports `embedding.available: true` while the
   configured backend is unreachable.** The probe checks configuration, not
   reachability, so a dead embedding host looks healthy. RKA already ships the
   reachability check needed — `POST /api/config/embedding/test` — so the
   capability endpoint could reuse it (cached, with a short TTL).
2. **Search degrades silently and expensively.** With the backend down, each
   query pays ~3 connect-timeouts (~25 s, often exceeding a 60 s client
   timeout) and returns `200 OK` with no indication to the caller that results
   are keyword-only. A caller cannot distinguish "no semantic match" from
   "semantic search did not run". Suggested: short-circuit after the first
   failure with a cached breaker, and surface a `degraded` flag in the
   response.
3. **No backfill after an outage, and no way to trigger one.** Entities created
   while the backend is unreachable are never embedded and nothing reconciles
   them afterwards; the status endpoint reports `idle` forever and there is no
   trigger endpoint. A transient backend failure becomes a permanent, silent
   hole in semantic retrieval — this is how project-F reached 0 % coverage. A
   fourth, related defect: embedding config changes do not take effect until
   the process restarts (the search path caches its provider client at
   startup), while `POST /api/config/embedding/test` builds a fresh client and
   passes, which makes the stale state actively misleading.

---

## Track 3 — retention (fade) benchmark

Run 2026-08-23. Completer: `qwen3.8-27b-mlx` on a separate LM Studio host
(<llm-host-B>), so the same model serves all three arms; embeddings served
locally. Corpus: 2 project-F scenarios, 6 probes, seeds quoted verbatim from the
live project, filler drawn from the PI's other CPS-security projects. The
`rka` arm reads the live project-F project read-only.

**Sample size is 6 probes per arm (n = 2 per distance bucket). One flip moves
a cell by 0.5. Nothing below is more than a directional signal.**

| arm | ≤2 000 | ≤10 000 | ≤50 000 | overall |
|---|---|---|---|---|
| `full_context` | 1.00 (n=2) | 0.50 (n=2) | 1.00 (n=2) | **0.83** |
| `rag` | 1.00 (n=2) | 0.50 (n=2) | 0.50 (n=2) | **0.67** |
| `rka` | 0.00 (n=2) | 0.50 (n=2) | 0.00 (n=2) | **0.17** |

### The fade thesis was not tested by this run

`full_context` passes at 1 280 tokens *and* at 35 555 tokens. Its single
failure is at 9 669 — the middle distance — so distance is not what drives it.
With a 262 k-context model, a 35 k-token transcript is simply not a hard
retrieval problem: **the regime where long-context degrades was never
reached.** Testing the thesis needs the 150 k+ distances the schema
originally called for, which this corpus deliberately shortened to fit the
completer's throughput.

`rag` is the one arm showing distance sensitivity: it answers the
current-metric probe correctly at 1 422 tokens and produces garbled output at
35 697 ("Use a capability completeness, and device-role clarity in the input
documentation"), consistent with lexical chunk selection missing the seed as
the transcript grows. n = 1, so this is a hint, not a finding.

### One cell is a scoring artifact, not a failure

`papers-mid` / `full_context` is scored FAIL on `must_not_include:
["proof-of-concept"]`. The actual response was correct:

> "*\<prior artefact\>* **should not** be positioned as … the *\<old framing\>*
> half of the narrative. That older framing is superseded."
>
> (paraphrased — the verbatim response quotes the PI's research content)

The model explicitly rejected the stale framing, and the substring check
penalised it for naming the very thing it was rejecting: the forbidden term
appeared inside the disclaimer. `must_not_include` cannot
distinguish *asserting* a stale claim from *disclaiming* it. Corrected for
this, `full_context` scores 6/6. The same check fired on `rag`'s
`papers-mid`, but the stored `response_excerpt` truncates at 400 characters,
so that one cannot be adjudicated — a harness limitation worth fixing
(store full responses).

### Why the `rka` arm lost — it was not a fair contest

The 0.17 does **not** measure RKA's retrieval design. Three handicaps compound:

1. **project-F has 0 % vector coverage.** All 205 of its entities were created
   after the 2026-05-23 embedding cutoff, so for this project RKA's "built-in
   RAG" *is* keyword-only FTS. The semantic half was structurally absent.
2. **The arms are not equally provisioned.** `_assemble_context` builds the
   `rag` arm from `lexical_top_chunks(seeds_text + transcript, …)` — its corpus
   literally contains the seed text verbatim. The `rka` arm deliberately does
   not get the seeds (`# Seeds are NOT pasted in: they must come back through
   retrieval`) and must find them among 205 competing real entities. `rag` is
   therefore retrieving from a corpus with the answer planted at position 0,
   which is a far easier task than the one `rka` was set.
3. **Search returns snippets, not content.** `/api/search` yields
   `{entity_type, entity_id, title, snippet, score}` with snippets capped near
   200 characters. For the budget probe, no returned snippet contained
   the figure the probe asked for — so even a correct hit could not satisfy
   the check. Real Brain
   usage searches *and then fetches* the entity; the arm only does the first
   step.

The target claim `clm_000005REDACTED` is present in `fts_claims`
but has no embedding, and is not returned even for the targeted keyword query
"final project-F budget direct costs F&A MTDC" — journal entries about the budget
outrank it.

### The `rka` arm fails, and fails dangerously

This was predicted before the run: probing the live project with the three
probe prompts retrieved only **1 of 3** seeded targets in the top 10. The arm
inherits that directly — but the failure mode matters more than the rate.

On `budget-near` it degraded safely, reporting absence:

> "The provided context does **not** record the exact value the question
> asked for."

On `metric-far` and `papers-mid` it did something worse — it retrieved a
*different real decision from the same project* and asserted it as current:

> "The in-force decision is **\<some other real decision in the same
> project\>**: …"

— a confident, well-formed citation of a decision that was never the answer.

That is confident, well-cited, and wrong: the decision actually in force is
`dec_000007REDACTED`. A single-query search returns something
semantically adjacent, and the model reasonably trusts it. For a system whose
purpose is keeping the researcher on current knowledge, **plausible
substitution is a more serious failure than a miss.**

### What this does and does not say about RKA

It does **not** say the knowledge is missing — Track 2 shows the graph
reconstructs these same decisions with recall 1.000 and 14/14 pivot
correctness. It says the **default context-assembly policy** (one
`/api/search` call, top 10) is too weak an entry point to feed a drafting
context, which is the same weakness `anchor_mrr` measured from the other
direction.

The obvious next experiment is a fourth arm built on `collect_report_context`
— RKA's own multi-angle seeded retrieval with graph expansion, whose
docstring reports 0.32 → 0.80 mean cohort recall over paragraph-only seeding.
That would separate "RKA retrieval is weak" from "the default single-query
call is weak", which this run cannot distinguish.

## Track 4 — writer A/B (not run: no corpus to draft from)

Blocked on corpus, not tooling. Arm A ("Writer skill with the live knowledge
base: claim spine, evidence bindings") requires a claim spine. The store holds
**3 manuscripts, 0 manuscript units, 0 manuscript claims, 0 evidence bindings,
0 planning branches** — the whole manuscript layer is registered but unused, so
Arm A has nothing to draft from and the "expected evidence set = the spine's
bindings" ground truth does not exist.

A **reduced form is available** and needs no spine:
`rka/skills/writer/scripts/verify_provenance.py` audits `% provenance:
<entity_id>` comments in a `.tex` file directly against the live project
(EXISTS / CURRENT / SUPPORTED / UNCONTESTED), so a two-arm comparison is
possible today:

- **Arm A** — draft a section with live RKA retrieval and provenance anchors.
- **Arm B** — same model, same source material as a flat dump, no graph.
- Expected-evidence ground truth taken from a project-F evidence cluster's claims
  (the same mechanical-derivation approach used for the tracing corpus)
  instead of from a spine.

Not run here: it needs a drafting pass per arm on the local completer, and the
result would characterise a 27B local model's LaTeX discipline as much as the
context policy. Worth doing with a stronger drafting model, or after a real
claim spine exists for one project-F section.

