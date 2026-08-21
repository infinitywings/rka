# ADR 0007: Seed-to-Contribution Guidance and Promotion

- Status: accepted for M4 / PR 7 implementation
- Date: 2026-08-15
- Scope: roadmap issue #58
- Depends on: ADR 0005 planning branches and ADR 0006 semantic patch proposals
- Related plan:
  [`2026-08-14-rka-epistemic-pipeline-and-manuscript-workbench.md`](../superpowers/plans/2026-08-14-rka-epistemic-pipeline-and-manuscript-workbench.md)

## Context

M3 made provisional manuscript planning resumable and made human and AI edits
share one conflict-safe proposal path. M4 must now guide a researcher from a
small insight to bounded research questions and contribution candidates without
turning the workbench into a rigid wizard or allowing a planning selection to
masquerade as canonical RKA semantics.

The current planning payloads provide typed stage containers, but PR 7 also
needs stable identities inside a stage, deterministic stage readiness, a
quick-reader projection, and an exact promotion path. In particular, one
`rq_contribution` artifact may contain several research-question and
contribution candidates. The artifact-level `promotion_target_*` fields cannot
represent the independent lifecycle and lineage of each candidate.

## Decision 1: Keep one guided but non-linear argument workflow

The PR 7 workflow covers these planning stages:

1. `seed`;
2. `paragraph_spine`;
3. `problem_scope`;
4. `landscape_gap`;
5. `response_mechanism`;
6. `challenge_innovation`; and
7. `rq_contribution`.

The interface may render landscape and gap, or RQs and contributions, as
separate views. They still resolve to the same typed planning artifacts above,
so navigation does not create a second storage model.

The stage rail recommends a next decision but never locks navigation. A
researcher may jump, fork a branch, compare alternatives, revise an upstream
artifact, combine options, or park unresolved work. Downstream artifacts remain
visible after an upstream edit, but their readiness becomes `blocked` or
`in_progress` until the researcher reviews the resulting mismatch.

## Decision 2: Give every promotable candidate a stable local identity

Structured stage payloads use stable `local_key` values for options, landscape
rows, challenge/innovation nodes, RQ candidates, and contribution candidates.
Changing wording appends an artifact version while preserving the local key.
A materially different idea receives a new local key rather than inheriting
promotion lineage accidentally.

RQ candidates record at least:

- exact question and bounded scope;
- rationale and assumptions;
- linked evidence and unresolved evidence needs;
- candidate disposition: `candidate`, `selected`, or `parked`.

Contribution candidates record at least:

- exact provisional wording and contribution type;
- linked RQ candidate keys or existing `dec_` identifiers;
- allowed wording and prohibited extensions;
- support, qualifier, and counterevidence identifiers;
- tested or intended conditions;
- novelty and significance risks;
- intended manuscript units and missing evidence;
- candidate disposition.

Entity identifiers inside a candidate must resolve to the same project and be
present in the artifact version's evidence/context bindings. Text inside a
planning artifact remains author intent or deliberation; it is never empirical
evidence.

## Decision 3: Make choice-first guidance an interaction contract

For one consequential framing decision, the workbench may offer two to four
genuine alternatives. Each option discloses:

- the proposed wording or structure;
- the evidence and assumptions behind it;
- its benefit, risk, and likely paper-level effect;
- unresolved conflicts or missing evidence; and
- why an option is recommended, when a recommendation is justified.

The available actions are select, revise, combine, park, or gather evidence.
Micro-selections are advisory and append planning versions. They do not create
a canonical decision, claim, or PI ratification. AI-generated choices use the
ADR 0006 context-manifest and semantic-patch path.

## Decision 4: Compute stage readiness deterministically

The selected branch exposes one deterministic argument-workflow projection.
For every stage it reports:

- the effective artifact and immutable version;
- lifecycle and categorical readiness;
- evidence bindings, assumptions, unresolved items, and conflicts;
- prerequisite and dependent stages;
- upstream versions used by the current artifact; and
- the next useful action.

The four user-facing verdicts remain `Ready`, `Needs review`, `Blocked`, and
`Exploratory`. Stored planning readiness remains the existing three-state
contract (`ready`, `in_progress`, `blocked`); `Exploratory` is a view state for
an absent or intentionally incomplete artifact, not a persisted claim about
quality.

An artifact cannot be `Ready` for promotion merely because required text fields
are populated. At minimum it must be selected, have no unresolved blocking
item, satisfy its typed schema, and meet the stage-specific evidence boundary.

## Decision 5: Separate selection, promotion, application, and ratification

Selecting a candidate changes only provisional planning state.

### Research-question promotion

Promoting one selected RQ candidate is a dedicated explicit PI action. It
creates a same-project `dec_` with `kind="research_question"`,
`decided_by="pi"`, and exact candidate wording, scope, rationale, assumptions,
and source lineage. It does not promote sibling candidates and cannot operate
on a stale artifact version.

### Contribution promotion

Promoting one selected contribution candidate first prepares an ADR 0006
`argument_spine_replace` proposal against the exact manuscript revision. The
proposal includes the candidate's bounded wording and typed claim evidence.
Creating the proposal does not modify the manuscript.

The researcher then explicitly applies the proposal. Application creates or
appends the native `mcl_` wording version, but the new exact wording remains
unratified.

Finally, a separate explicit PI action creates or selects an active PI decision
whose chosen text exactly matches the claim wording and binds that decision to
the exact `mcl_` version through the native ratification service. A changed
claim version requires a new ratification. The workbench must never describe
proposal creation or proposal application as PI ratification.

## Decision 6: Add an immutable candidate-promotion ledger

PR 7 adds an immutable, project-scoped ledger keyed by planning artifact
version and candidate local key. It records the independent events:

- RQ promoted to a `dec_`;
- contribution proposal prepared as an `spp_`;
- proposal applied to an exact `mcl_` version; and
- exact contribution version ratified by a `dec_`.

Each event records actor, reason, branch revision, candidate kind, exact target
and target version where applicable, and the relevant proposal or decision ID.
The ledger is included in change cursors, knowledge packs, whole-project
deletion, REST/MCP reads, and project-isolation checks. Events are append-only;
superseding wording adds lineage rather than rewriting history.

## Decision 7: Make the quick-reader spine a deterministic projection

The quick-reader view composes, in order:

- concrete problem and scope;
- defensible SOTA gap;
- core insight and response;
- challenge and innovation;
- selected RQs;
- selected or canonical contributions;
- strongest evidence preview; and
- boundary or reader payoff.

It reads the selected planning branch and current canonical manuscript. It does
not call an LLM at render time. Every sentence or slot identifies its source
artifact version or canonical record and labels provisional, applied, and
ratified content distinctly. When the paragraph spine disagrees with newer
stage artifacts or canonical wording, the discrepancy is visible rather than
silently reconciled.

## Decision 8: Preserve provider neutrality and public/private boundaries

PR 7 requires no server-side external model. Direct editing, host agents, and
LM Studio all use the same semantic proposal envelope. Provider output may
suggest choices but cannot promote or ratify them.

The internal view continues to show negative evidence, unresolved conflicts,
rejected alternatives, and material limitations. The quick-reader/public view
is a selective persuasive projection, but it may not broaden a claim, erase a
material boundary, or contradict the private evidence record.

## Consequences

- Researchers can iterate non-linearly without losing an auditable argument
  history.
- RQ and contribution candidates gain independent, exact promotion lineage.
- Applying manuscript wording and ratifying it remain visibly different acts.
- The quick-reader view reduces cognitive load without becoming a generated
  source of truth.
- PR 7 requires a migration, typed promotion models and services, REST/MCP and
  pack parity, an editable stage canvas, and real-project workflow tests.

## PR 7 implementation slices

1. Add stable candidate payloads, deterministic workflow projection, and the
   immutable promotion ledger.
2. Add choice-first stage editors that create ADR 0006 semantic proposals and
   support branch, compare, revise, combine, and park actions.
3. Add RQ promotion, contribution-proposal preparation, proposal/application
   status, and exact PI ratification controls.
4. Add the traceable quick-reader spine and evidence/conflict detail views.
5. Run service, API, MCP, migration, pack, project-isolation, browser,
   accessibility, restart/resume, concurrency, and real-project gates.
