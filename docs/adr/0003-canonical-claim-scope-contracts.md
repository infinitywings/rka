# ADR 0003: Canonical claim scope contracts

- Status: accepted and implemented in M1 PR 2
- Date: 2026-08-14
- Depends on: ADR 0002 Interpretation Staging

## Context

Canonical RKA claims (`clm_`) currently preserve source grounding, a numeric
confidence, independent scientific evidence status, staleness, and graph
contradictions. They do not preserve the conditions under which a claim is
intended to hold, which extensions are licensed or prohibited, how uncertainty
should be interpreted, or what would falsify the claim.

Interpretation candidates (`icd_`) already carry source-bounded preliminary
scope, uncertainty, and an optional falsifier. Those fields are immutable
extraction-time observations. They are not a reviewed contract for later use.

Native manuscript claims (`mcl_`) separately preserve exact, allowed, and
prohibited paper wording. Those limits are manuscript-specific and PI-ratified.
They must not be reused as the research-level scope of a canonical claim.

## Decision

### 1. Add immutable canonical claim-scope versions

Each reviewed or revised scope contract is appended as a `csc_` row in
`claim_scope_versions`. A claim stores only the current scope revision number.
Earlier versions remain immutable and project-portable.

Every version records:

- the claim content/type fingerprint to which it applies;
- typed applicability conditions;
- uncertainty level and explanation;
- an explicit extension policy: exact claim only, or bounded extensions;
- allowed and prohibited extensions;
- falsifier applicability, statement, and rationale;
- same-project canonical claims treated as disconfirming observations;
- draft/reviewed state, actor, reason, and optional originating candidate;
- the prior scope version it supersedes.

Appending a version requires `expected_revision`. Revision zero means the
claim has no scope contract. Stale clients receive a conflict rather than
overwriting newer review work.

### 2. Keep three distinct boundaries

| Boundary | Object | Meaning |
|---|---|---|
| Extracted/source-bounded | `icd_` | What the source passage appears to say under its recorded locator. |
| Canonical research scope | `csc_` for `clm_` | Conditions and inference limits for reusing a canonical research claim. |
| Manuscript wording | versioned `mcl_` | Paper-specific wording ratified for one manuscript. |

Promotion from an interpretation candidate creates a draft canonical scope
version that preserves candidate conditions, uncertainty, and falsifier
without inferring extension policy, prohibited extensions, or missing
semantics. It does not create manuscript wording or PI ratification.

### 3. Represent conditions without pretending unparsed text is structured

Canonical conditions are typed records with a condition kind, key, operator,
value, optional unit, and optional note. Supported operators cover equality,
set membership, ranges, inequalities, presence/absence, and a conservative
`described_by` fallback.

When a candidate contains only a free-text condition, promotion preserves it
as `kind=other`, `key=source_condition`, `operator=described_by`. RKA does not
guess a dataset, platform, threat model, metric, or numeric bound.

### 4. Make absence and inapplicability explicit

An extension policy is either:

- `exact_only`: no extension beyond the canonical claim is licensed; or
- `bounded`: one or more explicit extensions are licensed.

The falsifier state is `unknown`, `applicable`, or `not_applicable`.
`applicable` requires a falsifier statement. `not_applicable` requires a
rationale. This avoids treating an empty field as a scientific judgment.

### 5. Derive readiness; do not store a self-asserted ready flag

`scope_readiness` is computed from the current immutable version:

- `missing`: no scope version exists;
- `stale`: the version fingerprint does not match the current claim
  content/type;
- `incomplete`: required semantic fields remain unresolved;
- `needs_review`: semantically complete but still draft;
- `ready`: complete, current, and explicitly reviewed.

Contradiction, claim staleness, and scientific evidence status remain separate
dimensions. A scope may be well specified while the claim is contradicted.
RKA therefore returns explicit findings instead of laundering scientific
standing into scope readiness.

### 6. Preserve legacy behavior without inventing a backfill

Migration 041 adds `claims.scope_revision` with default zero and creates the
version table. Existing claims receive no generated scope row and project as
`scope_readiness=missing`.

Existing claim create/update clients remain valid. Scope writes use a separate
revision-guarded API. Changing claim content or type does not mutate history;
the prior scope projects as `stale` until a reviewer appends a new version.

### 7. Make scope a first-class portable and observable contract

Current scope and readiness are exposed through claim REST responses, MCP
queries, graph claim metadata, native manuscript evidence reads, and the web
workbench. Full immutable history is available through a dedicated claim-scope
read endpoint. Scope writes are available through one explicit append
operation shared by web and MCP clients.

Knowledge packs export, remap, import, and integrity-check scope versions.
Project deletion is the only authorized deletion path. Scope-version inserts
emit semantic change events so manuscript impact analysis can trace affected
evidence claims and units.

## Review invariants

A `reviewed` contract must:

1. describe at least one condition;
2. resolve uncertainty to a value other than `unknown`;
3. choose an extension policy;
4. provide allowed extensions when policy is `bounded`;
5. provide at least one prohibited extension;
6. resolve falsifier applicability and supply the corresponding statement or
   rationale;
7. reference only existing same-project disconfirming claims other than
   itself.

Draft versions may be incomplete so promotion and incremental curation remain
lossless.

## Consequences

- Legacy projects visibly acquire scope-review work instead of fabricated
  readiness.
- Claim content/type edits invalidate, rather than silently reuse, an older
  boundary.
- Manuscript candidate generation can reject or flag evidence whose canonical
  scope is missing, stale, incomplete, or unreviewed.
- A reviewed scope contract does not establish scientific support, resolve a
  contradiction, or ratify manuscript wording.
- PR 3 remains responsible for experiments, runs, measurements, tested
  conditions, and result locators. A scope condition does not prove that an
  experiment was executed under that condition.
