# M3 / PR 6 semantic-proposal exit evidence

- Date: 2026-08-15
- Baseline: `5ec717fca5936853ae80e71d5594e2557f37a1be`
- Scope: unified human, host-agent, and local-model semantic proposals
- Data safety: the browser walkthrough used only a disposable database under
  `/private/tmp`; no live RKA project or manuscript record was changed

## Contract exercised

The release candidate implements the boundary frozen in
[ADR 0006](../../adr/0006-unified-semantic-patch-proposals.md):

- one immutable `spp_` envelope for human, host-agent, and LM Studio edits;
- semantic before/after previews with keyed claim and unit changes;
- explicit apply, reject, supersede, and stale-base conflict transitions;
- atomic target snapshots, proposal persistence, apply checks, and provider
  success recording;
- exact `pcm_` disclosure manifests with resolved evidence, aggregate
  snapshots, omissions, constraints, and provider-call events;
- fail-closed AI scope checks for undisclosed targets, undisclosed evidence,
  and aggregate revisions changed after disclosure;
- no proposal-time mutation and no silent PI ratification changes;
- local-machine-only LM Studio configuration with schema-constrained output,
  redirects disabled, proxy environment ignored, and no cloud fallback;
- REST, MCP, workbench, KnowledgePack v7, whole-project deletion, and
  change-cursor parity; and
- Writer guidance that uses the proposal path while retaining direct CLI apply
  only as an explicitly reviewed compatibility workflow.

## Automated verification

| Gate | Result |
|---|---|
| Full Python suite | `3026 passed in 157.52s` |
| Focused semantic proposal/API/migration/pack suite | `14 passed in 2.42s` |
| MCP coverage | Included in the full suite; all MCP tests passed |
| Changed Python Ruff checks | Passed |
| Python bytecode compilation | Passed |
| Targeted changed-workbench ESLint | Passed with zero warnings |
| TypeScript and production Vite build | Passed |
| Docker Compose configuration | Valid |
| Dispatch schema count | `139` operations: `62` reads and `77` writes |
| Patch whitespace check | Passed |

The production build retains the repository's existing large-chunk advisory;
it introduces no build failure. The known baseline import-placement and unused
symbol findings in `rka/mcp/server.py` were excluded from the changed-source
Ruff gate; the modified server surface passed when those pre-existing findings
were ignored.

## Disposable browser walkthrough

The production frontend and the feature-branch API were served on a temporary
loopback port against a fresh SQLite database.

1. Opened the manuscript workbench and confirmed project-only proposal actions
   were disabled without a canonical manuscript.
2. Created and loaded a disposable native manuscript. The title and revision
   were projected from the canonical context endpoint.
3. Proposed a new title through the human workbench form. The proposal ledger
   showed one unapplied item and one `/title` semantic change while the
   canonical title remained unchanged.
4. Expanded the before/after preview, explicitly applied the proposal, and
   confirmed the ledger changed to `applied`, the pending count returned to
   zero, and the canonical title advanced only after approval.
5. Created a second proposal, explicitly rejected it, and confirmed the
   canonical title did not change.
6. Exercised the LM Studio form without a configured model and confirmed the
   server's actionable 422 configuration error appeared in the UI without a
   browser console warning or error.
7. Confirmed browser error and warning logs were empty throughout the successful
   propose, preview, apply, and reject flow.

The first walkthrough exposed a UI integration defect: the shared Base UI
button does not implicitly submit forms. `Save proposal` and `Generate
proposal` therefore appeared enabled but performed no request. Both controls
now declare `type="submit"`; the rebuilt flow passed end to end.

## Deliberate boundary and optional-provider status

LM Studio was installed but its OpenAI-compatible server was not listening on
`127.0.0.1:1234` during this gate, so a real model completion was not claimed.
Schema-valid generation, provider start/success/failure attribution, malformed
response handling, endpoint restrictions, and no-mutation behavior are covered
by automated adapter/service tests. A live local-model quality evaluation is an
optional deployment check, not authority for proposal validation or apply.

This slice intentionally does not add the guided seed-to-contribution workflow,
evaluation matrix, progressive outline editor, or manuscript-file writes.
Those remain M4 and M5 work after PR 6 review and merge.
