"""Regression tests for security and reliability findings from the v2.7 audit."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from rka.models.claim import ClaimCreate, ClaimUpdate
from rka.models.journal import JournalEntryCreate
from rka.models.manuscript_native import (
    ManuscriptCreate,
    ManuscriptReferenceManifestReplace,
)
from rka.models.mission import MissionCreate, MissionReportCreate, MissionUpdate
from rka.models.project import ProjectCreate
from rka.models.topic import TopicCreate
from rka.services.claims import ClaimNotFoundError, ClaimService
from rka.services.jobs import JobQueue
from rka.services.knowledge_pack import (
    PACK_SCHEMA_VERSION,
    KnowledgePackService,
)
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.missions import MissionNotFoundError, MissionService
from rka.services.notes import NoteService
from rka.services.project import ProjectService
from rka.services.topics import TopicNotFoundError, TopicService


async def _create_project(db, project_id: str, name: str) -> None:
    await ProjectService(db).create_project(
        ProjectCreate(id=project_id, name=name),
        actor="system",
    )


def _write_pack(
    path: Path,
    *,
    source_project_id: str,
    source_project_name: str,
    tables: dict[str, list[dict]],
) -> None:
    manifest = {
        "pack_format_version": PACK_SCHEMA_VERSION,
        "schema_version": 38,
        "project": {
            "id": source_project_id,
            "name": source_project_name,
            "description": "untrusted import regression",
            "created_by": "system",
        },
        "project_state": None,
        "tables": tables,
        "table_counts": {
            table: len(rows) for table, rows in tables.items()
        },
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))


@pytest.mark.asyncio
async def test_import_rejects_unapproved_row_key_before_any_db_write(
    db,
    tmp_path: Path,
) -> None:
    pack_path = tmp_path / "malicious-column.rka-pack.zip"
    injected_key = "content) VALUES ('injected'); --"
    _write_pack(
        pack_path,
        source_project_id="proj_untrusted_source",
        source_project_name="Untrusted Source",
        tables={
            "journal": [
                {
                    "id": "jrn_untrusted",
                    "type": "finding",
                    "content": "ordinary content",
                    "source": "executor",
                    "project_id": "proj_untrusted_source",
                    injected_key: "attacker controlled",
                }
            ]
        },
    )
    changes_before = db.conn.total_changes

    with pack_path.open("rb") as pack_file:
        with pytest.raises(
            ValueError,
            match=r"journal\[0\].*unsupported column",
        ):
            await KnowledgePackService(db).import_pack(
                pack_file,
                project_id="proj_untrusted_target",
                project_name="Untrusted Target",
            )

    assert db.conn.total_changes == changes_before
    assert await db.fetchone(
        "SELECT id FROM projects WHERE id = 'proj_untrusted_target'"
    ) is None
    assert await db.fetchone(
        "SELECT id FROM journal WHERE id = 'jrn_untrusted'"
    ) is None


@pytest.mark.asyncio
async def test_expired_final_job_attempt_is_terminalized_not_reclaimed(db) -> None:
    queue = JobQueue(db, lease_seconds=60)
    job_id = await queue.enqueue(
        "mission_embed",
        max_attempts=2,
    )

    first = await queue.claim_next("worker-one")
    assert first is not None
    assert first["attempts"] == 1
    await db.execute(
        "UPDATE jobs SET lease_until = '1970-01-01T00:00:00Z' WHERE id = ?",
        [job_id],
    )

    second = await queue.claim_next("worker-two")
    assert second is not None
    assert second["attempts"] == 2
    await db.execute(
        "UPDATE jobs SET lease_until = '1970-01-01T00:00:00Z' WHERE id = ?",
        [job_id],
    )

    assert await queue.claim_next("worker-three") is None
    exhausted = await queue.get(job_id)
    assert exhausted is not None
    assert exhausted["status"] == "failed"
    assert exhausted["attempts"] == 2
    assert exhausted["worker_id"] is None
    assert exhausted["lease_until"] is None
    assert exhausted["lease_token"] is None
    assert exhausted["completed_at"] is not None
    assert exhausted["last_error"] == "lease expired after maximum attempts"


@pytest.mark.asyncio
@pytest.mark.parametrize("target_kind", ["missing", "foreign"])
async def test_claim_update_not_found_has_no_side_effects(
    db,
    target_kind: str,
) -> None:
    await _create_project(db, "proj_foreign_claim", "Foreign Claim")
    foreign_note = await NoteService(
        db,
        project_id="proj_foreign_claim",
    ).create(
        JournalEntryCreate(
            type="finding",
            content="foreign evidence",
            source="executor",
        )
    )
    foreign_claim = await ClaimService(
        db,
        project_id="proj_foreign_claim",
    ).create(
        ClaimCreate(
            source_entry_id=foreign_note.id,
            claim_type="evidence",
            content="foreign claim text",
        )
    )
    target_id = (
        "clm_missing"
        if target_kind == "missing"
        else foreign_claim.id
    )
    changes_before = db.conn.total_changes

    with pytest.raises(ClaimNotFoundError, match="not found"):
        await ClaimService(db, project_id="proj_default").update(
            target_id,
            ClaimUpdate(content="must not be indexed"),
        )

    assert db.conn.total_changes == changes_before
    assert await db.fetchone(
        "SELECT content FROM claims WHERE id = ?",
        [foreign_claim.id],
    ) == {"content": "foreign claim text"}
    assert await db.fetchone(
        "SELECT id FROM fts_claims WHERE fts_claims MATCH 'must'"
    ) is None
    assert await db.fetchone(
        """SELECT id FROM audit_log
           WHERE entity_type = 'claim' AND entity_id = ?
             AND action = 'update'""",
        [target_id],
    ) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("target_kind", ["missing", "foreign"])
async def test_submit_report_not_found_has_no_side_effects(
    db,
    target_kind: str,
) -> None:
    await _create_project(db, "proj_foreign_mission", "Foreign Mission")
    foreign_mission = await MissionService(
        db,
        project_id="proj_foreign_mission",
    ).create(
        MissionCreate(phase="execution", objective="foreign mission")
    )
    target_id = (
        "mis_missing"
        if target_kind == "missing"
        else foreign_mission.id
    )
    changes_before = db.conn.total_changes

    with pytest.raises(MissionNotFoundError, match="not found"):
        await MissionService(db, project_id="proj_default").submit_report(
            target_id,
            MissionReportCreate(
                summary="must not persist",
                findings=["must not materialize"],
            ),
        )

    assert db.conn.total_changes == changes_before
    assert await db.fetchone(
        "SELECT status, report FROM missions WHERE id = ?",
        [foreign_mission.id],
    ) == {"status": "pending", "report": None}
    assert await db.fetchone(
        """SELECT id FROM events
           WHERE event_type = 'mission_completed' AND entity_id = ?""",
        [target_id],
    ) is None
    assert await db.fetchone(
        """SELECT id FROM audit_log
           WHERE entity_type = 'mission' AND entity_id = ?
             AND action = 'update'""",
        [target_id],
    ) is None
    assert await db.fetchone(
        "SELECT id FROM journal WHERE related_mission = ?",
        [target_id],
    ) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("target_kind", ["missing", "foreign"])
async def test_mission_update_not_found_has_no_side_effects(
    db,
    target_kind: str,
) -> None:
    await _create_project(db, "proj_foreign_mission_update", "Foreign Mission")
    foreign_mission = await MissionService(
        db,
        project_id="proj_foreign_mission_update",
    ).create(
        MissionCreate(phase="execution", objective="foreign mission")
    )
    target_id = (
        "mis_missing_update"
        if target_kind == "missing"
        else foreign_mission.id
    )
    changes_before = db.conn.total_changes

    with pytest.raises(MissionNotFoundError, match="not found"):
        await MissionService(db, project_id="proj_default").update(
            target_id,
            MissionUpdate(
                tags=["phantom-tag"],
                status="blocked",
            ),
        )

    assert db.conn.total_changes == changes_before
    assert await db.fetchone(
        "SELECT status FROM missions WHERE id = ?",
        [foreign_mission.id],
    ) == {"status": "pending"}
    assert await db.fetchone(
        """SELECT tag FROM tags
           WHERE entity_type = 'mission' AND entity_id = ?""",
        [target_id],
    ) is None
    assert await db.fetchone(
        """SELECT id FROM events
           WHERE entity_type = 'mission' AND entity_id = ?
             AND event_type = 'mission_blocked'""",
        [target_id],
    ) is None
    assert await db.fetchone(
        """SELECT id FROM audit_log
           WHERE entity_type = 'mission' AND entity_id = ?
             AND action = 'update'""",
        [target_id],
    ) is None


@pytest.mark.asyncio
async def test_topic_delete_rejects_foreign_id_without_deleting_assignments(
    db,
) -> None:
    await _create_project(db, "proj_foreign_topic", "Foreign Topic")
    foreign_service = TopicService(db, project_id="proj_foreign_topic")
    foreign_topic = await foreign_service.create(
        TopicCreate(name="foreign topic")
    )
    await foreign_service.assign_entity(
        foreign_topic.id,
        "journal",
        "jrn_foreign_topic_target",
    )
    changes_before = db.conn.total_changes

    with pytest.raises(TopicNotFoundError, match="not found"):
        await TopicService(db, project_id="proj_default").delete(
            foreign_topic.id
        )

    assert db.conn.total_changes == changes_before
    assert await db.fetchone(
        "SELECT id FROM topics WHERE id = ?",
        [foreign_topic.id],
    ) == {"id": foreign_topic.id}
    assert await db.fetchone(
        "SELECT topic_id FROM entity_topics WHERE topic_id = ?",
        [foreign_topic.id],
    ) == {"topic_id": foreign_topic.id}


@pytest.mark.asyncio
async def test_knowledge_pack_reports_latest_migration_filename(db) -> None:
    service = KnowledgePackService(db, project_id="proj_default")
    expected = await db.fetchone(
        """SELECT MAX(CAST(SUBSTR(filename, 1, 3) AS INTEGER)) AS version
           FROM schema_migrations"""
    )
    assert expected is not None
    assert await service._get_schema_version() == expected["version"]
    assert expected["version"] >= 39


@pytest.mark.asyncio
async def test_same_instant_historical_validation_is_not_current_or_blocking(db) -> None:
    service = NativeManuscriptService(db, project_id="proj_default")
    manuscript = await service.create(
        ManuscriptCreate(title="Strict freshness regression")
    )
    literature_id = "lit_same_instant"
    timestamp = "2026-07-23T10:00:00Z"
    await db.execute(
        """INSERT INTO literature
           (id, title, authors, year, doi, status, added_by, project_id,
            created_at, updated_at)
           VALUES (?, 'Same instant study', '["A. Author"]', 2026,
                   '10.1000/same-instant', 'cited', 'pi', 'proj_default',
                   ?, ?)""",
        [literature_id, timestamp, timestamp],
    )
    await service.replace_reference_manifest(
        manuscript.id,
        ManuscriptReferenceManifestReplace(
            expected_revision=1,
            members=[
                {
                    "citation_key": "author2026same",
                    "literature_id": literature_id,
                }
            ],
        ),
    )
    await db.execute(
        """INSERT INTO reference_validation_attestations
           (id, project_id, manuscript_id, canonical_manuscript_id,
            literature_id, input_doi, input_title, input_authors, status,
            retraction_check_enabled, retraction_checked, sources_tried,
            sources_confirmed, notes, stage_trace, full_json_payload,
            pipeline_version, started_at, completed_at)
           VALUES ('refval_same_instant', 'proj_default', ?, ?, ?,
                   '10.1000/same-instant', 'Same instant study',
                   '["A. Author"]', 'VERIFIED', 1, 1, '["crossref"]',
                   '["crossref"]', '[]', '{}', '{}', 'test/v1', ?, ?)""",
        [manuscript.id, manuscript.id, literature_id, timestamp, timestamp],
    )

    manifest = await service.get_reference_manifest(manuscript.id)
    assert manifest["approved_citation_keys"] == []
    assert manifest["members"][0]["validation"]["current"] is False

    readiness = await service.get_readiness(
        manuscript.id,
        target_phase="review",
    )
    assert "REFERENCE_VALIDATION_STALE" not in {
        finding["code"] for finding in readiness["findings"]
    }
