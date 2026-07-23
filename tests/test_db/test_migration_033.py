"""Migration 033 contracts for the native manuscript claim spine."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


MIGRATION = (
    Path(__file__).parents[2]
    / "rka"
    / "db"
    / "migrations"
    / "033_add_native_manuscript_spine.sql"
)


def test_migration_is_additive_and_does_not_import_or_ratify_legacy_rows(
    tmp_path: Path,
) -> None:
    """Legacy manuscript journals survive, but no native truth is inferred."""
    connection = sqlite3.connect(tmp_path / "migration-033-legacy.db")
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.executescript(
            """
            CREATE TABLE projects (id TEXT PRIMARY KEY);
            CREATE TABLE journal (
                id TEXT PRIMARY KEY,
                project_id TEXT
            );
            CREATE TABLE decisions (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                decided_by TEXT,
                status TEXT,
                chosen TEXT
            );
            CREATE TABLE claims (
                id TEXT PRIMARY KEY,
                project_id TEXT
            );
            INSERT INTO projects (id) VALUES ('prj_legacy');
            INSERT INTO journal (id, project_id)
            VALUES ('jrn_legacy_manuscript', 'prj_legacy');
            """
        )

        connection.executescript(MIGRATION.read_text())

        assert connection.execute(
            "SELECT id, project_id FROM journal WHERE id = 'jrn_legacy_manuscript'"
        ).fetchone() == ("jrn_legacy_manuscript", "prj_legacy")
        assert connection.execute("SELECT count(*) FROM manuscripts").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM manuscript_claim_ratifications"
        ).fetchone() == (0,)
    finally:
        connection.close()


async def _seed_project(db, project_id: str) -> None:
    await db.execute(
        """INSERT INTO projects (id, name, created_by)
           VALUES (?, ?, 'system')""",
        [project_id, project_id],
    )


async def _seed_journal(db, entry_id: str, project_id: str) -> None:
    await db.execute(
        """INSERT INTO journal (id, type, content, source, project_id)
           VALUES (?, 'note', 'terminal research evidence', 'executor', ?)""",
        [entry_id, project_id],
    )


async def _seed_decision(
    db,
    decision_id: str,
    project_id: str,
    *,
    chosen: str,
    decided_by: str = "pi",
    status: str = "active",
) -> None:
    await db.execute(
        """INSERT INTO decisions (
               id, phase, question, chosen, decided_by, status, project_id
           ) VALUES (?, 'paper_writing', 'Select wording', ?, ?, ?, ?)""",
        [decision_id, chosen, decided_by, status, project_id],
    )


async def _seed_core_claim(
    db,
    claim_id: str,
    source_entry_id: str,
    project_id: str,
) -> None:
    await db.execute(
        """INSERT INTO claims (
               id, source_entry_id, claim_type, content, verified,
               evidence_status, project_id
           ) VALUES (?, ?, 'result', 'measured result', 1, 'supported', ?)""",
        [claim_id, source_entry_id, project_id],
    )


async def _seed_native_spine(db) -> None:
    for project_id in ("prj_native_a", "prj_native_b"):
        await _seed_project(db, project_id)
        await _seed_journal(
            db,
            f"jrn_{project_id.removeprefix('prj_native_')}",
            project_id,
        )

    await _seed_core_claim(db, "clm_evidence_a", "jrn_a", "prj_native_a")
    await _seed_core_claim(db, "clm_evidence_b", "jrn_b", "prj_native_b")

    await db.execute(
        """INSERT INTO manuscripts (
               id, project_id, title, legacy_journal_id
           ) VALUES ('man_a', 'prj_native_a', 'Paper A', 'jrn_a')"""
    )
    await db.execute(
        """INSERT INTO manuscripts (id, project_id, title)
           VALUES ('man_b', 'prj_native_b', 'Paper B')"""
    )

    await db.execute(
        """INSERT INTO manuscript_claims (
               id, manuscript_id, project_id, local_key, kind
           ) VALUES ('mcl_a', 'man_a', 'prj_native_a', 'C1', 'empirical')"""
    )
    await db.execute(
        """INSERT INTO manuscript_claims (
               id, manuscript_id, project_id, local_key, kind
           ) VALUES ('mcl_b', 'man_b', 'prj_native_b', 'C1', 'empirical')"""
    )

    for claim_id, manuscript_id, project_id in (
        ("mcl_a", "man_a", "prj_native_a"),
        ("mcl_b", "man_b", "prj_native_b"),
    ):
        await db.execute(
            """INSERT INTO manuscript_claim_versions (
                   claim_id, version, manuscript_id, project_id,
                   exact_wording, allowed_wording, prohibited_wording
               ) VALUES (?, 1, ?, ?, 'Exact bounded result',
                         'Bounded result', '["Universal result"]')""",
            [claim_id, manuscript_id, project_id],
        )

    for unit_id, manuscript_id, project_id in (
        ("mun_a", "man_a", "prj_native_a"),
        ("mun_b", "man_b", "prj_native_b"),
    ):
        await db.execute(
            """INSERT INTO manuscript_units (
                   id, manuscript_id, project_id, local_key, kind, location,
                   artifact_ref, allowed_interpretation,
                   prohibited_interpretation
               ) VALUES (?, ?, ?, 'U-RESULT-1', 'result',
                         'sections/results.tex#r1', 'figures/r1.pdf',
                         'Measured on the tested systems',
                         'Universal across all systems')""",
            [unit_id, manuscript_id, project_id],
        )
    await db.commit()


@pytest.mark.asyncio
async def test_native_schema_has_expected_tables_indexes_and_triggers(db) -> None:
    names = {
        row["name"]
        for row in await db.fetchall(
            """SELECT name FROM sqlite_master
               WHERE type = 'table' AND name LIKE 'manuscript%'"""
        )
    }
    assert {
        "manuscripts",
        "manuscript_claims",
        "manuscript_claim_versions",
        "manuscript_claim_ratifications",
        "manuscript_units",
        "manuscript_claim_evidence",
        "manuscript_unit_evidence",
        "manuscript_claim_units",
        "manuscript_checkpoints",
        "manuscript_claim_verification_attestations",
    } <= names
    # Later additive migrations may add manuscript-prefixed support tables.
    assert "manuscript_migration_issues" in names

    triggers = {
        row["name"]
        for row in await db.fetchall(
            """SELECT name FROM sqlite_master
               WHERE type = 'trigger' AND name LIKE 'trg_manuscript%'"""
        )
    }
    assert {
        "trg_manuscript_claim_versions_no_update",
        "trg_manuscript_claim_versions_no_delete",
        "trg_manuscript_claim_ratifications_validate",
        "trg_manuscript_claim_ratifications_no_update",
        "trg_manuscript_claim_ratifications_no_delete",
        "trg_manuscript_checkpoints_validate_insert",
        "trg_manuscript_checkpoints_validate_resolution",
        "trg_manuscript_claim_verifications_no_update",
        "trg_manuscript_claim_verifications_no_delete",
    } <= triggers

    assert await db.fetchall("PRAGMA foreign_key_check") == []


@pytest.mark.asyncio
async def test_manuscript_and_version_constraints_are_closed_and_immutable(db) -> None:
    await _seed_native_spine(db)

    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscripts (id, project_id, title)
               VALUES ('jrn_wrong', 'prj_native_a', 'Not canonical')"""
        )

    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscripts (
                   id, project_id, title, legacy_journal_id
               ) VALUES (
                   'man_cross', 'prj_native_a', 'Cross scoped', 'jrn_b'
               )"""
        )

    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscript_claims (
                   id, manuscript_id, project_id, local_key, kind
               ) VALUES (
                   'mcl_dup', 'man_a', 'prj_native_a', 'C1', 'position'
               )"""
        )

    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscript_claims (
                   id, manuscript_id, project_id, local_key, kind
               ) VALUES (
                   'mcl_invalid', 'man_a', 'prj_native_a', 'C2', 'marketing'
               )"""
        )

    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscript_claim_versions (
                   claim_id, version, manuscript_id, project_id,
                   exact_wording, allowed_wording, prohibited_wording
               ) VALUES (
                   'mcl_a', 2, 'man_a', 'prj_native_a',
                   'New wording', 'New wording', '[]'
               )"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db.execute(
            """UPDATE manuscript_claim_versions
               SET exact_wording = 'silently strengthened'
               WHERE claim_id = 'mcl_a' AND version = 1"""
        )


@pytest.mark.asyncio
async def test_ratification_requires_exact_active_pi_decision_and_is_immutable(
    db,
) -> None:
    await _seed_native_spine(db)
    await _seed_decision(
        db,
        "dec_valid_a",
        "prj_native_a",
        chosen="Exact bounded result",
    )
    await _seed_decision(
        db,
        "dec_wrong_wording",
        "prj_native_a",
        chosen="Stronger than the evidence",
    )
    await _seed_decision(
        db,
        "dec_executor",
        "prj_native_a",
        chosen="Exact bounded result",
        decided_by="executor",
    )
    await _seed_decision(
        db,
        "dec_valid_b",
        "prj_native_b",
        chosen="Exact bounded result",
    )
    await db.commit()

    for decision_id in ("dec_wrong_wording", "dec_executor", "dec_valid_b"):
        with pytest.raises(sqlite3.IntegrityError, match="active same-project PI"):
            await db.execute(
                """INSERT INTO manuscript_claim_ratifications (
                       id, manuscript_id, project_id, claim_id, claim_version,
                       decision_id, ratified_at
                   ) VALUES (
                       ?, 'man_a', 'prj_native_a', 'mcl_a', 1, ?,
                       '2026-07-22T12:00:00Z'
                   )""",
                [f"mra_{decision_id}", decision_id],
            )

    await db.execute(
        """INSERT INTO manuscript_claim_ratifications (
               id, manuscript_id, project_id, claim_id, claim_version,
               decision_id, ratified_at
           ) VALUES (
               'mra_valid', 'man_a', 'prj_native_a', 'mcl_a', 1,
               'dec_valid_a', '2026-07-22T12:00:00Z'
           )"""
    )

    await _seed_decision(
        db,
        "dec_second_active",
        "prj_native_a",
        chosen="Exact bounded result",
    )
    with pytest.raises(sqlite3.IntegrityError, match="one active"):
        await db.execute(
            """INSERT INTO manuscript_claim_ratifications (
                   id, manuscript_id, project_id, claim_id, claim_version,
                   decision_id, ratified_at
               ) VALUES (
                   'mra_second', 'man_a', 'prj_native_a', 'mcl_a', 1,
                   'dec_second_active', '2026-07-22T12:00:01Z'
               )"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db.execute(
            """UPDATE manuscript_claim_ratifications
               SET ratified_at = '2026-07-22T13:00:00Z'
               WHERE id = 'mra_valid'"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db.execute(
            "DELETE FROM manuscript_claim_ratifications WHERE id = 'mra_valid'"
        )


@pytest.mark.asyncio
async def test_typed_joins_enforce_role_project_and_manuscript(db) -> None:
    await _seed_native_spine(db)

    await db.execute(
        """INSERT INTO manuscript_claim_evidence (
               manuscript_id, project_id, manuscript_claim_id, claim_version,
               evidence_claim_id, role
           ) VALUES (
               'man_a', 'prj_native_a', 'mcl_a', 1, 'clm_evidence_a', 'support'
           )"""
    )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscript_claim_evidence (
                   manuscript_id, project_id, manuscript_claim_id, claim_version,
                   evidence_claim_id, role
               ) VALUES (
                   'man_a', 'prj_native_a', 'mcl_a', 1,
                   'clm_evidence_b', 'support'
               )"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscript_claim_evidence (
                   manuscript_id, project_id, manuscript_claim_id, claim_version,
                   evidence_claim_id, role
               ) VALUES (
                   'man_a', 'prj_native_a', 'mcl_a', 1,
                   'clm_evidence_a', 'citation'
               )"""
        )

    await db.execute(
        """INSERT INTO manuscript_unit_evidence (
               manuscript_id, project_id, unit_id, evidence_claim_id, role
           ) VALUES (
               'man_a', 'prj_native_a', 'mun_a', 'clm_evidence_a', 'support'
           )"""
    )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscript_unit_evidence (
                   manuscript_id, project_id, unit_id, evidence_claim_id, role
               ) VALUES (
                   'man_a', 'prj_native_a', 'mun_b',
                   'clm_evidence_a', 'support'
               )"""
        )

    await db.execute(
        """INSERT INTO manuscript_claim_units (
               manuscript_id, project_id, manuscript_claim_id, claim_version,
               unit_id, relationship
           ) VALUES (
               'man_a', 'prj_native_a', 'mcl_a', 1, 'mun_a', 'tests'
           )"""
    )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscript_claim_units (
                   manuscript_id, project_id, manuscript_claim_id, claim_version,
                   unit_id, relationship
               ) VALUES (
                   'man_a', 'prj_native_a', 'mcl_a', 1, 'mun_b', 'tests'
               )"""
        )


@pytest.mark.asyncio
async def test_six_checkpoint_kinds_and_pi_resolution_gate(db) -> None:
    await _seed_native_spine(db)

    kinds = (
        "venue",
        "outline",
        "table_figure_plan",
        "reference_set",
        "draft_section",
        "final_layout",
    )
    for index, kind in enumerate(kinds):
        unit_id = "mun_a" if kind == "draft_section" else None
        await db.execute(
            """INSERT INTO manuscript_checkpoints (
                   id, manuscript_id, project_id, kind, unit_id
               ) VALUES (?, 'man_a', 'prj_native_a', ?, ?)""",
            [f"mck_{index}", kind, unit_id],
        )

    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscript_checkpoints (
                   id, manuscript_id, project_id, kind
               ) VALUES (
                   'mck_invalid', 'man_a', 'prj_native_a', 'style'
               )"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscript_checkpoints (
                   id, manuscript_id, project_id, kind
               ) VALUES (
                   'mck_missing_unit', 'man_a', 'prj_native_a', 'draft_section'
               )"""
        )

    await _seed_decision(
        db,
        "dec_checkpoint_pi",
        "prj_native_a",
        chosen="results-led",
    )
    await _seed_decision(
        db,
        "dec_checkpoint_executor",
        "prj_native_a",
        chosen="results-led",
        decided_by="executor",
    )
    await _seed_decision(
        db,
        "dec_checkpoint_b",
        "prj_native_b",
        chosen="results-led",
    )
    await db.commit()

    for decision_id in ("dec_checkpoint_executor", "dec_checkpoint_b"):
        with pytest.raises(sqlite3.IntegrityError, match="active same-project PI"):
            await db.execute(
                """UPDATE manuscript_checkpoints
                   SET status = 'resolved',
                       decision_id = ?,
                       approved_choice = 'results-led',
                       dependency_snapshot = '{"sha256":"test"}',
                       resolved_at = '2026-07-22T12:00:00Z'
                   WHERE id = 'mck_1'""",
                [decision_id],
            )

    await db.execute(
        """UPDATE manuscript_checkpoints
           SET status = 'resolved',
               decision_id = 'dec_checkpoint_pi',
               approved_choice = 'results-led',
               dependency_snapshot = '{"sha256":"test"}',
               resolved_at = '2026-07-22T12:00:00Z'
           WHERE id = 'mck_1'"""
    )
    row = await db.fetchone(
        """SELECT status, decision_id, approved_choice
           FROM manuscript_checkpoints WHERE id = 'mck_1'"""
    )
    assert row == {
        "status": "resolved",
        "decision_id": "dec_checkpoint_pi",
        "approved_choice": "results-led",
    }


@pytest.mark.asyncio
async def test_verification_attestations_are_dimensioned_scoped_and_immutable(
    db,
) -> None:
    await _seed_native_spine(db)
    values = [
        "mva_valid",
        "man_a",
        "prj_native_a",
        "mcl_a",
        1,
        "pass",
        "pass",
        "pass",
        "pass",
        "warn",
        "pass",
        "pass",
        "cursor-42",
        '{"clm_evidence_a":{"updated_at":"2026-07-22T10:00:00Z"}}',
        '{"findings":[]}',
        "claim-spine/v1",
        "2026-07-22T12:00:00Z",
        "2026-07-22T12:00:01Z",
    ]
    await db.execute(
        """INSERT INTO manuscript_claim_verification_attestations (
               id, manuscript_id, project_id, claim_id, claim_version,
               overall_verdict, grounding_verdict, evidence_verdict,
               contradiction_verdict, currency_verdict, ratification_verdict,
               unit_coverage_verdict, changelog_cursor, dependency_snapshot,
               full_json_payload, validator_version, started_at, completed_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        values,
    )

    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscript_claim_verification_attestations (
                   id, manuscript_id, project_id, claim_id, claim_version,
                   overall_verdict, grounding_verdict, evidence_verdict,
                   contradiction_verdict, currency_verdict,
                   ratification_verdict, unit_coverage_verdict,
                   full_json_payload, started_at, completed_at
               ) VALUES (
                   'mva_cross', 'man_a', 'prj_native_a', 'mcl_b', 1,
                   'pass', 'pass', 'pass', 'pass', 'pass', 'pass', 'pass',
                   '{}', '2026-07-22T12:00:00Z', '2026-07-22T12:00:01Z'
               )"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscript_claim_verification_attestations (
                   id, manuscript_id, project_id, claim_id, claim_version,
                   overall_verdict, grounding_verdict, evidence_verdict,
                   contradiction_verdict, currency_verdict,
                   ratification_verdict, unit_coverage_verdict,
                   full_json_payload, started_at, completed_at
               ) VALUES (
                   'mva_invalid', 'man_a', 'prj_native_a', 'mcl_a', 1,
                   'trusted', 'pass', 'pass', 'pass', 'pass', 'pass', 'pass',
                   '{}', '2026-07-22T12:00:00Z', '2026-07-22T12:00:01Z'
               )"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db.execute(
            """UPDATE manuscript_claim_verification_attestations
               SET overall_verdict = 'warn' WHERE id = 'mva_valid'"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db.execute(
            """DELETE FROM manuscript_claim_verification_attestations
               WHERE id = 'mva_valid'"""
        )
