# ADR 0011: Conflict-safe manuscript source synchronization

- Status: accepted for M5 / PR 10 implementation
- Date: 2026-08-17
- Baseline: `infinitywings/rka` `main` merge `116f76b`
- Scope: Markdown/LaTeX authoring files, stable manuscript-unit anchors,
  recoverable optimistic writes, provenance diagnostics, and public/private
  drafting views

## Context

RKA now owns a ratified manuscript aggregate: exact claim versions, claim
boundaries, typed evidence uses, typed citation intentions, progressive `mun_`
units, checkpoints, and readiness. Researchers still write the paper in normal
Markdown or LaTeX files. PR 10 must connect those files to RKA without making
either a second semantic authority or an unsafe remote filesystem API.

Source files also have a transaction boundary that SQLite cannot roll back. A
semantic-patch transaction therefore cannot safely include a file replacement.
The authoring path needs its own proposal ledger and recovery protocol while
retaining the same propose, inspect, explicitly apply, conflict, and audit
experience for human and AI edits.

## Decision

### 1. Preserve the four-layer authority model

- RKA remains authoritative for research evidence and manuscript semantics.
- Markdown and LaTeX remain authoritative only for public prose and layout.
- A source-edit proposal is a candidate authoring change, not evidence, a
  claim, a checkpoint, or a manuscript revision.
- Writing a file never changes claim wording, bindings, ratification, unit
  status, or readiness. Those changes continue through semantic proposals.
- An external editor may change a source file. RKA detects and reports that
  change; it does not overwrite it or infer a semantic update.

### 2. Use one source-proposal path for human and AI edits

Human and AI source changes use one immutable source-edit proposal envelope.
It records manuscript, relative path, source format, exact base hash, proposed
content and hash, origin/provider boundary, reason, validation findings, and
status. Creating a proposal does not touch the file. Only a PI or local web
user may apply or reject it.

The source ledger is intentionally separate from the semantic-patch ledger.
This avoids pretending that a filesystem replacement is part of a rollbackable
SQLite transaction. AI proposals still require a matching immutable Context
Capsule and may not self-apply. Direct API calls do not create a parallel write
path.

### 3. Resolve files only inside explicit allowlisted roots

`manuscripts.workspace_ref` selects a workspace, but it grants no authority by
itself. The server must also be configured with one or more
`RKA_MANUSCRIPT_WORKSPACE_ROOTS`. A source path must:

- be a normalized POSIX-relative path ending in `.md`, `.markdown`, or `.tex`;
- resolve below both the selected workspace and an allowlisted root;
- contain no symlink component;
- avoid `.git`, `.rka`, hidden recovery data, traversal, and special files;
- satisfy bounded UTF-8 file and request sizes.

An unconfigured, missing, foreign, or unsafe workspace fails closed. Source
content is never exposed through MCP in PR 10; it is a local web/REST surface.
The bundled Docker deployment binds the unauthenticated dashboard/API port to
host loopback. Remote access requires a separately reviewed authentication and
transport boundary; changing `X-RKA-Actor` is provenance, not authentication.

### 4. Make every replacement optimistic, atomic, and recoverable

Create, apply, reject, and supersede share a per-file advisory lock. Lock
acquisition uses nonblocking retries that yield to the async event loop, and the
lock remains held through the database terminal transition. A crash-applied
file with valid recovery metadata must be reconciled by retrying Apply; Reject
or Supersede cannot record a false terminal state.

Apply re-reads the file and compares its SHA-256 hash with the proposal's base
hash. A missing file is represented by the explicit sentinel `null`; an empty
file has the normal SHA-256 of empty bytes. Any mismatch marks the proposal
`conflicted`, preserves both versions, and performs no file write.

For a matching base, apply:

1. re-reads after asynchronous validation and requires the same base hash;
2. writes a recovery copy and manifest beneath the managed storage directory
   beside the active RKA database;
3. fsyncs the recovery file, manifest, leaf directory, and every newly ensured
   ancestor edge so a fresh recovery hierarchy is durable;
4. writes the proposed bytes to a deterministic same-directory swap file,
   preserves the existing regular-file mode, fsyncs the file, and fsyncs its
   containing directory;
5. for an existing target, atomically exchanges the target and swap names,
   hashes the exact displaced target, and restores that displaced object by a
   second exchange if it is not the reviewed base;
6. for a missing target, installs the proposed inode with a no-clobber hard link
   so a file that appears at the commit point wins and is never overwritten;
7. removes the validated displaced/swap name and fsyncs the source directory;
8. records the applied event with before, after, and recovery hashes.

The name-exchange primitive is `renameatx_np(..., RENAME_SWAP)` on macOS and
`renameat2(..., RENAME_EXCHANGE)` on Linux. A deployment without an atomic
exchange primitive fails closed instead of falling back to a check-then-rename
sequence. A deterministic swap left by a crash is reconciled before the ledger
can become `applied`: the service either finishes cleanup and repeats the source
directory fsync, or restores the exact displaced external object and records a
conflict.

The recovery manifest is durable even if the database event cannot be
committed after replacement. The service never runs `git add`, commit, reset,
checkout, merge, or push.

### 5. Use explicit, stable `mun_` range anchors

Anchors are comments that normal Markdown and LaTeX renderers ignore:

```markdown
<!-- rka:unit mun_... begin -->
Public prose.
<!-- rka:unit mun_... end -->
```

```tex
% rka:unit mun_... begin
Public prose.
% rka:unit mun_... end
```

The parser requires a unique, balanced, non-nested range per `mun_` in a file.
It validates that every unit belongs to the selected manuscript and reports a
content hash for the anchored region. Line numbers are diagnostic only; the
stable identity is the explicit `mun_` token. Duplicate, foreign, nested,
unbalanced, or removed-unit anchors are blocking findings for apply.

### 6. Treat provenance comments as verifiable links, not trusted evidence

An anchored unit may contain hidden comments such as:

```markdown
<!-- rka:provenance claim=mcl_... evidence=clm_... citation=Smith2026 -->
```

The service parses identifiers, then verifies them against that unit's current
claim links, typed evidence uses, and citation uses. Unknown, foreign, stale, or
unbound references are findings. A valid comment proves only that the prose
declares a link to a current RKA object; it does not prove the prose accurately
expresses that object. That judgment remains review work.

### 7. Keep public prose and private reviewer risk structurally separate

The source editor displays three distinct projections:

- **Draft source:** editable public Markdown/LaTeX plus a non-authoritative
  preview;
- **Quick reader:** current unit order, communicative job, takeaway, and
  quick-reader role, with anchor health;
- **Reviewer risk (private):** prohibited wording, qualifiers,
  counterevidence, unresolved citation verification, and unallocated adverse
  evidence.

Private material is never inserted into source content by projection or apply.
The UI labels it private planning context. The draft editor can link to those
records for review without copying them into public prose.

### 8. Project source impact without changing semantic readiness

The source projection joins current file anchors to `mun_` units and current
semantic bindings. It reports missing anchors, externally changed files,
unverified provenance comments, and upstream RKA impact for anchored units.
Source-file currency is an authoring diagnostic, not a semantic readiness gate
and does not invalidate PI checkpoints by itself.

## Consequences

- Researchers can use normal editors alongside the workbench without silent
  overwrites.
- RKA can navigate from prose ranges to exact units, claims, evidence, and
  citations while keeping the limits of that link visible.
- Candidate prose is reviewable and auditable without being promoted to
  semantic truth.
- Filesystem and database failure cannot be made perfectly atomic; the durable
  recovery-before-exchange protocol and deterministic swap make every expected
  partial naming state observable and repairable.
- Deployments must explicitly mount and allowlist manuscript workspaces.

## PR 10 exit gate

- migration applies on fresh, upgraded, and restarted databases;
- path traversal, symlink, special-file, size, encoding, and foreign-project
  attempts fail closed;
- human and AI edits use the same proposal service and only PI/web may apply;
- an external edit produces a durable conflict and leaves the file untouched;
- same-file apply/reject/supersede races yield rather than blocking the event
  loop and cannot produce a file/ledger terminal-state mismatch;
- applied writes are atomic, mode-preserving, and recoverable;
- Markdown and LaTeX anchors round-trip and invalid anchors are actionable;
- provenance comments are checked against current typed bindings;
- source, quick-reader, and private-risk views remain distinct;
- no source action invokes Git;
- focused, full, build/lint, restart, browser, and disposable real-project
  validations pass.
