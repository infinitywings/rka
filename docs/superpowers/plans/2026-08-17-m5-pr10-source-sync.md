# M5 PR 10 implementation plan: manuscript source synchronization

- Date: 2026-08-17
- Tracking issue: #61
- Depends on: merged PR #84 / typed academic-writing core
- Design authority: ADR 0011

## Goal

Add a narrow local authoring workbench for Markdown and LaTeX that keeps prose
linked to RKA's ratified manuscript units while preventing stale overwrites,
unsafe path access, accidental publication of private risk material, and
automatic Git mutation.

## Slice A: source proposal and recovery substrate

1. Add migration 050 with immutable source-edit proposals and append-only
   transition events.
2. Add typed request/response models and new ID prefixes.
3. Add configured workspace-root and recovery-root policy to `RKAConfig`.
4. Implement strict path resolution, bounded UTF-8 reads, SHA-256 currency,
   recovery manifests, same-directory atomic replacement, and directory fsync.
5. Mark a proposal conflicted when the current file hash differs; retain the
   proposed content and current hash in the event ledger.

Gate: unit tests prove no write before apply, exact replay/conflict behavior,
recovery-before-replace, mode preservation, and no Git subprocess path.

## Slice B: anchors, provenance, and projections

1. Parse balanced Markdown/LaTeX `mun_` ranges without nesting or overlap.
2. Resolve anchor unit IDs against the selected manuscript and report region
   hashes and line diagnostics.
3. Parse hidden provenance comments and verify claim, evidence, and citation
   references against current unit bindings.
4. Project source files, anchor health, quick-reader flow, and private reviewer
   risk without mutating semantic readiness.
5. Include source proposal/event tables in project deletion and integrity
   checks. Keep file content out of KnowledgePack export; export only an
   explicit omission warning because workspace files and recovery data are
   installation-local.

Gate: Markdown and LaTeX round trips, malformed/foreign anchor rejection,
binding mismatch diagnostics, project isolation, deletion, and pack omission
tests pass.

## Slice C: REST and local workbench

1. Add local REST endpoints to list/read source files, create/get/list source
   proposals, and explicitly apply/reject them.
2. Restrict source reads and proposal transitions to the local web transport;
   do not expose source content in the MCP operation registry.
3. Add a `SourceSyncPanel` to the Outline stage with file selector, source and
   preview split view, hash/currency state, anchor/provenance diagnostics, and
   a prepare-then-apply flow.
4. Add separate Quick reader and Reviewer risk tabs. Reviewer risk is visibly
   private and cannot populate the source editor automatically.
5. Preserve unsent edits when a background refetch notices an external file
   change; require compare/reload or a new proposal.

Gate: keyboard navigation, labels, readable conflict/recovery messages,
responsive layout, production build, changed-file lint, and browser console
health pass.

## Slice D: release evidence

1. Run migration fresh/upgrade/restart tests.
2. Run service, REST, authorization, project-scope, and security tests.
3. Run MCP drift tests to prove the surface did not accidentally expand.
4. Run the complete Python suite and production web build/lint.
5. Use a disposable copy of a mature manuscript workspace to demonstrate:
   - one Markdown and one LaTeX anchor;
   - verified support and citation provenance;
   - a private qualifier/counterevidence risk;
   - a successful apply and recovery artifact;
   - an external-edit conflict with no overwrite;
   - restart persistence and zero Git mutation.
6. Request an independent code and workflow audit, correct findings, and only
   then merge.

## Deliberate non-goals

- Word or rich-text round trips;
- LaTeX macro expansion or compilation;
- automatic prose generation or semantic promotion;
- three-way merge automation (PR 10 preserves both versions and supports
  explicit rebase; it does not guess a merge);
- automatic Git operations;
- MCP exposure of arbitrary source files;
- source inbox/repository/URL ingestion, which remains PR 11.
