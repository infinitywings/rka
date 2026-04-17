"""Tests for migration 017: decision_options table + decisions columns."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from rka.infra.database import Database


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """Fresh DB with the full migration chain (schema.sql + 001..latest)."""
    db_path = str(tmp_path / "test_017.db")
    database = Database(db_path)
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_decision_options_schema_shape(db: Database):
    """decision_options table has all 22 expected columns with correct types."""
    rows = await db.fetchall("PRAGMA table_info(decision_options)")
    columns = {r["name"]: r["type"] for r in rows}

    expected = {
        "id": "TEXT",
        "decision_id": "TEXT",
        "project_id": "TEXT",
        "label": "TEXT",
        "summary": "TEXT",
        "justification": "TEXT",
        "expert_archetype": "TEXT",
        "explanation": "TEXT",
        "pros": "TEXT",
        "cons": "TEXT",
        "evidence": "TEXT",
        "confidence_verbal": "TEXT",
        "confidence_numeric": "REAL",
        "confidence_evidence_strength": "TEXT",
        "confidence_known_unknowns": "TEXT",
        "effort_time": "TEXT",
        "effort_cost": "TEXT",
        "effort_reversibility": "TEXT",
        "dominated_by": "TEXT",
        "presentation_order_seed": "INTEGER",
        "is_recommended": "INTEGER",
        "created_at": "TEXT",
    }
    assert columns == expected

    # Decisions table has the 4 new columns appended.
    dec_rows = await db.fetchall("PRAGMA table_info(decisions)")
    dec_cols = {r["name"] for r in dec_rows}
    assert {"recommended_option_id", "pi_selected_option_id",
            "pi_override_rationale", "presentation_method"}.issubset(dec_cols)


@pytest.mark.asyncio
async def test_decision_options_fk_enforced(db: Database):
    """FK on decision_options.decision_id rejects inserts against a non-existent decision."""
    with pytest.raises(Exception):
        await db.execute(
            """INSERT INTO decision_options
               (id, decision_id, project_id, label, summary, justification, explanation,
                pros, cons, evidence, confidence_verbal, confidence_numeric,
                confidence_evidence_strength, confidence_known_unknowns,
                effort_time, effort_reversibility, presentation_order_seed)
               VALUES ('opt_bad', 'dec_missing', 'proj_default',
                       'L', 'S', 'J', 'E',
                       '["p1","p2","p3"]', '["c1","c2","c3"]', '[]',
                       'high', 0.7, 'strong', '["unk1"]',
                       'M', 'reversible', 1)""",
        )


@pytest.mark.asyncio
async def test_decision_options_pros_length_check(db: Database):
    """CHECK constraint rejects pros arrays of length != 3."""
    # First seed a decision to reference.
    await db.execute(
        """INSERT INTO decisions (id, phase, question, decided_by, status, project_id)
           VALUES ('dec_t', 'p1', 'Q?', 'brain', 'active', 'proj_default')""",
    )
    # pros has only 2 items — should fail CHECK.
    with pytest.raises(Exception):
        await db.execute(
            """INSERT INTO decision_options
               (id, decision_id, project_id, label, summary, justification, explanation,
                pros, cons, evidence, confidence_verbal, confidence_numeric,
                confidence_evidence_strength, confidence_known_unknowns,
                effort_time, effort_reversibility, presentation_order_seed)
               VALUES ('opt_bad_pros', 'dec_t', 'proj_default',
                       'L', 'S', 'J', 'E',
                       '["p1","p2"]', '["c1","c2","c3"]', '[]',
                       'high', 0.7, 'strong', '["unk1"]',
                       'M', 'reversible', 1)""",
        )


@pytest.mark.asyncio
async def test_migration_017_additive_legacy_options_untouched(db: Database):
    """A decisions row with legacy options JSON survives the migration chain untouched."""
    # Insert a row mimicking a pre-v2.2 decision with legacy options JSON.
    legacy_options = '[{"label":"A","description":"first"},{"label":"B","description":"second"}]'
    await db.execute(
        """INSERT INTO decisions (id, phase, question, options, decided_by, status, project_id)
           VALUES ('dec_legacy', 'setup', 'legacy?', ?, 'pi', 'active', 'proj_default')""",
        [legacy_options],
    )
    await db.commit()

    row = await db.fetchone(
        """SELECT options, recommended_option_id, pi_selected_option_id,
                  pi_override_rationale, presentation_method
           FROM decisions WHERE id = 'dec_legacy'"""
    )
    # Legacy JSON column is preserved verbatim.
    assert row["options"] == legacy_options
    # New columns default to NULL on pre-existing rows.
    assert row["recommended_option_id"] is None
    assert row["pi_selected_option_id"] is None
    assert row["pi_override_rationale"] is None
    assert row["presentation_method"] is None
