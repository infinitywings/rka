# M5 PR 10 Exit Evidence: Conflict-Safe Manuscript Source Synchronization

Date: 2026-08-17
Baseline: `main` at `116f76b`
Implementation branch: `codex/m5-source-sync`
Tracking issue: #61
Design authority: ADR 0011

## Scope exercised

- Migration 050 on a fresh database, after restart, and as a late migration over
  existing manuscript records.
- Immutable source proposals and append-only proposal events with project-scoped
  foreign keys and deletion authorization.
- Explicitly allowlisted Markdown/LaTeX workspace reads with traversal,
  symlink, special-file, UTF-8, and size-boundary checks.
- Balanced `mun_` source ranges and exact claim, evidence, and citation
  provenance validation against current manuscript bindings.
- Prepare, review, apply, reject, supersede, hash-conflict, crash-recovery,
  nonblocking same-file transition serialization, mode-preserving atomic
  exchange, durable managed manifests, and retained displaced-inode recovery
  without Git operations.
- Quick-reader source ranges and a separate private reviewer-risk projection for
  boundaries, qualifiers, counterevidence, and citation-verification warnings.
- Local-web-only REST authorization; arbitrary manuscript source content is not
  added to the MCP surface or portable KnowledgePack payloads. The bundled
  Docker port is now host-loopback-only so this unauthenticated surface is not
  published to the LAN by default.
- Project deletion removes chained source-proposal histories, ledger rows, and
  managed recovery data while failing closed on a replaced recovery-directory
  symlink.
- Responsive workbench controls for file selection, public source editing,
  preview, diagnostics, external-change detection, and explicit review/apply.

## Disposable end-to-end pilot

A disposable project, manuscript, workspace, and database under
`/private/tmp/rka-source-pilot` exercised the production web build against a
loopback-only RKA server. The pilot contained:

- one Markdown file and one LaTeX file with stable `mun_` anchors;
- one unit-bound manuscript claim, verified support, private qualifier,
  private counterevidence, and a self-attested citation;
- valid hidden provenance for the public source;
- a deliberately private prohibited-wording boundary.

The browser workbench demonstrated that:

1. Preparing `msp_01M08QHN6FPMV6DK6KRPTCKG80` left `main.md` at its original
   SHA-256 and status `proposed`.
2. Reloading the workbench showed only `Review source diff`; no Apply control was
   available until the full current/proposed source was loaded for review.
3. Explicit Apply atomically replaced the file, advanced the proposal to
   revision 2 / `applied`, and retained `before.bin` plus a versioned recovery
   manifest. The applied event records `git_operation: false`.
4. Restarting the server preserved the applied proposal, both transition events,
   the recovery path, and the full reviewed content.
5. The Quick reader linked the canonical unit to both Markdown and LaTeX ranges.
   The private tab showed the claim boundary, qualifier, counterevidence, and
   stale citation warning without placing them in the public editor.
6. A clean editor adopted an external source change through the ten-second poll
   without a manual check. After a keyboard-entered unsent draft, the next
   external edit updated the displayed source hash but preserved the draft,
   raised the explicit conflict banner, and disabled Prepare. Reload remained a
   separate user action; no overwrite occurred.
7. A 390x844 responsive check initially exposed a narrow tab/header overflow.
   The panel was corrected with wrapping, minimum-width, and mobile-select rules,
   then visually rechecked successfully.
8. The final browser console contained no warnings or errors.

The pilot workspace is disposable and is not part of the repository. It did not
touch a live research project or invoke a model.

## Automated evidence

| Gate | Result |
| --- | --- |
| Migration/source/API/project/pack corrective suite (command below) | **69 passed** |
| MCP schema/model-drift suite (command below) | **994 passed** |
| Full Python suite: `.venv/bin/python -m pytest -q` | **3,202 passed in 251.74s** |
| Changed Python files: Ruff | **Passed** |
| Python compile check: `.venv/bin/python -m compileall -q rka` | **Passed** |
| Git whitespace/error check: `git diff --check 116f76b --` | **Passed** |
| Docker Compose validation: `docker compose config --quiet` | **Passed** |
| Web production build: `(cd web && npm run build)` | **Passed**; existing large-chunk warning remains |
| Changed web files: ESLint | **Passed** |
| Browser prepare/review/apply/restart/automatic-conflict/private-risk pilot | **Passed** |

Corrective suite command:

```text
.venv/bin/python -m pytest -q tests/test_db/test_migration_050.py tests/test_services/test_manuscript_source.py tests/test_api/test_manuscript_sources.py tests/test_services/test_project.py tests/test_services/test_knowledge_pack_native.py
```

MCP schema/model-drift command:

```text
.venv/bin/python -m pytest -q tests/test_mcp/test_v270_model_drift.py tests/test_mcp/test_mcp_tool_surface.py tests/test_mcp/test_native_manuscript_operations.py
```

Ruff command:

```text
.venv/bin/python -m ruff check rka/api/app.py rka/api/deps.py rka/api/routes/manuscript_sources.py rka/config.py rka/infra/ids.py rka/models/manuscript_source.py rka/services/knowledge_pack.py rka/services/manuscript_source.py rka/services/project.py tests/test_api/test_manuscript_sources.py tests/test_db/test_migration_050.py tests/test_services/test_knowledge_pack_native.py tests/test_services/test_manuscript_source.py tests/test_services/test_project.py
```

Changed-web ESLint command:

```text
cd web && npx eslint src/api/client.ts src/api/types.ts src/components/workbench/SourceSyncPanel.tsx src/hooks/useManuscriptSources.ts src/pages/ManuscriptWorkbench.tsx
```

The disposable virtual environment uses the repository-locked
`sqlite-vec==0.1.6`; no temporary dependency override was needed for the final
full-suite result.

## Independent-audit corrections

The first exact-commit audit kept the candidate in draft and identified
same-file event-loop blocking, terminal-transition races, a late external-edit
overwrite window, deletion failure for supersession chains, omitted unallocated
adverse evidence, and a UI guard that depended on manual refresh. The corrected
candidate adds deterministic regression coverage for:

- two concurrent same-file applies completing without event-loop deadlock;
- apply racing reject and supersede after the filesystem commit point;
- a late external edit injected at the final atomic-exchange call, with the exact
  displaced external object restored instead of overwritten;
- an editor descriptor opened before Apply writing after displaced-byte
  validation, with that exact inode still linked at the recorded hidden recovery
  path after the public target and ledger become applied;
- missing-file creation with a no-clobber hard link, including an external file
  appearing at the commit point;
- database interruption after exchange, interrupted exchange with the reviewed
  base retained at the deterministic swap name, and failure between cleanup and
  source-directory fsync, all reconciled by retrying Apply;
- restoration of an external object retained by a crash-interrupted exchange;
- retry of every recovery-ancestor directory-fsync barrier and the failed source
  directory fsync before the ledger may become applied;
- retry of a failed rollback-directory fsync before Apply may record conflict,
  plus the same durable recovery guard for Reject and Supersede;
- retention of every pre-existing deterministic recovery inode before terminal
  conflict, including proposal, reviewed-base, and unclassified content, with
  the source directory fsynced and retained path recorded as the ledger closes;
- restart classification before any fresh replacement when a valid recovery
  manifest and retained inode exist, including a public target whose bytes have
  returned to the reviewed base;
- boundary verification of both installed proposal and displaced target, with a
  mutated proposal inode restored to its hidden recovery name instead of being
  unlinked;
- rejection of a crash-applied proposal until Apply reconciles the ledger;
- deletion of a service-created three-proposal supersession history, plus
  explicit preview/result reporting of source-adjacent recovery candidates that
  are intentionally not auto-deleted;
- private projection of unallocated claim-level qualifier and counterevidence;
- direct invalid-UTF-8 and configured-size-limit reads; and
- an automatic clean-editor reload followed by a background refetch preserving
  a dirty browser draft and disabling Prepare.

The browser pilot remains complementary disposable evidence rather than a
committed test artifact. The concurrency, recovery, deletion, and risk
semantics above are established by committed deterministic tests.

## Review interpretation

These checks establish the implementation candidate's source-synchronization
contract, local security boundary, crash/conflict behavior, and workbench
interaction. They do not establish support for arbitrary LaTeX macro expansion,
Word round trips, automatic three-way merging, or automatic prose generation;
those remain deliberate non-goals. The candidate remains unmerged until an
independent audit reviews the exact commit and any findings are corrected.
