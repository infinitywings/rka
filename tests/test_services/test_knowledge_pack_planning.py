"""Knowledge-pack round trip for manuscript planning deliberation."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from rka.infra.database import Database
from rka.infra.ids import generate_id
from rka.models.manuscript_native import ManuscriptCreate
from rka.models.planning import (
    PlanningArtifactVersionAppend,
    PlanningBranchCreate,
    PlanningBranchTransition,
    PlanningEvidenceBindingInput,
)
from rka.services.knowledge_pack import (
    KnowledgePackIntegrityError,
    KnowledgePackService,
    PACK_SCHEMA_VERSION,
)
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.planning import ManuscriptPlanningService


@pytest.mark.asyncio
async def test_pack_v7_round_trip_preserves_frozen_planning_lineage(
    db_with_project,
) -> None:
    db = db_with_project
    source_project = "proj_default"
    journal_id = generate_id("journal")
    await db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES (?, ?, 'insight', ?, 'pi', 'tested')""",
        [journal_id, source_project, "Timing metadata can expose hidden agent state."],
    )
    await db.commit()
    manuscript = await NativeManuscriptService(db, project_id=source_project).create(
        ManuscriptCreate(title="Portable planning workbench"), actor="pi"
    )

    planning = ManuscriptPlanningService(db, project_id=source_project)
    primary = await planning.create_branch(
        PlanningBranchCreate(
            manuscript_id=manuscript.id,
            name="primary",
            purpose="Develop the central timing-side-channel framing.",
            created_by="pi",
            reason="Start the manuscript deliberation.",
        )
    )
    primary = await planning.append_artifact_version(
        primary["branch"]["id"],
        PlanningArtifactVersionAppend(
            expected_branch_revision=1,
            local_key="central-insight",
            stage_type="seed",
            lifecycle="selected",
            summary="Initial timing insight.",
            payload={
                "insight": "Observable timing can reveal hidden agent state.",
                "audience": ["security", "AI agents"],
            },
            origin="user",
            readiness_state="ready",
            created_by="pi",
            reason="Record the one-sentence seed.",
            evidence_bindings=[
                PlanningEvidenceBindingInput(
                    entity_type="journal",
                    entity_id=journal_id,
                    role="support",
                    locator_kind="whole_entity",
                    locator_value="full_record",
                )
            ],
        ),
    )
    child = await planning.create_branch(
        PlanningBranchCreate(
            manuscript_id=manuscript.id,
            name="reviewer-scope",
            purpose="Explore a narrower claim boundary without losing the primary branch.",
            parent_branch_id=primary["branch"]["id"],
            created_by="pi",
            reason="Compare a reviewer-resilient alternative.",
        )
    )
    child = await planning.append_artifact_version(
        child["branch"]["id"],
        PlanningArtifactVersionAppend(
            expected_branch_revision=1,
            local_key="central-insight",
            stage_type="seed",
            lifecycle="parked",
            summary="Bounded alternative timing insight.",
            payload={
                "insight": "In the measured agent loop, observable timing can reveal hidden state.",
                "significance": "The bounded wording remains useful if broader transfer does not hold.",
            },
            origin="user_revised",
            unresolved_items=["Cross-platform transfer remains untested."],
            readiness_state="blocked",
            readiness_missing=["Replication on a second agent runtime."],
            created_by="pi",
            reason="Park a narrower alternative for later comparison.",
        ),
    )
    child = await planning.transition_branch(
        child["branch"]["id"],
        PlanningBranchTransition(
            expected_revision=2,
            target_state="selected",
            actor="pi",
            reason="Continue from the bounded alternative.",
        ),
    )
    assert child["branch"]["parent_branch_revision"] == 2

    pack_path, _ = await KnowledgePackService(db, project_id=source_project).export_pack()
    with open(pack_path, "rb") as pack_file:
        result = await KnowledgePackService(db).import_pack(
            pack_file,
            project_id="proj_planning_import",
            project_name="Imported Planning Workbench",
        )

    assert PACK_SCHEMA_VERSION == 8
    for table in (
        "manuscript_planning_branches",
        "manuscript_planning_branch_events",
        "manuscript_planning_artifacts",
        "manuscript_planning_artifact_versions",
        "manuscript_planning_evidence_bindings",
    ):
        assert result.imported_counts[table] >= 1

    imported_manuscript = await db.fetchone(
        """SELECT * FROM manuscripts
           WHERE project_id = 'proj_planning_import' AND title = ?""",
        ["Portable planning workbench"],
    )
    imported_branches = await db.fetchall(
        """SELECT * FROM manuscript_planning_branches
           WHERE project_id = 'proj_planning_import' ORDER BY name"""
    )
    by_name = {row["name"]: row for row in imported_branches}
    imported_primary = by_name["primary"]
    imported_child = by_name["reviewer-scope"]

    assert imported_manuscript["id"] != manuscript.id
    assert imported_primary["context_key"] == imported_manuscript["id"]
    assert imported_child["context_key"] == imported_manuscript["id"]
    assert imported_child["parent_branch_id"] == imported_primary["id"]
    assert imported_child["parent_branch_revision"] == 2
    assert imported_primary["revision"] == 3

    imported_planning = ManuscriptPlanningService(db, project_id="proj_planning_import")
    resumed = await imported_planning.resume(manuscript_id=imported_manuscript["id"])
    assert resumed is not None
    assert resumed["branch"]["name"] == "reviewer-scope"
    assert resumed["parking_lot"][0]["version"]["payload"]["insight"].startswith(
        "In the measured agent loop"
    )
    inherited_id = resumed["parking_lot"][0]["version"]["derived_from_version_id"]
    assert inherited_id is not None
    assert inherited_id != primary["effective_artifacts"][0]["version"]["id"]

    comparison = await imported_planning.compare_branches(
        imported_primary["id"], imported_child["id"]
    )
    assert comparison["summary"] == {
        "added": 0,
        "removed": 0,
        "changed": 1,
        "unchanged": 0,
    }
    imported_binding = await db.fetchone(
        """SELECT binding.entity_id, journal.content
           FROM manuscript_planning_evidence_bindings AS binding
           JOIN journal ON journal.id = binding.entity_id
                      AND journal.project_id = binding.project_id
           WHERE binding.project_id = 'proj_planning_import'"""
    )
    assert imported_binding["entity_id"] != journal_id
    assert imported_binding["content"] == "Timing metadata can expose hidden agent state."
    assert await KnowledgePackService(db, project_id="proj_planning_import").check_integrity() == []
    assert await db.fetchall("PRAGMA foreign_key_check") == []


@pytest.mark.asyncio
async def test_pack_v7_rejects_invalid_typed_planning_payload(
    tmp_path: Path,
) -> None:
    source_project = "proj_invalid_planning_source"
    branch_id = "mpb_invalid_payload"
    artifact_id = "pla_invalid_payload"
    version_id = "plv_invalid_payload"
    tables = {
        "manuscript_planning_branches": [
            {
                "id": branch_id,
                "project_id": source_project,
                "context_key": "project",
                "name": "invalid",
                "purpose": "Exercise the semantic pack gate.",
                "state": "selected",
                "revision": 2,
                "created_by": "import",
            }
        ],
        "manuscript_planning_artifacts": [
            {
                "id": artifact_id,
                "branch_id": branch_id,
                "project_id": source_project,
                "local_key": "seed",
                "stage_type": "seed",
                "current_version": 1,
                "current_version_id": version_id,
                "created_by": "import",
            }
        ],
        "manuscript_planning_artifact_versions": [
            {
                "id": version_id,
                "artifact_id": artifact_id,
                "branch_id": branch_id,
                "project_id": source_project,
                "version": 1,
                "branch_revision": 2,
                "lifecycle": "candidate",
                "summary": "Syntactically valid JSON with an invalid empty insight.",
                "payload": json.dumps({"insight": ""}),
                "origin": "imported",
                "created_by": "import",
                "reason": "Verify semantic validation.",
            }
        ],
        "manuscript_planning_branch_events": [
            {
                "id": "pbe_invalid_created",
                "branch_id": branch_id,
                "project_id": source_project,
                "branch_revision": 1,
                "action": "created",
                "to_state": "selected",
                "actor": "import",
                "reason": "Synthetic creation event.",
                "details": "{}",
            },
            {
                "id": "pbe_invalid_version",
                "branch_id": branch_id,
                "project_id": source_project,
                "branch_revision": 2,
                "action": "artifact_version_appended",
                "from_state": "selected",
                "to_state": "selected",
                "actor": "import",
                "reason": "Synthetic version event.",
                "details": json.dumps(
                    {
                        "artifact_id": artifact_id,
                        "artifact_version_id": version_id,
                    }
                ),
            },
        ],
    }
    manifest = {
        "pack_format_version": PACK_SCHEMA_VERSION,
        "schema_version": 43,
        "project": {
            "id": source_project,
            "name": "Invalid Planning Source",
            "created_by": "system",
        },
        "project_state": None,
        "tables": tables,
        "table_counts": {table: len(rows) for table, rows in tables.items()},
    }
    pack_path = tmp_path / "invalid-planning.rka-pack.zip"
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))

    db = Database(str(tmp_path / "invalid-planning.db"))
    await db.connect()
    await db.initialize_schema()
    await db.initialize_phase2_schema()
    try:
        with pack_path.open("rb") as pack_file:
            with pytest.raises(KnowledgePackIntegrityError) as excinfo:
                await KnowledgePackService(db).import_pack(
                    pack_file,
                    project_id="proj_invalid_planning_target",
                    project_name="Invalid Planning Target",
                )
        assert {issue["category"] for issue in excinfo.value.issues} == {"planning_payload_invalid"}
        assert (
            await db.fetchone("SELECT id FROM projects WHERE id = 'proj_invalid_planning_target'")
            is None
        )
    finally:
        await db.close()
