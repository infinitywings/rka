# ADR 0009: Progressive outline and manuscript-unit editing

- Status: accepted for M5 / PR 9 implementation
- Date: 2026-08-15
- Baseline: `infinitywings/rka` `main` merge `a49475b`
- Scope: L2-L5 outline hierarchy, writing rationale, semantic edit previews,
  binding-preserving expansion/condensation, reorder impact, and Outline gates

## Context

The ratified argument and evaluation records now produce stable `mcl_` claims
and `mun_` result units, but the Outline stage is still read-only. A useful
editor must let a researcher elaborate a paper from broad units to finer
argument beats and evidence intentions without creating a second source of
truth or silently losing claim/evidence bindings during structural edits.

## Decision

### 1. Keep `mun_` as the unit identity and add a one-to-one outline profile

Every active outline card is a native manuscript unit. Optional outline-profile
metadata supplies its L2-L5 level, parent unit, communicative job, intended
reader takeaway, transition, quick-reader role, evidence plan, figure/table/
citation intentions, and current blocker. Existing units remain readable but
are reported as incomplete until the required rationale is supplied.

`outline_level` is hierarchy depth only: L2 is the shallowest stored unit and
L5 the deepest. It does not encode a rhetorical type or require every L2 unit
to be a section or every L5 unit to be claim-sized. Unit `kind`,
`communicative_job`, and `intended_takeaway` carry those semantics. Every
parent must have a strictly shallower depth than its child.

The profile is not a second outline authority. It is stored in the same
manuscript aggregate, exported with the argument spine, guarded by manuscript
revision, and covered by the same checkpoint dependency snapshot.

### 2. Make every structural edit a proposal

Direct edits, expansion, condensation, and reorder requests are deterministic
server-side transformations of the current exported spine. The server creates
an ordinary ADR 0006 `argument_spine_replace` proposal. No action mutates the
manuscript before the researcher inspects and explicitly applies that proposal.

The request names intent, affected stable local keys, and new structured
content. It cannot supply a forged before-state. Apply rechecks the manuscript
revision and fingerprint transactionally.

An AI author must first persist an exact context manifest and label the
proposal `host_agent` or `lm_studio` with provider, model, and boundary. AI/MCP
transports may prepare proposals but cannot apply or reject them. Only a PI or
the local web UI may perform the review transition. This is a local
interaction guard, not network authentication; remote deployments still need
their own authenticated transport boundary.

The public human bulk-replacement compatibility route also creates and applies
an attributed proposal ledger entry. The direct native upsert remains an
internal service primitive for reviewed apply and import transactions, not an
agent-facing mutation bypass.

### 3. Preserve semantic bindings by construction

- Edit preserves all unspecified unit fields, claim links, and evidence roles.
- Reorder requires exactly the current active unit-key set and changes only
  sequence. Parents must precede children and each subtree must remain
  contiguous. Its preview reports changed predecessors and transition risks.
- Expand keeps the parent and creates children one level lower. Children inherit
  the parent's claim links and typed support/qualifier/counterevidence bindings
  unless the request explicitly narrows them to subsets.
- Condense keeps the parent, unions child claim/evidence bindings onto it, and
  marks the selected descendants removed. Other descendants are never swept in
  implicitly.

The validator rejects unknown parents, self-parenting, cycles, a parent whose
level is not above its child, foreign evidence, duplicate local keys, and
binding subsets that were not present on the source unit.

### 4. Treat rationale completeness and checkpoint state separately

The outline projection reports a blocker per active unit when communicative
job, intended takeaway, intended claim, or evidence plan is missing. It also
reports the latest Outline checkpoint and whether the current dependency
snapshot is pending, resolved, rejected, or superseded.

A proposal may still be prepared while incomplete so researchers can work
incrementally. Creating or resolving the Outline checkpoint stays an explicit
existing manuscript operation. Any applied spine edit invalidates a resolved
Outline checkpoint only when its dependency snapshot changes.

The Outline checkpoint dependency snapshot includes exact claim/unit evidence
roles and relevant source state. Rebinding support as qualifier, adding
counterevidence, or changing the evidence source therefore supersedes the
earlier approval even when unit prose and order are unchanged.

### 5. Keep manuscript files out of PR 9

PR 9 edits semantic outline units only. Markdown/LaTeX file creation, source
anchors, merge conflicts, and filesystem synchronization remain PR 10. The UI
must label locations and citation/figure/table intentions as plans, not as proof
that files or references already exist.

## Consequences

- A researcher can collapse or expand L2-L5 structure without losing the
  higher-level parent or provenance links.
- Canonical mutation, AI assistance, and direct editing converge on the same
  review ledger.
- Existing manuscripts migrate safely and reveal missing rationale instead of
  receiving invented metadata.
- PR 10 can attach source files to stable `mun_` identities without redesigning
  outline authority.
