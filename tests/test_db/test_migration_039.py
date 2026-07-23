"""Migration 039 removes unreachable change tracking objects."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_immutable_update_triggers_and_redundant_index_are_removed(db) -> None:
    trigger_names = {
        row["name"]
        for row in await db.fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        )
    }
    assert {
        "trg_change_manuscript_claim_versions_update",
        "trg_change_manuscript_claim_ratifications_update",
        "trg_change_manuscript_claim_verifications_update",
        "trg_change_reference_validations_update",
    }.isdisjoint(trigger_names)

    index_names = {
        row["name"]
        for row in await db.fetchall(
            "PRAGMA index_list(reference_validation_attestations)"
        )
    }
    assert "idx_reference_validations_job" not in index_names
    assert "uq_reference_validations_job" in index_names

    assert await db.fetchone(
        "SELECT filename FROM schema_migrations WHERE filename = ?",
        ["039_cleanup_immutable_change_tracking.sql"],
    ) == {"filename": "039_cleanup_immutable_change_tracking.sql"}
