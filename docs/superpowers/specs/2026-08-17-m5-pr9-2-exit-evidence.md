# M5 PR 9.2 Exit Evidence: Typed Academic-Writing Core

Date: 2026-08-17  
Baseline: `origin/main` at `f70d360`  
Implementation branch: `codex/m5-typed-writing-core`

## Scope exercised

- Migration 049 on a fresh database, on restart, and as a late migration over
  legacy manuscript rows.
- Typed claim boundaries (`conditions`, `falsification_criteria`).
- Typed unit roles and rhetorical moves.
- Evidence-use propositions and warrants for support, qualifier, and
  counterevidence bindings.
- Unit-level citation uses with reference-manifest membership and current
  validation checks.
- Progressive outline expansion/condensation, semantic patches, checkpoints,
  change tracking, project deletion, and knowledge-pack rekey/import paths.
- MCP typed-operation parity and workbench rendering/edit controls.
- Deterministic academic-readiness v2 with structural blockers and advisory
  judgment checks.

## Disposable real-project-derived pilot

The pilot test
`test_invarllm_derived_pilot_preserves_argument_boundaries_and_tradeoffs`
uses a read-only snapshot of three claim identities and bounded findings from
RKA project `prj_01KN51HD73DSY9ZR9C56JYRNYZ`. It recreates those rows only in
the isolated pytest database; it does not mutate the live project.

The pilot proves that one strength-first paper claim can retain, in the same
auditable substrate:

- the favorable eTaF1/precision result;
- the exact HAI 21.03/configuration conditions;
- a protocol-matched falsification criterion;
- the recall/scenario-coverage qualifier;
- counterevidence that the predicted AffF1 recovery did not materialize;
- proposition-specific warrants; and
- one currently verified citation plus one explicitly self-attested citation.

Expected readiness behavior also passed: structure, claim allocation, evidence
presence, evidence-use explanation, claim boundaries, and rhetorical annotation
pass; the self-attested citation produces a non-blocking citation warning.

## Automated evidence

| Gate | Result |
| --- | --- |
| Focused migration/service/MCP/model-drift suite | **1,006 passed** |
| Disposable INVARLLM pilot | **1 passed** (included above) |
| Changed Python files: Ruff lint | **Passed** |
| Python compile check | **Passed** |
| Git whitespace/error check | **Passed** |
| Web production build | **Passed**; existing large-chunk warning remains |
| Changed web files: ESLint | **Passed** |
| Full Python suite | **3,114 passed, 21 skipped, 11 failed** |

The 11 full-suite failures are confined to pre-existing embedding/backfill
metadata tests. Re-running the exact five affected test files on both this
branch and a detached clean `origin/main` worktree produced the same result:
**11 failed, 24 passed, 6 skipped**. None of the failing modules is modified by
PR 9.2.

Full-tree web lint reports seven errors and two warnings in unchanged UI files
(`badge.tsx`, `button.tsx`, `tabs.tsx`, `useTheme.tsx`, `Journal.tsx`,
`ResearchMap.tsx`, and `Settings.tsx`). The two PR 9.2 web files pass ESLint.

## Review interpretation

The implementation is ready for draft-PR review. The focused change surface,
MCP parity, migration paths, web build, and real-project-derived academic
workflow are green. The repository-wide embedding and legacy lint baselines
remain separately visible and must not be represented as PR 9.2 regressions or
as fixed by this change.

