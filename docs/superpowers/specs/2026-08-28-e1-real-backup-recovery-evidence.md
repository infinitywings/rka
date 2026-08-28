# E1.5 Real-Backup Upgrade and Recovery Evidence

- Date: 2026-08-28
- Issue: [#125](https://github.com/infinitywings/rka/issues/125)
- Candidate base: `6485d81` plus the bounded #125 implementation
- Live runtime observed read-only: RKA `3.0.0`, image
  `sha256:27121e4e687d8c09e9b057daee7637cabea69d71638056b45c746361499689bc`
- Previous runtime: RKA `2.9.0`, image
  `sha256:9de17a8f96b992ff312693d23f3ddb00645571836f97ceb3eb2b7617713bdf49`

## Safety boundary

The live database and containers were not migrated, restarted, replaced, or
re-embedded. A read-only SQLite online backup was written to container `/tmp`,
normalized to a portable single-file DELETE-journal database, copied to
`/private/tmp`, and then removed from the container. Every subsequent write
used a disposable database or temporary bind mount.

The source snapshot:

- SHA-256: `acc7f225e2cb59792f08bee82947db355921dddba69faf055b6c7ca41c2d5f8c`
- size: 200,622,080 bytes;
- SQLite `integrity_check`: `ok`;
- foreign-key violations: 0;
- projects: 20;
- SQL migrations: 53;
- runtime schema upgrades: 1.

The committed report must not contain the snapshot, record text, raw entity-ID
sets, artifact files, or project paths. The final private JSON report is
`/private/tmp/rka-e1-125-report-v4.json`.

## Upgrade and idempotence result

`scripts/core_recovery_smoke.py` took another online snapshot and ran the
normal base-plus-Phase-2 initialization path against only a temporary copy.

| Check | Result |
|---|---|
| SQLite integrity after candidate startup | pass |
| Foreign-key findings before/after | 0 / 0 |
| Shared non-index data tables | 78 / 78 |
| Changed row digests | none |
| Changed ID sets | none |
| Changed link tables | none |
| Changed revision tables | none |
| SQL migrations before/after | 53 / 53 |
| Runtime upgrades before/after | 1 / 1 |
| Second migration pass | 0 applied |

This was a schema-53 compatibility/idempotence case. It therefore required
exact preservation and did not invoke the older migration-052 repair allowance.

## Knowledge-pack result

Two complementary real projects were selected without committing their raw IDs
or content:

| Project role | Project fingerprint | Re-keyed entity count | Canonical mismatch | Critical target issue |
|---|---|---:|---:|---:|
| Experiment plan/run/observation/locator chain | `8bd3f780b15ec013` | 227 | 0 | 0 |
| Claim, cluster, edge, decision, and journal graph | `71f1fdf364e13da1` | 726 | 0 | 0 |

For each pack, the harness captured the importer's in-memory ID bijection and
independently compared source-database rows with the manifest, then
mapped the source manifest forward into the target namespace without calling
the production remap helpers. Project metadata/state, portable Core rows,
links, revisions, ID-map
coverage/uniqueness, manifest counts, imported counts, and final semantic
integrity all matched. These two real packs contained no claim-scope versions
or artifacts, so those checks were not represented as non-vacuous real-data
evidence. FTS/vector rows and rebuildable derived views were also not
represented as exact live-database preservation evidence.

Focused provider-free regressions separately proved that both inline pack
import and background `index_project()` rebuild artifact and figure vector
rows with the target `project_id` and correct `entity_type`, and that both are
searchable after import. The recovery regression used a non-empty bundled
artifact and verified its imported bytes. Another regression proved that
re-keying an entity ID embedded in claim prose updates a previously current
claim-scope hash while an already stale scope remains stale.

## Exact rollback and previous-runtime result

The harness restored the untouched backup byte-for-byte into a third temporary
path and reproduced the complete pre-upgrade logical snapshot. The pinned RKA
2.9.0 image then ran its normal migration command against only that restored
copy:

```text
rka, version 2.9.0
Applied 0 migration(s).
```

Post-open verification under the previous runtime found:

- SQLite integrity: pass;
- foreign-key violations: 0;
- SQL migrations: 53;
- runtime upgrades: 1;
- changed rows, IDs, links, or revisions: none.

This proves that the preserved backup and exact previous image form a usable
rollback pair. It does not authorize replacement of the live deployment.

## Pre-existing installation findings

The source-wide semantic check also reported installation-local warnings while
validating each selected project: incomplete index inspection, orphaned FTS
rows, orphaned vector rows, and stranded entities. Existing integrity queries
collect capped samples across several index families, so their reported counts
are **sample counts, not exact totals**. These findings were neither caused nor
repaired by #125. They require a separate, explicitly authorized maintenance
investigation before any deletion, reindex, or re-homing action.

## Automated verification

The final candidate passed the following independent gates:

| Gate | Result |
|---|---|
| Focused backup, pack, vector partition/search, migration, and recovery regressions | 82 passed |
| Core suite (`not writer and not agentic`) | 3,021 passed |
| Retained Writer/Agentic compatibility suite | 294 passed |
| Core startup smoke | migrations, REST, MCP, worker, and sqlite-vec passed |
| Compose validation | `docker compose config --quiet` passed |
| Patch hygiene | selected Ruff checks and `git diff --check` passed |

The startup smoke used a temporary loopback port and disposable database. No
test in this final gate changed the live RKA database or container state.
