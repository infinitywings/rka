"""Tests for project knowledge-pack export/import."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rka.infra.database import Database
from rka.models.decision import DecisionCreate, DecisionOption
from rka.models.journal import JournalEntryCreate
from rka.models.literature import LiteratureCreate
from rka.models.project import ProjectCreate
from rka.services.artifacts import ArtifactService
from rka.services.decisions import DecisionService
from rka.services.knowledge_pack import KnowledgePackService
from rka.services.literature import LiteratureService
from rka.services.notes import NoteService
from rka.services.project import ProjectService


async def _make_db(path: Path) -> Database:
    db = Database(str(path))
    await db.connect()
    await db.initialize_schema()
    await db.initialize_phase2_schema()
    return db


@pytest.mark.asyncio
async def test_knowledge_pack_round_trip_imports_into_same_db_with_remapped_ids_and_artifacts(tmp_path: Path):
    db = await _make_db(tmp_path / "round-trip.db")
    artifact_path = tmp_path / "reference.txt"
    artifact_path.write_text("artifact payload", encoding="utf-8")

    try:
        project_svc = ProjectService(db)
        await project_svc.create_project(
            ProjectCreate(id="proj_export", name="Export Source", description="pack source"),
            actor="system",
        )
        note_svc = NoteService(db, project_id="proj_export")
        decision_svc = DecisionService(db, project_id="proj_export")
        literature_svc = LiteratureService(db, project_id="proj_export")
        artifact_svc = ArtifactService(db, project_id="proj_export")

        decision = await decision_svc.create(
            DecisionCreate(
                question="Use background probe for local LLM startup?",
                options=[
                    DecisionOption(label="block startup", description="wait for readiness"),
                    DecisionOption(label="background probe", description="serve immediately"),
                ],
                chosen="background probe",
                rationale="Keeps the API responsive while the local model warms up.",
                decided_by="pi",
                phase="validation",
                tags=["llm", "startup"],
            ),
            actor="pi",
        )
        literature = await literature_svc.create(
            LiteratureCreate(
                title="Background probing for local inference",
                doi="10.1234/rka-pack-roundtrip",
                abstract="A paper about background startup checks.",
                related_decisions=[decision.id],
                added_by="web_ui",
                tags=["llm"],
            ),
            actor="web_ui",
        )
        note = await note_svc.create(
            JournalEntryCreate(
                content="The imported knowledge pack should restore this note and keep it searchable.",
                type="finding",
                source="web_ui",
                phase="validation",
                related_decisions=[decision.id],
                related_literature=[literature.id],
                tags=["export", "import"],
            ),
            actor="web_ui",
        )
        artifact = await artifact_svc.register(
            filepath=str(artifact_path),
            filename="reference.txt",
            created_by="web_ui",
            metadata={"kind": "test"},
        )

        export_svc = KnowledgePackService(db, project_id="proj_export")
        pack_path, _ = await export_svc.export_pack()

        import_svc = KnowledgePackService(db)
        with open(pack_path, "rb") as pack_file:
            result = await import_svc.import_pack(
                pack_file,
                project_id="proj_imported",
                project_name="Imported Copy",
            )

        imported_note = await db.fetchone(
            "SELECT * FROM journal WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
            ["proj_imported"],
        )
        imported_decision = await db.fetchone(
            "SELECT * FROM decisions WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
            ["proj_imported"],
        )
        imported_literature = await db.fetchone(
            "SELECT * FROM literature WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
            ["proj_imported"],
        )
        imported_artifact = await db.fetchone(
            "SELECT * FROM artifacts WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
            ["proj_imported"],
        )
        imported_doi_rows = await db.fetchall(
            "SELECT id, project_id FROM literature WHERE doi = ? ORDER BY project_id",
            ["10.1234/rka-pack-roundtrip"],
        )
        fts_rows = await db.fetchall(
            "SELECT id FROM fts_journal WHERE fts_journal MATCH ? ORDER BY id",
            ["searchable"],
        )

        assert result.project_id == "proj_imported"
        assert result.project_name == "Imported Copy"
        assert result.source_project_id == "proj_export"
        assert result.imported_counts["journal"] == 1
        assert result.imported_counts["decisions"] == 1
        assert result.imported_counts["literature"] == 1
        assert result.imported_counts["artifacts"] == 1
        assert result.artifact_files_restored == 1

        assert imported_note is not None
        assert imported_decision is not None
        assert imported_literature is not None
        assert imported_artifact is not None

        assert imported_note["id"] != note.id
        assert imported_decision["id"] != decision.id
        assert imported_literature["id"] != literature.id
        assert imported_artifact["id"] != artifact["id"]

        assert json.loads(imported_note["related_decisions"]) == [imported_decision["id"]]
        assert json.loads(imported_note["related_literature"]) == [imported_literature["id"]]
        assert json.loads(imported_literature["related_decisions"]) == [imported_decision["id"]]

        assert imported_literature["doi"] == "10.1234/rka-pack-roundtrip"
        assert [(row["project_id"], row["id"]) for row in imported_doi_rows] == [
            ("proj_export", literature.id),
            ("proj_imported", imported_literature["id"]),
        ]

        assert Path(imported_artifact["filepath"]).exists()
        assert Path(imported_artifact["filepath"]).read_text(encoding="utf-8") == "artifact payload"
        assert sorted(row["id"] for row in fts_rows) == sorted([note.id, imported_note["id"]])
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_knowledge_pack_import_rejects_duplicate_target_project_name(tmp_path: Path):
    db = await _make_db(tmp_path / "target-name.db")

    try:
        project_svc = ProjectService(db)
        await project_svc.create_project(
            ProjectCreate(id="proj_export", name="Export Source", description="pack source"),
            actor="system",
        )
        note_svc = NoteService(db, project_id="proj_export")
        await note_svc.create(
            JournalEntryCreate(content="Imported project names must stay unique.", type="finding"),
            actor="pi",
        )

        export_svc = KnowledgePackService(db, project_id="proj_export")
        pack_path, _ = await export_svc.export_pack()

        with open(pack_path, "rb") as pack_file:
            with pytest.raises(ValueError, match="Project name 'Export Source' already exists"):
                await KnowledgePackService(db).import_pack(
                    pack_file,
                    project_id="proj_clone",
                    project_name="Export Source",
                )
    finally:
        await db.close()
