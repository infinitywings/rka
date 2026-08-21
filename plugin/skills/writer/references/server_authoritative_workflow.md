# Server-Authoritative Manuscript Workflow

RKA core is the semantic system of record for a manuscript. Writer owns the
authoring workspace and renders deterministic views of that record. This
boundary prevents a local planning file from silently diverging from the
research graph.

## Authority boundary

RKA owns:

- the canonical `man_` manuscript identity, lifecycle, venue, and revision;
- stable `mcl_` manuscript claims and immutable wording versions;
- evidence, qualifier, and counterevidence bindings;
- `mra_` bindings between one exact claim version and one active PI decision;
- `mun_` claim-sized manuscript units and result interpretation boundaries;
- the L2-L5 outline hierarchy, writing rationale, and evidence intentions
  attached one-to-one to `mun_` identities;
- `mck_` manuscript checkpoints;
- `mva_` multidimensional verification attestations;
- `mrf_` citation-key membership bound to exact same-project `lit_` records;
- readiness, monotonic change cursors, and evidence-to-writing impact.

Writer owns:

- LaTeX, Word, Markdown, figures, tables, and other manuscript files;
- venue structure, citation formatting, rendering, and layout checks;
- `.planning/ACTIVE_WORKFLOW.md` as disposable authoring-session state;
- deterministic projections such as `RKA_CLAIM_SPINE.yaml`,
  `CONTRIBUTION_CONTRACT.md`, `ARGUMENT_SPINE.md`, and `RESULTS_TRACE.md`.

The canonical manuscript identifier is `man_...`. A legacy `jrn_...` manifest
may be accepted as a compatibility alias, but new workflows store and use the
resolved `man_...` identifier.

## Normal session loop

1. Read `.rka/manuscript.json`. Require an explicit `project_id` and canonical
   `manuscript_id`.
2. Inspect changes since the last synchronized projection:

   ```bash
   rka writer impact \
     --project-id prj_... \
     --manuscript-id man_... \
     --claim-spine .planning/RKA_CLAIM_SPINE.yaml
   ```

3. Review only the affected claims, units, source records, files, and
   artifacts reported by RKA. A partial page is not a clean result; continue
   pagination or resynchronize.
4. Refresh the local projection and generated views:

   ```bash
   rka writer sync \
     --project-id prj_... \
     --manuscript-id man_... \
     --output .planning/RKA_CLAIM_SPINE.yaml \
     --render-dir .planning
   ```

5. Ask RKA for the target-phase readiness verdict:

   ```bash
   rka writer readiness \
     --project-id prj_... \
     --manuscript-id man_... \
     --target-phase drafting
   ```

6. Continue only when the server returns a non-blocking categorical verdict.
   Local renderers may add stricter file-level findings, but cannot override a
   server `BLOCK` or `ERROR`.

The synchronized cursor is captured before the aggregate projection is read.
This is intentionally conservative: a concurrent change may be reported again,
but it cannot be incorrectly hidden as already reviewed.

## Building or revising the argument spine

`rka writer assist` is a read-only, server-attested candidate generator. It
does not flatten all journal entries or supported claims. It smooths evidence
through current Brain-reviewed clusters bound to active research questions,
groups duplicate support, and returns exclusions and contradiction blockers.
Its scope is the project research map, so the PI and Writer must select the
research questions relevant to this manuscript. It cannot create a manuscript
claim or ratify wording.

Semantic changes follow this order:

1. Inspect candidate cluster lineage, exclusions, duplicate groups, and
   blockers. Resolve stale clusters and counterevidence through Brain.
2. Select in-scope research questions and assemble a bounded contribution
   contract, exact claim wording, prohibited wording, and claim-sized units.
3. Dry-run candidate spine material locally:

   ```bash
   rka writer import-spine \
     --project-id prj_... \
     --manuscript-id man_... \
     --input proposal.yaml
   ```

4. Review the diff, evidence roles, result coverage, and prohibited wording.
5. On a server exposing semantic patches, create an
   `argument_spine_replace` through `create_semantic_patch_proposal`. Review
   its immutable diff and findings. An AI author first persists an exact
   context manifest and records its origin/provider boundary, then stops at
   `proposed`. The PI or local web UI separately applies or rejects the `spp_`;
   stale bases become conflicts.
6. The direct CLI form below is a local compatibility path only. It must be an
   explicit human action with PI authorization and an expected manuscript revision:

   ```bash
   rka writer import-spine \
     --project-id prj_... \
     --manuscript-id man_... \
     --input proposal.yaml \
     --expected-revision 7 \
     --apply
   ```

7. Record the PI decision separately, then bind the exact active claim version
   through `ratify_manuscript_claim`.
8. Synchronize again before drafting.

An import may create or update claim identities, wording versions, evidence
roles, units, and unit bindings. It never imports or synthesizes PI
ratifications. Revision conflicts must be inspected and rebased; never retry
blindly against a newer revision.

The complete journal-to-prose admission policy is in
[`evidence_to_spine_pipeline.md`](evidence_to_spine_pipeline.md).

## Developing the progressive outline

After the claim spine is present, use `manuscript_outline` to resume the
canonical unit hierarchy. L2-L5 values express pure depth, not rhetorical
type; unit `kind` and rationale express the writing role. Each major unit must expose its communicative
job, intended reader takeaway, intended claim, and evidence plan, together
with reverse claim/evidence navigation and any completeness blocker.

Direct editing and AI suggestions share one proposal-first route, but not the
same review authority:

1. Read the current outline and manuscript revision.
2. For AI-authored changes, persist `prepare_semantic_patch_context`. Prepare
   `edit`, `expand`, `condense`, or `reorder` with that exact provenance
   through `prepare_manuscript_outline_proposal`.
3. Inspect the immutable semantic diff, validation findings, binding changes,
   and downstream order impact.
4. The Writer stops at `proposed`. The PI or local web UI applies or rejects
   the `spp_` separately. A stale manuscript revision becomes a conflict and
   must be rebased explicitly.
5. Re-query `manuscript_outline`; never infer success from the proposal alone.

Expansion retains its parent and cannot invent undisclosed claim/evidence
bindings. Condensation unions named descendant bindings into the retained
parent before removal. Reorder requires the exact active unit-key set, places
parents before children, keeps subtrees contiguous, and changes no semantic
content. Outline checkpoint dependencies include typed claim/unit evidence
bindings. Creating and resolving the Outline checkpoint are
separate PI-authority operations; neither proposal preparation nor apply
ratifies the outline. Writer-owned Markdown or LaTeX files remain projections
until source synchronization is introduced.

## Readiness and change impact

RKA readiness is the authoritative mechanical gate. It checks, among other
invariants:

- active manuscript state and required venue;
- at least one active manuscript claim;
- exact current PI ratification of each active wording version;
- current, grounding-verified, scientifically supported, uncontested evidence;
- terminal source currency and project isolation;
- result-unit coverage for empirical claims;
- source-backed result units with explicit interpretation boundaries;
- an explicit non-empty reference manifest for review and later phases, with
  every active member's latest exact validation VERIFIED, identity-matched,
  retraction-checked when enabled, and not older than a literature update;
- resolved checkpoints required by the target phase.

The change ledger is an invalidation aid, not a truth oracle. `impact` maps
post-cursor events to affected claims, units, file anchors, and artifact
references. Unrelated project changes must not appear in a manuscript impact
report. After reviewing or repairing relevant changes, run `sync` and
`readiness` again.

## Legacy migration

`rka-claim-spine/v1` and tagged `jrn_` manifests are compatibility inputs only.
Use dry-run import to inspect them. Migration never:

- deletes the legacy journal record;
- infers a claim from prose;
- treats `verified=true` as scientific validation;
- creates a PI ratification without an exact active PI decision;
- chooses among ambiguous venue, phase, or manuscript tags.

`rka-claim-spine/v2` is a server-generated projection. Do not edit it and then
assume the edit changed RKA. Use an explicit dry-run/apply proposal and
resynchronize.
