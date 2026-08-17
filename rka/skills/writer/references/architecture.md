# Writer Architecture

Writer is an authoring skill over an RKA-managed research project. RKA core is
the semantic authority; Writer owns files, venue adaptation, drafting,
rendering, and deterministic human-readable projections.

## Deployment model

```text
Writer session
  |
  +-- rka MCP or trusted local REST
  |     +-- native man_ manuscript aggregate
  |     +-- project research graph and entity resolver
  |     +-- readiness, change cursor, and impact mapping
  |     +-- durable reference-validation jobs
  |
  +-- manuscript workspace
        +-- .rka/manuscript.json
        +-- .planning/RKA_CLAIM_SPINE.yaml       generated
        +-- .planning/CONTRIBUTION_CONTRACT.md   generated
        +-- .planning/ARGUMENT_SPINE.md          generated
        +-- .planning/RESULTS_TRACE.md            generated
        +-- .planning/FRAMING_SESSION.yaml        advisory interaction state
        +-- .planning/ACTIVE_WORKFLOW.md          local session state
        +-- sections/, figures/, tables/, charts/
        +-- refs.bib, main.tex, styles/
```

The portable workspace contains no credential and no default RKA project.
Every command passes an explicit `project_id`. `.rka/manuscript.json` stores
the canonical `man_` id returned or resolved by `rka writer init`.

## Authority boundary

| RKA core owns | Writer owns |
|---|---|
| `man_` identity, venue, phase, state, revision | authoring files and directory layout |
| stable `mcl_` claim identity and immutable wording versions | prose and section structure |
| evidence roles and terminal source provenance | venue-specific citation formatting |
| exact PI ratifications (`mra_`) | deterministic Markdown/YAML rendering |
| manuscript units (`mun_`) and result boundaries | figures, tables, and chart source files |
| checkpoints (`mck_`) and verification attestations (`mva_`) | compilation and layout audit |
| readiness, change cursors, and impact | disposable local session notes |

Local files cannot create semantic truth. A local proposal changes the
aggregate only through an explicit, revision-guarded command. A generated
projection is replaced by `rka writer sync`, not repaired by hand.

## Native manuscript aggregate

The canonical manuscript uses `man_`. A legacy tagged `jrn_` may remain linked
through `legacy_journal_id` and may be accepted as an input alias during the
compatibility window.

The aggregate contains:

- `manuscripts`: identity, project, title, abstract, venue, phase, state,
  workspace reference, optimistic revision, and optional legacy alias;
- `manuscript_claims`: stable local keys and closed claim kinds;
- `manuscript_claim_versions`: immutable exact, allowed, and prohibited
  wording;
- `manuscript_claim_ratifications`: immutable exact-version bindings to active
  same-project PI decisions;
- `manuscript_units`: stable claim-sized locations with explicit result
  interpretation boundaries;
- typed claim-evidence, unit-evidence, and claim-unit joins;
- `manuscript_checkpoints`: six closed checkpoint kinds and explicit decision
  resolution;
- `manuscript_claim_verification_attestations`: immutable multidimensional
  findings with dependency snapshots and tool provenance.

Critical joins carry the project boundary. The service does not infer
ratification from tags, prose, a filled YAML cell, or an arbitrary decision.

## Claim and evidence semantics

Native manuscript claim kinds are:

- `empirical`;
- `methodological`;
- `theoretical`;
- `survey`;
- `position`.

Evidence roles are `support`, `qualifier`, and `counterevidence`. These roles
are manuscript bindings, not new scientific facts. The underlying `clm_`
records still require:

- source-grounding verification;
- scientific `evidence_status` of `supported` or `partially_supported` when
  used as positive support;
- explicit `contradicted: false`;
- current same-project state;
- a current non-manuscript terminal source.

`claims.verified` means extraction fidelity only. It does not establish
measurement integrity, replication, or scientific truth. An `ecl_` synthesis
helps discovery but cannot serve as terminal empirical evidence. A `dec_`
licenses wording or resolves a checkpoint but cannot supply empirical support.

Scientific `supports`, `contradicts`, and `qualifies` edges belong to
`claim_edges` between `clm_` records. Cross-type provenance uses the
schema-valid `entity_links` vocabulary. Writer never invents edge types.

## Noise smoothing and candidate discovery

The writing path is hierarchical:

```text
journal -> staged interpretation candidate -> explicitly promoted grounded claim
-> reviewed evidence cluster
-> active research question -> unratified candidate -> native claim and unit
```

Each boundary reduces noise without destroying history. Journals are never
promoted directly. Candidate extraction is not claim creation; the reviewer
must inspect its exact locator, uncertainty, scope, and conflict/duplicate
hints before explicit promotion. Source claims must then pass grounding, scientific-support,
currency, project, source, and contradiction checks. Duplicate support stays
linked but does not create extra candidate claims. A cluster must be current,
Brain-reviewed, sufficiently confident, and bound to an active research
question.

`manuscript_writing_candidates` is a read-only project-map view. It returns
both eligible and blocked clusters, excluded claim reasons, duplicate groups,
and lineage. It deliberately creates neither manuscript records nor PI
ratifications. The PI/Writer selects in-scope research questions, bounds exact
and prohibited wording, and then submits a revision-guarded native spine
change.

See
[`evidence_to_spine_pipeline.md`](evidence_to_spine_pipeline.md) for the full
admission and change-handling contract.

## PI ratification

A manuscript claim may have many immutable wording versions. A ratification
binds exactly one version to one active same-project PI decision whose selected
wording exactly matches that version.

Changing licensed wording requires:

1. append a new claim wording version;
2. supersede the earlier PI decision when appropriate;
3. record a new active PI decision with the exact new wording;
4. bind that decision to the new version;
5. synchronize Writer projections.

The argument-spine upsert deliberately never creates a ratification.

## Units and result trace

A `mun_` is the smallest meaningful writing unit, not necessarily a section.
It carries a stable local key, kind, source location, optional artifact, order,
and drafting status. Its one-to-one outline profile supplies an L2-L5 level,
parent, communicative job, intended reader takeaway, transition,
quick-reader role, evidence plan, and figure/table/citation intentions.
The level is pure hierarchy depth: L2 is shallowest and L5 deepest. It is not
a rhetorical type; unit `kind` and the rationale fields express whether a unit
acts as a section, paragraph, result, transition, or other argument beat.
Claim-unit relationships are `advances`, `tests`, `bounds`, or `mentions`.

`manuscript_outline` is the resumable projection for navigating this hierarchy
and its reverse claim/evidence bindings. Structural changes are never applied
in place: `prepare_manuscript_outline_proposal` deterministically prepares an
`argument_spine_replace` semantic proposal for edit, expand, condense, or
reorder. AI-authored proposals require an exact context manifest and retain
their origin/provider boundary. AI/MCP transports stop at `proposed`; the PI
or local web UI separately applies or rejects the proposal.
Expansion retains the parent and can only narrow inherited bindings;
condensation preserves their union on the retained parent; reorder changes
only sequence, keeps parents before children and subtrees contiguous, and
reports affected predecessors. This keeps direct editing and
AI assistance on one auditable mutation path.

Every active empirical claim requires an active result unit. Every result unit
requires:

- an artifact reference;
- an allowed interpretation;
- a prohibited interpretation;
- source-backed evidence;
- a relationship to at least one manuscript claim.

This bidirectional rule prevents unsupported contributions and orphan results.

## Transactions and revisions

Semantic mutations are aggregate-atomic. Row changes, normalized links, audit
records, and queued follow-up work commit together. Relation updates reconcile
the complete desired set so removed relations do not survive as stale edges.

Manuscript updates use optimistic concurrency:

1. read the current revision;
2. prepare a bounded change;
3. submit `expected_revision`;
4. on conflict, inspect the new aggregate and rebase;
5. never retry blindly.

Slow or external work runs after commit through durable jobs. A pending or
failed job never masquerades as a completed attestation.

## Projections and compatibility

`rka writer sync` exports `rka-claim-spine/v2` plus a conservative integer
change cursor. It then optionally renders:

- `CONTRIBUTION_CONTRACT.md`;
- `ARGUMENT_SPINE.md`;
- `RESULTS_TRACE.md`.

These are caches and review aids. Their authority metadata and manuscript
revision make accidental use of an unscoped or stale file visible.

`rka-claim-spine/v1` remains readable for migration. `rka writer import-spine`
is dry-run by default and may apply claim, version, evidence, unit, and binding
changes only with a revision precondition. It never imports ratifications.

## Currency and impact

RKA records semantic changes in a monotonic project-scoped cursor. Writer saves
a watermark with each synchronized projection and asks RKA to map later
changes to:

- affected manuscript claims;
- affected manuscript units;
- source file locations;
- artifact references;
- changed source entities.

The watermark is captured before the aggregate read. This can rediscover a
concurrent change but cannot hide it. A partial impact response requires
pagination or a full resynchronization.

Impact narrows review; readiness decides whether a phase can advance. After
reviewing relevant changes, Writer synchronizes and asks for readiness again.

## Readiness

Server readiness is categorical and evidence linked. Depending on target
phase, it checks:

- active manuscript state and venue;
- active claims with wording versions;
- current exact PI ratifications;
- eligible support and source currency;
- contradiction state;
- empirical result coverage;
- unit evidence and result boundaries;
- resolved checkpoint kinds.

`BLOCK` and `ERROR` stop advancement. A local script can add a stricter
file-level block but cannot override the server.

## Workspace initialization

`rka writer init`:

1. validates the explicit project and target path;
2. creates a native manuscript or resolves a supplied `man_`/legacy `jrn_`;
3. verifies title and venue;
4. substitutes the workspace template in a staging directory;
5. writes `.rka/manuscript.json` with `authoritative_source: rka`;
6. atomically publishes the complete workspace.

If native registration succeeds but publication fails, rerun with the returned
canonical id. Do not register a duplicate.

## Normal and exceptional flows

Normal flow:

```text
impact -> inspect affected scope -> sync -> readiness -> draft/review
```

Semantic revision:

```text
assist/research -> dry-run import -> PI review -> apply with revision
-> explicit PI decision -> exact ratification -> sync -> readiness
```

Evidence change:

```text
change event -> impact mapping -> claim/unit review
-> gather evidence or narrow wording -> new version if needed
-> new PI decision and ratification -> sync -> readiness
```

The detailed command sequence is in
[`server_authoritative_workflow.md`](server_authoritative_workflow.md).
