# M2 Workbench Scope-Navigation Walkthrough

Date: 2026-08-14

Branch: `feature/rka-workbench-scope-navigation`

Base commits:

- `fb4ab7c` — canonical claim scope contracts;
- `ceab2a1` — corrected MCP operation-count documentation.

## Purpose

Exercise the first M2 / PR 4 hardening slice against a production-built RKA
image without reading or mutating the live RKA database. The walkthrough checks
that the workbench can summarize the M1 review boundaries, preserve navigation
state in URLs, and move from a manuscript statement to its canonical evidence
boundary without creating a second semantic store.

## Disposable scenario

The production image was started on localhost-only port `19715` with a fresh
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

All eleven checks passed in the in-app browser. The production web build also
passed TypeScript compilation and focused ESLint checks. The existing Vite
large-chunk warning remains; it is not introduced by this slice.

## Preserved boundaries

- The workbench remains read-only and performs no LLM call.
- URL state stores navigation only; RKA remains the semantic authority.
- Review-queue counts are derived from the first 200 records. If that cap is
  reached, the capsule labels the summary as partial instead of presenting it
  as a complete project count.
- PR 3 experiment/run/result semantics remain absent and must stay visibly
  absent; journal entries and interpretation candidates are not substitutes.
- A mature real-project positive-path walkthrough is still required before the
  full M2 exit gate is declared complete.
