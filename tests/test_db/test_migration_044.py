"""Migration 044 semantic patch ledger constraints."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rka.infra.database import Database


@pytest.mark.asyncio
async def test_migration_044_installs_immutable_manifests_and_guarded_proposals(
    tmp_path: Path,
) -> None:
    db = Database(str(tmp_path / "migration-044.db"))
    await db.connect()
    try:
        await db.initialize_schema()
        await db.initialize_phase2_schema()
        tables = {
            row["name"]
            for row in await db.fetchall(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "semantic_patch_context_manifests",
            "semantic_patch_proposals",
            "semantic_patch_proposal_events",
            "semantic_patch_provider_events",
        } <= tables

        await db.execute(
            """INSERT INTO semantic_patch_context_manifests
               (id, project_id, origin, provider, model, boundary,
                selected_context, resolved_context, target_bases,
                constraints, omissions, truncation_notes, manifest_hash)
               VALUES ('pcm_test', 'proj_default', 'host_agent', 'chatgpt', 'host',
                       'host_conversation', '[]', '{}', '[]', '[]', '[]', '[]', ?)""",
            ["0" * 64],
        )
        await db.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            await db.execute(
                "UPDATE semantic_patch_context_manifests SET model = 'changed' WHERE id = 'pcm_test'"
            )
        await db.conn.rollback()

        with pytest.raises(sqlite3.IntegrityError):
            await db.execute(
                """INSERT INTO semantic_patch_context_manifests
                   (id, project_id, origin, provider, model, boundary,
                    selected_context, resolved_context, target_bases,
                    constraints, omissions, truncation_notes, manifest_hash)
                   VALUES ('pcm_human', 'proj_default', 'human', 'human', 'none',
                           'none', '[]', '{}', '[]', '[]', '[]', '[]', ?)""",
                ["0" * 64],
            )
        await db.conn.rollback()

        for event_id, event in (("pce_started", "started"), ("pce_done", "succeeded")):
            await db.execute(
                """INSERT INTO semantic_patch_provider_events
                   (id, call_id, project_id, context_manifest_id, event,
                    provider, model, boundary, details)
                   VALUES (?, 'spc_test', 'proj_default', 'pcm_test', ?,
                           'chatgpt', 'host', 'host_conversation', '{}')""",
                [event_id, event],
            )
        await db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            await db.execute(
                """INSERT INTO semantic_patch_provider_events
                   (id, call_id, project_id, context_manifest_id, event,
                    provider, model, boundary, details)
                   VALUES ('pce_failed', 'spc_test', 'proj_default', 'pcm_test', 'failed',
                           'chatgpt', 'host', 'host_conversation', '{}')"""
            )
        await db.conn.rollback()

        await db.execute(
            """INSERT INTO semantic_patch_proposals
               (id, project_id, origin, intent, reason, created_by, operations,
                target_bases, semantic_diff, validation_findings, boundary)
               VALUES ('spp_test', 'proj_default', 'human', 'Test transition',
                       'Exercise trigger', 'pi', '[]', '[]', '[]', '[]', 'none')"""
        )
        await db.commit()
        with pytest.raises(sqlite3.IntegrityError, match="only proposed records"):
            await db.execute(
                """UPDATE semantic_patch_proposals
                   SET status = 'proposed', revision = 2,
                       updated_at = '2099-01-01T00:00:00Z',
                       closed_at = '2099-01-01T00:00:00Z'
                   WHERE id = 'spp_test'"""
            )
        await db.conn.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="only proposed records"):
            await db.execute(
                """UPDATE semantic_patch_proposals
                   SET status = 'applied', revision = 2,
                       updated_at = '2099-01-01T00:00:00Z',
                       closed_at = '2099-01-01T00:00:00Z'
                   WHERE id = 'spp_test'"""
            )
        await db.conn.rollback()
    finally:
        await db.close()
