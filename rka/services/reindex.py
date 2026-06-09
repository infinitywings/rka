"""FTS index rebuild — recovery path for search-index drift (v2.7.0.7).

The FTS5 indexes are maintained entirely in application code
(`BaseService._sync_fts`). Any write-path slip — a missing `_sync_fts`
call, a swallowed INSERT failure, a partial knowledge-pack import — leaves
the index silently out of sync with the source rows, degrading search
recall with no operator signal and (until now) no in-product repair.

`reindex_fts` rebuilds every FTS table from its authoritative source
table. It is the recovery path surfaced as `rka admin reindex`.

Design:
  - For each entity type, DELETE the FTS rows then re-INSERT from source.
  - Optionally scope to one project_id (only that project's ids are
    rebuilt — useful for a targeted repair without touching other
    projects' index rows).
  - Per-table work runs inside a SAVEPOINT so a failure on one table does
    not corrupt the others; the failure is reported, not swallowed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rka.infra.database import Database

logger = logging.getLogger(__name__)


# entity_type -> (source_table, fts_table, text_columns)
# `id` is always the first FTS column; text_columns are the remaining ones.
_REINDEX_MAP: dict[str, tuple[str, str, list[str]]] = {
    "journal": ("journal", "fts_journal", ["content", "summary"]),
    "decision": ("decisions", "fts_decisions", ["question", "rationale"]),
    "literature": ("literature", "fts_literature", ["title", "abstract", "notes"]),
    "mission": ("missions", "fts_missions", ["objective", "context"]),
    "claim": ("claims", "fts_claims", ["content"]),
    "cluster": ("evidence_clusters", "fts_clusters", ["label", "synthesis"]),
}


@dataclass
class ReindexReport:
    """Per-table outcome of a reindex run."""

    results: dict[str, int] = field(default_factory=dict)  # entity_type -> rows reindexed
    failures: dict[str, str] = field(default_factory=dict)  # entity_type -> error

    @property
    def total_reindexed(self) -> int:
        return sum(self.results.values())

    @property
    def ok(self) -> bool:
        return not self.failures


async def reindex_fts(
    db: Database,
    *,
    project_id: str | None = None,
    entity_types: list[str] | None = None,
) -> ReindexReport:
    """Rebuild FTS indexes from source tables.

    Args:
        db: connected Database.
        project_id: when set, only rebuild that project's rows (DELETE+
            re-INSERT scoped to ids belonging to the project). When None,
            rebuild every row in every FTS table (full global repair).
        entity_types: subset of _REINDEX_MAP keys to rebuild; default all.

    Returns a ReindexReport with per-type counts + any per-type failures.
    """
    report = ReindexReport()
    targets = entity_types or list(_REINDEX_MAP.keys())

    for etype in targets:
        spec = _REINDEX_MAP.get(etype)
        if spec is None:
            report.failures[etype] = f"unknown entity type {etype!r}"
            continue
        source_table, fts_table, text_cols = spec
        savepoint = f"reindex_{etype}"
        try:
            await db.execute(f"SAVEPOINT {savepoint}")
            # 1. Clear existing FTS rows (scoped to the project's ids when asked).
            if project_id is None:
                await db.execute(f"DELETE FROM {fts_table}")
            else:
                await db.execute(
                    f"DELETE FROM {fts_table} WHERE id IN "
                    f"(SELECT id FROM {source_table} WHERE project_id = ?)",
                    [project_id],
                )
            # 2. Re-INSERT from source.
            select_cols = ", ".join(["id", *text_cols])
            where = "WHERE project_id = ?" if project_id is not None else ""
            params = [project_id] if project_id is not None else []
            rows = await db.fetchall(
                f"SELECT {select_cols} FROM {source_table} {where}", params
            )
            insert_cols = ", ".join(["id", *text_cols])
            placeholders = ", ".join("?" for _ in range(1 + len(text_cols)))
            count = 0
            for row in rows:
                values = [row["id"]] + [(row[c] or "") for c in text_cols]
                await db.execute(
                    f"INSERT INTO {fts_table} ({insert_cols}) VALUES ({placeholders})",
                    values,
                )
                count += 1
            await db.execute(f"RELEASE {savepoint}")
            report.results[etype] = count
            logger.info("reindex_fts: rebuilt %s (%d rows)", fts_table, count)
        except Exception as exc:  # noqa: BLE001
            try:
                await db.execute(f"ROLLBACK TO {savepoint}")
                await db.execute(f"RELEASE {savepoint}")
            except Exception:  # pragma: no cover
                pass
            report.failures[etype] = f"{type(exc).__name__}: {exc}"
            logger.warning("reindex_fts: %s failed: %s", fts_table, exc)

    await db.commit()
    return report
