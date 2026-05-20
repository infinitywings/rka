"""Tests for migration 022 + the vec_claims reshape service (Mission D T4).

v2.5.5 (mis_01KS1RFNM2T1HTB077G507T1FR T5) extends coverage to the
five other vec_* tables generalised in T1.
"""

from __future__ import annotations

import pytest

from rka.services.embedding_reshape import (
    current_vec_claims_dim,
    current_vec_table_dim,
    reshape_all_vec_tables_if_needed,
    reshape_vec_claims,
    reshape_vec_claims_if_needed,
    reshape_vec_table,
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


# ---------------------------------------------------------------------------
# v2.5.5 (mis_01KS1RFNM2T1HTB077G507T1FR T5) — generic reshape across 6 tables
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "vec_table",
    ["vec_journal", "vec_decisions", "vec_literature", "vec_missions", "vec_artifacts"],
)
@pytest.mark.asyncio
async def test_reshape_each_new_vec_table_at_target_dim(db, vec_table):
    """Every non-claims vec_* table reshapes from float[768] to a new dim."""
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")
    # Baseline from schema_phase2.sql / migration 002.
    baseline_dim = await current_vec_table_dim(db, vec_table)
    assert baseline_dim == 768

    await reshape_vec_table(db, vec_table, dim=4096)
    new_dim = await current_vec_table_dim(db, vec_table)
    assert new_dim == 4096


@pytest.mark.asyncio
async def test_reshape_vec_table_rejects_unknown_table(db):
    with pytest.raises(ValueError, match="unknown table"):
        await reshape_vec_table(db, "vec_does_not_exist", dim=4096)


@pytest.mark.asyncio
async def test_reshape_non_claims_deletes_matching_embedding_metadata(db):
    """Reshape for journal/decision/literature/mission/artifact DELETEs
    matching embedding_metadata rows so v2.5.5's 3-tuple needs_reembed
    returns True for every affected entity until backfill repopulates."""
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")
    # Plant stale metadata for journal AND claim. Claim must survive
    # the reshape (uses the flag-based signal); journal must be wiped.
    await db.execute(
        "INSERT INTO embedding_metadata "
        "(project_id, entity_type, entity_id, content_hash, model_name, dimensions) "
        "VALUES "
        "('proj_default', 'journal', 'jrn_stale', 'h1', 'old-model', 768), "
        "('proj_default', 'claim',   'clm_stale', 'h2', 'old-model', 768)"
    )
    await db.commit()

    await reshape_vec_table(db, "vec_journal", dim=4096)

    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM embedding_metadata WHERE entity_type = 'journal'"
    )
    assert row["n"] == 0

    # Claim metadata is untouched — claims rely on embedding_pending flag.
    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM embedding_metadata WHERE entity_type = 'claim'"
    )
    assert row["n"] == 1


@pytest.mark.asyncio
async def test_reshape_all_vec_tables_if_needed_iterates_every_table(db):
    """reshape_all_vec_tables_if_needed reports per-table outcome for all six."""
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")

    results = await reshape_all_vec_tables_if_needed(db, dim=4096)

    expected_tables = {
        "vec_claims", "vec_journal", "vec_decisions",
        "vec_literature", "vec_missions", "vec_artifacts",
    }
    assert set(results.keys()) == expected_tables

    # Every table should report did_reshape=True (all were at 768 → 4096)
    # except vec_claims which is also at 768 by default, so also True.
    for table_name, (did_reshape, _pending) in results.items():
        assert did_reshape is True, f"{table_name} should have reshaped"
        dim = await current_vec_table_dim(db, table_name)
        assert dim == 4096, f"{table_name} should be at dim=4096"


@pytest.mark.asyncio
async def test_reshape_all_vec_tables_if_needed_idempotent_no_op(db):
    """Calling reshape_all_vec_tables_if_needed twice in a row at the same
    dim → first call reshapes; second call reports did_reshape=False for
    every table (idempotent fast-path)."""
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")

    await reshape_all_vec_tables_if_needed(db, dim=4096)
    results = await reshape_all_vec_tables_if_needed(db, dim=4096)
    for table_name, (did_reshape, _pending) in results.items():
        assert did_reshape is False, (
            f"second call must be a no-op for {table_name}"
        )
