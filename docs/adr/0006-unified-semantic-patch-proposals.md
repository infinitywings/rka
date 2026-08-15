# ADR 0006: Unified semantic patch proposals

- Status: accepted for M3 / PR 6 implementation
- Date: 2026-08-15
- Baseline: `infinitywings/rka` `main` merge `5ec717f`
- Scope: human and AI edit proposals, semantic preview, optimistic apply,
  conflict preservation, context manifests, and provider boundaries

## Context

The workbench can now preserve alternative planning branches, but edits still
arrive through unrelated mutation routes. A direct form edit, a host-agent
suggestion, and a local-model suggestion need one reviewable contract. Letting
any provider call canonical mutation routes directly would erase the distinction
between generation and researcher approval and would make stale suggestions
dangerous.

## Decision

### 1. Use one immutable proposal envelope

Every semantic edit is first stored as an `spp_` proposal. Supported operations
are deliberately narrow:

- append a version of a provisional planning artifact;
- update descriptive manuscript metadata; and
- replace the canonical argument-spine projection.

Lifecycle transitions, claim ratification, reference validation, experiment
records, and authoring-file patches stay outside this contract. They retain
their existing domain-specific gates.

The server captures the current target snapshot, computes the semantic diff,
validates the proposed result, and records warnings. Callers provide intent and
the desired result; they cannot supply or override the before-state or diff.

### 2. Separate propose from apply

Creating a proposal never mutates planning or manuscript state. Apply is a
separate explicit operation with an expected proposal revision. It rechecks all
captured manuscript, branch, and artifact heads inside one database transaction
before delegating to the existing canonical services.

If a base changed, no target mutation occurs. The original proposal is retained
as `conflicted`, and an immutable event records the expected and current heads.
A revised proposal is a new `spp_` linked through `supersedes_proposal_id`; it
does not rewrite the earlier proposal.

### 3. Preserve manuscript authority

Argument-spine apply continues to append claim wording versions, retire omitted
claims, and remove omitted units through `NativeManuscriptService`. It never
creates or rewrites PI ratification. Changing currently ratified wording is a
prominent review warning because the newly appended wording is not ratified.

The validator also warns when a proposal removes qualifier or counterevidence
bindings, broadens allowed wording, or removes prohibited wording. Warnings are
not silently hidden; the researcher decides whether to apply.

### 4. Make context disclosure exact and durable

AI-origin proposals require an immutable `pcm_` context manifest created before
generation. It contains:

- exact selected entity IDs and roles;
- project-attested normalized records and revision fingerprints;
- optional locators and source closure;
- target base snapshots and hashes;
- prompt constraints, omissions, and truncation notes; and
- provider, model, and boundary classification.

The manifest is canonical-JSON hashed. Provider-call start/success/failure
events refer to that manifest without storing credentials. Preparing a host
manifest opens exactly one call record; persisting the validated proposal
closes it successfully. A used host manifest cannot ambiguously attribute a
second generation. The LM Studio adapter records the same lifecycle around its
HTTP request.

An AI proposal may mutate only aggregates explicitly snapshotted in its
manifest, and the captured aggregate revision must still be current when the
proposal is persisted. Every evidence or promotion-target entity referenced by
the proposal must appear in the resolved selection or captured target
snapshot. RKA fails closed when the generated edit reaches beyond this exact
disclosure boundary; a valid database ID alone is not proof that the provider
saw it.

### 5. Keep provider adapters outside semantic authority

Host agents receive a context manifest and the JSON proposal schema over MCP,
then submit their candidate through the ordinary proposal operation. RKA does
not need or store a ChatGPT or Claude subscription credential for this path.

LM Studio is an optional server-side adapter. Its base URL must use loopback or
Docker's exact `host.docker.internal` gateway, and its model is configured
through environment settings. The
adapter requests schema-constrained JSON and submits the parsed result through
the same proposal service. There is no fallback from local to cloud and no API
key is stored in the database, manifest, log, or proposal.

### 6. Treat proposal history as project semantics

Proposal, manifest, and event rows are project scoped, included in knowledge
packs, visible through change cursors, and deleted only through the existing
whole-project authorization path. REST, MCP, and the workbench expose the same
proposal lifecycle and label unapplied state explicitly.

## Consequences

- Human and AI edits share validation, preview, conflict, and apply semantics.
- Provider output is never canonical merely because generation succeeded.
- Stale suggestions remain auditable and cannot overwrite newer work.
- Local inference can remain local, while host-agent use has an explicit
  disclosure record.
- The operation set is intentionally smaller than arbitrary JSON Patch; later
  file editing and richer promotions can build on the same envelope without
  weakening current manuscript invariants.
