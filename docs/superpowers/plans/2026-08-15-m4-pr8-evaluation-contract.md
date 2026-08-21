# M4 PR 8: Evaluation Contract and Results Trace Implementation Plan

## Goal

Connect every major manuscript claim to the evidence needed to support or
falsify it, the exact evidence currently available, the work needed to close
gaps, and the strongest interpretation the current record permits.

## Slice A: Typed contract and deterministic read model

1. Replace the draft-only evaluation payload with stable structured
   commitments, evidence requirements, and explicit observation outcomes while
   retaining read compatibility for legacy commitments.
2. Validate that every referenced canonical entity is disclosed in the
   planning version's evidence bindings.
3. Add an evaluation-workflow projection that resolves exact claim versions,
   RQ decisions, experiment plan versions, runs, observations, and locators.
4. Return categorical readiness and concrete blocker/warning/next-action text;
   never return a synthetic quality score.

## Slice B: Guarded canonical actions

1. Add an immutable evaluation-action ledger.
2. Create one idempotent missing-evidence mission action for a selected,
   unresolved requirement.
3. Prepare one semantic result-unit proposal from located observations and a
   verified same-project artifact.
4. Record the exact `mun_` and manuscript revision after explicit proposal
   application.
5. Preserve all existing spine relationship, evidence, title, and ordering
   semantics during proposal round trips.

## Slice C: Surface parity

1. Add REST reads/actions and error mappings.
2. Add MCP reads/actions with explicit project IDs.
3. Register the ledger in knowledge-pack export/import/integrity and whole-
   project deletion.
4. Add change tracking for every canonical evaluation action.

## Slice D: Workbench

1. Extend the guided stage editor to the evaluation stage with a structured
   starter contract.
2. Render a claim-centered matrix with evidence requirements, exact run and
   locator links, outcome/claim-effect badges, categorical readiness, and
   action lineage.
3. Offer explicit mission and result-proposal actions only when server
   preconditions permit them.
4. Keep adverse outcomes and missing evidence visible in the private interface;
   distinguish proposal prepared, applied, and canonical result states.

## Verification gates

- Model tests reject unknown references, missing bindings, duplicate stable
  keys, incompatible outcome/effect pairs, and under-specified selected
  commitments.
- Service/API/MCP tests cover project isolation, stale branch/manuscript
  revisions, idempotence, negative/inconclusive behavior, and proposal
  prepare/apply lineage.
- Migration tests prove immutability, deletion authorization, and change-event
  emission.
- Knowledge-pack round trip preserves the ledger and every foreign key.
- The full Python suite and production web build pass.
- Browser tests exercise keyboard navigation, narrow/wide layouts, error and
  empty states, matrix inspection, mission creation, and proposal preparation.
- A disposable clone of a real project is taken from seed/contribution through
  evaluation contract, missing-evidence mission, exact observation/locator
  binding, result-unit proposal, apply, restart/resume, and pack round trip.

## Exit evidence

The PR description must identify the exact test commands, counts, browser
scenarios, real-project clone ID, created evaluation artifact/version, mission,
experiment plan/run/observation/locator, proposal, and resulting manuscript
unit. It must also state any untested boundary without presenting it as passed.
