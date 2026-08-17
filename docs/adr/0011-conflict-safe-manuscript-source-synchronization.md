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
`conflicted` and preserves both versions. A mismatch found before the commit
point performs no exchange. A mismatch discovered by inspecting the exact
displaced object after exchange triggers an immediate reverse exchange; the
proposal can therefore be transiently observable to another local reader, but
the final public target is restored before the conflict becomes terminal.
Conflict events distinguish an observed exchange, no observed exchange, and a
recovery-era state where an earlier exchange is possible but no longer provable.

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
   verifies both the installed proposal and the exact displaced target, and
   restores the prior target by a second exchange if either boundary object
   differs from its reviewed hash;
6. for a missing target, installs the proposed inode with a no-clobber hard link
   so a file that appears at the commit point wins and is never overwritten;
7. for an existing target, retains the exact displaced inode at its deterministic
   hidden recovery name so writes through an editor descriptor opened before
   exchange cannot be destroyed by unlink; for a missing target, removes the
   redundant proposal hard link;
8. fsyncs the source directory and records the applied event with before, after,
   recovery, and retained-displaced paths.

The name-exchange primitive is `renameatx_np(..., RENAME_SWAP)` on macOS and
`renameat2(..., RENAME_EXCHANGE)` on Linux. A deployment without an atomic
exchange primitive fails closed instead of falling back to a check-then-rename
sequence. A deterministic swap left by a crash is reconciled before the ledger
can become `applied`: the service either finishes cleanup and repeats the source
directory fsync, or restores the exact displaced external object and records a
conflict. Recovery classification runs before any fresh replacement, including
when the public target has returned to base-equivalent bytes. A retry that sees
an external or base-equivalent target with valid recovery metadata retains any
pre-existing deterministic recovery inode, whether it currently contains
proposal, reviewed-base, or unclassified bytes. This also protects a descriptor
opened while proposal bytes were transiently public during a rolled-back
exchange. The service then repeats the source-directory fsync before the ledger
can become terminally `conflicted`; Reject and Supersede share the same guard.
Only a swap freshly created and still owned by the current pre-exchange
invocation may be unlinked automatically. A missing-file hard-link install may
also drop the redundant hidden name because the same inode remains public.
Recovery classification is bounded: an oversized retained regular inode is
reported as `oversized` without reading it into memory, retained in place, and
does not prevent Apply conflict, Reject, or Supersede from reaching a durable
terminal state. Symlinks and non-regular recovery objects still fail closed.

Source events separate the durable naming fact from a mutable byte
classification. `source_recovery_state` says only whether a recovery name was
retained, missing, or not checked. `source_recovery_last_observed` records the
last bounded observation (`reviewed_base`, `proposal`, `unclassified`,
`oversized`, or `missing`) immediately before the transition. It is not a
promise that a still-open external descriptor cannot change those bytes later;
the retained path is the durable audit handle. `retained_source_path` is generic;
`displaced_source_path` is populated only when an original target actually
existed, never for a redundant proposal hard link from missing-file recovery.

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
- Each successful existing-file Apply retains one hidden displaced-inode
  recovery artifact next to the source. This deliberate storage cost is what
  preserves late writes through pre-opened editor descriptors; PR 10 never
  deletes those artifacts automatically. Project-deletion preview and result
  enumerate their deterministic candidate paths before deleting the RKA ledger;
  cleanup remains a deliberate researcher action after all editor descriptors
  are closed.
- Filesystem and database failure cannot be made perfectly atomic; the durable
  recovery-before-exchange protocol and deterministic swap make every expected
  partial naming state observable and repairable.
- Deployments must explicitly mount and allowlist manuscript workspaces.

## PR 10 exit gate

- migration applies on fresh, upgraded, and restarted databases;
- path traversal, symlink, special-file, size, encoding, and foreign-project
  attempts fail closed;
- human and AI edits use the same proposal service and only PI/web may apply;
- an external edit produces a durable conflict and restores the exact external
  target before the ledger becomes terminal, even if a transient exchange was
  observable;
- same-file apply/reject/supersede races yield rather than blocking the event
  loop and cannot produce a file/ledger terminal-state mismatch;
- applied writes are atomic, mode-preserving, and recoverable;
- Markdown and LaTeX anchors round-trip and invalid anchors are actionable;
- provenance comments are checked against current typed bindings;
- source, quick-reader, and private-risk views remain distinct;
- no source action invokes Git;
- focused, full, build/lint, restart, browser, and disposable real-project
  validations pass.
