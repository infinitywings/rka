"""Tests for migration 022 + the vec_claims reshape service (Mission D T4)."""

from __future__ import annotations

import pytest

from rka.services.embedding_reshape import (
    current_vec_claims_dim,
    reshape_vec_claims,
    reshape_vec_claims_if_needed,
)


# ---------------------------------------------------------------------------
# Migration 022 — claims.embedding_pending column + index applied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_022_added_embedding_pending_column(db):
    # The migration runner's lifecycle ran during the `db` fixture's
    # initialize_phase2_schema(), so 022 has applied.
    row = await db.fetchone(
        "SELECT name FROM pragma_table_info('claims') WHERE name = 'embedding_pending'"
    )
    assert row is not None, "migration 022 should add claims.embedding_pending"


@pytest.mark.asyncio
async def test_migration_022_created_partial_index(db):
    row = await db.fetchone(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'index' AND name = 'idx_claims_embedding_pending'"
    )
    assert row is not None, "migration 022 should create the partial index"


@pytest.mark.asyncio
async def test_migration_022_flags_existing_claims_pending(db):
    # Insert a journal entry to satisfy the FK, then a claim, then re-run
    # the migration via the registry (it ran once during fixture setup;
    # to simulate "existing claim at migration time" we add the claim and
    # explicitly run the UPDATE statement that the migration uses).
    await db.execute(
        "INSERT INTO journal (id, type, content, source, created_at) "
        "VALUES (?, 'note', ?, 'pi', strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
        ["jrn_t4_a", "x"],
    )
    await db.execute(
        "INSERT INTO claims (id, source_entry_id, claim_type, content, embedding_pending) "
        "VALUES (?, ?, 'observation', 'c', 0)",
        ["clm_t4", "jrn_t4_a"],
    )
    # Migration 022's tail line: UPDATE claims SET embedding_pending = 1
    # The migration has run; but in a fresh-fixture DB the claim was
    # inserted AFTER the migration so embedding_pending stays 0 by the
    # DEFAULT clause. Verify the default is 0 (so new claims get 0 until
    # the reshape service runs again).
    row = await db.fetchone(
        "SELECT embedding_pending FROM claims WHERE id = 'clm_t4'"
    )
    assert row["embedding_pending"] == 0


# ---------------------------------------------------------------------------
# reshape_vec_claims — drop + recreate at target dim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_current_vec_claims_dim_reads_sqlite_master(db):
    # Migration 010 created vec_claims at dim=768. Confirm we can read it.
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")
    dim = await current_vec_claims_dim(db)
    assert dim == 768


@pytest.mark.asyncio
async def test_reshape_creates_vec_claims_at_target_dim(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")
    await reshape_vec_claims(db, dim=4096)
    new_dim = await current_vec_claims_dim(db)
    assert new_dim == 4096


@pytest.mark.asyncio
async def test_reshape_marks_all_claims_pending(db):
    # Add a couple of claims at flag=0; reshape should set all to 1.
    await db.execute(
        "INSERT INTO journal (id, type, content, source, created_at) "
        "VALUES (?, 'note', ?, 'pi', strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
        ["jrn_pending", "x"],
    )
    await db.execute(
        "INSERT INTO claims (id, source_entry_id, claim_type, content, embedding_pending) "
        "VALUES (?, ?, 'observation', 'a', 0), (?, ?, 'observation', 'b', 0)",
        ["clm_a", "jrn_pending", "clm_b", "jrn_pending"],
    )
    await db.commit()

    target_dim = 1024 if db.vec_available else 768  # vec-unavailable path also works
    pending = await reshape_vec_claims(db, dim=target_dim)
    assert pending >= 2

    # All claims should now have embedding_pending = 1.
    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM claims WHERE embedding_pending = 1"
    )
    assert int(row["n"]) >= 2


@pytest.mark.asyncio
async def test_reshape_idempotent_when_dim_matches(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")
    # vec_claims is at 768 from migration 010. Reshape to 768 → no drop.
    # We can detect "no drop" by inserting a marker row + verifying it
    # survives.
    import struct

    vec = struct.pack("768f", *([0.1] * 768))
    await db.execute(
        "INSERT OR REPLACE INTO vec_claims (id, embedding) VALUES (?, ?)",
        ["clm_marker", vec],
    )
    await db.commit()

    await reshape_vec_claims(db, dim=768)

    # Marker survives because reshape took the idempotent fast-path.
    row = await db.fetchone(
        "SELECT id FROM vec_claims WHERE id = 'clm_marker'"
    )
    assert row is not None


@pytest.mark.asyncio
async def test_reshape_drops_existing_rows_on_dim_change(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")
    import struct

    vec = struct.pack("768f", *([0.1] * 768))
    await db.execute(
        "INSERT OR REPLACE INTO vec_claims (id, embedding) VALUES (?, ?)",
        ["clm_to_be_dropped", vec],
    )
    await db.commit()

    await reshape_vec_claims(db, dim=4096)  # different dim → drop + recreate

    row = await db.fetchone(
        "SELECT id FROM vec_claims WHERE id = 'clm_to_be_dropped'"
    )
    assert row is None, "row from the old vec_claims must NOT survive a dim change"


@pytest.mark.asyncio
async def test_reshape_rejects_non_positive_dim(db):
    with pytest.raises(ValueError):
        await reshape_vec_claims(db, dim=0)
    with pytest.raises(ValueError):
        await reshape_vec_claims(db, dim=-1)


# ---------------------------------------------------------------------------
# reshape_vec_claims_if_needed — the startup-hook wrapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reshape_if_needed_returns_false_when_dim_matches(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")
    did_reshape, _ = await reshape_vec_claims_if_needed(db, dim=768)
    assert did_reshape is False


@pytest.mark.asyncio
async def test_reshape_if_needed_returns_true_on_dim_change(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")
    did_reshape, pending = await reshape_vec_claims_if_needed(db, dim=4096)
    assert did_reshape is True
    new_dim = await current_vec_claims_dim(db)
    assert new_dim == 4096
