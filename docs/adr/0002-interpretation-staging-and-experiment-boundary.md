# ADR 0002: Interpretation Staging and the experiment boundary

- Status: accepted for M1 implementation
- Date: 2026-08-14
- Scope: noisy-source interpretation, candidate review, claim promotion, and
  the boundary with future experiment records

## Context

RKA currently allows both the background LLM extractor and the Brain-facing
`extract_claims` operation to write directly into `claims`. That collapses
three different assertions into one row:

1. a source contains some text or observation;
2. an actor interprets that source as an atomic proposition; and
3. the proposition is ready to participate in the canonical research graph.

Noisy journals make that collapse unsafe. Planning notes, author intent,
speculation, copied literature language, and measured observations can all
look claim-like while requiring different treatment. Execution records create
a related problem: evidence that a command ran is not automatically evidence
for the scientific interpretation placed on its output.

## Decision

### 1. Add a distinct Interpretation Staging aggregate

An `icd_` interpretation candidate is a project-scoped, reviewable assertion
with:

- one source entity and one typed exact locator;
- one atomic statement;
- an epistemic kind;
- explicit scope conditions, uncertainty, and optional falsifier;
- an optional proposed canonical claim kind;
- actor, extraction tool, and optional model provenance;
- duplicate or conflict hints;
- a revision-guarded review status and disposition.

Candidate rows are mutable only through typed service operations. Every state
transition appends an immutable `icv_` review event. Hints and promotion records
are separate typed rows; they are not encoded as tags or an unvalidated JSON
envelope.

### 2. Automated extraction stops at candidates

LLM/background extraction and the Brain-facing `extract_claims` compatibility
operation create candidates. They do not create `clm_` records. Direct
`POST /api/claims` remains available for an actor that is intentionally
creating a canonical grounded claim, preserving the existing API contract.

### 3. Promotion is explicit and attested

Promotion requires:

- the candidate's current revision;
- an actor and review rationale;
- an explicit assertion that grounding was checked;
- a journal source with a valid typed locator; and
- a proposed claim kind.

Promotion creates a new `clm_`, an active `ipm_` lineage record, and a
`claim derived_from interpretation_candidate` link. The claim also retains its
existing direct journal lineage. Promotion sets grounding fidelity, never
scientific support: `verified=true` and `evidence_status=unassessed` are
deliberately independent.

### 4. Reversal is non-destructive

Revoking a promotion does not delete either object. It revokes the active
`ipm_` record, marks the promoted claim stale, reopens the candidate, and
appends a review event. A later promotion creates a new claim and lineage row.
Historical claims therefore remain auditable without continuing to appear as
current interpretations.

### 5. Source and claim boundaries are explicit

M1 candidates may cite journal, literature, or artifact sources. Because the
current canonical claim schema requires `source_entry_id`, M1 promotion is
limited to journal-backed candidates. Literature- or artifact-backed
candidates can be reviewed, deferred, rejected, classified, merged, or used to
request an evidence mission, but they cannot be silently converted through a
synthetic journal note. Generalized multi-source claim grounding belongs in
the claim-scope/evidence work, not in this migration.

### 6. Experiment execution remains a separate future aggregate

M1 does not model an experiment, run, measurement, or evidence locator beyond
the candidate's source locator. PR 3 will add those types. Its invariant is:

```text
experiment plan -> execution run -> observed result -> interpretation candidate
                  (execution fact)   (measurement)     (scientific meaning)
```

A successful run may ground an observation candidate. It does not prove that
the result supports a hypothesis, establishes causality, generalizes beyond
tested conditions, or licenses manuscript wording.

## Typed locator contract

Locators use columns rather than an opaque document blob:

- `text_offset`, `page`, and `line_range` require a non-negative start and an
  optional end no smaller than the start;
- `section`, `url_fragment`, and `record` require a non-empty value;
- a whole-record locator is explicit (`record: full_record`) rather than
  represented by missing offsets.

The locator identifies where an interpretation came from. It does not attest
that the source is correct.

## Review lifecycle

Review status is `pending`, `in_review`, or `resolved`. Resolved dispositions
are:

- `promoted`;
- `merged`;
- `deferred`;
- `rejected`;
- `classified_decision`;
- `classified_plan`;
- `classified_author_intent`; or
- `evidence_mission_requested`.

Reopen and promotion-revocation operations restore `pending` without erasing
prior review history. Every mutation requires `expected_revision`; a stale
client receives a conflict rather than overwriting newer review work.

## Consequences

- Canonical claims become quieter because extraction no longer equals
  promotion.
- Review workload becomes visible and deterministic.
- Negative, duplicate, conflicting, and non-claim material remains useful
  without leaking into public manuscript prose.
- Existing direct claim clients keep working, but callers relying on
  `extract_claims` returning `clm_` IDs must migrate to candidate review and
  promotion.
- Generalized literature/artifact promotion and run/result semantics remain
  intentionally gated on later milestones.
