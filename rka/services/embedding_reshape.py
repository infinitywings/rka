"""Drop + recreate vec_* virtual tables at a config-driven dim.

v2.5.5 (`mis_01KS1RFNM2T1HTB077G507T1FR`) generalizes the v2.5.x
claims-only pattern to all six vec_* tables — Bug 1 of the
embedding-dim-mismatch cluster. The v2.4-era `reshape_vec_claims*` and
`current_vec_claims_dim` symbols stay as thin wrappers so the existing
boot + test surface remains stable.

Two calling sites:

  1. **App startup** (`rka/api/app.py`): after
     `Database.initialize_phase2_schema()`, the configured embedding dim
     is compared against each vec_* table; any mismatch triggers a
     drop+recreate at the configured dim plus a pending-flag flip so
     backfill can pick the work up on next PUT.

  2. **PUT /api/config/embedding** (`rka/api/routes/config.py`): when
     the backend/model/dim signature changes, every vec_* table is
     reshape-checked before the BackfillService kicks off.

Pending-signal per entity type:

  - `claim` keeps the v2.4 `claims.embedding_pending` flag — existing
    tests + backfill cursor depend on it.
  - the other five (`journal | decision | literature | mission |
    artifact`) use the `embedding_metadata`-absence signal: reshape
    DELETEs metadata rows for that entity_type so v2.5.5's 3-tuple
    `needs_reembed` (model_name + dimensions + content_hash) returns
    True until backfill repopulates them.

Pre-flight backup is the responsibility of
`EmbeddingConfigService.save_config()` — it copies the prior
`embedding_config.json` to `embedding_config.backup.json` on every
save, so by the time PUT calls reshape the backup already exists.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


_VEC_DIM_RX = re.compile(r"embedding\s+float\[(\d+)\]", re.IGNORECASE)


# vec_table → (entity_type, entity_table). entity_type is the canonical
# `embedding_metadata.entity_type` string; entity_table is the SQL table
# that holds the source rows.
_TABLE_TO_ENTITY: dict[str, tuple[str, str]] = {
    "vec_claims":    ("claim",      "claims"),
    "vec_journal":   ("journal",    "journal"),
    "vec_decisions": ("decision",   "decisions"),
    "vec_literature":("literature", "literature"),
    "vec_missions":  ("mission",    "missions"),
    "vec_artifacts": ("artifact",   "artifacts"),
}

_VEC_TABLE_NAMES: tuple[str, ...] = tuple(_TABLE_TO_ENTITY.keys())


# ---------------------------------------------------------------------------
# Dim inspection
# ---------------------------------------------------------------------------


async def current_vec_table_dim(db: Any, table_name: str) -> int | None:
    """Inspect sqlite_master to find `table_name`'s current dim, or None.

    Returns None when sqlite-vec isn't loaded, the table doesn't exist,
    or its CREATE SQL doesn't carry a parseable `embedding float[N]`
    column (defensive — every vec0 table this codebase creates does).
    """
    if not getattr(db, "vec_available", False):
        return None
    row = await db.fetchone(
        "SELECT sql FROM sqlite_master WHERE name = ?", [table_name]
    )
    if not row:
        return None
    sql = row["sql"] or ""
    match = _VEC_DIM_RX.search(sql)
    if not match:
        return None
    return int(match.group(1))


async def current_vec_claims_dim(db: Any) -> int | None:
    """Backward-compat thin wrapper for the v2.4 single-table surface."""
    return await current_vec_table_dim(db, "vec_claims")


# ---------------------------------------------------------------------------
# Reshape (generic)
# ---------------------------------------------------------------------------


async def reshape_vec_table(db: Any, table_name: str, *, dim: int) -> int:
    """Drop + recreate `table_name` at `dim`; mark its entities pending.

    Returns the count of entities in the corresponding entity table
    (claims for vec_claims, journal for vec_journal, etc.) — the same
    number that `needs_reembed` will report True for until backfill
    repopulates them. Safe to call when the table is already at `dim`
    (idempotent fast-path: skip drop, return current pending count).

    Pending-signal logic per entity type:
      - `vec_claims`: `UPDATE claims SET embedding_pending = 1`
      - all others: `DELETE FROM embedding_metadata WHERE entity_type = ?`
        — the v2.5.5 3-tuple `needs_reembed` returns True for any entity
        without a current-config-matching metadata row.

    Raises:
      ValueError for non-positive `dim` or unknown `table_name`.
    """
    if dim <= 0:
        raise ValueError(f"reshape_vec_table: dim must be positive (got {dim})")
    if table_name not in _TABLE_TO_ENTITY:
        raise ValueError(
            f"reshape_vec_table: unknown table {table_name!r}; "
            f"expected one of {_VEC_TABLE_NAMES}"
        )
    entity_type, entity_table = _TABLE_TO_ENTITY[table_name]

    if not getattr(db, "vec_available", False):
        # No sqlite-vec → no vec_* table to reshape. Still flag pending
        # so the moment vec loads (e.g. via a config update or extension
        # install), backfill picks the work up.
        await _mark_pending(db, table_name, entity_type, entity_table)
        await db.commit()
        return await _count_entity_rows(db, entity_table)

    existing_dim = await current_vec_table_dim(db, table_name)
    if existing_dim == dim:
        logger.info(
            "reshape_vec_table: %s already at dim=%d; no-op", table_name, dim
        )
        return await _count_pending(db, table_name, entity_type, entity_table)

    logger.info(
        "reshape_vec_table: dropping %s (was dim=%s) and recreating at dim=%d",
        table_name, existing_dim, dim,
    )
    await db.execute(f"DROP TABLE IF EXISTS {table_name}")
    await db.execute(
        f"CREATE VIRTUAL TABLE {table_name} USING vec0("
        f"id TEXT PRIMARY KEY, embedding float[{dim}])"
    )
    await _mark_pending(db, table_name, entity_type, entity_table)
    await db.commit()
    return await _count_entity_rows(db, entity_table)


async def reshape_all_vec_tables_if_needed(
    db: Any, *, dim: int
) -> dict[str, tuple[bool, int]]:
    """Iterate every known vec_* table; reshape-if-needed; return per-table outcome.

    Output shape: `{ table_name: (did_reshape, pending_count) }`.
    `did_reshape` is True iff the table was actually dropped and rebuilt
    at a new dim; `pending_count` is the post-operation pending count.
    """
    out: dict[str, tuple[bool, int]] = {}
    for tbl in _VEC_TABLE_NAMES:
        entity_type, entity_table = _TABLE_TO_ENTITY[tbl]
        existing_dim = await current_vec_table_dim(db, tbl)
        if existing_dim == dim:
            pending = await _count_pending(db, tbl, entity_type, entity_table)
            out[tbl] = (False, pending)
        else:
            pending = await reshape_vec_table(db, tbl, dim=dim)
            out[tbl] = (True, pending)
    return out


# ---------------------------------------------------------------------------
# Backward-compat thin wrappers (v2.4 surface)
# ---------------------------------------------------------------------------


async def reshape_vec_claims(db: Any, *, dim: int) -> int:
    """v2.4-compat: reshape vec_claims and mark its claims pending."""
    return await reshape_vec_table(db, "vec_claims", dim=dim)


async def reshape_vec_claims_if_needed(db: Any, *, dim: int) -> tuple[bool, int]:
    """v2.4-compat startup-hook wrapper for vec_claims only.

    Returns `(did_reshape, claims_pending)`. New code should prefer
    `reshape_all_vec_tables_if_needed` which covers every entity type.
    """
    existing_dim = await current_vec_table_dim(db, "vec_claims")
    if existing_dim == dim:
        return (False, await _count_pending(db, "vec_claims", "claim", "claims"))
    pending = await reshape_vec_table(db, "vec_claims", dim=dim)
    return (True, pending)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _mark_pending(
    db: Any, table_name: str, entity_type: str, entity_table: str
) -> None:
    """Flip the pending signal for every entity of this type.

    `vec_claims` keeps the v2.4 `embedding_pending` flag pattern (the
    BackfillService cursor reads it directly); the other five use
    metadata-absence as the signal.
    """
    if table_name == "vec_claims":
        await db.execute(f"UPDATE {entity_table} SET embedding_pending = 1")
    else:
        await db.execute(
            "DELETE FROM embedding_metadata WHERE entity_type = ?",
            [entity_type],
        )


async def _count_entity_rows(db: Any, entity_table: str) -> int:
    row = await db.fetchone(f"SELECT COUNT(*) AS n FROM {entity_table}")
    return int((row or {}).get("n") or 0)


async def _count_pending(
    db: Any, table_name: str, entity_type: str, entity_table: str
) -> int:
    """Post-op pending count, using the appropriate signal per table."""
    if table_name == "vec_claims":
        row = await db.fetchone(
            f"SELECT COUNT(*) AS n FROM {entity_table} WHERE embedding_pending = 1"
        )
    else:
        row = await db.fetchone(
            f"""
            SELECT COUNT(*) AS n FROM {entity_table} e
            WHERE NOT EXISTS (
                SELECT 1 FROM embedding_metadata m
                WHERE m.entity_type = ? AND m.entity_id = e.id
            )
            """,
            [entity_type],
        )
    return int((row or {}).get("n") or 0)


async def _count_claims(db: Any) -> int:
    """Backward-compat: kept because external code may import it."""
    return await _count_entity_rows(db, "claims")


async def _count_claims_pending(db: Any) -> int:
    """Backward-compat: kept because external code may import it."""
    return await _count_pending(db, "vec_claims", "claim", "claims")
