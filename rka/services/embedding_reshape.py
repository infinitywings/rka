"""Drop + recreate the vec_claims virtual table at a config-driven dim.

Called in two places:

  1. **App startup**: after `Database.initialize_phase2_schema()`, we read
     the current embedding config and reshape vec_claims if its dim no
     longer matches. Safe to skip if sqlite-vec isn't loaded.

  2. **PUT /api/config/embedding**: when the backend/model/dim signature
     changes (T3 route handler), we reshape then kick off backfill.

Pre-flight backup is the responsibility of T2's
`EmbeddingConfigService.save_config()` — it copies the prior
`embedding_config.json` to `embedding_config.backup.json` on every save,
so by the time PUT calls reshape, the backup already exists. For
startup-time reshape, the backup is whatever the most recent save left
behind.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


_VEC_DIM_RX = re.compile(r"embedding\s+float\[(\d+)\]", re.IGNORECASE)


async def current_vec_claims_dim(db: Any) -> int | None:
    """Inspect sqlite_master to find vec_claims' current dim, or None if absent."""
    if not getattr(db, "vec_available", False):
        return None
    row = await db.fetchone(
        "SELECT sql FROM sqlite_master WHERE name = 'vec_claims'"
    )
    if not row:
        return None
    sql = row["sql"] or ""
    match = _VEC_DIM_RX.search(sql)
    if not match:
        return None
    return int(match.group(1))


async def reshape_vec_claims(db: Any, *, dim: int) -> int:
    """Drop + recreate `vec_claims` at `dim`; mark every claim pending.

    Returns the number of claims now flagged `embedding_pending = 1`
    (= total row count of `claims`). Safe to call when vec_claims is
    already at `dim` — falls through to a flag-pending no-op without
    dropping the table (avoids redundant work + lock churn).

    Raises `ValueError` for non-positive dim.
    """
    if dim <= 0:
        raise ValueError(f"reshape_vec_claims: dim must be positive (got {dim})")

    if not getattr(db, "vec_available", False):
        # No sqlite-vec → no vec_claims to reshape. Still flag pending so
        # the moment vec loads (e.g. via a config update or extension
        # install), backfill picks the work up.
        await db.execute("UPDATE claims SET embedding_pending = 1")
        await db.commit()
        return await _count_claims(db)

    existing_dim = await current_vec_claims_dim(db)
    if existing_dim == dim:
        # Idempotent fast-path: dim unchanged → just ensure pending flag.
        # (Skipping the drop avoids invalidating any embeddings already
        # written at the right dim — the backfill loop will skip rows
        # that don't actually need re-embed via its own per-row check.)
        logger.info(
            "reshape_vec_claims: vec_claims already at dim=%d; no-op", dim
        )
        return await _count_claims_pending(db)

    logger.info(
        "reshape_vec_claims: dropping vec_claims (was dim=%s) and recreating at dim=%d",
        existing_dim,
        dim,
    )
    await db.execute("DROP TABLE IF EXISTS vec_claims")
    await db.execute(
        f"CREATE VIRTUAL TABLE vec_claims USING vec0("
        f"id TEXT PRIMARY KEY, embedding float[{dim}])"
    )
    await db.execute("UPDATE claims SET embedding_pending = 1")
    await db.commit()
    return await _count_claims(db)


async def reshape_vec_claims_if_needed(
    db: Any, *, dim: int
) -> tuple[bool, int]:
    """Convenience wrapper used by app startup.

    Returns `(did_reshape, claims_pending)`. `did_reshape` is True only
    when vec_claims was actually dropped and rebuilt at a new dim.
    """
    existing_dim = await current_vec_claims_dim(db)
    if existing_dim == dim:
        return (False, await _count_claims_pending(db))
    pending = await reshape_vec_claims(db, dim=dim)
    return (True, pending)


async def _count_claims(db: Any) -> int:
    row = await db.fetchone("SELECT COUNT(*) AS n FROM claims")
    return int((row or {}).get("n") or 0)


async def _count_claims_pending(db: Any) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM claims WHERE embedding_pending = 1"
    )
    return int((row or {}).get("n") or 0)
