# ADR 0010: Typed academic-writing semantics

- Status: accepted
- Date: 2026-08-17
- Scope: M5 / PR 9.2

## Context

The progressive outline has stable `mun_` identities, depth, claim and
evidence bindings, writing rationale, and proposal-first editing.  It does not
yet say what academic job a unit performs, why one evidence item supports the
proposition used in that unit, or which verified reference supports which
literature move.  Those gaps make the outline structurally navigable but still
force the researcher or Writer to reconstruct the argument from prose.

The independent M5 audit recommended a typed-bindings-first design.  The
alternative—six new contract records and a many-dimensional judgment gate—
would duplicate current authorities and increase cognitive load.

## Decision

### One unit identity, independent dimensions

`mun_` remains the canonical manuscript-unit identity.  `outline_level` means
only tree depth.  It never encodes section, paragraph, or rhetorical meaning.
Academic meaning is represented independently:

- `unit_role`: structural writing role (`section`, `argument_block`,
  `paragraph_plan`, `result`, `caption`, `appendix`, `other`);
- `rhetorical_move`: small cross-genre vocabulary describing the unit's main
  move; and
- existing `kind`, communicative job, takeaway, transition, and quick-reader
  fields remain complementary rather than being inferred from depth.

Legacy rows use `unspecified`.  RKA does not invent a role during migration.

### Warrants belong to evidence use

`supported_proposition` and `warrant` live on the unit-to-evidence binding.
They describe what the source-backed claim supports in this unit and the
authorial reasoning connecting it to that proposition.  A warrant is authored
reasoning, never generated evidence and never a substitute for a `clm_`
source.

### Citation records are bindings, not bibliography copies

A unit citation-use binding points to one existing manuscript reference
membership.  It stores only the citation role, supported proposition,
verification state, and optional comparison axis.  Bibliographic metadata
continues to live in `literature` and the manuscript reference manifest.

The core citation roles are `imports`, `bounds`, `baseline`, `extends`, and
`refutes`.  A citation use may be `unverified`, `self_attested`, `verified`, or
`rejected`.  `verified` is accepted only when the bound literature has a DOI
or stable URL and the current manuscript-bound reference validation is
verified.  A citation lacking a stable identifier may remain self-attested,
but cannot be promoted to verified.

### Claim versions state boundaries

Immutable manuscript-claim versions add `conditions` and
`falsification_criteria`.  These fields are versioned with wording because a
claim's defensible boundary changes its meaning.  Migration supplies empty
arrays; missing values are reported, never invented.

### Readiness is deterministic and proportionate

Academic readiness v2 is a computed projection, not stored truth.  Each
dimension reports `pass`, `warn`, or `not_applicable`, plus findings and a
`blocking` flag.  Only deterministic structural failures—invalid hierarchy,
missing claim allocation, or missing required evidence presence—may block.
Missing roles, warrants, claim boundaries, or verified citation use warn.
Claim-level qualifiers and counterevidence that are not allocated to any
active unit also warn with exact IDs. They remain visible in the private
workbench substrate; materiality remains a PI/Writer judgment rather than a
deterministic blocker.
Rhetorical fit, coherence, venue fit, persuasiveness, and reviewer simulation
remain human/LLM judgments and cannot acquit or block canonical state.

### Human approvals bind to complete, portable dependencies

Draft-section checkpoints cover the selected unit's role, rhetorical move,
claim boundaries, evidence propositions and warrants, and citation-use
semantics. Outline checkpoints cover the corresponding manuscript-wide maps.
Snapshots retain normalized dependency components beside their digest for
auditability. Knowledge-pack import rekeys those components and recomputes the
digest, so a faithful import preserves approval currency while a same-unit
semantic change invalidates only the affected approval.

Condense proposals fail closed when the parent and child assign different
semantics to the same evidence or citation identity. RKA never chooses one
warrant, verification state, or comparison axis by insertion order.

### Agents propose spine replacement; humans apply it

The legacy MCP `upsert_argument_spine` name remains parseable for compatibility
but performs no write and returns a structured deprecation response. Agents
prepare attributable `argument_spine_replace` semantic-patch proposals. A PI or
web user applies the reviewed full-replacement proposal separately.

### Private analysis and public prose stay separate

Negative, conflicting, abandoned, and reviewer-risk material remains visible
in RKA's private author substrate.  Public prose is strength-first and
evidence-bounded.  Material limitations must be handled where they affect a
claim; non-material or speculative concerns need not be copied into public
prose.  An unresolved materiality classification is not treated as permission
to omit a material concern.

## Consequences

- The migration is additive and project-scoped.
- Knowledge packs must round-trip and rekey every new binding.
- Knowledge-pack import recomputes checkpoint digests after rekeying their
  auditable dependency components.
- Outline proposals and bulk spine synchronization preserve the new fields.
- The workbench uses progressive disclosure: role/move are primary controls;
  warrants, citation-use currency, and private adverse evidence appear next to
  the binding or claim they qualify.
- Markdown/LaTeX file synchronization, anchors, and merge policy remain PR 10.
- No embedded LLM or automatic Git operation is introduced.
