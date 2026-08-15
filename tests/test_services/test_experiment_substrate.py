"""Experiment evidence substrate lifecycle and epistemic-boundary tests."""

from __future__ import annotations

import sqlite3

import pytest

from rka.models.experiment import (
    EvidenceLocatorCreate,
    ExperimentCreate,
    ExperimentObservationCreate,
    ExperimentRunCreate,
    ExperimentRunTransition,
    ExperimentTransition,
)
from rka.models.interpretation import (
    InterpretationCandidateCreate,
    InterpretationTriage,
)
from rka.models.project import ProjectCreate
from rka.services.experiments import ExperimentConflictError, ExperimentService
from rka.services.interpretation import InterpretationService
from rka.services.project import ProjectService


PROJECT = "proj_default"
HASH = "a" * 64


def _experiment() -> ExperimentCreate:
    return ExperimentCreate(
        title="Latency experiment",
        objective="Measure detector latency under the frozen workload.",
        hypothesis="Median latency is lower than the baseline.",
        protocol="Run the benchmark and retain raw results.",
        conditions=["frozen workload"],
        variables=["detector"],
        metrics=["median latency"],
        baselines=["baseline detector"],
        success_criteria=["95% CI below zero"],
        failure_criteria=["95% CI includes zero"],
        repository_url="https://github.com/example/evaluation",
        commit_sha="0123456789abcdef0123456789abcdef01234567",
        working_tree_state="clean",
        created_by="brain",
        reason="Test the paper claim.",
    )


@pytest.mark.asyncio
async def test_lifecycle_preserves_negative_evidence_and_requires_review(db) -> None:
    experiments = ExperimentService(db, project_id=PROJECT)
    interpretations = InterpretationService(db, project_id=PROJECT)

    experiment = await experiments.create_experiment(_experiment())
    assert experiment.status == "planned"
    assert experiment.current_plan.version == 1

    active = await experiments.transition_experiment(
        experiment.id,
        ExperimentTransition(
            expected_revision=1,
            target_status="active",
            actor="pi",
            reason="Protocol reviewed.",
        ),
    )
    run = await experiments.create_run(
        ExperimentRunCreate(
            experiment_id=experiment.id,
            plan_version=active.current_plan_version,
            label="seed-1",
            runner="local",
            command="python evaluate.py",
            created_by="executor",
            reason="Execute the reviewed plan.",
        )
    )
    assert run.status == "queued"
    assert [(event.action, event.to_status) for event in run.events] == [
        ("created", "queued")
    ]

    observation_input = ExperimentObservationCreate(
        run_id=run.id,
        name="latency difference",
        kind="comparison",
        direction="negative",
        summary="The proposed detector was slower than the baseline.",
        value_real=4.2,
        unit="ms",
        sample_size=30,
        uncertainty_note="Bootstrap interval excludes zero.",
        observed_at="2026-08-15T12:00:00Z",
        recorded_by="executor",
    )
    with pytest.raises(ExperimentConflictError, match="queued runs"):
        await experiments.create_observation(observation_input)

    running = await experiments.transition_run(
        run.id,
        ExperimentRunTransition(
            expected_revision=1,
            action="start",
            actor="executor",
            reason="Benchmark process started.",
        ),
    )
    observation = await experiments.create_observation(observation_input)
    locator = await experiments.add_locator(
        EvidenceLocatorCreate(
            observation_id=observation.id,
            source_kind="repository",
            repository_url="https://github.com/example/evaluation",
            commit_sha="0123456789abcdef0123456789abcdef01234567",
            relative_path="results/latency.json",
            locator_kind="json_pointer",
            locator_value="/comparison/median_ms",
            content_hash=HASH,
            created_by="executor",
        )
    )
    assert locator.content_hash == HASH

    succeeded = await experiments.transition_run(
        run.id,
        ExperimentRunTransition(
            expected_revision=running.revision,
            action="succeed",
            actor="executor",
            reason="Benchmark command exited normally.",
        ),
    )
    assert succeeded.status == "succeeded"
    assert observation.direction == "negative"

    await db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES ('jrn_experiment_claim', ?, 'finding', ?, 'executor', 'tested')""",
        [PROJECT, "The detector reduces latency."],
    )
    await db.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, confidence, verified,
            evidence_status, stale, project_id)
           VALUES ('clm_experiment_target', 'jrn_experiment_claim', 'result', ?,
                   0.8, 1, 'unassessed', 0, ?)""",
        ["The detector reduces latency.", PROJECT],
    )
    await db.commit()

    candidate = await interpretations.create(
        InterpretationCandidateCreate(
            source_type="experiment_observation",
            source_id=observation.id,
            locator_kind="record",
            locator_value="full_record",
            statement="The proposed detector was 4.2 ms slower than the baseline.",
            epistemic_kind="observation",
            uncertainty="low",
            proposed_claim_type="result",
            created_by="brain",
            extraction_tool="pytest",
        )
    )
    reviewed = await interpretations.triage(
        candidate.id,
        InterpretationTriage(
            action="classify_evidence",
            expected_revision=1,
            actor="pi",
            reason="Checked the exact result locator and comparison scope.",
            target_entity_id="clm_experiment_target",
            evidence_role="counterevidence",
        ),
    )
    assert reviewed.disposition == "classified_evidence"
    relation = await db.fetchone(
        "SELECT * FROM claim_evidence_relations WHERE candidate_id = ?",
        [candidate.id],
    )
    assert relation["role"] == "counterevidence"
    claim = await db.fetchone(
        "SELECT evidence_status FROM claims WHERE id = 'clm_experiment_target'"
    )
    assert claim["evidence_status"] == "unassessed"

    reopened = await interpretations.triage(
        candidate.id,
        InterpretationTriage(
            action="revoke_evidence",
            expected_revision=reviewed.revision,
            actor="pi",
            reason="The claim scope changed; preserve but revoke this relation.",
            target_entity_id="clm_experiment_target",
        ),
    )
    assert reopened.review_status == "pending"
    relation = await db.fetchone(
        "SELECT status, revocation_reason FROM claim_evidence_relations WHERE candidate_id = ?",
        [candidate.id],
    )
    assert relation["status"] == "revoked"
    assert "scope changed" in relation["revocation_reason"]

    completed = await experiments.transition_experiment(
        experiment.id,
        ExperimentTransition(
            expected_revision=active.revision,
            target_status="completed",
            actor="pi",
            reason="Execution record is complete; interpretation remains explicit.",
        ),
    )
    assert completed.status == "completed"


@pytest.mark.asyncio
async def test_revisions_append_only_rows_and_artifact_hash_are_enforced(db) -> None:
    service = ExperimentService(db, project_id=PROJECT)
    experiment = await service.create_experiment(_experiment())

    with pytest.raises(ExperimentConflictError, match="revision is 1"):
        await service.transition_experiment(
            experiment.id,
            ExperimentTransition(
                expected_revision=2,
                target_status="active",
                actor="pi",
                reason="Stale writer.",
            ),
        )

    active = await service.transition_experiment(
        experiment.id,
        ExperimentTransition(
            expected_revision=1,
            target_status="active",
            actor="pi",
            reason="Approved.",
        ),
    )
    run = await service.create_run(
        ExperimentRunCreate(
            experiment_id=experiment.id,
            plan_version=1,
            label="manual check",
            runner="manual",
            created_by="pi",
            reason="Capture a qualitative result.",
        )
    )
    running = await service.transition_run(
        run.id,
        ExperimentRunTransition(
            expected_revision=1,
            action="start",
            actor="pi",
            reason="Started.",
        ),
    )
    observation = await service.create_observation(
        ExperimentObservationCreate(
            run_id=run.id,
            name="manual inspection",
            kind="qualitative",
            direction="neutral",
            summary="The output format is readable.",
            value_text="readable",
            observed_at="2026-08-15T12:00:00Z",
            recorded_by="pi",
        )
    )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db.execute(
            "UPDATE experiment_observations SET summary = 'rewritten' WHERE id = ?",
            [observation.id],
        )

    await db.execute(
        """INSERT INTO artifacts
           (id, filename, filepath, content_hash, extraction_status, project_id)
           VALUES ('art_exact_result', 'result.json', '/tmp/result.json', ?, 'complete', ?)""",
        [HASH, PROJECT],
    )
    await db.commit()
    locator = await service.add_locator(
        EvidenceLocatorCreate(
            observation_id=observation.id,
            source_kind="artifact",
            artifact_id="art_exact_result",
            locator_kind="whole_artifact",
            locator_value="full_file",
            created_by="pi",
        )
    )
    assert locator.content_hash == HASH

    with pytest.raises(ExperimentConflictError, match="queued or running"):
        await service.transition_experiment(
            experiment.id,
            ExperimentTransition(
                expected_revision=active.revision,
                target_status="abandoned",
                actor="pi",
                reason="Cannot close while the run is active.",
            ),
        )
    assert running.status == "running"


@pytest.mark.asyncio
async def test_experiment_relations_fail_closed_across_projects(db) -> None:
    await ProjectService(db).create_project(
        ProjectCreate(id="proj_experiment_other", name="Other Experiment Project"),
        actor="system",
    )
    source = ExperimentService(db, project_id=PROJECT)
    foreign = ExperimentService(db, project_id="proj_experiment_other")
    experiment = await source.create_experiment(_experiment())

    with pytest.raises(ValueError, match="not found"):
        await foreign.create_run(
            ExperimentRunCreate(
                experiment_id=experiment.id,
                plan_version=1,
                label="cross-project run",
                runner="local",
                created_by="executor",
                reason="Must not cross project scope.",
            )
        )

    assert await foreign.get_experiment(experiment.id) is None
    assert await foreign.list_runs(experiment_id=experiment.id) == []
