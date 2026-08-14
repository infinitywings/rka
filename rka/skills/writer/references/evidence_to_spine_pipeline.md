# Evidence-to-Spine Pipeline

This workflow turns a noisy, chronological research record into a bounded
paper argument without treating every note as equally reliable. RKA owns the
research graph and manuscript semantics; Writer turns the approved projection
into prose. The pipeline is deliberately lossy at each review boundary:
irrelevant, duplicate, stale, weak, and unresolved material remains preserved
in RKA but does not silently enter the manuscript.

## The pipeline

```text
jrn_ observations and decisions
        |
        | exact locator, epistemic kind, explicit review
        v
icd_ interpretation candidates
        |
        | promotion with grounding fidelity and immutable lineage
        v
clm_ atomic claims
        |
        | typed applicability, uncertainty, extension limits, falsifier
        v
csc_ canonical claim-scope versions
        |
        | cluster membership, duplicate grouping, contradiction edges
        v
ecl_ evidence clusters
        |
        | Brain synthesis and confidence review
        v
dec_ research questions
        |
        | manuscript-scope selection by PI and Writer
        v
unratified writing candidates
        |
        | contribution boundary, exact wording, prohibited wording
        v
mcl_ manuscript claims + PI ratification
        |
        | claim-sized unit plan and bidirectional result coverage
        v
mun_ units, argument spine, and results trace
        |
        | evidence-grounded, claim-centered drafting and citation validation
        v
manuscript prose
```

No arrow is an automatic promotion. Each boundary has an owner, an admission
rule, and an explicit failure state.

## 1. Journal quarantine

Journal entries are chronological research records. They may be observations,
instructions, partial interpretations, abandoned ideas, or manuscript prose.
They are never writing candidates by themselves.

The Brain may extract an atomic `clm_` only when:

- the source entry exists in the same project;
- the claim states one checkable proposition;
- extraction fidelity is explicit (`verified` concerns faithful extraction,
  not scientific truth);
- the source is not retracted, superseded, or manuscript-derived;
- uncertainty and scope remain visible.

Keep noisy journal records. Do not delete history merely because a record is
not manuscript-ready. Supersede or retract it through RKA when its status has
changed.

## 2. Claim admission

A `clm_` is eligible as positive manuscript support only when all of these are
true:

- grounding extraction is verified;
- scientific `evidence_status` is `supported` or `partially_supported`;
- claim and terminal source are current;
- project ownership is attested;
- the source is not manuscript prose;
- unresolved contradiction edges do not touch the claim.
- its current canonical `csc_` contract is complete, reviewed, and still
  matches the claim's current content and type.

Candidate scope on `icd_` is source-bounded extraction context. Canonical scope
on `csc_` is the research-level applicability contract. Manuscript wording on
`mcl_` is paper-specific and PI-ratified. Do not collapse these layers. Legacy
claims with no `csc_` remain `scope_readiness=missing`, and a claim edit makes
its older contract stale. Scope readiness never replaces grounding,
scientific-support, contradiction, or currency checks.

Claims that fail admission stay visible in the candidate report with reason
codes. They are not silently discarded or converted into qualifiers.

Repeated claims are grouped by normalized content inside their evidence
cluster. One representative supports navigation; all original claim IDs remain
in lineage. Duplicate records do not create artificial evidential weight.

## 3. Cluster and research-question smoothing

The Brain organizes admitted claims into `ecl_` clusters bound to active
research-question decisions. An evidence cluster is eligible for Writer
discovery only when:

- it is bound to a current research question;
- its synthesis was reviewed by the Brain;
- confidence is `strong` or `moderate`;
- it is current and does not need reprocessing;
- no cluster-review item remains pending;
- it contains manuscript-ready positive support;
- counterevidence has been resolved, not hidden.

An LLM-created synthesis is not sufficient until the Brain reviews it. An
`ecl_` is a discovery and synthesis layer, not terminal empirical evidence.
The supporting `clm_` and their terminal sources remain the provenance base.
"Resolved counterevidence" means an explicit, provenance-preserving
disposition: repair the evidence gap, narrow or withdraw the affected claim,
or assign proportionate public treatment. It never means deleting, relabeling,
or privately dismissing an adverse result that remains material.

Use:

```text
rka_query(args={
  "operation": "manuscript_writing_candidates",
  "project_id": "prj_...",
  "id": "man_..."
})
```

or:

```bash
rka writer assist --project-id prj_... --manuscript-id man_...
```

The response covers the project research map, not an inferred manuscript
topic. The PI and Writer must select which research questions are in scope.
The response includes:

- every reviewed cluster and its eligibility blockers;
- excluded source claims and reason codes;
- duplicate-support groups;
- qualifiers and counterevidence;
- an unratified candidate spine;
- candidate-to-cluster/RQ lineage.
- canonical `csc_` IDs and prohibited extensions for every admitted support
  claim.

## 4. Contribution contract

Before outline approval, convert the selected candidates into one bounded
contribution contract. At minimum, record:

- problem and field gap;
- research question addressed;
- technical response;
- required, available, and missing evidence;
- exact contribution wording;
- strongest allowed interpretation;
- prohibited interpretations;
- novelty and significance risks;
- supporting, qualifying, and counterevidence IDs.

The generated `CONTRIBUTION_CONTRACT.md` is a review view. Semantic content
lives in native manuscript claims, evidence bindings, and decisions.

The contract fails closed when a core contribution has no admitted support,
when counterevidence remains unresolved, or when prohibited wording is empty.
The PI ratifies the exact wording through an active `paper_writing` decision.
A decision licenses wording and scope; it does not supply empirical evidence.

### Internal completeness and public selection

RKA and the contribution contract retain the complete positive, qualifying,
contradicting, and speculative record. Public prose is a selective projection,
not a dump of that record. Classify every risk or boundary through
[`persuasive_framing.md`](persuasive_framing.md):

- M1 and M2 receive visible, proportionate public treatment because omission
  would distort a claim or its scope;
- M3 belongs in methods, an appendix, an artifact, or reproducibility material;
- M4 and S remain in the internal planning and review record unless the venue
  requires disclosure.

Selection changes placement, not evidence. It never authorizes cherry-picking,
suppression of a claim-relevant mixed result, or deletion of provenance.

## 5. Argument spine and unit plan

Build the argument at claim-sized granularity:

```text
problem -> gap -> response -> evidence -> interpretation -> boundary
```

For each `mun_` unit, specify:

- communicative job;
- contribution claim links;
- RKA support, qualifier, and counterevidence IDs;
- source location;
- artifact binding where applicable;
- allowed and prohibited interpretation;
- relationship: `advances`, `tests`, `bounds`, or `mentions`;
- drafting status.

The outline checkpoint approves this contribution and argument boundary, not
merely a list of section headings. The deterministic
`ARGUMENT_SPINE.md` projection should let the PI inspect:

- which introduction promise each result tests;
- which discussion statement resolves each research question;
- where material or venue-required boundaries constrain interpretation.

## 6. Results-to-claim trace

Every active empirical contribution must have an active result unit, and every
major result unit must serve a claim or be explicitly exploratory.

Each result unit requires:

- a typed, same-project `art_` or `fig_` binding;
- a complete extraction with content hash;
- admitted evidence;
- allowed and prohibited interpretation;
- a claim-unit relationship.

Use `supports` or `fails to support` language. A result does not become
universal proof because it appears in a figure. `RESULTS_TRACE.md` is the
bidirectional coverage view; the native unit and evidence joins are
authoritative.

## 7. Writing strategy

Draft one unit at a time:

1. Resolve the unit, ratified claim version, positive support, qualifiers,
   counterevidence, prohibited wording, and publication-boundary
   classifications from RKA and the private planning record.
2. Extract the evidence facts, conditions, and material boundaries before
   drafting.
3. Draft the smallest claim-centered, strength-first prose block that performs
   the unit's communicative job and makes the strongest evidence easy to find.
4. Stay within the allowed interpretation and apply M1-M4/S public placement.
5. Run the quick-reader checks in `persuasive_framing.md`; revise the framing
   or escalate an unresolved materiality decision.
6. Attach citations in a separate pass and validate them.
7. Update unit status through a revision-guarded aggregate change.
8. Synchronize projections and re-run readiness.

Generated projections aid review but never supply evidence. A local prose edit
does not change RKA semantics.

## Change handling

Use the semantic change cursor to localize re-review:

```text
impact -> inspect affected lineage -> sync -> readiness
```

When an upstream record changes:

- do not rewrite all claims from the newest journal entry;
- do not silently strengthen or weaken PI-ratified wording;
- re-run cluster review when the cluster is stale;
- append a new manuscript-claim wording version when meaning changes;
- obtain a new PI decision and ratification;
- supersede dependent checkpoints when their semantic fingerprint changes.

This preserves the historical trace while preventing old approvals from
authorizing new semantics.

## Failure handling

| Condition | Action |
|---|---|
| journal only, no grounded claim | inspect pending `icd_` candidates; return to Brain staging/review and explicit promotion |
| unverified or weak claim | keep excluded with reason |
| duplicate claim | group; preserve all lineage |
| stale cluster | Brain reprocesses cluster |
| orphaned cluster | bind to a current research question |
| unresolved contradiction | block candidate promotion |
| candidate outside manuscript scope | leave unselected |
| missing prohibited wording | PI/Writer bounds the claim |
| changed ratified wording | append version and obtain new PI decision |
| result without artifact or claim | block readiness |
| unsupported prose request | create an evidence-gap mission or narrow wording |

## Design lineage

The contribution, argument, unit-plan, and result-coverage concepts were
informed by the high-level workflow ideas in
[PaperSpine](https://github.com/WUBING2023/PaperSpine). This implementation is
independently expressed in RKA-native graph, revision, project-isolation, and
PI-ratification semantics. It does not embed PaperSpine's orchestrator, copy
its templates, use fixed section/count heuristics, or convert structural
completeness into a claim of scientific correctness.
