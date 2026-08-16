# M4 / PR 7 seed-to-contribution exit evidence

- Date: 2026-08-15
- Baseline: `6cdf0f7073ecb30300df030d4016b95377652b57`
- Branch: `agent/m4-seed-to-contribution`
- Pull request: [#78](https://github.com/infinitywings/rka/pull/78)
- Scope: deterministic seed-through-contribution guidance, stable candidate
  identity, semantic-proposal stage editing, and explicit promotion lineage
- Data safety: all browser mutations used fresh or online-backup SQLite copies;
  the live RKA database and projects were read only

## Contract exercised

The release candidate implements the boundary frozen in
[ADR 0007](../../adr/0007-seed-to-contribution-guidance-and-promotion.md):

- seven guided but non-linear planning stages from `seed` through
  `rq_contribution`;
- deterministic categorical verdicts, next actions, blockers, warnings, and a
  quick-reader projection with exact source-version references;
- stable local keys for landscape rows, challenge/innovation pairs, RQs, and
  contributions;
- exact prerequisite-head pins that block downstream readiness after an
  upstream revision until the downstream option is reviewed again;
- choice-first stage editing through ADR 0006 proposals, with no branch
  mutation before explicit apply;
- immutable RQ promotion, contribution proposal preparation, contribution
  application, and exact claim-version ratification events;
- exact-text PI decision enforcement for contribution ratification;
- REST, MCP, knowledge-pack, deletion, change-cursor, and project-isolation
  parity; and
- preservation of proposal authorship and proposal reason on the applied
  planning version, while the separate apply event records the approver and
  approval reason.

## Automated verification

| Gate | Result |
|---|---|
| Full Python suite | `3061 passed in 163.37s` |
| Focused semantic-provenance regression | Passed |
| MCP coverage | Included in the full suite; query and execute surfaces passed |
| TypeScript and production Vite build | Passed |
| Targeted changed-workbench ESLint | Passed with zero findings |
| Patch whitespace check | Passed |

The production build retains the repository's existing large-chunk advisory;
it introduces no build failure. The Python run retains one upstream Pydantic
forward-reference warning and the expected read-only pytest-cache warning.

## Fresh-database browser walkthrough

The production frontend and feature-branch API were served on loopback against
a fresh disposable database.

1. Created a project-only planning branch at revision 1.
2. Captured a selected, ready seed through a human semantic proposal.
3. Confirmed the proposal ledger showed one pending edit while the branch
   remained at revision 1 with zero artifacts.
4. Explicitly applied the proposal and confirmed revision 2, one selected
   artifact, a `Ready` seed verdict, and `paragraph_spine` as the next stage.
5. Restarted the service and confirmed the branch, artifact, verdict, and next
   action resumed without replay.
6. Confirmed the browser error log was empty and the new editor exposed named
   controls without duplicate DOM identifiers.

## Real-project end-to-end walkthrough

The source project was `prj_01KN51HD73DSY9ZR9C56JYRNYZ` (Invarllm). Its live
SQLite database was copied through SQLite's online-backup API and mounted into
a separate disposable container. Migrations and browser writes operated only
on that copy.

### Project-only branch and invalidation

The first branch bound its seed to one recorded RQ decision, one evidence
cluster, and one causal claim. Its paragraph spine cited the original WADI null
result, the WADI rescue result, and the recorded pipeline-mechanism diagnosis.
The proposal preview pinned the exact seed artifact and version. After the seed
was revised from v1 to v2, the existing paragraph spine remained visible but
became `Blocked`, with `paragraph_spine` again recommended. This passed the
non-destructive downstream-invalidation contract.

That pass exposed a semantic-preview mismatch: apply replaced the reviewed
planning-version reason with a generic approval reason. The implementation now
persists the proposal's reviewed `created_by` and `reason` exactly; the proposal
event separately records the actor and reason for apply. A focused regression
and the full suite pass with that correction.

### Manuscript-bound complete path

A disposable native manuscript and selected branch were then created inside
the same copied Invarllm project. The browser captured and explicitly applied:

1. a mechanism-level seed;
2. a one-paragraph paper spine;
3. explicit problem, included scope, exclusions, assumptions, and terms;
4. a literature/SOTA comparison with exact `lit_` bindings and a bounded gap;
5. a trace-repair-validate response mechanism;
6. two stable challenge/innovation pairs with required evidence and
   boundaries; and
7. one selected RQ plus one selected exact contribution candidate.

The selected RQ promoted to one active same-project PI `dec_`. The contribution
first produced an unapplied ADR 0006 `argument_spine_replace` proposal against
manuscript revision 1. Before apply, the manuscript still had zero claims. The
semantic diff added one exact methodological claim with two support claims,
one qualifier claim, allowed wording, and two prohibited extensions. Explicit
apply advanced the manuscript to revision 2 and recorded the exact `mcl_` v1.

A PI decision whose chosen text did not equal the applied wording was rejected
with HTTP 409. A second active PI decision whose chosen text exactly matched
the claim succeeded, advanced the manuscript to revision 3, and appended the
fourth promotion event. After restart, the browser restored all seven planning
artifacts, branch revision 8, the promoted RQ decision, contribution proposal
and application, exact ratification, and four-event audit history with no
browser console errors.

The source claims in this legacy project remain visibly `unassessed` and have
missing canonical scope contracts. The workbench therefore continues to show
blocking evidence-readiness findings. Exact wording ratification records the
PI's semantic choice; it does not claim that the manuscript is ready to move
to drafting or that the underlying evidence has been assessed.

## Compatibility finding retained for M6

The live pack exporter includes five agentic-branch claim-staleness columns
that current `main` does not model. The PR 7 importer rejected the pack rather
than silently dropping those fields. The real-project test therefore used an
online database backup, not a lossy pack rewrite. Lossless cross-branch pack
migration remains an intake/hardening task for M6.

## Exit decision

PR 7 satisfies its feature-branch release gate. PR 8 can begin only after PR 7
review and merge; it remains responsible for the evaluation contract and
results trace rather than expanding this branch's contribution workflow.
