"""Tests for migration 009: v2 schema changes and type mapping."""

from __future__ import annotations

import pytest
import pytest_asyncio
from pathlib import Path

from rka.infra.database import Database


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """Create a fresh database with schema initialized."""
    db_path = str(tmp_path / "test_v2.db")
    database = Database(db_path)
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_journal_has_v2_columns(db: Database):
    """After migration, journal table has status and pinned columns."""
    row = await db.fetchone(
        "SELECT status, pinned FROM journal LIMIT 0"
    )
    # No rows, but the query succeeds → columns exist
    assert row is None


@pytest.mark.asyncio
async def test_journal_accepts_v2_types(db: Database):
    """Journal table accepts the new v2 types: note, log, directive."""
    for jtype in ("note", "log", "directive"):
        await db.execute(
            """INSERT INTO journal (id, type, content, source, confidence, importance, status, pinned, project_id)
               VALUES (?, ?, ?, 'brain', 'hypothesis', 'normal', 'active', 0, 'proj_default')""",
            [f"jrn_test_{jtype}", jtype, f"test {jtype}"],
        )
    await db.commit()

    rows = await db.fetchall("SELECT id, type FROM journal ORDER BY id")
    types = {r["type"] for r in rows}
    assert types == {"note", "log", "directive"}


@pytest.mark.asyncio
async def test_journal_status_check_constraint(db: Database):
    """Journal status column enforces the CHECK constraint."""
    with pytest.raises(Exception):
        await db.execute(
            """INSERT INTO journal (id, type, content, source, confidence, importance, status, pinned, project_id)
               VALUES ('jrn_bad', 'note', 'test', 'brain', 'hypothesis', 'normal', 'INVALID', 0, 'proj_default')""",
        )


@pytest.mark.asyncio
async def test_decisions_have_v2_columns(db: Database):
    """Decisions table has superseded_by, scope_version, kind, related_journal."""
    await db.execute(
        """INSERT INTO decisions (id, phase, question, decided_by, status, kind, related_journal, project_id)
           VALUES ('dec_test', 'p1', 'test?', 'brain', 'active', 'research_question', '["jrn_1"]', 'proj_default')""",
    )
    await db.commit()
    row = await db.fetchone("SELECT kind, related_journal, scope_version FROM decisions WHERE id = 'dec_test'")
    assert row["kind"] == "research_question"
    assert row["related_journal"] == '["jrn_1"]'
    assert row["scope_version"] == 1


@pytest.mark.asyncio
async def test_missions_have_v2_columns(db: Database):
    """Missions table has iteration, parent_mission_id, motivated_by_decision."""
    # motivated_by_decision is a FK to decisions(id); seed the referenced row first.
    await db.execute(
        """INSERT INTO decisions (id, phase, question, decided_by, status, project_id)
           VALUES ('dec_x', 'p1', 'test?', 'brain', 'active', 'proj_default')""",
    )
    await db.execute(
        """INSERT INTO missions (id, phase, objective, status, iteration, motivated_by_decision, project_id)
           VALUES ('msn_test', 'p1', 'test', 'pending', 2, 'dec_x', 'proj_default')""",
    )
    await db.commit()
    row = await db.fetchone("SELECT iteration, motivated_by_decision FROM missions WHERE id = 'msn_test'")
    assert row["iteration"] == 2
    assert row["motivated_by_decision"] == "dec_x"


@pytest.mark.asyncio
async def test_claims_table_exists(db: Database):
    """Claims table is created by migration."""
    # claims.source_entry_id FKs to journal(id); seed it first.
    await db.execute(
        """INSERT INTO journal (id, type, content, source, confidence, importance, status, pinned, project_id)
           VALUES ('jrn_1', 'note', 'src', 'brain', 'hypothesis', 'normal', 'active', 0, 'proj_default')""",
    )
    await db.execute(
        """INSERT INTO claims (id, source_entry_id, claim_type, content, project_id)
           VALUES ('clm_test', 'jrn_1', 'hypothesis', 'test claim', 'proj_default')""",
    )
    await db.commit()
    row = await db.fetchone("SELECT * FROM claims WHERE id = 'clm_test'")
    assert row is not None
    assert row["claim_type"] == "hypothesis"
    assert row["confidence"] == 0.5
    assert row["verified"] == 0
    assert row["stale"] == 0


@pytest.mark.asyncio
async def test_evidence_clusters_table_exists(db: Database):
    """Evidence clusters table is created by migration."""
    await db.execute(
        """INSERT INTO evidence_clusters (id, label, project_id)
           VALUES ('ecl_test', 'test cluster', 'proj_default')""",
    )
    await db.commit()
    row = await db.fetchone("SELECT * FROM evidence_clusters WHERE id = 'ecl_test'")
    assert row is not None
    assert row["confidence"] == "emerging"
    assert row["synthesized_by"] == "llm"


@pytest.mark.asyncio
async def test_claim_edges_table_exists(db: Database):
    """Claim edges table is created by migration."""
    # claims.source_entry_id FKs to journal(id); claim_edges.source_claim_id FKs to claims(id).
    # Seed the full chain before the claim_edges insert.
    await db.execute(
        """INSERT INTO journal (id, type, content, source, confidence, importance, status, pinned, project_id)
           VALUES ('jrn_1', 'note', 'src', 'brain', 'hypothesis', 'normal', 'active', 0, 'proj_default')""",
    )
    await db.execute(
        """INSERT INTO claims (id, source_entry_id, claim_type, content, project_id)
           VALUES ('clm_e1', 'jrn_1', 'evidence', 'test', 'proj_default')""",
    )
    await db.execute(
        """INSERT INTO claim_edges (id, source_claim_id, relation, project_id)
           VALUES ('ce_test', 'clm_e1', 'member_of', 'proj_default')""",
    )
    await db.commit()
    row = await db.fetchone("SELECT * FROM claim_edges WHERE id = 'ce_test'")
    assert row is not None


@pytest.mark.asyncio
async def test_topics_table_exists(db: Database):
    """Topics and entity_topics tables are created."""
    await db.execute(
        """INSERT INTO topics (id, name, project_id)
           VALUES ('top_test', 'mqtt/scalability', 'proj_default')""",
    )
    await db.execute(
        """INSERT INTO entity_topics (topic_id, entity_type, entity_id)
           VALUES ('top_test', 'journal', 'jrn_1')""",
    )
    await db.commit()
    row = await db.fetchone("SELECT * FROM topics WHERE id = 'top_test'")
    assert row["name"] == "mqtt/scalability"


@pytest.mark.asyncio
async def test_context_snapshots_table_exists(db: Database):
    """Context snapshots table is created."""
    await db.execute(
        """INSERT INTO context_snapshots (id, entry_ids, project_id)
           VALUES ('cs_test', '["jrn_1","jrn_2"]', 'proj_default')""",
    )
    await db.commit()
    row = await db.fetchone("SELECT * FROM context_snapshots WHERE id = 'cs_test'")
    assert row is not None


@pytest.mark.asyncio
async def test_review_queue_table_exists(db: Database):
    """Review queue table is created."""
    await db.execute(
        """INSERT INTO review_queue (id, item_type, item_id, flag, project_id)
           VALUES ('rq_test', 'cluster', 'ecl_1', 'low_confidence_cluster', 'proj_default')""",
    )
    await db.commit()
    row = await db.fetchone("SELECT * FROM review_queue WHERE id = 'rq_test'")
    assert row["flag"] == "low_confidence_cluster"
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_fts_claims_table_exists(db: Database):
    """FTS5 table for claims is created."""
    await db.execute(
        "INSERT INTO fts_claims (id, content) VALUES ('clm_1', 'test claim content')",
    )
    await db.commit()
    rows = await db.fetchall(
        "SELECT * FROM fts_claims WHERE fts_claims MATCH 'claim'",
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_entity_links_accepts_new_link_types(db: Database):
    """entity_links accepts the new v2 link types without CHECK constraint issues."""
    new_types = [
        "informed_by", "justified_by", "motivated",
        "derived_from", "builds_on", "supports", "contradicts",
    ]
    for i, lt in enumerate(new_types):
        await db.execute(
            """INSERT INTO entity_links (id, source_type, source_id, link_type, target_type, target_id, project_id)
               VALUES (?, 'decision', 'dec_1', ?, 'journal', 'jrn_1', 'proj_default')""",
            [f"el_{i}", lt],
        )
    await db.commit()
    rows = await db.fetchall("SELECT link_type FROM entity_links ORDER BY id")
    assert len(rows) == len(new_types)
