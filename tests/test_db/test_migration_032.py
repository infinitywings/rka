"""Migration 032 schema contract for immutable reference attestations."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_reference_validation_attestation_schema_and_triggers(db) -> None:
    columns = await db.fetchall("PRAGMA table_info(reference_validation_attestations)")
    names = {column["name"] for column in columns}
    assert {
        "id",
        "project_id",
        "manuscript_id",
        "literature_id",
        "input_doi",
        "input_title",
        "input_authors",
        "status",
        "retraction_check_enabled",
        "retraction_checked",
        "sources_tried",
        "sources_confirmed",
        "notes",
        "stage_trace",
        "full_json_payload",
        "pipeline_version",
        "started_at",
        "completed_at",
        "created_at",
    } <= names

    triggers = await db.fetchall(
        """SELECT name FROM sqlite_master
           WHERE type = 'trigger' AND tbl_name = 'reference_validation_attestations'"""
    )
    assert {
        "trg_reference_validations_no_update",
        "trg_reference_validations_no_delete",
    } <= {trigger["name"] for trigger in triggers}

    indexes = await db.fetchall("PRAGMA index_list(reference_validation_attestations)")
    index_names = {index["name"] for index in indexes}
    assert {
        "idx_reference_validations_manuscript",
        "idx_reference_validations_literature",
        "idx_reference_validations_status",
    } <= index_names
