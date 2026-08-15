"""Knowledge-pack round trip for experiment evidence lineage."""

from __future__ import annotations

import json

import pytest

from rka.models.experiment import (
    EvidenceLocatorCreate,
    ExperimentCreate,
    ExperimentObservationCreate,
    ExperimentRunCreate,
    ExperimentRunTransition,
)
from rka.models.interpretation import InterpretationCandidateCreate, InterpretationTriage
from rka.services.experiments import ExperimentService
from rka.services.interpretation import InterpretationService
from rka.services.knowledge_pack import KnowledgePackService, PACK_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_current_pack_round_trip_preserves_experiment_evidence_lineage(
    db_with_project,
) -> None:
    db = db_with_project
    project_id = "proj_default"
    experiments = ExperimentService(db, project_id=project_id)
    interpretations = InterpretationService(db, project_id=project_id)

    experiment = await experiments.create_experiment(
        ExperimentCreate(
            title="Pack experiment",
            objective="Preserve evidence lineage through export and import.",
            protocol="Execute one run and retain an exact repository locator.",
            metrics=["latency"],
            created_by="brain",
            reason="Exercise the current pack format.",
        )
    )
    run = await experiments.create_run(
        ExperimentRunCreate(
            experiment_id=experiment.id,
            plan_version=1,
            label="pack-run",
            runner="local",
            config={"seed": 7},
            created_by="executor",
            reason="Execute immutable plan version 1.",
        )
    )
    running = await experiments.transition_run(
        run.id,
        ExperimentRunTransition(
            expected_revision=1,
            action="start",
            actor="executor",
            reason="Started.",
        ),
    )
    observation = await experiments.create_observation(
        ExperimentObservationCreate(
            run_id=run.id,
            name="latency",
            kind="metric",
            direction="positive",
            summary="Median latency was 12 ms.",
            value_real=12.0,
            unit="ms",
            sample_size=20,
            observed_at="2026-08-15T12:00:00Z",
            recorded_by="executor",
        )
    )
    await experiments.add_locator(
        EvidenceLocatorCreate(
            observation_id=observation.id,
            source_kind="repository",
            repository_url="https://github.com/example/evaluation",
            commit_sha="0123456789abcdef0123456789abcdef01234567",
            relative_path="results/latency.json",
            locator_kind="json_pointer",
            locator_value="/latency/median",
            content_hash="b" * 64,
            created_by="executor",
        )
    )
    await experiments.transition_run(
        run.id,
        ExperimentRunTransition(
            expected_revision=running.revision,
            action="succeed",
            actor="executor",
            reason="Process exited normally.",
        ),
    )

    await db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES ('jrn_pack_experiment', ?, 'finding', ?, 'executor', 'tested')""",
        [project_id, "Median latency is low."],
    )
    await db.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, confidence, verified,
            evidence_status, stale, project_id)
           VALUES ('clm_pack_experiment', 'jrn_pack_experiment', 'result', ?,
                   0.8, 1, 'unassessed', 0, ?)""",
        ["Median latency is low.", project_id],
    )
    await db.commit()
    candidate = await interpretations.create(
        InterpretationCandidateCreate(
            source_type="experiment_observation",
            source_id=observation.id,
            locator_kind="record",
            locator_value="full_record",
            statement="Median latency was 12 ms.",
            epistemic_kind="observation",
            proposed_claim_type="result",
            created_by="brain",
            extraction_tool="pack_test",
        )
    )
    await interpretations.triage(
        candidate.id,
        InterpretationTriage(
            action="classify_evidence",
            expected_revision=1,
            actor="pi",
            reason="Reviewed exact locator and bounded claim scope.",
            target_entity_id="clm_pack_experiment",
            evidence_role="support",
        ),
    )

    pack_path, _ = await KnowledgePackService(
        db, project_id=project_id
    ).export_pack()
    with open(pack_path, "rb") as pack_file:
        result = await KnowledgePackService(db).import_pack(
            pack_file,
            project_id="proj_experiment_import",
            project_name="Imported Experiment Evidence",
        )

    assert PACK_SCHEMA_VERSION == 6
    for table in (
        "experiments",
        "experiment_plan_versions",
        "experiment_runs",
        "experiment_run_events",
        "experiment_observations",
        "evidence_locators",
        "claim_evidence_relations",
    ):
        assert result.imported_counts[table] >= 1

    imported_experiment = await db.fetchone(
        "SELECT * FROM experiments WHERE project_id = 'proj_experiment_import'"
    )
    imported_run = await db.fetchone(
        "SELECT * FROM experiment_runs WHERE project_id = 'proj_experiment_import'"
    )
    imported_observation = await db.fetchone(
        "SELECT * FROM experiment_observations WHERE project_id = 'proj_experiment_import'"
    )
    imported_locator = await db.fetchone(
        "SELECT * FROM evidence_locators WHERE project_id = 'proj_experiment_import'"
    )
    imported_candidate = await db.fetchone(
        """SELECT * FROM interpretation_candidates
           WHERE project_id = 'proj_experiment_import'
             AND source_type = 'experiment_observation'"""
    )
    imported_relation = await db.fetchone(
        "SELECT * FROM claim_evidence_relations WHERE project_id = 'proj_experiment_import'"
    )
    imported_claim = await db.fetchone(
        """SELECT * FROM claims
           WHERE project_id = 'proj_experiment_import'
             AND content = 'Median latency is low.'"""
    )

    assert imported_experiment["id"] != experiment.id
    assert imported_run["experiment_id"] == imported_experiment["id"]
    assert imported_run["plan_version"] == 1
    assert json.loads(imported_run["config"]) == {"seed": 7}
    assert imported_observation["run_id"] == imported_run["id"]
    assert imported_observation["direction"] == "positive"
    assert imported_locator["observation_id"] == imported_observation["id"]
    assert imported_locator["content_hash"] == "b" * 64
    assert imported_candidate["source_id"] == imported_observation["id"]
    assert imported_relation["candidate_id"] == imported_candidate["id"]
    assert imported_relation["observation_id"] == imported_observation["id"]
    assert imported_relation["claim_id"] == imported_claim["id"]
    assert imported_claim["evidence_status"] == "unassessed"
    assert await db.fetchall("PRAGMA foreign_key_check") == []
