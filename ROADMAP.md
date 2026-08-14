# RKA Roadmap

This roadmap turns the detailed [epistemic pipeline and manuscript workbench
plan](docs/superpowers/plans/2026-08-14-rka-epistemic-pipeline-and-manuscript-workbench.md)
into implementation milestones. It combines the ARA-inspired research-artifact
substrate with a researcher-facing manuscript drafting workbench.

The M0 authority, stage, proposal, and provider decisions are recorded in
[ADR 0001](docs/adr/0001-manuscript-workbench-authority-stage-and-ai-boundary.md).
The M1 interpretation boundary is recorded in
[ADR 0002](docs/adr/0002-interpretation-staging-and-experiment-boundary.md).
The canonical-claim applicability boundary is recorded in
[ADR 0003](docs/adr/0003-canonical-claim-scope-contracts.md).

The roadmap is ordered by dependency, not by invented delivery dates. Every
milestone must satisfy its exit gate before dependent work is treated as ready.

## Now

**M0, M1 / PR 1, and M1 / PR 2 are committed. The first M2 / PR 4 workbench
hardening slice is locally complete and validated.** The choice-first Writer
delta is reconciled, the authority and AI boundary is recorded in ADR 0001,
and the read-only workbench has been walked through with DelaySteer and a
full-manuscript control.

The walkthrough and its design revisions are recorded in
[`2026-08-14-delaysteer-workbench-walkthrough.md`](docs/superpowers/specs/2026-08-14-delaysteer-workbench-walkthrough.md).
The authority and stage contracts have researcher approval. PR 1 now includes
the candidate schema and immutable audit history, exact source locators,
duplicate/conflict hints, explicit promotion and revocation, deterministic
review UI, REST/MCP/knowledge-pack parity, a full-suite release gate, an
isolated Docker smoke test, and a disposable DelaySteer browser pilot. PR 2
adds immutable canonical scope revisions, typed applicability conditions,
explicit extension and falsifier policy, independent scope/evidence/source/
contradiction axes, stale-content detection, fail-closed Writer eligibility,
and complete REST/MCP/pack/graph/workbench projections. Its release gate passed
the full Python suite, production web build, isolated container smoke test,
revision-conflict check, and browser walkthrough of missing, incomplete, ready,
and stale states.

PR 4 now projects interpretation and scope readiness in the Context Capsule,
stores workbench stage and review selection in shareable URLs, and provides
direct evidence-to-scope/source/interpretation trace exits. Its disposable
production-browser walkthrough verified deep links, Back recovery, mismatched
filter recovery, and independent epistemic labels. The evidence is recorded in
[`2026-08-14-workbench-scope-navigation-walkthrough.md`](docs/superpowers/specs/2026-08-14-workbench-scope-navigation-walkthrough.md).

The real-project admission pass now covers DelaySteer, InvarLLM, CPSEval, and
detectability through an online database backup. Project isolation passed, and
the workbench correctly refused to invent scopes or spines: the first two
projects have no native manuscript, while CPSEval and detectability have native
manuscripts but empty spines; all four still contain only legacy claims with
missing canonical scopes. The immediate target remains **M2 / PR 4**, but its
positive-path exit now requires an explicitly authorized semantic-migration
pilot. CPSEval is the recommended smallest pilot because it already has a
native manuscript and fewer legacy claims than detectability. PR 3 remains
explicitly deferred until the experiment/run/result schema is separately
designed and reviewed; the workbench must label that missing semantic layer
rather than infer experiments from journal entries.

## Dependency map

```mermaid
flowchart LR
  M0["M0 Foundation and validation"] --> M1["M1 Epistemic research substrate"]
  M0 --> M2["M2 Read-only workbench MVP"]
  M1 --> M3["M3 Deliberation and safe editing"]
  M2 --> M3
  M3 --> M4["M4 Contribution and evaluation workflow"]
  M4 --> M5["M5 Outline and drafting"]
  M1 --> M6["M6 Intake, artifact views, and hardening"]
  M5 --> M6
```

M1 and M2 may proceed in parallel after M0. M2 must label missing experiment
semantics rather than pretending that M1 is already complete.

## Milestones

| Order | Milestone | Outcome | Planned work items | Exit gate |
|---|---|---|---|---|
| **M0** | **Foundation and validation** | Reconcile the existing Writer behavior and validate the proposed workbench before schema work. | PR 0A Writer delta reconciliation; PR 0B ADRs and read-only UX prototype; DelaySteer walkthrough. | A researcher can walk through the interface with a real RKA project, trace every displayed item to its source, and approve the authority and stage contracts. |
| **M1** | **Epistemic research substrate** | Convert noisy journal material into reviewable candidates and bounded evidence without overstating conclusions. | PR 1 Interpretation Staging; PR 2 claim scope contracts; PR 3 experiments, runs, results, and evidence locators. | Candidate-to-claim promotion is explicit and reversible; claims carry scope and falsifier information; positive, negative, and inconclusive results remain traceable and project-isolated. |
| **M2** | **Read-only manuscript workbench MVP** | Make the current argument and evidence navigable before enabling mutation. | PR 4 workbench shell and Context Capsule. | A researcher can inspect the sentence/paragraph spine, RQs, clusters, claims, sources, manuscript units, evidence, trace paths, and stale-impact warnings without changing canonical state. |
| **M3** | **Deliberation and safe editing** | Support resumable human/AI collaboration with one auditable mutation path. | PR 5 versioned planning artifacts and branches; PR 6 unified human/AI patch proposals and local-model adapter. | Direct edits and AI proposals use the same semantic diff, validation, conflict, apply/reject, and provenance path; no ratified semantics are silently overwritten. |
| **M4** | **Contribution and evaluation workflow** | Guide the researcher from framing through bounded contributions and testable evaluation commitments. | PR 7 seed-through-contribution workflow; PR 8 evaluation contract and results trace. | Problem, gap, insight, challenges, innovations, RQs, contributions, and evaluation commitments are linked; PI ratification is explicit; missing evidence becomes visible work. |
| **M5** | **Outline and drafting** | Turn the ratified spine into an expandable, evidence-linked manuscript. | PR 9 progressive outline and unit editor; PR 10 draft editor and source synchronization. | The researcher can expand and condense claim-sized units, draft in Markdown/LaTeX, navigate provenance, and apply conflict-safe writes without automatic Git operations. |
| **M6** | **Intake, artifact views, and hardening** | Complete source intake, deterministic ARA-inspired views, grounded foresight, and production-quality reliability. | PR 11 Source Inbox; PR 12A artifact profile and deterministic viewer; PR 12B grounded research foresight; PR 13 end-to-end reliability and usability. | Imported sources are safe and traceable; projections are deterministic rather than authoritative; foresight is advisory; real-project, security, accessibility, migration, and concurrency suites pass. |

## Tracking convention

- One GitHub milestone corresponds to each roadmap milestone above.
- One GitHub issue corresponds to each planned PR-sized work item.
- The single issue labeled `priority: next` is the immediate implementation
  target. Move that label only when its exit criteria are satisfied or the
  dependency order is explicitly revised.
- Use `roadmap` on every roadmap issue and `area: writer`, `area: substrate`,
  `area: workbench`, or `area: artifact` to make the work scannable.
- An issue is complete only when its acceptance criteria and required tests are
  satisfied. A rendered UI, an LLM response, or green unit tests alone do not
  establish workflow correctness.

## Cross-cutting constraints

- RKA remains the semantic authority; workbench and ARA-style views are
  projections over native RKA objects.
- Evidence, interpretation, PI ratification, AI suggestion, and public prose
  remain distinct.
- No journal entry becomes a claim automatically. Promotion must preserve the
  exact source locator and decision lineage.
- Negative, inconclusive, conflicting, and superseded evidence remains visible
  in the private reasoning substrate.
- Human and AI edits follow the same versioned proposal and validation path.
- External content is untrusted input: preview and hash it, never execute it or
  obey embedded instructions.
- Readiness is categorical (`Ready`, `Needs review`, `Blocked`, or
  `Exploratory`), never a paper score or acceptance prediction.

## First useful release

The first useful release spans M0–M5. It is reached when a researcher can start
with an insight, develop and ratify a traceable paper spine, connect it to
claims and evaluation evidence, produce a claim-sized outline, and expand a
unit into evidence-bounded draft prose through a recoverable, conflict-safe
workflow. M6 then completes intake, exchange/viewer capabilities, grounded
foresight, and operational hardening.

The detailed design, data model, UI behavior, API/MCP surface, tests, and full
acceptance criteria remain in the linked implementation plan and are normative
for the corresponding roadmap issues.
