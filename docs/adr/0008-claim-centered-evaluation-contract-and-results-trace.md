# ADR 0008: Claim-Centered Evaluation Contract and Results Trace

- Status: accepted for M4 / PR 8 implementation
- Date: 2026-08-15
- Scope: roadmap issue #59
- Depends on: ADR 0004 experiment evidence, ADR 0005 planning branches,
  ADR 0006 semantic patches, and ADR 0007 contribution promotion
- Related plan:
  [`2026-08-15-m4-pr8-evaluation-contract.md`](../superpowers/plans/2026-08-15-m4-pr8-evaluation-contract.md)

## Context

The workbench can now promote bounded contribution candidates into exact native
manuscript claims. It still lacks the next scientific contract: what evidence
would support or falsify each claim, which exact experiment plan and run
produced available evidence, what remains missing, and what language the result
actually permits.

Journal entries, repository state, and fluent result summaries are not adequate
substitutes for this contract. They can be noisy, stale, incomplete, or written
before the governing claim was narrowed. PR 8 therefore connects the
provisional paper plan to the canonical experiment substrate without allowing
planning text to become evidence or allowing an outcome direction to be
silently reinterpreted as support.

## Decision 1: Keep the evaluation contract provisional and versioned

The evaluation matrix is the typed payload of the existing `evaluation`
planning stage. Every structured commitment has a stable `local_key` and pins:

- one exact native manuscript claim and wording version;
- the research-question decisions it answers;
- one or more evidence requirements;
- the intended method, baselines, metrics, conditions, success criteria, and
  failure criteria; and
- allowed interpretation plus explicitly prohibited extensions.

Editing a commitment appends a planning-artifact version. It never rewrites an
experiment, observation, claim, mission, or manuscript unit.

Legacy free-text evaluation commitments remain readable, but they are not
promotion-ready. A researcher must revise them into the structured contract
before the deterministic workflow can become ready.

## Decision 2: Bind evidence at exact experiment granularity

Each evidence requirement has a stable key and, when applicable, pins one
`exp_`, one exact `epv_`, and its plan version number. Available evidence is an
explicit list of observation bindings. Every binding names:

- the exact `obs_`;
- one or more exact `elc_` locators;
- the observation's role in the evaluation;
- a controlled outcome: `supports`, `partially_supports`,
  `fails_to_support`, `inconclusive`, or `exploratory`;
- its effect on the claim as written; and
- a bounded interpretation note.

The server verifies project ownership and the complete experiment -> plan ->
run -> observation -> locator chain. It does not infer support from a positive
metric direction, infer failure from a negative metric direction, or treat the
existence of a run as evidence.

## Decision 3: Treat adverse and ambiguous outcomes as constraints

`fails_to_support`, `inconclusive`, and `exploratory` are preserved verbatim in
the workflow projection. They cannot satisfy a required conclusive-evidence
slot merely because data exists.

Every observation binding also records a claim effect:

- `supports_as_worded`;
- `requires_narrowing`;
- `negative_result`;
- `exploratory_only`; or
- `unresolved`.

The server rejects logically incompatible pairs, such as
`fails_to_support` plus `supports_as_worded`. An unresolved adverse outcome is
blocking. A reviewed narrowing or negative-result disposition remains visible
as `Needs review` until the relevant claim and result unit are aligned. Public
prose may be selective and persuasive, but it may not contradict this private
contract or broaden the allowed interpretation.

## Decision 4: Compute readiness categorically, with reasons

The evaluation workflow reports `Ready`, `Needs review`, `Blocked`, or
`Exploratory`; it never collapses scientific readiness into a numeric score.
For each commitment and evidence requirement it reports exact resolved records,
missing or invalid links, outcome constraints, prior action lineage, and the
next useful action.

At minimum, a ready selected commitment must have:

- a current, active exact manuscript claim version;
- resolvable active RQ decisions;
- at least one structured required-evidence statement;
- exact experiment-plan and observation-locator closure where empirical
  evidence is required;
- no unresolved adverse outcome;
- explicit allowed and prohibited interpretations; and
- a selected, mechanically ready evaluation artifact with reviewed upstream
  heads.

Missing evidence is a work item, not a sentence-completion opportunity.

## Decision 5: Promote missing evidence only through explicit missions

For one selected commitment requirement that still lacks conclusive evidence,
an explicit action may create a canonical `mis_`. The mission includes the
requirement, experiment intent, acceptance/failure criteria, scope boundaries,
and exact planning-version provenance. An immutable evaluation-action event
links the source contract version to the mission.

Mission preparation is idempotent for one artifact version and requirement.
Replanning requires a new evaluation artifact version rather than silently
rewriting the old mission's provenance.

## Decision 6: Create result units only through semantic review

When exact located observations exist, an explicit action may prepare an ADR
0006 `argument_spine_replace` proposal that adds or revises one native result
unit. The proposal:

- links the result unit to the exact manuscript claim with relationship
  `tests`;
- carries forward the claim's typed support, qualifier, and counterevidence;
- requires a same-project canonical result artifact;
- copies the contract's allowed and prohibited interpretation boundaries; and
- records exact observation and locator identifiers in its audit details.

The proposal action may copy the current claim boundary only when the located
evidence is explicitly classified as `supports_as_worded`. A
`requires_narrowing`, `negative_result`, `exploratory_only`, or `unresolved`
effect must first revise or replace the manuscript claim and evaluation
contract. This prevents an adverse result from inheriting the old claim's
positive allowed interpretation.

Preparation does not change the manuscript. Application is a separate explicit
semantic-patch action. The evaluation-action ledger records both preparation
and the exact resulting `mun_` after application.

## Decision 7: Add an immutable evaluation-action ledger

The project-scoped ledger records:

- missing-evidence mission creation;
- result-unit proposal preparation; and
- result-unit proposal application.

Each row pins the branch revision, artifact and artifact version, commitment
and optional requirement key, target identifier and version, actor, reason,
proposal when applicable, and structured details. The ledger is append-only,
included in change cursors and knowledge packs, deleted only through authorized
whole-project deletion, and exposed consistently through REST and MCP.

## Decision 8: Preserve round-trip manuscript semantics

The native spine export used to prepare a result proposal must round-trip unit
titles, ordering, all evidence roles, and exact claim-unit relationship types.
Adding a result unit must not silently turn an existing `tests` or `bounds`
relationship into `advances`, discard qualifier/counterevidence, or erase unit
metadata.

## Consequences

- A paper claim has an auditable path from evaluation intent to exact results.
- Noisy journal prose remains context rather than empirical authority.
- Negative and inconclusive results narrow or block claims instead of being
  polished into success.
- Missing evidence becomes executable, provenance-linked work.
- Result-unit drafting remains reviewable and conflict-safe.
- PR 8 requires typed payloads, deterministic projection, a migration, guarded
  actions, REST/MCP/pack/delete parity, a matrix UI, and real-project testing.
