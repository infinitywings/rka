# M3 / PR 5 planning-branch exit evidence

- Date: 2026-08-15
- Baseline: `ba687721b9632a4a12c864100d9690ca428ac005`
- Scope: versioned provisional planning artifacts and recoverable branches
- Data safety: all browser mutations used a disposable database; no live RKA
  project or manuscript record was changed

## Contract exercised

The release candidate implements the boundary frozen in
[ADR 0005](../../adr/0005-versioned-manuscript-planning-branches.md):

- project-only and manuscript-bound planning contexts;
- immutable typed stage versions and evidence bindings;
- frozen copy-on-write branch ancestry;
- deterministic selection, resume, comparison, parking, archive, and
  reactivation;
- optimistic branch and artifact revisions;
- REST, MCP, KnowledgePack, project deletion, and change-cursor parity; and
- an explicitly provisional workbench projection that does not promote or
  overwrite canonical manuscript semantics.

## Automated verification

| Gate | Result |
|---|---|
| Full Python suite | `2970 passed in 146.70s` |
| Focused planning/API/MCP/pack/deletion suite | `826 passed in 3.72s` |
| Planning-source Ruff checks | Passed |
| Python bytecode compilation | Passed |
| Targeted workbench ESLint | Passed |
| TypeScript and production Vite build | Passed |
| Patch whitespace check | Passed |

The production build retained the repository's existing large-chunk advisory;
it introduced no build failure. The repository-wide ESLint command still has
pre-existing failures outside the changed workbench files, so the release gate
uses a targeted zero-warning check for every modified frontend source plus the
complete TypeScript production build.

## Browser walkthrough

The built frontend and a local RKA server were exercised against a disposable
SQLite database in the in-app browser.

1. Opened the manuscript workbench without a manuscript and confirmed the
   project-level empty planning state.
2. Created the initial branch and confirmed it became the deterministic
   selected resume head.
3. Forked `mechanism-first` from the selected branch and confirmed the child
   displayed its frozen parent revision.
4. Selected the child and confirmed the previous selection returned to active
   state with an appended branch event.
5. Compared the two alternatives and received deterministic added, removed,
   changed, and unchanged summaries.
6. Archived and reactivated the non-selected branch and confirmed history was
   preserved.
7. Reloaded the page and confirmed the selected branch and frozen ancestry
   resumed from server state rather than browser-only state.
8. Repeated the workbench layout check at `390 x 844`; the document and body
   widths remained 390 pixels and the branch controls remained reachable.
9. Checked browser error and warning logs after the flow; both were empty.

The first walkthrough exposed an async form-reset defect: React cleared the
event target before the request completed. Capturing the form element before
the await fixed it, and the complete create/fork flow passed after rebuilding.

## Deliberate boundary

This slice records AI-origin metadata but does not call an AI provider and does
not apply planning artifacts to canonical manuscripts or files. Unified human
and AI proposal envelopes, semantic diffs, validation, conflict resolution,
apply/reject, and provider adapters remain M3 / PR 6 work.
