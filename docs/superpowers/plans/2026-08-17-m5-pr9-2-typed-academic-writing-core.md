# M5 / PR 9.2 — Typed academic-writing semantic core

## Outcome

Make the progressive outline useful as an academic argument workbench: a
researcher can see what each unit does, which claims and references it carries,
what proposition each evidence item supports, and why that support is
defensible.  The implementation must remain lighter than a form-heavy contract
system and must not make model judgment a hard gate.

## Schema

Migration 049 is additive:

1. `manuscript_unit_outline_profiles`
   - `unit_role` with an honest `unspecified` legacy default;
   - `rhetorical_move` with an honest `unspecified` legacy default.
2. `manuscript_unit_evidence`
   - nullable, non-blank `supported_proposition` and `warrant`.
3. `manuscript_claim_versions`
   - JSON arrays `conditions` and `falsification_criteria`.
4. `manuscript_unit_citations`
   - project/manuscript/unit/reference-membership FKs;
   - typed citation role;
   - supported proposition, verification state, optional comparison axis;
   - semantic change events for insert/update/delete.

No bibliographic metadata is duplicated.  No existing row is semantically
backfilled from heuristics.

## Service and API contract

- Native context and spine projections include all new fields.
- Spine input accepts evidence-use objects while retaining ID-only input as a
  compatibility form; output carries both typed uses and legacy ID arrays.
- Citation uses are addressed by citation key on portable input and resolved
  to the current manuscript reference membership on write.
- `verified` citation uses fail closed unless stable identity and current
  reference validation are present.
- Exact replays remain no-ops; changed warrants/citations bump revision and
  invalidate only affected outline/draft approvals.
- Outline edit/expand/condense preserves typed use metadata.
- REST and typed MCP reuse the existing manuscript-spine and outline-proposal
  operations; no parallel mutation path is added.

## Readiness v2

The outline projection adds `academic_readiness` with deterministic dimensions:

- structure;
- claim allocation;
- evidence presence;
- evidence-use explanation;
- claim boundaries;
- citation support; and
- rhetorical annotation.

Every dimension is `pass`, `warn`, or `not_applicable`.  Findings name exact
unit/claim/evidence/reference IDs.  Only the first three dimensions can set a
blocking finding, and only from deterministic absence or invalidity.

## Workbench behavior

- Unit role and rhetorical move are editable through the existing semantic
  proposal form.
- Evidence proposition/warrant and citation-use state are shown alongside the
  unit, behind an academic-support disclosure.
- Readiness is summarized with the next actionable deterministic gap; detailed
  findings remain available without turning the screen into a compliance form.
- Private reviewer-risk material is never rendered as manuscript prose.

## Verification

- migration fresh/restart/late-application tests;
- service no-op and one-field-change tests;
- stable-identifier and reference-validation enforcement;
- REST/MCP typed schema and dispatch parity;
- knowledge-pack export/import/rekey, deletion, and change-cursor tests;
- frontend type/build/lint tests;
- disposable real-project-derived outline with one support warrant, one
  qualified/counterevidence use, one verified citation, and one self-attested
  citation;
- full Python suite and production web build, with pre-existing failures
  reproduced against untouched main before being classified as baseline.

## Non-goals

Source-file synchronization, stable source anchors, three-way merge, LaTeX
macro parsing, argument dependency graphs, embedded model orchestration,
automatic Git actions, Source Inbox, ARA viewer, and reviewer-score prediction.

