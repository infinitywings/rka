# Legacy Writer compatibility export

E2.3 provides a one-way, read-only handoff from the frozen Writer tables in
RKA Core to standalone `rka-writer` staging. It does **not** switch authority,
delete Core data, or make Writer a dependency of Core.

## Create the bundle

The CLI creates a private disposable backup with SQLite's online-backup API,
exports from that immutable snapshot, and deletes the temporary database:

```bash
rka export-writer \
  --project-id prj_01... \
  --output /private/tmp/rka-writer/project.rka-writer-export.zip
```

`export-writer` opens only its backup with SQLite immutable/read-only/query-only
enforcement, checks SQLite integrity, frozen table schemas, Writer-owned
foreign keys, internal Writer and external Core logical references, and
embedded content hashes, and atomically writes a mode-0600 archive. Missing
projects, tables, primary keys,
project-scoping columns, or referenced records fail visibly.

## Bundle contract

The machine-readable v1 descriptor is
[`contracts/rka-legacy-writer-export-v1.json`](../contracts/rka-legacy-writer-export-v1.json).
The archive contains:

- `manifest.json`, with Core/schema versions, source project identity, the
  exact table inventory, row counts, schema hashes, table hashes, an external
  Core-reference index, the aggregate semantic root, and an
  explicit `authority_switched: false` attestation; and
- one canonical JSON payload under `tables/<table>.json` for every frozen
  Writer table, including empty tables.

Rows remain project-scoped and retain their original identifiers, revisions,
bindings, ratifications, reference locators, source proposals, immutable
events, and timestamps. Each table descriptor records its primary key,
columns, foreign keys, row count, payload SHA-256, and schema SHA-256. The
aggregate `semantic_root_sha256` covers table data/schema descriptors and Core
reference snapshots, making staging comparison independent of ZIP metadata.

The v1 table set is frozen. A missing or additional table, incompatible
descriptor, or changed format version requires a new compatibility version;
it must not be silently accepted as v1.

## Import boundary

Use the matching standalone Writer importer from `rka-project/rka-writer`:

```bash
python -m rka_writer_staging stage \
  /private/tmp/rka-writer/project.rka-writer-export.zip \
  --staging-root /private/tmp/rka-writer/staging
```

The importer verifies the complete bundle before committing generic staging
rows. Staged data is inspection/migration input only. Promotion into future
Writer-owned schemas and the authority switch are E4 work; removal of legacy
Core state is a separately approved E5 breaking change.
