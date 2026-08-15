# ADR 0005: Versioned manuscript-planning branches and artifacts

- Status: accepted for M3 / PR 5 implementation
- Date: 2026-08-15
- Baseline: `infinitywings/rka` `main` merge
  `ba687721b9632a4a12c864100d9690ca428ac005`
- Scope: provisional planning branches, typed stage artifacts, immutable
  versions, exact RKA bindings, resume/comparison, portability, and workbench
  projection

## Context

The M2 workbench can inspect canonical RKA evidence and manuscript semantics,
but it cannot preserve an unfinished insight, compare alternative paper
framings, resume after interruption, or park a useful idea. Treating these
deliberations as journal entries would add noise upstream of claims. Treating
them as manuscript claims would overstate their authority. Storing them only
in browser state or generated files would lose recovery, lineage, and project
isolation.

The workbench therefore needs a third semantic layer:

```text
canonical evidence -> provisional planning -> canonical manuscript -> files
```

Planning may cite evidence and may later motivate a reviewed promotion, but it
does not itself prove a claim, ratify wording, modify a manuscript aggregate,
or edit an authoring file.

## Decision

### 1. Make project-level planning first class

A planning context can be bound to a native `man_` or to the project before a
manuscript exists. Project-level planning uses the reserved context key
`project`; manuscript-bound planning uses the exact canonical manuscript ID
and pins its base revision. Creating a manuscript is not a prerequisite for
capturing the initial insight.

### 2. Use recoverable copy-on-write branches

An `mpb_` is the stable identity of one planning alternative. It records name,
purpose, creator, state, context, and optional parent. A child pins the exact
parent branch revision visible at fork time. Later parent edits therefore do
not drift the child's inherited view.

Branch states are `active`, `selected`, `archived`, and `superseded`. At most
one branch is selected per project/context, and the selected branch is the
deterministic resume head. Archiving never deletes history. Selecting another
branch advances both affected branch revisions and appends exact events.

### 3. Separate stable artifacts from immutable versions

A `pla_` identifies one branch-local stage artifact by stage and local key. A
`plv_` is an immutable version. Updating an artifact appends a version and
advances both the artifact and branch heads under optimistic concurrency.
Every branch revision has exactly one immutable `pbe_` event.

A first child override points to the inherited parent version through
`derived_from_version_id`; later edits use an exact predecessor through
`supersedes_version_id`. Branch comparison resolves each ancestor only through
the revision pinned by its child.

### 4. Validate closed payloads for every planning stage

Planning does not use one unconstrained JSON blob. The supported stages are:

- seed;
- paragraph spine;
- problem scope;
- landscape and gap;
- response mechanism;
- challenge and innovation;
- research questions and contributions;
- evaluation;
- outline; and
- review.

Each stage has a closed Pydantic payload. Unknown fields and missing required
structure fail before persistence. Knowledge-pack integrity repeats this
semantic validation rather than trusting JSON syntax alone.

### 5. Preserve alternatives and incomplete work explicitly

Artifact lifecycle is `candidate`, `reviewed`, `selected`, `parked`,
`superseded`, or `archived`. Readiness is categorical: `blocked`,
`in_progress`, or `ready`, with explicit missing items and notes. Parking is a
recoverable status, not deletion or evidence rejection.

### 6. Bind exact RKA context without promoting it

A `plb_` binds an exact artifact version to a typed, same-project RKA entity
with role `support`, `qualifier`, `counterevidence`, `context`, `inspiration`,
or `unresolved`. Optional locators, versions, and content hashes pin the part
used. Bindings are immutable and remain part of the internal reasoning audit.

These roles describe how a record informed the provisional artifact. They do
not change canonical claim evidence status, manuscript evidence joins, or PI
ratification.

### 7. Record actor and AI origin precisely

Every mutation records an actor and reason. Artifact origin distinguishes
`user`, `user_revised`, `imported`, and `ai_suggested`. AI suggestions require
provider, model, and context-manifest hash. PR 5 stores this provenance but
does not introduce an AI broker or allow AI to bypass the same version append
contract.

### 8. Treat lifecycle operations as complete project semantics

Planning tables are core KnowledgePack content. Export/import re-keys
manuscript contexts, branch ancestry, artifact heads, version lineage, event
details, promotion references, and evidence bindings. Import rolls back on
broken lineage, head mismatch, unresolved typed evidence, or invalid stage
payload. Whole-project deletion removes the aggregate under the existing
authorization guard. Change cursors expose branch and artifact changes.

REST and MCP expose the same typed operations. The workbench restores the
selected branch, shows frozen ancestry and parking, and supports branch create,
select, archive/reactivate, and comparison. It labels all planning state as
provisional.

## Consequences

- Researchers can interrupt and resume without replaying a framing interview.
- Alternative spines remain comparable after their parent evolves.
- Noisy journal records are not overloaded with UI deliberation.
- Planning can start before manuscript registration.
- Pack restore and project cleanup preserve aggregate semantics.
- A selected planning artifact still requires a later, explicit reviewed path
  to become a decision, manuscript claim, unit, experiment, or file edit.
- Unified human/AI semantic proposals, diff preview, validation, apply/reject,
  and provider adapters remain M3 / PR 6 work.
