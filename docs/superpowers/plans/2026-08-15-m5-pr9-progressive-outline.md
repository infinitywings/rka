# M5 / PR 9 implementation plan: progressive outline and unit editor

## Outcome

Turn a ratified argument spine into a resumable L2-L5 outline whose units carry
writing rationale, intended claims, and evidence plans. All changes remain
proposal-first and auditable.

## Contract slice

1. Add a project/manuscript-scoped one-to-one outline profile for every `mun_`.
2. Extend native context and deterministic spine export with hierarchy and
   writing-rationale fields.
3. Add an outline projection with per-unit completeness, reverse claim links,
   typed evidence, parent/child navigation, and current Outline checkpoint.
4. Add deterministic proposal preparation for edit, expand, condense, and
   reorder. Reuse ADR 0006 apply/reject and conflict behavior.
5. Expose equivalent REST and typed MCP operations.
6. Add an Outline-stage editor that shows hierarchy, rationale, provenance,
   blockers, downstream reorder impact, and the separate proposal ledger.
7. Include the profile in knowledge packs, project deletion, and semantic
   change accounting.

## Required invariants

- Stable `mun_` and `mcl_` identities survive edit and reorder.
- Expand retains its parent; children can inherit only disclosed source
  bindings.
- Condense unions bindings into the retained parent before descendants are
  removed.
- Reorder receives the exact active-key set and changes no semantic content.
- No proposal creates PI ratification or resolves an Outline checkpoint.
- Old or incomplete units remain visible with categorical blockers.
- Cross-project parents, claims, evidence, proposals, and checkpoints fail
  closed.

## Test and release gate

- Fresh migration and legacy-unit compatibility.
- Service tests for all four actions, hierarchy validation, binding
  preservation, stale-base conflict, and checkpoint invalidation.
- REST/MCP parity and exact project scoping.
- Knowledge-pack round trip/rekey, project deletion, and foreign-key check.
- Full Python suite, production web build, changed-file lint, isolated restart
  and resume, and a disposable real-project browser walkthrough.
- No live RKA research project receives semantic writes during acceptance.
