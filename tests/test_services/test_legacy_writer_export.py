"""E2.3 legacy Writer compatibility-export regressions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import rka.config as config_module
from rka.cli import main
from rka.infra.ids import generate_id
from rka.infra.sqlite_backup import backup_sqlite_database
from rka.models.planning import (
    PlanningArtifactVersionAppend,
    PlanningBranchCreate,
    PlanningEvidenceBindingInput,
)
from rka.services.legacy_writer_export import (
    LEGACY_WRITER_EXPORT_CONTRACT,
    LEGACY_WRITER_SCHEMA_FINGERPRINT,
    LEGACY_WRITER_SCHEMA_SHA256,
    LEGACY_WRITER_TABLES,
    LegacyWriterExportError,
    export_legacy_writer_bundle,
)
from rka.services.planning import ManuscriptPlanningService
from tests.test_services.test_knowledge_pack_native import _seed_native_manuscript


async def _seed_export_fixture(db) -> dict[str, str]:
    source = await _seed_native_manuscript(db)
    project_id = "proj_default"
    figure_id = generate_id("figure")
    figure_unit_id = generate_id("manuscript_unit")
    await db.execute(
        """INSERT INTO figures (id, artifact_id, caption, project_id)
           VALUES (?, ?, 'Compatibility figure', ?)""",
        [figure_id, source["artifact_id"], project_id],
    )
    await db.execute(
        """INSERT INTO manuscript_units
           (id, manuscript_id, project_id, local_key, kind, location,
            artifact_ref, sequence)
           VALUES (?, ?, ?, 'F1', 'caption', 'figures/compatibility', ?, 99)""",
        [figure_unit_id, source["manuscript_id"], project_id, figure_id],
    )
    await db.commit()
    planning = ManuscriptPlanningService(db, project_id=project_id)
    branch = await planning.create_branch(
        PlanningBranchCreate(
            manuscript_id=source["manuscript_id"],
            name="writer-export",
            purpose="Verify the compatibility handoff.",
            created_by="pi",
            reason="Seed the E2.3 round trip.",
        )
    )
    await planning.append_artifact_version(
        branch["branch"]["id"],
        PlanningArtifactVersionAppend(
            expected_branch_revision=1,
            local_key="central-insight",
            stage_type="seed",
            lifecycle="selected",
            summary="A compact research insight.",
            payload={"insight": "Keep the evidence lineage auditable."},
            origin="user",
            readiness_state="ready",
            created_by="pi",
            reason="Preserve planning lineage.",
            evidence_bindings=[
                PlanningEvidenceBindingInput(
                    entity_type="journal",
                    entity_id=source["legacy_id"],
                    role="support",
                    locator_kind="whole_entity",
                    locator_value="full_record",
                )
            ],
        ),
    )

    proposal_id = generate_id("manuscript_source_proposal")
    event_id = generate_id("manuscript_source_event")
    content = "\\section{Introduction}\nCompatibility text.\n"
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    await db.execute(
        """INSERT INTO manuscript_source_proposals
           (id, project_id, manuscript_id, origin, relative_path, source_format,
            proposed_content, proposed_content_hash, created_by, reason,
            validation_findings, boundary)
           VALUES (?, ?, ?, 'human', 'paper.tex', 'latex', ?, ?, 'pi', ?, '[]', 'none')""",
        [
            proposal_id,
            project_id,
            source["manuscript_id"],
            content,
            content_hash,
            "Seed source-state migration coverage.",
        ],
    )
    await db.execute(
        """INSERT INTO manuscript_source_events
           (id, proposal_id, project_id, proposal_revision, action, actor, reason, details)
           VALUES (?, ?, ?, 1, 'proposed', 'pi', ?, '{}')""",
        [event_id, proposal_id, project_id, "Record the source proposal."],
    )
    await db.execute(
        """INSERT INTO manuscript_migration_issues
           (legacy_journal_id, project_id, canonical_candidate_id, reason, details)
           VALUES (?, NULL, ?, 'missing_title', '{}')""",
        [source["legacy_id"], source["manuscript_id"]],
    )
    await db.commit()
    planning_version = await db.fetchone(
        """SELECT id FROM manuscript_planning_artifact_versions
           WHERE branch_id = ? AND project_id = ?""",
        [branch["branch"]["id"], project_id],
    )
    assert planning_version is not None
    source.update(
        {
            "planning_version_id": planning_version["id"],
            "proposal_id": proposal_id,
            "source_event_id": event_id,
            "figure_id": figure_id,
        }
    )
    return source


def _manifest(bundle: Path) -> dict:
    with zipfile.ZipFile(bundle) as archive:
        return json.loads(archive.read("manifest.json"))


@pytest.mark.asyncio
async def test_export_preserves_all_writer_state_and_core_references(
    db_with_project,
    tmp_path: Path,
) -> None:
    source = await _seed_export_fixture(db_with_project)
    snapshot = tmp_path / "snapshot.db"
    backup_sqlite_database(db_with_project.db_path, snapshot)
    before_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    output = tmp_path / "writer.rka-writer-export.zip"

    result = export_legacy_writer_bundle(snapshot, "proj_default", output)
    manifest = _manifest(output)

    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == before_hash
    assert result.path == output
    assert manifest["contract"] == LEGACY_WRITER_EXPORT_CONTRACT
    assert manifest["schema_fingerprint"] == LEGACY_WRITER_SCHEMA_FINGERPRINT
    assert manifest["authority"]["authority_switched"] is False
    assert manifest["required_tables"] == list(LEGACY_WRITER_TABLES)
    assert set(manifest["tables"]) == set(LEGACY_WRITER_TABLES)
    assert manifest["table_count"] == len(LEGACY_WRITER_TABLES) == 29
    assert result.semantic_root_sha256 == manifest["semantic_root_sha256"]
    assert {descriptor["schema_sha256"] for descriptor in manifest["tables"].values()} == set(
        LEGACY_WRITER_SCHEMA_SHA256.values()
    )
    assert all(
        reference["resolution_status"] == "resolved" for reference in manifest["core_references"]
    )
    assert {
        (reference["entity_type"], reference["entity_id"])
        for reference in manifest["core_references"]
    } >= {
        ("journal", source["legacy_id"]),
        ("claim", source["evidence_id"]),
        ("decision", source["ratifying_decision_id"]),
        ("artifact", source["artifact_id"]),
        ("figure", source["figure_id"]),
        ("literature", source["active_literature_id"]),
        ("job", source["validation_job_id"]),
    }

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert names == [
            *(f"tables/{table}.json" for table in LEGACY_WRITER_TABLES),
            "manifest.json",
        ]
        manuscripts = json.loads(archive.read("tables/manuscripts.json"))
        ratifications = json.loads(archive.read("tables/manuscript_claim_ratifications.json"))
        planning_versions = json.loads(
            archive.read("tables/manuscript_planning_artifact_versions.json")
        )
        source_proposals = json.loads(archive.read("tables/manuscript_source_proposals.json"))
        migration_issues = json.loads(archive.read("tables/manuscript_migration_issues.json"))

    assert manuscripts[0]["id"] == source["manuscript_id"]
    assert any(row["id"] == source["ratification_id"] for row in ratifications)
    assert any(row["id"] == source["planning_version_id"] for row in planning_versions)
    assert source_proposals == [
        next(row for row in source_proposals if row["id"] == source["proposal_id"])
    ]
    assert any(row["project_id"] is None for row in migration_issues)


@pytest.mark.asyncio
async def test_export_rejects_schema_drift_and_dangling_logical_reference(
    db_with_project,
    tmp_path: Path,
) -> None:
    await _seed_export_fixture(db_with_project)
    snapshot = tmp_path / "snapshot.db"
    backup_sqlite_database(db_with_project.db_path, snapshot)

    with sqlite3.connect(snapshot) as connection:
        connection.execute("ALTER TABLE manuscript_claims ADD COLUMN unsupported TEXT")
    with pytest.raises(LegacyWriterExportError, match="unsupported v1 schema"):
        export_legacy_writer_bundle(snapshot, "proj_default", tmp_path / "schema.zip")

    backup_sqlite_database(db_with_project.db_path, snapshot)
    with sqlite3.connect(snapshot) as connection:
        connection.execute(
            """INSERT INTO manuscript_planning_evidence_bindings
               (id, artifact_version_id, artifact_id, project_id, entity_type,
                entity_id, role, source_version, locator_kind, locator_value,
                locator_start, locator_end, content_hash, ordinal, note)
               SELECT 'plb_missing', artifact_version_id, artifact_id, project_id,
                      'journal', 'jrn_missing', 'support', source_version,
                      locator_kind, locator_value, locator_start, locator_end,
                      content_hash, ordinal + 1, note
               FROM manuscript_planning_evidence_bindings LIMIT 1"""
        )
    with pytest.raises(LegacyWriterExportError, match="missing Core reference"):
        export_legacy_writer_bundle(snapshot, "proj_default", tmp_path / "reference.zip")

    backup_sqlite_database(db_with_project.db_path, snapshot)
    with sqlite3.connect(snapshot) as connection:
        connection.execute(
            """INSERT INTO manuscript_planning_evidence_bindings
               (id, artifact_version_id, artifact_id, project_id, entity_type,
                entity_id, role, source_version, locator_kind, locator_value,
                locator_start, locator_end, content_hash, ordinal, note)
               SELECT 'plb_missing_internal', artifact_version_id, artifact_id,
                      project_id, 'manuscript', 'man_missing', 'support',
                      source_version, locator_kind, locator_value, locator_start,
                      locator_end, content_hash, ordinal + 2, note
               FROM manuscript_planning_evidence_bindings LIMIT 1"""
        )
    with pytest.raises(LegacyWriterExportError, match="missing internal reference"):
        export_legacy_writer_bundle(
            snapshot,
            "proj_default",
            tmp_path / "internal-reference.zip",
        )

    backup_sqlite_database(db_with_project.db_path, snapshot)
    with sqlite3.connect(snapshot) as connection:
        connection.execute("DROP TRIGGER trg_planning_artifacts_validate_update")
        connection.execute(
            """UPDATE manuscript_planning_artifacts
               SET current_version_id = 'plv_missing'
               WHERE project_id = 'proj_default'"""
        )
    with pytest.raises(LegacyWriterExportError, match="invalid current version pointer"):
        export_legacy_writer_bundle(
            snapshot,
            "proj_default",
            tmp_path / "current-version.zip",
        )

    backup_sqlite_database(db_with_project.db_path, snapshot)
    with sqlite3.connect(snapshot) as connection:
        connection.execute(
            """INSERT INTO reference_validation_migration_issues
               (project_id, attestation_id, issue_code, details)
               VALUES ('proj_default', 'rvd_missing', 'test_missing', '{}')"""
        )
    with pytest.raises(LegacyWriterExportError, match="missing attestation"):
        export_legacy_writer_bundle(
            snapshot,
            "proj_default",
            tmp_path / "migration-attestation.zip",
        )


@pytest.mark.asyncio
async def test_export_rejects_runtime_sidecar(
    db_with_project,
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "snapshot.db"
    backup_sqlite_database(db_with_project.db_path, snapshot)
    sidecar = Path(f"{snapshot}-wal")
    sidecar.touch()

    with pytest.raises(LegacyWriterExportError, match="runtime sidecars"):
        export_legacy_writer_bundle(snapshot, "proj_default", tmp_path / "writer.zip")


@pytest.mark.asyncio
async def test_export_writer_cli_creates_private_backup(
    db_with_project,
    monkeypatch,
    tmp_path: Path,
) -> None:
    await _seed_export_fixture(db_with_project)
    source = tmp_path / "live.db"
    backup_sqlite_database(db_with_project.db_path, source)
    output = tmp_path / "writer.zip"
    monkeypatch.setattr(
        config_module,
        "RKAConfig",
        lambda: SimpleNamespace(database_url=str(source)),
    )

    result = CliRunner().invoke(
        main,
        ["export-writer", "--project-id", "proj_default", "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    assert "Semantic root:" in result.output
    assert output.is_file()


def test_contract_table_registry_matches_exporter() -> None:
    contract_path = Path(__file__).parents[2] / "contracts" / "rka-legacy-writer-export-v1.json"
    contract = json.loads(contract_path.read_text())
    assert contract["tables"] == list(LEGACY_WRITER_TABLES)
    assert contract["schema_fingerprint"] == LEGACY_WRITER_SCHEMA_FINGERPRINT
