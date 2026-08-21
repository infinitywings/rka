# M5 PR 9.1 — Outline and Knowledge-Pack Integrity Hardening

## Outcome

Make the merged progressive-outline foundation safe to move between RKA
installations and quiet enough to support long manuscripts. The same semantic
state must survive export/import/rekey, the importer must enforce the same
hierarchy accepted by the manuscript service, and mechanical no-op rewrites
must not masquerade as research changes.

## Invariants

1. Knowledge-pack import never silently drops an unknown semantic column.
2. The reserved agentic staleness-resolution schema is portable and keeps its
   original migration identity (`030_staleness_resolution.sql`).
3. Imported outline profiles obey the canonical cycle, parent-depth,
   parent-before-child, active-parent, and contiguous-subtree rules before the
   transaction may commit.
4. Rekeying updates exact and embedded entity IDs in all four outline-intention
   JSON fields and in staleness-resolution references.
5. Insert, update, and delete events for outline profiles identify both the
   manuscript and manuscript unit in the semantic change cursor.
6. Expansion may intentionally narrow inherited evidence, but every removed
   support, qualifier, or counterevidence binding is visible in the immutable
   proposal warning set.
7. `rationale_complete` names rationale completeness. The historical
   `checkpoint_ready` field remains a deprecated response alias for one
   compatibility window and is no longer used by the web workbench.
8. Replaying an identical spine is a true no-op. A partial edit updates only
   rows and binding sets whose semantic values changed.

## Compatibility policy

The importer remains strict for genuinely unknown columns. Cross-version
compatibility is achieved by adopting the already-deployed additive migration,
not by filtering uploaded rows. Existing agentic databases have migration 030
recorded and skip it; main-line databases apply it once even if later migration
numbers are already present. Import rekeying preserves resolution prose and
rewrites its journal reference.

## Test gates

- fresh and late-application migration-030 coverage, including CHECK values;
- migration-048 insert/update/delete attribution and idempotent restart;
- corrupt-pack rollback for cycles, depth inversion, removed parent,
  child-before-parent order, and non-contiguous subtrees;
- intention JSON plus staleness-resolution round-trip/rekey;
- exact no-op and one-field-edit change-event counts;
- expansion warning parity for all three evidence roles;
- REST/MCP/projection compatibility for `rationale_complete`;
- full Python suite, production web build, changed-file lint, and a disposable
  real-project-derived pack round-trip.

## Non-goals

Typed rhetorical roles, warrants, citation verification, readiness v2, draft
file synchronization, and embedded LLM orchestration remain PR 9.2 or PR 10
work. PR 9.1 changes integrity and observability, not manuscript meaning.
