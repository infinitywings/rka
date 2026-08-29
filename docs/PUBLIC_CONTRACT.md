# RKA Core public contract

RKA Core exposes versioned REST and MCP contracts for clients that do not
import Core models, services, or database code. The discovery endpoint is
`GET /api/capabilities`; clients should require `rka-core/v1` before starting
a workflow. The reviewable baselines are checked into
`contracts/rka-rest-v1.openapi.json` and `contracts/rka-mcp-v1.json`.

## Stable, preview, and compatibility surfaces

The initial `rka-rest/v1` baseline contains 133 stable Core operations. The
initial `rka-mcp/v1` baseline contains 81 stable typed operations behind the
five default transport tools (`rka_query`, `rka_execute`, `rka_describe`,
`rka_load_tools`, and the compatibility alias `rka_help`).

This snapshot describes the default stdio profile. Optional connector-only
skill adapter tools (`rka_list_skills`, `rka_read_skill`, and
`rka_start_session`) are disabled while the snapshot is generated and remain
outside `rka-mcp/v1`. The two compatibility transport entrypoints
`rka_load_tools` and `rka_help` are frozen here as transport schemas; they are
not additional typed research operations.

Product ownership and usage readiness are different dimensions. The current
runtime also exposes 28 REST and 22 MCP Core-owned preview operations. They are
listed in each snapshot so their boundary cannot drift silently, but they do
not receive the v1 stability promise. Frozen Writer operations, shelved
Agentic operations, and Core-legacy summary/session operations are likewise
inventoried but excluded from the stable Core contract.

An intentional additive change, such as a new optional response field or a
new operation, may update a v1 snapshot after review. Removing or renaming an
operation or field, adding a required input, narrowing an enum/type, changing
response status or shape, or changing project-scoping semantics requires a new
contract version unless an explicitly reviewed compatibility plan preserves
existing clients.

## Project scope

Every project-scoped REST request must explicitly send either the
`X-RKA-Project` header or the `project_id` query parameter. Every
project-scoped MCP operation must explicitly include `project_id`. There is no
active-project or default-project fallback. Unscoped discovery and lifecycle
operations, including capabilities, health, project listing, and project
creation, are the exceptions declared by their schemas.

The server validates that the selected project exists before a scoped
operation runs. A missing scope returns 422; an unknown project returns 404.
Clients must keep one project ID pinned through a logical workflow rather than
relying on session state.

## Revisions, hashes, and cursors

Revision and hash fields are not universal properties of every Core record.
Clients may depend on them only where the endpoint schema declares them. For
example, claim-scope writes use `expected_revision`; a stale revision returns
409, and the resulting scope version records `revision` and
`claim_content_hash`. Experiment plans and evidence/artifact records have
their own declared revision or content-hash fields.

`GET /api/changes?cursor=...` returns a project-scoped synchronization cursor.
That cursor orders the change feed; it is not an entity revision and must not
be used as an optimistic-lock value. Knowledge-pack manifests and future
export contracts may define additional checksums independently.

## Retry and idempotency expectations

Core does not currently implement a general `Idempotency-Key` header. Retry
behavior is therefore operation-specific:

- Reads are safe to retry.
- Claim-to-cluster `member_of` edge creation uses a natural key and returns the
  existing edge when repeated. Artifact registration is content-addressed
  within a project. These writes are safe to repeat with identical inputs.
- Revision-guarded writes must reuse the revision they actually read. A stale
  write fails with 409 and requires a new read and an explicit reconciliation;
  it must not be silently replayed against the newer revision.
- General create operations, including journal entries, decisions,
  literature, missions, projects, and most other POST requests, are not
  covered by a generic idempotency promise. After a timeout or lost response,
  query the relevant public read/change surface and reconcile before deciding
  whether to create again. Blind retry can create a second record.

These rules describe the current implementation. The architectural goal that
all retriable writes eventually accept an idempotency key is not yet a public
Core v1 guarantee.

## Reviewing and updating snapshots

Run the read-only check locally with:

```bash
python scripts/update_contract_snapshots.py
```

For an intentional contract change, regenerate both baselines with:

```bash
python scripts/update_contract_snapshots.py --write
```

The pull request must explain the semantic change and include the readable
JSON diff. CI runs the check independently and fails if runtime schemas and the
checked-in snapshots differ. Prose-only schema descriptions, examples, build
timestamps, and package patch versions are removed from the baseline so the
diff remains focused on wire behavior.

Knowledge Pack format v8 also transports immutable `src_` registered-source
envelopes, `sad_` explicit admissions, and the exact artifact bytes they hash.
Import fails closed when the source manifest, artifact hash, candidate revision,
canonical target, or provenance edge does not agree. Source registration alone
never grants canonical journal/claim/decision status.
