# RKA Performance & Research-Quality Evaluation Plan

**Date**: 2026-08-23
**Branch**: `claude/rka-performance-eval-mtyuqz`
**Baseline HEAD**: `db2e78d` (merge of PR #85, M5/PR 10 conflict-safe manuscript source sync)
**Status**: plan — no evaluation code in this change

---

## 1. Where the system stands and what has (and has not) been evaluated

RKA is now a substantially different system from the last time it was measured.
Since the two existing evaluation efforts, the epistemic pipeline (M0–M5) has
landed: interpretation staging, canonical claim scope contracts,
experiment/run/observation evidence substrate, versioned planning branches,
unified semantic patch proposals, seed-to-contribution promotion, the
claim-centered evaluation contract, the progressive L2–L5 outline editor, the
typed academic-writing core, and conflict-safe manuscript source sync. The MCP
dispatch surface is at 150 operations (67 reads / 83 writes).

What exists today under `eval-harness/`:

| Effort | Era | What it measured | Headline results |
|---|---|---|---|
| **Eval v1** (`eval-harness/`) | v2.3.5 | Retrieval quality: 2×2 (OR/AND × FTS-only/hybrid), 35 labeled queries, P@10 / MRR / NDCG@10 | AND-fix: null. Semantic-hybrid: +9% NDCG@10 (re-ranking effect). Four structural retrieval failure classes identified (temporal language, structural traversal, cluster retrieval, actor filtering). |
| **Eval v2** (`eval-harness/v2/`) | v2.5.x | Composed-context coverage: 16 session-start scenarios, critical/expanded recall, ordering, breadth, efficiency | Critical recall 0.958 (passes 0.85 floor), but ordering 0.251 and efficiency 0.037 — bundles are ~96% padding; cluster→parent-RQ traversal is the recall failure mode; `rka_multi_hop_retrieval` returned 422 everywhere. |

Both are **component-level infrastructure evals** — they measure whether RKA
retrieves and composes context well. Neither measures the thing the project's
own paper claims as its contribution.

The paper (`docs/paper/RKA-paper.pdf`, "Framing Is Human", §7) commits to four
forms of evidence and three research questions:

- **RQ1**: does the three-actor architecture produce an auditable record with
  preserved provenance across extended use?
- **RQ2**: does the structured-decision interface surface researcher/AI
  disagreement in reviewable form?
- **RQ3**: is the system usable by researchers other than the author?

§7.1 promises three concrete self-study metrics over the eight-month
`rka_development` record — **provenance coverage**, **research-debt
trajectory**, and **mission-cycle metrics** — and states that "concrete values
… are being accumulated," with values reported at study completion. **No code
in `rka/` currently computes any of these three metrics.** This is the single
largest gap between what the system claims and what has been measured, and it
is also the cheapest to close: the data already exists in the
`rka_development` database.

## 2. Three distinct questions hiding inside "performance"

"How does RKA perform" decomposes into three questions that need different
instruments. Conflating them is the main design risk for this evaluation.

1. **Infrastructure quality** — do retrieval, context composition, and the
   dispatch surface work well? (Eval v1/v2 territory; measurable, already
   partially done, now stale.)
2. **Record quality** — does the substrate actually stay auditable, grounded,
   and current over months of real use, or does it silently accumulate
   research debt? (The paper's §7.1 metrics; RQ1/RQ2.)
3. **Research-outcome quality** — does *using* RKA lead to measurably better
   research work than not using it? (The causal claim; hardest to measure;
   the paper defers the multi-arm study on it to future work.)

The mechanisms RKA is designed around map onto measurable proxies:

| Mechanism | Claimed contribution | Measurable proxy | Track |
|---|---|---|---|
| Provenance-by-construction (typed links, source spans) | Resistance to research debt | Provenance coverage %, debt trajectory | T1 |
| Progressive crystallization (candidate → claim → scope → cluster) | Tentative vs. reviewed knowledge separation | Promotion/rejection rates, scope coverage, staleness residence time | T1 |
| Fail-closed admission gates (Writer eligibility, checkpoint fingerprints) | Manuscript claims cannot outrun evidence | Gate precision/recall under audit + injection | T3 |
| Persistent longitudinal record | Resumability without reconstructing reasoning | Cold-start resumption benchmark vs. raw-log baseline | T4 |
| Decision gates + checkpoints | Human framing authority; auditable disagreement | Mission-cycle metrics, supersede-chain audits, case studies | T1, T5 |
| Retrieval + composed context | Right context at session start | Eval v1/v2 refresh on current HEAD | T2 |

## 3. Evaluation tracks

### Track 1 — Self-study metrics extractor (closes the paper's §7.1 gap)

**Highest priority.** A read-only analyzer, proposed home
`eval-harness/v3/self_study/`, run against a **backup copy** of the
`rka_development` database (never the live volume), producing `metrics.json`
plus time-series CSVs.

Definitions, grounded in the current schema:

- **Provenance coverage**: fraction of non-retracted rows in `claims` whose
  chain terminates at an acceptable source. A claim is *covered* when its
  `source_entry_id` journal row (or, transitively via `entity_links` /
  `claim_edges` / manuscript evidence bindings) reaches a `pi`-authored
  journal entry, a `literature` row, or an experiment-substrate observation
  with an exact locator — and the claim is not `stale=1`. Report overall,
  by `claim_type`, and by creation month. The same computation over
  `manuscript_claims` / `manuscript_claim_versions` (which carry
  applicability conditions and falsifiers) gives the stricter M5-era figure.
- **Research-debt trajectory**: per month, claims created uncovered vs.
  covered, plus debt retirements (claims that later gained coverage or were
  retracted/superseded). Headline: net debt slope and median
  time-to-coverage. The `stale` flag and `staleness_resolution` records give
  a second debt axis: how long invalidated claims stay unresolved.
- **Mission-cycle metrics**: from `missions`, `checkpoints`, `events`, and
  `audit_log` timestamps — mission duration distribution, checkpoints per
  mission, mission-to-report (Backbrief journal) cycle time, and the fraction
  of missions abandoned vs. closed. This answers "is the workflow friction
  low enough to be used" with the system's own eight-month history.
- **Pipeline-stage flow (new, M5-era)**: interpretation candidates by outcome
  (promoted / rejected / deferred / merged), scope-contract coverage of
  canonical claims, proposal apply/reject rates from the semantic-patch
  ledger, and manuscript-unit evidence-binding completeness from the outline
  readiness projection. These quantify progressive crystallization, which
  neither v1 nor v2 touched.

Effort: small (a few days). No production-code changes; pure SQL + Python over
a DB copy. Output feeds the paper's §7.1 directly.

### Track 2 — Component-eval refresh (regression baseline)

Re-run Eval v1 and Eval v2 against current HEAD before any new tuning work.
Three specific checks beyond the headline metrics:

- Is `rka_multi_hop_retrieval` still 422 across the board? (Eval v2 Finding 4
  flagged it as a real defect, not corpus noise.)
- Has cluster→parent-RQ traversal improved since the entity-links and
  outline/spine work landed?
- Bundle efficiency: still ~0.037, or did the dispatch-surface redesign change
  the composed-context shape?

Caveat: both corpora are frozen against v2.3–2.5-era database content; entity
IDs in `expected_entities` must be re-validated against the current DB before
trusting deltas. Budget a corpus-refresh pass (Eval v2 already has a
documented refresh procedure from 2026-05-20).

### Track 3 — Grounding-gate fidelity audit (the "research quality" teeth)

The strongest *system-level* claim RKA makes is fail-closed manuscript
admission: a claim can't enter the spine without grounding, scope, evidence
status, contradiction, and freshness checks. Measure the gate like a
classifier:

- **Precision arm (audit)**: sample N admitted manuscript claim/evidence
  bindings from real projects (rka_development, CPSEval copy); a human judges
  whether the bound evidence genuinely supports the stated proposition and
  warrant. Reported as gate precision. This is analogous to a groundedness
  audit in RAG evaluation, but over the curated record instead of raw
  retrieval.
- **Recall arm (injection)**: on a disposable DB copy, construct deliberately
  defective inputs — claim with no evidence binding, claim whose source
  journal was superseded, claim contradicting an active cluster, scope-less
  legacy claim, evidence entity outside the disclosed context manifest — and
  verify each is blocked or visibly flagged at the checkpoint/readiness
  layer. Every injection case that passes silently is a bug with a
  reproduction attached.

This track converts "provenance by construction" from an architecture claim
into a measured property, and its failure cases are directly actionable.

### Track 4 — Resumption benchmark (the most publishable quantitative result)

RKA's central usability promise is "resume long-running projects without
reconstructing prior reasoning." That is testable without a multi-arm human
study:

- Freeze a project state (e.g., rka_development at a past checkpoint, or
  CPSEval). Author, from the record, a ground-truth quiz: 15–25 questions
  with verifiable answers ("what was decided about X and why", "which
  alternative was rejected and on what evidence", "what is currently believed
  about Y and is it stale?").
- **Arm A**: a fresh agent session answers using RKA (MCP session-start
  workflow). **Arm B**: the same model answers from the raw material the
  record was distilled from (chat transcripts / repo / notes) with equal
  token budget. Optional **Arm C**: plain vector-RAG over the same raw
  material, as the "vector databases retrieve similar passages" strawman the
  README argues against.
- Score answer correctness (human-graded against ground truth), provenance
  citation correctness (does the cited entity actually say that), tokens and
  wall-clock to first correct answer.

This directly operationalizes "contributes to research quality": correct,
attributable reconstruction of prior reasoning is the necessary condition for
every downstream quality claim. It is also the evaluation a skeptical reviewer
will find most convincing, because it has a real baseline.

### Track 5 — Human-evidence instruments (case studies + user study scaffolding)

The paper already contains the qualitative arms (self-study narrative, three
edge-cloud-agent case studies, N=3 independent use). What to do now is
*instrumentation, not the study itself*:

- Freeze the case-study extraction procedure as a script (given a decision ID,
  emit the full supersede/evidence chain as an archival artifact), so case
  studies are reproducible walks of the record rather than manual curation.
- Write the multi-arm study protocol as a document now — tasks, arms
  (RKA vs. coding-assistant-only), rubric dimensions (framing defensibility,
  evidence traceability, decision auditability), grader blinding — so
  independent-use data being captured today lands in a form the future study
  can use. Defer execution, exactly as §7.4 does.

### Track 6 — Cost and friction

Every gate has a price; the evaluation should report it rather than hide it:
tokens consumed by the 5-tool dispatch surface per session-start versus the
legacy surface, median operation latency by dispatch branch (the REST layer
already logs enough to derive this), and operations-per-mission overhead.
Pairs with Track 1's mission-cycle metrics to answer "is the discipline cheap
enough that people keep paying it."

## 4. Sequencing and effort

| Order | Track | Effort | Why this order |
|---|---|---|---|
| 1 | T1 self-study extractor | days | Data already exists; unblocks the paper's promised §7.1 values; zero production risk |
| 2 | T2 component refresh | days (plus corpus re-validation) | Establishes the regression baseline before any tuning; cheap because harnesses exist |
| 3 | T3 gate audit + injection | ~1 week | Highest-value new evidence per unit effort; produces bug reproductions as a side effect |
| 4 | T4 resumption benchmark | 1–2 weeks | Strongest publishable quantitative result; needs T1's DB-snapshot tooling first |
| 5 | T5 instruments | days | Documents/scripts only; execution deferred |
| 6 | T6 cost/friction | days | Piggybacks on T1/T2 runs |

## 5. Threats to validity (declare up front)

- **N=1 / self-familiarity**: the self-study record is the author's own; T1
  reports trajectories, not prevalence. The paper already frames this
  honestly — keep that framing.
- **Self-referential corpus**: rka_development is a record *about building
  RKA*; retrieval queries about RKA leak into the corpus (Eval v1's Q19
  self-hit). Prefer CPSEval/edge-cloud-agent data for T3/T4 where possible.
- **LLM-judge bias**: any automated grading in T4 must be spot-checked by a
  human on a sample; grade with a model family different from the one under
  test where feasible.
- **Stale corpora**: T2 deltas are meaningless until `expected_entities` are
  re-validated against the current database.
- **Gate audit sampling**: T3 precision must sample across claim types and
  projects, not just the easy method-claims path exercised in the CPSEval
  positive-path pilot.

## 6. Immediate next actions

1. Take a backup copy of the `rka_development` database (`/data/rka.db` from
   the `rka-data` volume) and stamp it with the HEAD commit — every track
   consumes snapshots, never the live DB.
2. Scaffold `eval-harness/v3/self_study/` with the three §7.1 metric queries
   and a per-month time-series output.
3. Re-validate the Eval v2 scenario corpus entity IDs against that snapshot.
4. File the T3 injection cases as a test matrix before writing code — each
   row is (defect constructed, layer expected to block, observed behavior).
