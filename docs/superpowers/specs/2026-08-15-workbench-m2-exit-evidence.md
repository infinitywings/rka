# M2 Read-Only Workbench Exit Evidence

Date: 2026-08-15

Branch: `feature/rka-workbench-m2-exit-evidence`

Merged-main baseline: `8b5e4f0` (PR 73)

## Purpose

Close the remaining M2 usability and state-integrity gates before any M3
deliberation or mutation interface is enabled. This pass asks whether the
read-only workbench remains truthful and operable when data is loading, absent,
or capped, and whether a keyboard user can navigate the application and guided
stage rail without losing URL-resumable state.

## Data isolation

The test server used the production RKA `2.9.0` image on localhost-only port
`19713` and a new copy of the disposable CPSEval pilot database. The live RKA
server and database were not restarted or changed. The relevant database
hashes were:

```text
live online backup, unchanged:
279cd694f06c2d580ce28eabfc94580d65e7d7f9c9fee38cd1865892644daf21

post-CPSEval pilot input:
0932ddc190eb294a92eace53e64f6e0f9ca2d66236407cf9d6bef58e335fc62f

M2 boundary-case fixture:
2e24fce503e58f85f587a9268e6de054c2a2cc579147ade6b688bdc884b9131f
```

All three databases passed `PRAGMA integrity_check`. To reach the API's
200-record claim limit, the fixture added exactly 21 plainly named low-
confidence, unverified, unassessed claims to the disposable InvarLLM project
through the normal `POST /api/claims` interface. The project moved from 179 to
200 claims. These are test-only records and were never written to the live
database.

## State-integrity changes

- Project-only mode now states that no manuscript is selected and explains how
  to load a canonical `man_` aggregate.
- A requested manuscript is labeled `Loading manuscript` while its context is
  in flight; readiness says it is waiting for context rather than claiming the
  manuscript is absent.
- Each stage renders a live loading status for its authoritative dependencies
  and suppresses empty conclusions until those reads settle.
- Dependent read failures render an explicit alert instead of a permanent
  loading label.
- Review-queue summaries distinguish no records from loading and failure.
- Reaching the 200-record API limit now says `200 records shown; total unknown`
  and warns that the displayed counts are not project totals. The UI no longer
  implies that `200` proves additional records exist.

## Keyboard and accessibility changes

- A first-focus skip link moves focus to the main application landmark.
- The guided stage rail supports Arrow keys, Home, and End for focus movement.
- Enter and Space explicitly select the focused stage and preserve the choice
  in `?stage=...`.
- Custom evidence cards, queue links, and stage controls expose visible focus
  rings.
- The evidence inspector is a polite atomic live region, so a keyboard
  selection is announced without forcing focus away from the stage control.
- Loading states use `role=status`; failures use `role=alert`.

## Browser acceptance matrix

| Case | Project / manuscript | Result |
|---|---|---|
| Project-only exploration | CPSEval, no manuscript | Explicit project-only status; canonical manuscript fields remain unselected rather than unavailable. |
| Empty canonical manuscript | detectability / `man_01KTA076RZS52C2T1JPP0D39KT` | `No paper spine yet` and `No native manuscript units` appear only after successful authoritative reads. |
| Capped claim queue | disposable InvarLLM fixture | `200 blocking scope`, `200 records shown; total unknown`, and the non-total warning render together. |
| Delayed context | CPSEval / `man_01M00D9BPMA60CN3FXTE86C4W1` through a localhost-only 1.5-second delay proxy | Loading manuscript, readiness-wait, and stage-loading messages render; no empty or unavailable conclusion flashes. The canonical ESCAPE spine replaces them after completion. |
| Stage keyboard navigation | project-only workbench | Arrow Down focuses Paper spine; Enter selects `?stage=spine`; End focuses Outline; Space selects `?stage=outline`. |
| Skip navigation | loaded CPSEval manuscript | Activating `Skip to main content` targets `#main-content` and moves focus to the `main` landmark. |
| Responsive boundary | InvarLLM at 390 by 844 | Mobile navigation replaces the fixed sidebar; project-only and capped-count disclosures remain visible with no horizontal layout blocker. |

## Verification

- focused ESLint on the five changed workbench/layout files: pass;
- TypeScript and Vite production build: pass;
- `git diff --check`: pass;
- production Docker image build: pass;
- full backend suite in a disposable runner with the checkout mounted
  read-only: `2,844 passed` in 148.63 seconds;
- browser acceptance matrix above: pass;
- disposable fixture integrity check and isolation hashes: pass.

The repository-wide ESLint command still reports the known baseline violations
in shared `badge`, `button`, and `tabs` components plus `useTheme`, `Journal`,
`ResearchMap`, and `Settings`. None is introduced by this branch. The full
backend suite emitted the existing Pydantic forward-reference warning plus the
expected pytest-cache warning because the checkout was deliberately mounted
read-only; neither affected test execution.

## Exit decision

This branch closes M2. The read-only workbench now has a real
positive scope-to-spine path, resumable evidence navigation, responsive layout,
explicit boundary states, and keyboard-operable stage navigation without
weakening the separation among applicability, source grounding, scientific
support, PI ratification, and drafting readiness.

The next dependency-ordered target is **M1 / PR 3**: separately design and
review first-class experiment, run, result, measurement, metric, baseline,
condition, and evidence-locator semantics. M3 mutation UI remains blocked until
that substrate is accepted.
