"""Project service tests."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from rka.models.project import ProjectCreate
from rka.models.claim import ClaimCreate, ClaimScopeCondition, ClaimScopeWrite
from rka.models.interpretation import InterpretationCandidateCreate
from rka.services.claims import ClaimService
from rka.services.interpretation import InterpretationService
from rka.services.project import ProjectService


@pytest.mark.asyncio
async def test_create_project_rejects_duplicate_name(db):
    svc = ProjectService(db)

    await svc.create_project(
        ProjectCreate(id="proj_one", name="Duplicate Name", description="one"),
        actor="system",
    )

    with pytest.raises(ValueError, match="Project name 'Duplicate Name' already exists"):
        await svc.create_project(
            ProjectCreate(id="proj_two", name="Duplicate Name", description="two"),
            actor="system",
        )


@pytest.mark.asyncio
async def test_delete_project_failure_rolls_back_prior_table_deletes(
    db,
    monkeypatch: pytest.MonkeyPatch,
):
    svc = ProjectService(db)
    project_id = "proj_atomic_delete"
    await svc.create_project(
        ProjectCreate(
            id=project_id,
            name="Atomic Delete",
            description="rollback regression",
        ),
        actor="system",
    )
    await db.execute(
        """INSERT INTO review_queue
           (id, item_type, item_id, flag, project_id)
           VALUES ('rvw_atomic_delete', 'claim', 'clm_anchor',
                   'stale_dependency', ?)""",
        [project_id],
    )
    await db.commit()
    pack_dir = (
        Path(db.db_path).resolve().parent
        / "knowledge-packs"
        / project_id
    )
    pack_dir.mkdir(parents=True)
    (pack_dir / "must-survive.txt").write_text("rollback", encoding="utf-8")

    original_execute = db.execute

    async def fail_after_first_table(sql, params=None):
        if sql.startswith("DELETE FROM claim_edges"):
            raise RuntimeError("simulated mid-delete failure")
        return await original_execute(sql, params)

    monkeypatch.setattr(db, "execute", fail_after_first_table)

    with pytest.raises(RuntimeError, match="simulated mid-delete failure"):
        await svc.delete_project(project_id, confirm=True)

    assert await db.fetchone(
        "SELECT id FROM projects WHERE id = ?",
        [project_id],
    ) is not None
    assert await db.fetchone(
        "SELECT id FROM review_queue WHERE id = 'rvw_atomic_delete'"
    ) is not None
    assert (pack_dir / "must-survive.txt").read_text(encoding="utf-8") == "rollback"


@pytest.mark.asyncio
async def test_failed_project_create_rolls_back_before_unrelated_write(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another task cannot commit a half-created project."""
    svc = ProjectService(db)
    real_execute = db.execute
    first_inserted = asyncio.Event()
    release_first = asyncio.Event()
    second_attempted = asyncio.Event()
    second_finished = asyncio.Event()

    async def controlled_execute(sql, params=None):
        if (
            "INSERT OR IGNORE INTO project_states" in sql
            and params
            and params[0] == "proj_partial"
        ):
            raise RuntimeError("forced project-state failure")
        result = await real_execute(sql, params)
        if (
            "INSERT INTO projects" in sql
            and params
            and params[0] == "proj_partial"
        ):
            first_inserted.set()
            await release_first.wait()
        return result

    monkeypatch.setattr(db, "execute", controlled_execute)

    async def failing_create() -> None:
        with pytest.raises(RuntimeError, match="forced project-state failure"):
            await svc.create_project(
                ProjectCreate(id="proj_partial", name="Partial"),
                actor="system",
            )

    async def unrelated_write() -> None:
        await first_inserted.wait()
        second_attempted.set()
        await db.execute(
            """INSERT INTO projects (id, name, created_by)
               VALUES ('proj_unrelated', 'Unrelated', 'system')"""
        )
        await db.commit()
        second_finished.set()

    first_task = asyncio.create_task(failing_create())
    second_task = asyncio.create_task(unrelated_write())
    await second_attempted.wait()
    await asyncio.sleep(0)
    assert not second_finished.is_set()

    release_first.set()
    await asyncio.gather(first_task, second_task)

    assert await db.fetchone(
        "SELECT id FROM projects WHERE id = 'proj_partial'"
    ) is None
    assert await db.fetchone(
        "SELECT id FROM projects WHERE id = 'proj_unrelated'"
    ) == {"id": "proj_unrelated"}


@pytest.mark.asyncio
async def test_confirmed_project_delete_is_only_immutable_history_exception(
    db,
) -> None:
    svc = ProjectService(db)
    project_id = "proj_delete_native"
    await svc.create_project(
        ProjectCreate(id=project_id, name="Delete Native"),
        actor="system",
    )
    await db.execute(
        """INSERT INTO literature
           (id, title, status, added_by, project_id)
           VALUES ('lit_delete_native', 'Delete Native', 'read', 'web_ui', ?)""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO manuscripts
           (id, project_id, title, phase, state)
           VALUES ('man_delete_native', ?, 'Delete Native', 'planning', 'active')""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO manuscript_reference_members
           (id, manuscript_id, project_id, citation_key, literature_id)
           VALUES (
               'mrf_delete_native', 'man_delete_native', ?,
               'DeleteNative2026', 'lit_delete_native'
           )""",
        [project_id],
    )

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        await db.execute(
            """DELETE FROM manuscript_reference_members
               WHERE id = 'mrf_delete_native'"""
        )

    result = await svc.delete_project(project_id, confirm=True)

    assert result["confirmed"] is True
    assert await db.fetchone(
        "SELECT id FROM projects WHERE id = ?",
        [project_id],
    ) is None
    assert await db.fetchall(
        "SELECT * FROM project_deletion_authorizations"
    ) == []
    assert await db.fetchall("PRAGMA foreign_key_check") == []


@pytest.mark.asyncio
async def test_confirmed_project_delete_removes_interpretation_history(db) -> None:
    svc = ProjectService(db)
    project_id = "proj_delete_interpretations"
    await svc.create_project(
        ProjectCreate(id=project_id, name="Delete Interpretation History"),
        actor="system",
    )
    await db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES ('jrn_delete_interpretations', ?, 'note', ?, 'executor', 'tested')""",
        [project_id, "The isolated run measured 42 ms."],
    )
    await db.commit()
    candidate = await InterpretationService(db, project_id=project_id).create(
        InterpretationCandidateCreate(
            source_type="journal",
            source_id="jrn_delete_interpretations",
            locator_kind="record",
            locator_value="full_record",
            statement="The isolated run measured 42 ms.",
            epistemic_kind="observation",
            created_by="executor",
            extraction_tool="pytest",
            proposed_claim_type="result",
        )
    )

    with pytest.raises(sqlite3.IntegrityError, match="project-authorized deletion"):
        await db.execute(
            "DELETE FROM interpretation_candidates WHERE id = ?",
            [candidate.id],
        )

    result = await svc.delete_project(project_id, confirm=True)

    assert result["confirmed"] is True
    assert await db.fetchall(
        "SELECT * FROM interpretation_candidates WHERE project_id = ?",
        [project_id],
    ) == []
    assert await db.fetchall(
        "SELECT * FROM interpretation_review_events WHERE project_id = ?",
        [project_id],
    ) == []
    assert await db.fetchall("PRAGMA foreign_key_check") == []


@pytest.mark.asyncio
async def test_confirmed_project_delete_removes_claim_scope_history(db) -> None:
    svc = ProjectService(db)
    project_id = "proj_delete_claim_scope"
    await svc.create_project(
        ProjectCreate(id=project_id, name="Delete Claim Scope History"),
        actor="system",
    )
    await db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES ('jrn_delete_claim_scope', ?, 'note', ?, 'executor', 'tested')""",
        [project_id, "The isolated run measured 42 ms."],
    )
    await db.commit()
    claims = ClaimService(db, project_id=project_id)
    claim = await claims.create(
        ClaimCreate(
            source_entry_id="jrn_delete_claim_scope",
            claim_type="result",
            content="The isolated run measured 42 ms.",
            verified=True,
        ),
        actor="executor",
    )
    await claims.append_scope(
        claim.id,
        ClaimScopeWrite(
            expected_revision=0,
            actor="brain",
            reason="Reviewed exact evaluation boundary.",
            conditions=[
                ClaimScopeCondition(
                    kind="environment",
                    key="run_mode",
                    operator="equals",
                    value="isolated",
                )
            ],
            uncertainty="low",
            extension_policy="exact_only",
            prohibited_extensions=["concurrent workloads"],
            falsifier_status="applicable",
            falsifier="The same isolated run does not reproduce 42 ms.",
            review_status="reviewed",
        ),
    )

    with pytest.raises(sqlite3.IntegrityError, match="project-authorized deletion"):
        await db.execute(
            "DELETE FROM claim_scope_versions WHERE claim_id = ?",
            [claim.id],
        )

    result = await svc.delete_project(project_id, confirm=True)

    assert result["confirmed"] is True
    assert await db.fetchall(
        "SELECT * FROM claim_scope_versions WHERE project_id = ?",
        [project_id],
    ) == []
    assert await db.fetchall("PRAGMA foreign_key_check") == []


@pytest.mark.asyncio
async def test_delete_project_removes_only_service_owned_knowledge_pack_dir(
    db,
    tmp_path: Path,
) -> None:
    svc = ProjectService(db)
    project_id = "proj_delete_pack_files"
    await svc.create_project(
        ProjectCreate(id=project_id, name="Delete Pack Files"),
        actor="system",
    )

    pack_root = Path(db.db_path).resolve().parent / "knowledge-packs"
    project_pack_dir = pack_root / project_id
    project_pack_dir.mkdir(parents=True)
    (project_pack_dir / "artifacts").mkdir()
    (project_pack_dir / "artifacts" / "owned.bin").write_bytes(b"owned")
    sibling_dir = pack_root / "proj_unrelated_pack"
    sibling_dir.mkdir()
    (sibling_dir / "keep.bin").write_bytes(b"keep")

    external_artifact = tmp_path / "external-artifact.txt"
    external_artifact.write_text("user-owned", encoding="utf-8")
    await db.execute(
        """INSERT INTO artifacts
           (id, filename, filepath, extraction_status, project_id)
           VALUES (
               'art_external_delete_guard', 'external-artifact.txt', ?,
               'complete', ?
           )""",
        [str(external_artifact), project_id],
    )
    await db.commit()

    preview = await svc.delete_project(project_id, confirm=False)
    assert preview["confirmed"] is False
    assert (project_pack_dir / "artifacts" / "owned.bin").read_bytes() == b"owned"
    assert external_artifact.read_text(encoding="utf-8") == "user-owned"

    result = await svc.delete_project(project_id, confirm=True)

    assert result["confirmed"] is True
    assert not project_pack_dir.exists()
    assert (sibling_dir / "keep.bin").read_bytes() == b"keep"
    assert external_artifact.read_text(encoding="utf-8") == "user-owned"


@pytest.mark.asyncio
async def test_delete_project_reports_post_commit_storage_cleanup_failure(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = ProjectService(db)
    project_id = "proj_cleanup_warning"
    await svc.create_project(
        ProjectCreate(id=project_id, name="Cleanup Warning"),
        actor="system",
    )
    project_pack_dir = (
        Path(db.db_path).resolve().parent / "knowledge-packs" / project_id
    )
    project_pack_dir.mkdir(parents=True)
    (project_pack_dir / "owned.bin").write_bytes(b"owned")

    def fail_cleanup(_path: Path) -> None:
        raise PermissionError("simulated cleanup denial")

    monkeypatch.setattr("rka.services.project.shutil.rmtree", fail_cleanup)
    result = await svc.delete_project(project_id, confirm=True)

    assert result["confirmed"] is True
    assert result["managed_storage_cleanup"] == {
        "status": "failed",
        "path": str(project_pack_dir),
        "error": "simulated cleanup denial",
    }
    assert "was permanently deleted from RKA" in result["message"]
    assert await db.fetchone(
        "SELECT id FROM projects WHERE id = ?",
        [project_id],
    ) is None
    assert (project_pack_dir / "owned.bin").read_bytes() == b"owned"


@pytest.mark.asyncio
async def test_delete_project_rejects_symlinked_knowledge_pack_dir(
    db,
    tmp_path: Path,
) -> None:
    svc = ProjectService(db)
    project_id = "proj_symlink_pack"
    await svc.create_project(
        ProjectCreate(id=project_id, name="Symlink Pack"),
        actor="system",
    )

    external_dir = tmp_path / "external-pack-target"
    external_dir.mkdir()
    external_file = external_dir / "preserve.txt"
    external_file.write_text("external", encoding="utf-8")
    pack_root = Path(db.db_path).resolve().parent / "knowledge-packs"
    pack_root.mkdir()
    (pack_root / project_id).symlink_to(external_dir, target_is_directory=True)

    with pytest.raises(
        ValueError,
        match="project directory must not be a symbolic link",
    ):
        await svc.delete_project(project_id, confirm=True)

    assert await db.fetchone(
        "SELECT id FROM projects WHERE id = ?",
        [project_id],
    ) == {"id": project_id}
    assert external_file.read_text(encoding="utf-8") == "external"


@pytest.mark.asyncio
async def test_project_counts_and_delete_include_indirect_children(db) -> None:
    svc = ProjectService(db)
    project_id = "proj_indirect_children"
    await svc.create_project(
        ProjectCreate(id=project_id, name="Indirect Children"),
        actor="system",
    )
    await db.execute(
        """INSERT INTO qa_sessions (id, project_id, title)
           VALUES ('qas_indirect_delete', ?, 'Indirect')""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO qa_logs (id, session_id, question, answer)
           VALUES ('qal_indirect_one', 'qas_indirect_delete', 'Q1', 'A1'),
                  ('qal_indirect_two', 'qas_indirect_delete', 'Q2', 'A2')"""
    )
    await db.execute(
        """INSERT INTO topics (id, name, project_id)
           VALUES ('top_indirect_delete', 'indirect', ?)""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO entity_topics
           (topic_id, entity_type, entity_id, assigned_by)
           VALUES
             ('top_indirect_delete', 'journal', 'jrn_indirect_one', 'brain'),
             ('top_indirect_delete', 'journal', 'jrn_indirect_two', 'brain'),
             ('top_indirect_delete', 'journal', 'jrn_indirect_three', 'brain')"""
    )
    await db.commit()

    preview = await svc.delete_project(project_id, confirm=False)

    assert preview["entity_counts"]["qa_sessions"] == 1
    assert preview["entity_counts"]["qa_logs"] == 2
    assert preview["entity_counts"]["topics"] == 1
    assert preview["entity_counts"]["entity_topics"] == 3
    assert preview["total_rows"] == sum(preview["entity_counts"].values())
    assert await db.fetchone(
        "SELECT id FROM projects WHERE id = ?",
        [project_id],
    ) == {"id": project_id}

    result = await svc.delete_project(project_id, confirm=True)

    assert result["entity_counts"] == preview["entity_counts"]
    assert await db.fetchone(
        "SELECT id FROM projects WHERE id = ?",
        [project_id],
    ) is None
    assert await db.fetchall(
        "SELECT id FROM qa_logs WHERE session_id = 'qas_indirect_delete'"
    ) == []
    assert await db.fetchall(
        "SELECT topic_id FROM entity_topics "
        "WHERE topic_id = 'top_indirect_delete'"
    ) == []
