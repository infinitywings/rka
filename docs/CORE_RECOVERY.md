# RKA Core Backup and Recovery

This runbook validates recovery without modifying the live RKA database or
replacing a running container. It deliberately uses temporary directories and
an exact previous image ID. Do not use the stock Compose file for a parallel
drill: its fixed container names and port collide with the live deployment.

## Create a consistent backup

`rka backup` uses SQLite's online-backup API. It includes committed WAL pages,
writes an integrity-checked temporary database, and atomically publishes the
destination as a portable single-file DELETE-journal snapshot. A foreign-key
warning describes findings already present in the source; it does not silently
repair or omit them.

```bash
rka backup --output /private/tmp/rka-recovery/source.db
```

When RKA runs in Docker, create the snapshot inside the mounted data volume and
then copy only that completed snapshot out of the container:

```bash
docker exec rka-server rka backup --output /data/recovery-source.db
docker cp rka-server:/data/recovery-source.db /private/tmp/rka-recovery/source.db
```

## Run the disposable validation

Select one or more real projects that cover the desired Core records. The
script makes another online snapshot, upgrades only temporary copies, compares
all shared data-table counts and digests, validates portable Core pack state
under intentional ID re-keying, and restores an exact rollback copy. It rejects
a report path that aliases the database or its runtime files. Its persisted JSON
contains counts, schema names, and hashes rather than research content, paths,
exception messages, or raw entity IDs.

```bash
python scripts/core_recovery_smoke.py \
  --source-db /private/tmp/rka-recovery/source.db \
  --project-id prj_FIRST \
  --project-id prj_SECOND \
  --report /private/tmp/rka-recovery/report.json
```

This smoke is a current-schema compatibility and idempotence gate. Shared
canonical rows, IDs, links, revisions, and both migration ledgers must remain
exact. Test an older database as a separate reviewed migration case with an
explicitly documented set of expected migrations; this command does not
silently allow ledger or data changes.

Knowledge-pack import is a clone operation: entity IDs intentionally change.
The smoke reads canonical Core rows independently from the source database,
compares them with the manifest, then independently maps the source manifest
forward into the target namespace by the captured one-to-one ID map. It
compares that expectation with raw imported rows plus project metadata/state,
links, revisions, scope hashes, artifact bytes, counts, and final integrity.
The equality gate intentionally excludes FTS/vector indexes and rebuildable
derived views such as review queues, topics, context snapshots, keynodes, and
graph views; their behavior has separate focused tests. It does not redefine
the separate Writer compatibility export planned for E2.

## Prove rollback with the previous runtime

Before building or replacing any image, record the exact image ID used by the
running server. A mutable tag such as `latest` is not rollback evidence.

```bash
docker inspect --format '{{.Image}}' rka-server
docker image inspect --format '{{.Id}}' IMAGE_ID_FROM_PREVIOUS_COMMAND
```

Copy the untouched backup into a third temporary directory, remove any stale
sidecars in that directory, and let the pinned old image run its normal
base-plus-Phase-2 startup path against only that copy:

```bash
mkdir -p /private/tmp/rka-recovery/old-runtime
cp /private/tmp/rka-recovery/source.db /private/tmp/rka-recovery/old-runtime/rka.db
rm -f /private/tmp/rka-recovery/old-runtime/rka.db-wal \
  /private/tmp/rka-recovery/old-runtime/rka.db-shm \
  /private/tmp/rka-recovery/old-runtime/rka.db-journal \
  /private/tmp/rka-recovery/old-runtime/rka.db.phase2.lock
docker run --rm --name rka-recovery-old \
  -v /private/tmp/rka-recovery/old-runtime:/data \
  IMAGE_ID_FROM_PREVIOUS_COMMAND rka migrate
```

Record the image ID, `rka --version`, migration/runtime ledgers, SQLite
integrity, foreign-key findings, and the restored snapshot comparison in the
private recovery evidence. Never point the old image at the upgraded copy or
the live `rka-data` volume.

## Recovery gate

Do not replace live state unless all of the following are true:

- the online backup passes SQLite integrity and its SHA-256 is recorded;
- the disposable upgrade is idempotent and reports no unexplained row, ID,
  link, or revision change;
- selected packs preserve canonical Core state and final integrity;
- the exact backup is restored and the pinned previous runtime opens it;
- the live migration/replacement has separate PI authorization.
