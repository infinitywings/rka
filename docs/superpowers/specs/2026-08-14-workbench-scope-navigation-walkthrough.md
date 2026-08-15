# M2 Workbench Scope-Navigation Walkthrough

Date: 2026-08-14

Branch: `feature/rka-workbench-navigation-m2`

Merged-main baseline:

- `1ef67b6` — merged canonical claim scope contracts (PR 71).

Validation refresh: 2026-08-15

## Purpose

Exercise the first M2 / PR 4 hardening slice against a production-built RKA
image without reading or mutating the live RKA database. The walkthrough checks
that the workbench can summarize the M1 review boundaries, preserve navigation
state in URLs, and move from a manuscript statement to its canonical evidence
boundary without creating a second semantic store.

## Disposable scenario

The rebased production image was started on localhost-only port `19712` with a fresh
container-owned database and embeddings disabled. The scenario contained:

- one source journal record;
- one pending `icd_` interpretation candidate;
- one supported, verified `clm_` result;
- one reviewed, ready `csc_` scope contract with three typed conditions;
- one native `man_` aggregate with one empirical `mcl_` claim and one result
  `mun_`, both bound to the canonical evidence claim.

The container was stopped and auto-removed after testing.

## Acceptance path

1. Open the manuscript workbench directly at `?stage=scope`.
2. Verify the stage rail resumes at **Problem and scope**, rather than silently
   returning to the seed.
3. Verify the Context Capsule shows one pending interpretation, one ready claim
   scope, manuscript readiness, research-map counts, and semantic-impact state.
4. Verify the capsule explicitly says interpretation review does not establish
   scientific support and claim scope does not collapse evidence,
   contradiction, or grounding state.
5. Inspect the manuscript scope card and verify the evidence inspector exposes
   `mcl_`, `clm_`, and `csc_` identifiers.
6. Follow **Review clm_...** and verify the claim-scope page opens the exact
   claim from `claim_id`, even though its readiness is not the page's default
   filter.
7. Verify the scope detail contains the reviewed contract and all three typed
   applicability conditions.
8. Use browser Back and verify the manuscript route resumes at `?stage=scope`.
9. Follow the Context Capsule interpretation link and verify the pending queue
   and exact source detail render.
10. Open a deliberately mismatched URL containing the pending `candidate_id`
    and `review_status=resolved`; verify the explicit candidate identity wins
    and the pending candidate remains selected.
11. Select **Paper spine** in the stage rail and verify the URL changes to
    `?stage=spine` together with the visible stage.

## Result

All eleven checks passed in the in-app browser both before and after rebasing
onto merged PR 71. The production web build, focused ESLint checks, Docker
image build, and full backend suite (`2,844 passed`) also passed on the rebased
branch. The existing Vite large-chunk warning remains; it is not introduced by
this slice.

## Preserved boundaries

- The workbench remains read-only and performs no LLM call.
- URL state stores navigation only; RKA remains the semantic authority.
- Review-queue counts are derived from the first 200 records. If that cap is
  reached, the capsule labels the summary as partial instead of presenting it
  as a complete project count.
- PR 3 experiment/run/result semantics remain absent and must stay visibly
  absent; journal entries and interpretation candidates are not substitutes.

## Real-project admission test

After the disposable synthetic path passed, the live RKA database was copied
with SQLite's online-backup API and mounted into a separate disposable
container. Migrations and browser reads therefore operated only on the copy.
The live database, running containers, and semantic records were not changed.

The following read-only cases were exercised:

| Project | Native manuscript | Observed admission state |
| --- | --- | --- |
| DelaySteer | none | 5 RQs, 13 clusters, 69 claims; all 69 canonical scopes missing |
| InvarLLM | none | 6 RQs, 7 clusters, 179 claims returned by the scope queue; all scopes missing |
| CPSEval | drafting `man_` exists | 2 RQs, 6 clusters, 81 claims; manuscript spine empty and all scopes missing |
| detectability | drafting `man_` exists | 5 RQs, 13 clusters, 134 claims; manuscript spine empty and all scopes missing |

The workbench admitted the research landscape but kept paper spine,
contribution, scope, evaluation, and outline stages blocked or exploratory.
This is correct: pre-M1 records are not silently reclassified as reviewed
interpretations, and legacy claims are not assigned invented applicability
contracts.

Project isolation was also checked explicitly. Opening the CPSEval manuscript
while InvarLLM was active returned the scoped not-found state, displayed the
workbench error, and did not leak the foreign manuscript title. Selecting
CPSEval then loaded that same `man_` aggregate normally. The same denial/load
sequence passed for detectability.

### Additional compatibility finding

The live pack exporter produced pack-format v2 records containing five
agentic-branch claim-staleness columns that current `main` does not model:
`staleness_resolution`, `staleness_resolution_journal_id`,
`staleness_resolved_by`, `staleness_reviewed_at`, and `staleness_verdict`.
The importer rejected them rather than silently discarding semantic history.
That fail-closed behavior is correct, but a lossless migration design is needed
in the later intake/hardening milestone before these packs are portable across
the branches.

## Remaining M2 gate

A real project cannot yet demonstrate the positive scope-to-spine path because
the required PI-reviewed semantic records do not exist. The next controlled
step is to copy the live database online, isolate CPSEval in a disposable
instance, review a bounded subset of its claims, append canonical scopes, and
create a minimal claim-sized spine through the normal revision-guarded
interfaces. CPSEval is the smallest current pilot (81 claims and an existing
native manuscript), so it is the recommended case.

The disposable pilot must preserve the live database and all live semantic
records unchanged. It exists to validate the workflow, not to manufacture a
positive result in the research system.
