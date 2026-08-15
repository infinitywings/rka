"""Migration 042 preserves existing interpretation staging lineage."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rka.infra.database import Database
from rka.models.interpretation import (
    InterpretationCandidateCreate,
    InterpretationHintCreate,
    InterpretationTriage,
)
from rka.services.interpretation import InterpretationService


@pytest.mark.asyncio
async def test_041_upgrade_preserves_candidates_hints_and_review_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path(__file__).parents[2] / "rka" / "db" / "migrations"
    before_dir = tmp_path / "migrations-before-042"
    before_dir.mkdir()
    for migration in source.glob("*.sql"):
        if migration.name.startswith("._"):
            continue
        if int(migration.name.split("_", 1)[0]) <= 41:
            shutil.copy2(migration, before_dir / migration.name)

    monkeypatch.setattr(
        Database,
        "_migrations_directory",
        staticmethod(lambda: before_dir),
    )
    database = Database(str(tmp_path / "upgrade-041.db"))
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    try:
        await database.execute(
            """INSERT INTO journal
               (id, project_id, type, content, source, confidence)
               VALUES ('jrn_upgrade_042_a', 'proj_default', 'finding',
                       'Measured latency was 42 ms.', 'executor', 'tested')"""
        )
        await database.execute(
            """INSERT INTO journal
               (id, project_id, type, content, source, confidence)
               VALUES ('jrn_upgrade_042_b', 'proj_default', 'finding',
                       'Measured latency was 43 ms.', 'executor', 'tested')"""
        )
        await database.commit()
        service = InterpretationService(database, project_id="proj_default")
        first = await service.create(
            InterpretationCandidateCreate(
                source_type="journal",
                source_id="jrn_upgrade_042_a",
                locator_kind="text_offset",
                locator_start=0,
                locator_end=27,
                statement="Latency was 42 ms.",
                epistemic_kind="observation",
                created_by="executor",
                extraction_tool="migration_test",
            )
        )
        second = await service.create(
            InterpretationCandidateCreate(
                source_type="journal",
                source_id="jrn_upgrade_042_b",
                locator_kind="text_offset",
                locator_start=0,
                locator_end=27,
                statement="Latency was 43 ms.",
                epistemic_kind="observation",
                created_by="executor",
                extraction_tool="migration_test",
            )
        )
        detailed = await service.add_hint(
            first.id,
            InterpretationHintCreate(
                related_candidate_id=second.id,
                kind="conflict",
                confidence=0.9,
                rationale="Same metric, different recorded value.",
                created_by="brain",
                expected_revision=1,
            ),
        )
        reviewed = await service.triage(
            first.id,
            InterpretationTriage(
                action="start_review",
                expected_revision=detailed.revision,
                actor="brain",
            ),
        )
        assert reviewed.review_status == "in_review"

        upgrade_dir = tmp_path / "migration-042-only"
        upgrade_dir.mkdir()
        migration_042 = source / "042_add_experiment_evidence_substrate.sql"
        shutil.copy2(migration_042, upgrade_dir / migration_042.name)
        monkeypatch.setattr(
            Database,
            "_migrations_directory",
            staticmethod(lambda: upgrade_dir),
        )

        assert await database.run_migrations() == 1
        upgraded = await InterpretationService(
            database, project_id="proj_default"
        ).get_detail(first.id)
        assert upgraded is not None
        assert upgraded.review_status == "in_review"
        assert upgraded.revision == reviewed.revision
        assert [(hint.kind, hint.related_candidate_id) for hint in upgraded.hints] == [
            ("conflict", second.id)
        ]
        assert [event.action for event in upgraded.review_events] == [
            "created",
            "hint_added",
            "start_review",
        ]
        assert await database.fetchall("PRAGMA foreign_key_check") == []

        candidate_sql = await database.fetchone(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'interpretation_candidates'"
        )
        assert "experiment_observation" in candidate_sql["sql"]
        assert await database.fetchone(
            "SELECT filename FROM schema_migrations WHERE filename = ?",
            [migration_042.name],
        ) == {"filename": migration_042.name}
    finally:
        await database.close()
