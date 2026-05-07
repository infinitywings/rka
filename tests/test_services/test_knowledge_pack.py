"""Tests for project knowledge-pack export/import."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rka.infra.database import Database
from rka.models.decision import DecisionCreate, DecisionOption
from rka.models.journal import JournalEntryCreate
from rka.models.literature import LiteratureCreate
from rka.models.mission import MissionCreate
from rka.models.project import ProjectCreate
from rka.services.artifacts import ArtifactService
from rka.services.decisions import DecisionService
from rka.services.knowledge_pack import KnowledgePackService
from rka.services.literature import LiteratureService
from rka.services.missions import MissionService
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
async def test_knowledge_pack_import_with_mission_motivated_by_decision(tmp_path: Path):
    """Import must succeed when missions reference decisions via motivated_by_decision FK."""
    db = await _make_db(tmp_path / "mission-fk.db")

    try:
        project_svc = ProjectService(db)
        await project_svc.create_project(
            ProjectCreate(id="proj_src", name="Source", description="src"),
            actor="system",
        )
        decision_svc = DecisionService(db, project_id="proj_src")
        mission_svc = MissionService(db, project_id="proj_src")

        decision = await decision_svc.create(
            DecisionCreate(
                question="Which broker to use?",
                decided_by="pi",
                phase="design",
            ),
            actor="pi",
        )
        mission = await mission_svc.create(
            MissionCreate(
                phase="design",
                objective="Evaluate broker options",
                motivated_by_decision=decision.id,
            ),
            actor="executor",
        )

        export_svc = KnowledgePackService(db, project_id="proj_src")
        pack_path, _ = await export_svc.export_pack()

        import_svc = KnowledgePackService(db)
        with open(pack_path, "rb") as pack_file:
            result = await import_svc.import_pack(
                pack_file,
                project_id="proj_dst",
                project_name="Destination",
            )

        assert result.imported_counts["missions"] == 1
        assert result.imported_counts["decisions"] == 1

        imported_mission = await db.fetchone(
            "SELECT * FROM missions WHERE project_id = ?", ["proj_dst"]
        )
        imported_decision = await db.fetchone(
            "SELECT * FROM decisions WHERE project_id = ? LIMIT 1", ["proj_dst"]
        )

        assert imported_mission is not None
        assert imported_decision is not None
        assert imported_mission["id"] != mission.id
        assert imported_mission["motivated_by_decision"] == imported_decision["id"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_knowledge_pack_import_remaps_decision_related_journal(tmp_path: Path):
    """Import must remap decision.related_journal JSON references."""
    db = await _make_db(tmp_path / "dec-journal.db")

    try:
        project_svc = ProjectService(db)
        await project_svc.create_project(
            ProjectCreate(id="proj_src", name="Source", description="src"),
            actor="system",
        )
        decision_svc = DecisionService(db, project_id="proj_src")
        note_svc = NoteService(db, project_id="proj_src")

        note = await note_svc.create(
            JournalEntryCreate(content="Background analysis.", type="note"),
            actor="executor",
        )
        decision = await decision_svc.create(
            DecisionCreate(
                question="Which approach?",
                decided_by="brain",
                phase="design",
                related_journal=[note.id],
            ),
            actor="brain",
        )

        export_svc = KnowledgePackService(db, project_id="proj_src")
        pack_path, _ = await export_svc.export_pack()

        import_svc = KnowledgePackService(db)
        with open(pack_path, "rb") as pack_file:
            result = await import_svc.import_pack(
                pack_file,
                project_id="proj_dst",
                project_name="Destination",
            )

        imported_decision = await db.fetchone(
            "SELECT * FROM decisions WHERE project_id = ?", ["proj_dst"]
        )
        imported_note = await db.fetchone(
            "SELECT * FROM journal WHERE project_id = ?", ["proj_dst"]
        )

        assert imported_decision is not None
        assert imported_note is not None
        related_journal = json.loads(imported_decision["related_journal"])
        assert related_journal == [imported_note["id"]]
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


# Defect 3 (mis_01KR1Z28QW9WYXG4VV8PGYWD8G T5):
# _sync_imported_indexes now iterates claims and evidence_clusters; the import
# transaction now runs check_integrity before commit and rolls back on
# critical issues; the success path repairs non-critical claim_count drift.


import zipfile  # noqa: E402

from rka.services.knowledge_pack import (  # noqa: E402
    KnowledgePackIntegrityError,
    PACK_SCHEMA_VERSION,
)


def _write_synthetic_pack(
    pack_path: Path,
    *,
    source_project_id: str,
    source_project_name: str,
    tables: dict[str, list[dict]],
) -> None:
    """Build a minimal pack zip with the supplied tables payload.

    Used by integrity-gate tests that need to inject malformed rows the
    export path would never produce on its own.
    """
    manifest = {
        "pack_format_version": PACK_SCHEMA_VERSION,
        "schema_version": 21,  # DB migration number; advisory only
        "project": {
            "id": source_project_id,
            "name": source_project_name,
            "description": "synthetic pack",
            "created_by": "system",
        },
        "project_state": None,
        "tables": tables,
        "table_counts": {k: len(v) for k, v in tables.items()},
    }
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))


@pytest.mark.asyncio
async def test_knowledge_pack_import_indexes_imported_claims_and_clusters(tmp_path: Path):
    """T5: post-import, claim and cluster rows are in their FTS tables without a
    manual reindex. Pre-v2.3.4 _sync_imported_indexes stopped at missions, so
    imported claims/clusters were silently invisible to search.
    """
    db = await _make_db(tmp_path / "claim-cluster-fts.db")
    try:
        project_svc = ProjectService(db)
        await project_svc.create_project(
            ProjectCreate(id="proj_pack_src", name="Pack Source", description="s"),
            actor="system",
        )

        # Seed a journal entry as the FK target for the claim's source_entry_id.
        note_svc = NoteService(db, project_id="proj_pack_src")
        seed = await note_svc.create(
            JournalEntryCreate(content="seed entry for claim source.", type="note"),
            actor="pi",
        )

        # Insert one cluster + one claim directly so they show up in the export.
        await db.execute(
            """INSERT INTO evidence_clusters (id, label, synthesis, project_id)
               VALUES (?, ?, ?, ?)""",
            ["ecl_t5_a", "Latency cluster",
             "Synthesis: tuned configuration consistently lowers tail latency.",
             "proj_pack_src"],
        )
        await db.execute(
            """INSERT INTO claims
               (id, source_entry_id, claim_type, content, confidence, project_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ["clm_t5_a", seed.id, "observation",
             "Tuned configuration reduces 99th-percentile latency by 18 percent.",
             0.85, "proj_pack_src"],
        )
        await db.commit()

        export_svc = KnowledgePackService(db, project_id="proj_pack_src")
        pack_path, _ = await export_svc.export_pack()

        with open(pack_path, "rb") as pack_file:
            await KnowledgePackService(db).import_pack(
                pack_file, project_id="proj_pack_dst", project_name="Pack Dest",
            )

        # FTS hit on the imported claim by content keyword.
        claim_hits = await db.fetchall(
            "SELECT id FROM fts_claims WHERE fts_claims MATCH ?", ["latency"],
        )
        # FTS hit on the imported cluster by label keyword.
        cluster_hits = await db.fetchall(
            "SELECT id FROM fts_clusters WHERE fts_clusters MATCH ?", ["Latency"],
        )

        # Both source and imported (remapped) IDs must be FTS-visible.
        all_imported_claim_ids = await db.fetchall(
            "SELECT id FROM claims WHERE project_id = ?", ["proj_pack_dst"],
        )
        all_imported_cluster_ids = await db.fetchall(
            "SELECT id FROM evidence_clusters WHERE project_id = ?", ["proj_pack_dst"],
        )
        imported_claim_ids = {r["id"] for r in all_imported_claim_ids}
        imported_cluster_ids = {r["id"] for r in all_imported_cluster_ids}

        fts_claim_ids = {r["id"] for r in claim_hits}
        fts_cluster_ids = {r["id"] for r in cluster_hits}

        assert imported_claim_ids and imported_claim_ids.issubset(fts_claim_ids), (
            f"Imported claims missing from fts_claims: imported={imported_claim_ids} "
            f"fts={fts_claim_ids}"
        )
        assert imported_cluster_ids and imported_cluster_ids.issubset(fts_cluster_ids), (
            f"Imported clusters missing from fts_clusters: imported={imported_cluster_ids} "
            f"fts={fts_cluster_ids}"
        )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_knowledge_pack_import_rolls_back_on_orphan_entity_link(tmp_path: Path):
    """T5: a pack carrying an entity_link whose target_id points at a
    non-existent entity must roll back (orphaned_entity_link_targets is one of
    the four critical-integrity categories) and leave NO rows for the target
    project. Pre-v2.3.4 the integrity check was advisory-only; partial state
    landed.
    """
    pack_path = tmp_path / "synthetic-orphan.rka-pack.zip"
    _write_synthetic_pack(
        pack_path,
        source_project_id="proj_orphan_src",
        source_project_name="Orphan Source",
        tables={
            "journal": [{
                "id": "jrn_t5_orphan", "type": "note",
                "content": "Will be rolled back.", "source": "pi",
                "confidence": "tested", "status": "active",
                "project_id": "proj_orphan_src",
            }],
            # entity_link references a decision_id that doesn't exist in the
            # pack — orphan target by construction.
            "entity_links": [{
                "id": "lnk_t5_orphan",
                "source_type": "journal", "source_id": "jrn_t5_orphan",
                "link_type": "references",
                "target_type": "decision", "target_id": "dec_does_not_exist",
                "project_id": "proj_orphan_src",
            }],
        },
    )

    db = await _make_db(tmp_path / "orphan-rollback.db")
    try:
        with open(pack_path, "rb") as pack_file:
            with pytest.raises(KnowledgePackIntegrityError) as excinfo:
                await KnowledgePackService(db).import_pack(
                    pack_file,
                    project_id="proj_orphan_dst",
                    project_name="Orphan Dest",
                )
        # The error carries the structured findings.
        cats = {issue["category"] for issue in excinfo.value.issues}
        assert "orphaned_entity_link_targets" in cats

        # Critical: no rows for the target project survived. Check across
        # projects, journal, and entity_links.
        assert (await db.fetchall(
            "SELECT id FROM projects WHERE id = ?", ["proj_orphan_dst"],
        )) == []
        assert (await db.fetchall(
            "SELECT id FROM journal WHERE project_id = ?", ["proj_orphan_dst"],
        )) == []
        assert (await db.fetchall(
            "SELECT id FROM entity_links WHERE project_id = ?", ["proj_orphan_dst"],
        )) == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_knowledge_pack_import_recomputes_stale_claim_count(tmp_path: Path):
    """T5 (Brain success-path addition): when the post-insert integrity check
    reports a non-critical claim_count_mismatch, the import commits and the
    success path runs a project-scoped recompute so the row lands with the
    correct derived count instead of the stale value the pack carried.
    """
    pack_path = tmp_path / "synthetic-stale-count.rka-pack.zip"
    _write_synthetic_pack(
        pack_path,
        source_project_id="proj_stale_src",
        source_project_name="Stale Count Source",
        tables={
            "journal": [{
                "id": "jrn_t5_stale", "type": "note",
                "content": "seed", "source": "pi",
                "confidence": "tested", "status": "active",
                "project_id": "proj_stale_src",
            }],
            "claims": [{
                "id": "clm_t5_stale_1", "source_entry_id": "jrn_t5_stale",
                "claim_type": "observation",
                "content": "single member claim",
                "confidence": 0.7, "project_id": "proj_stale_src",
            }],
            "evidence_clusters": [{
                "id": "ecl_t5_stale", "label": "Stale-count cluster",
                # Pack carries claim_count = 99 (deliberately wrong).
                "claim_count": 99,
                "project_id": "proj_stale_src",
            }],
            "claim_edges": [{
                "id": "clmedge_t5_stale_member", "source_claim_id": "clm_t5_stale_1",
                "target_claim_id": None, "cluster_id": "ecl_t5_stale",
                "relation": "member_of", "confidence": 0.9,
                "project_id": "proj_stale_src",
            }],
        },
    )

    db = await _make_db(tmp_path / "stale-count.db")
    try:
        with open(pack_path, "rb") as pack_file:
            result = await KnowledgePackService(db).import_pack(
                pack_file,
                project_id="proj_stale_dst",
                project_name="Stale Count Dest",
            )

        # Issue surfaced (proves the gate ran) and import committed (success
        # path returned a result).
        issue_cats = {i["category"] for i in result.integrity_issues}
        assert "claim_count_mismatch" in issue_cats

        rows = await db.fetchall(
            "SELECT id, claim_count FROM evidence_clusters WHERE project_id = ?",
            ["proj_stale_dst"],
        )
        assert len(rows) == 1
        assert rows[0]["claim_count"] == 1, (
            "Success-path recompute should have repaired the stale claim_count "
            f"(99 → 1 member_of edge); got {rows[0]['claim_count']}."
        )
    finally:
        await db.close()
