"""Migration 035 contracts for the durable semantic change cursor."""

from __future__ import annotations

import sqlite3

import pytest


@pytest.mark.asyncio
async def test_change_cursor_schema_is_monotonic_immutable_and_indexed(db) -> None:
    columns = {
        row["name"]: row
        for row in await db.fetchall("PRAGMA table_info(change_events)")
    }
    assert columns["cursor"]["type"] == "INTEGER"
    assert columns["cursor"]["pk"] == 1
    assert {
        "project_id",
        "source_table",
        "operation",
        "entity_type",
        "entity_id",
        "manuscript_id",
        "manuscript_claim_id",
        "manuscript_unit_id",
        "related_entity_type",
        "related_entity_id",
        "details",
        "changed_at",
    } <= columns.keys()

    indexes = {
        row["name"]
        for row in await db.fetchall(
            """SELECT name FROM sqlite_master
               WHERE type = 'index' AND tbl_name = 'change_events'"""
        )
    }
    assert {
        "idx_change_events_project_cursor",
        "idx_change_events_entity",
        "idx_change_events_manuscript",
        "idx_change_events_related",
    } <= indexes

    await db.execute(
        """INSERT INTO change_events (
               project_id, source_table, operation, entity_type, entity_id
           ) VALUES (
               'proj_default', 'test', 'insert', 'journal', 'jrn_cursor_one'
           )"""
    )
    first = await db.fetchone(
        "SELECT cursor FROM change_events WHERE entity_id = 'jrn_cursor_one'"
    )
    await db.execute(
        """INSERT INTO change_events (
               project_id, source_table, operation, entity_type, entity_id
           ) VALUES (
               'proj_default', 'test', 'update', 'journal', 'jrn_cursor_two'
           )"""
    )
    second = await db.fetchone(
        "SELECT cursor FROM change_events WHERE entity_id = 'jrn_cursor_two'"
    )
    assert int(second["cursor"]) > int(first["cursor"])

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db.execute(
            "UPDATE change_events SET operation = 'delete' WHERE cursor = ?",
            [first["cursor"]],
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db.execute(
            "DELETE FROM change_events WHERE cursor = ?",
            [first["cursor"]],
        )


@pytest.mark.asyncio
async def test_change_triggers_cover_core_edges_and_every_native_table(db) -> None:
    triggers = {
        row["name"]
        for row in await db.fetchall(
            """SELECT name FROM sqlite_master
               WHERE type = 'trigger' AND name LIKE 'trg_change_%'"""
        )
    }
    required_insert_triggers = {
        # Core authoritative entities.
        "trg_change_journal_insert",
        "trg_change_decisions_insert",
        "trg_change_literature_insert",
        "trg_change_missions_insert",
        "trg_change_checkpoints_insert",
        "trg_change_claims_insert",
        "trg_change_evidence_clusters_insert",
        # Semantic metadata and graph edges.
        "trg_change_tags_insert",
        "trg_change_entity_links_insert",
        "trg_change_claim_edges_insert",
        # Every native manuscript aggregate table from migration 033.
        "trg_change_manuscripts_insert",
        "trg_change_manuscript_claims_insert",
        "trg_change_manuscript_claim_versions_insert",
        "trg_change_manuscript_claim_ratifications_insert",
        "trg_change_manuscript_units_insert",
        "trg_change_manuscript_claim_evidence_insert",
        "trg_change_manuscript_unit_evidence_insert",
        "trg_change_manuscript_claim_units_insert",
        "trg_change_manuscript_checkpoints_insert",
        "trg_change_manuscript_claim_verifications_insert",
        # The legacy immutable verification surface remains visible too.
        "trg_change_reference_validations_insert",
    }
    assert required_insert_triggers <= triggers

    immutable_update_stems = {
        "trg_change_manuscript_claim_versions",
        "trg_change_manuscript_claim_ratifications",
        "trg_change_manuscript_claim_verifications",
        "trg_change_reference_validations",
    }
    for insert_trigger in required_insert_triggers:
        stem = insert_trigger.removesuffix("_insert")
        if stem in immutable_update_stems:
            # Migration 039 removes unreachable AFTER UPDATE triggers from
            # append-only tables whose BEFORE UPDATE guards always abort.
            assert f"{stem}_update" not in triggers
        else:
            assert f"{stem}_update" in triggers
        assert f"{stem}_delete" in triggers

    assert {
        "trg_change_events_no_update",
        "trg_change_events_no_delete",
    } <= triggers
    assert await db.fetchall("PRAGMA foreign_key_check") == []
