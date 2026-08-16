"""Claim-centered evaluation contract, mission, and result trace tests."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from rka.infra.ids import generate_id
from rka.models.decision import DecisionCreate
from rka.models.experiment import (
    EvidenceLocatorCreate,
    ExperimentCreate,
    ExperimentObservationCreate,
    ExperimentRunCreate,
    ExperimentRunTransition,
)
from rka.models.manuscript_native import ManuscriptCreate
from rka.models.planning import (
    PlanningArtifactVersionAppend,
    PlanningBranchCreate,
    PlanningEvaluationMissionCreate,
    PlanningEvaluationResultProposalPrepare,
)
from rka.models.semantic_patch import SemanticPatchProposalTransition
from rka.services.decisions import DecisionService
from rka.services.experiments import ExperimentService
from rka.services.knowledge_pack import KnowledgePackService
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.planning import ManuscriptPlanningService, PlanningConflictError
from rka.services.project import ProjectService
from rka.services.semantic_patch import SemanticPatchService


PROJECT = "proj_default"
HASH = "b" * 64


def test_evaluation_payload_rejects_incompatible_outcome_effect_and_hidden_refs() -> None:
    base = {
        "expected_branch_revision": 1,
        "local_key": "evaluation",
        "stage_type": "evaluation",
        "lifecycle": "selected",
        "summary": "Exact contract.",
        "payload": {
            "commitments": [{
                "local_key": "claim-1-evaluation",
                "claim_id": "mcl_01CLAIM",
                "claim_version": 1,
                "research_question_refs": ["dec_01RQ"],
                "method": "Run the frozen comparison.",
                "requirements": [{
                    "local_key": "primary-effect",
                    "kind": "support",
                    "description": "Measure the primary effect.",
                    "experiment_id": "exp_01EXP",
                    "plan_version_id": "epv_01PLAN",
                    "plan_version": 1,
                    "acceptance_criteria": ["Interval excludes zero."],
                    "failure_criteria": ["Interval includes zero."],
                    "observations": [{
                        "observation_id": "obs_01OBS",
                        "locator_ids": ["elc_01LOC"],
                        "role": "primary",
                        "outcome": "fails_to_support",
                        "claim_effect": "supports_as_worded",
                        "interpretation": "The expected effect was absent.",
                    }],
                }],
                "baselines": ["frozen baseline"],
                "metrics": ["effect size"],
                "conditions": ["frozen workload"],
                "success_criteria": ["Positive bounded effect."],
                "failure_criteria": ["No bounded effect."],
                "allowed_interpretation": "The effect holds in the frozen workload.",
                "prohibited_interpretation": ["The effect always holds."],
                "disposition": "selected",
            }],
            "validity_checks": ["Repeat across seeds."],
        },
        "origin": "user",
        "readiness_state": "ready",
        "created_by": "pi",
        "reason": "Test the exact evaluation schema.",
        "evidence_bindings": [],
    }
    with pytest.raises(ValidationError, match="incompatible"):
        PlanningArtifactVersionAppend.model_validate(base)

    base["payload"]["commitments"][0]["requirements"][0]["observations"][0].update({
        "outcome": "supports",
        "claim_effect": "supports_as_worded",
    })
    with pytest.raises(ValidationError, match="absent from evidence bindings"):
        PlanningArtifactVersionAppend.model_validate(base)


async def _canonical_setup(db, artifact_path: Path | None = None):
    journal_id = generate_id("journal")
    evidence_claim_id = generate_id("claim")
    await db.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, status, project_id)
           VALUES (?, 'finding', 'The bounded effect was measured.', 'executor',
                   'tested', 'high', 'active', ?)""",
        [journal_id, PROJECT],
    )
    await db.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, confidence, verified,
            evidence_status, stale, project_id)
           VALUES (?, ?, 'result', 'The bounded effect was measured.', 0.9, 1,
                   'supported', 0, ?)""",
        [evidence_claim_id, journal_id, PROJECT],
    )
    artifact_id = generate_id("artifact")
    artifact_hash = HASH
    if artifact_path is not None:
        payload = b'{"primary":{"effect":0.42}}'
        artifact_path.write_bytes(payload)
        artifact_hash = hashlib.sha256(payload).hexdigest()
    registered_path = str(artifact_path) if artifact_path is not None else "/tmp/results.json"
    await db.execute(
        """INSERT INTO artifacts
           (id, filename, filepath, filetype, file_size, mime, content_hash,
            extraction_status, created_by, project_id)
           VALUES (?, 'results.json', ?, 'json', 10,
                   'application/json', ?, 'complete', 'executor', ?)""",
        [artifact_id, registered_path, artifact_hash, PROJECT],
    )
    await db.commit()

    manuscripts = NativeManuscriptService(db, project_id=PROJECT)
    manuscript = await manuscripts.create(
        ManuscriptCreate(title="Evaluation contract test"), actor="pi"
    )
    context = await manuscripts.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine={
            "claims": [{
                "claim_id": "bounded-effect",
                "claim_type": "empirical",
                "status": "active",
                "text": "The method improves the bounded primary effect.",
                "allowed_wording": "The method improves the effect in the frozen workload.",
                "prohibited_wording": ["The method always improves the effect."],
                "evidence_ids": [evidence_claim_id],
                "qualifier_ids": [],
                "counterevidence_ids": [],
                "unit_links": [],
            }],
            "units": [],
        },
        actor="pi",
    )
    manuscript_claim = context["claims"][0]
    rq = await DecisionService(db, project_id=PROJECT).create(
        DecisionCreate(
            question="Does the method improve the bounded primary effect?",
            chosen="Does the method improve the bounded primary effect?",
            rationale="This is the central empirical uncertainty.",
            decided_by="pi",
            phase="paper_framing",
            kind="research_question",
        ),
        actor="pi",
    )

    experiments = ExperimentService(db, project_id=PROJECT)
    experiment = await experiments.create_experiment(
        ExperimentCreate(
            title="Bounded primary comparison",
            objective="Measure the bounded effect under the frozen workload.",
            hypothesis="The effect is positive.",
            protocol="Run the frozen benchmark and retain exact output.",
            conditions=["frozen workload"],
            variables=["method"],
            metrics=["effect size"],
            baselines=["frozen baseline"],
            success_criteria=["95% interval excludes zero."],
            failure_criteria=["95% interval includes zero."],
            created_by="brain",
            reason="Evaluate the exact manuscript claim.",
        )
    )
    run = await experiments.create_run(
        ExperimentRunCreate(
            experiment_id=experiment.id,
            plan_version=1,
            label="seed-1",
            runner="local",
            command="python evaluate.py",
            created_by="executor",
            reason="Execute the reviewed plan.",
        )
    )
    running = await experiments.transition_run(
        run.id,
        ExperimentRunTransition(
            expected_revision=1,
            action="start",
            actor="executor",
            reason="Start exact evaluation.",
        ),
    )
    return {
        "manuscript": context["manuscript"],
        "manuscript_claim": manuscript_claim,
        "evidence_claim_id": evidence_claim_id,
        "artifact_id": artifact_id,
        "rq": rq,
        "experiment": experiment,
        "run": running,
        "experiments": experiments,
    }


def _evaluation_payload(setup, observations=None):
    return {
        "commitments": [{
            "local_key": "bounded-effect-evaluation",
            "claim_id": setup["manuscript_claim"]["id"],
            "claim_version": setup["manuscript_claim"]["version"],
            "research_question_refs": [setup["rq"].id],
            "method": "Run the frozen comparison and retain exact evidence.",
            "requirements": [{
                "local_key": "primary-effect",
                "kind": "support",
                "description": "Measure and falsify the bounded primary effect.",
                "required": True,
                "experiment_id": setup["experiment"].id,
                "plan_version_id": setup["experiment"].current_plan.id,
                "plan_version": 1,
                "acceptance_criteria": ["95% interval excludes zero."],
                "failure_criteria": ["95% interval includes zero."],
                "observations": observations or [],
                "missing_evidence": "Collect the exact primary comparison.",
            }],
            "baselines": ["frozen baseline"],
            "metrics": ["effect size"],
            "conditions": ["frozen workload"],
            "success_criteria": ["Positive bounded effect."],
            "failure_criteria": ["No bounded effect."],
            "allowed_interpretation": "The method improves the effect in the frozen workload.",
            "prohibited_interpretation": ["The method always improves the effect."],
            "disposition": "selected",
        }],
        "validity_checks": ["Repeat across seeds."],
    }


def _bindings(setup, observation_id=None, locator_id=None):
    rows = [
        {"entity_type": "manuscript_claim", "entity_id": setup["manuscript_claim"]["id"], "role": "context"},
        {"entity_type": "decision", "entity_id": setup["rq"].id, "role": "context"},
        {"entity_type": "experiment", "entity_id": setup["experiment"].id, "role": "context"},
        {"entity_type": "experiment_plan_version", "entity_id": setup["experiment"].current_plan.id, "role": "context"},
    ]
    if observation_id:
        rows.append({"entity_type": "experiment_observation", "entity_id": observation_id, "role": "support"})
    if locator_id:
        rows.append({"entity_type": "evidence_locator", "entity_id": locator_id, "role": "support"})
    return rows


@pytest.mark.asyncio
async def test_missing_evidence_mission_then_exact_result_proposal_and_apply(
    db_with_project,
    tmp_path: Path,
) -> None:
    setup = await _canonical_setup(db_with_project, tmp_path / "results.json")
    planning = ManuscriptPlanningService(db_with_project, project_id=PROJECT)
    branch_context = await planning.create_branch(
        PlanningBranchCreate(
            manuscript_id=setup["manuscript"]["id"],
            name="evaluation",
            purpose="Exercise the claim-centered evaluation contract.",
            created_by="pi",
            reason="Create a selected evaluation branch.",
        )
    )
    branch_id = branch_context["branch"]["id"]
    rq_context = await planning.append_artifact_version(
        branch_id,
        PlanningArtifactVersionAppend(
            expected_branch_revision=1,
            local_key="rq-portfolio",
            stage_type="rq_contribution",
            lifecycle="selected",
            summary="Selected RQ and bounded empirical contribution.",
            payload={
                "research_questions": [{
                    "local_key": "rq-primary",
                    "question": setup["rq"].question,
                    "scope": "Frozen workload.",
                    "rationale": "The bounded effect is the central uncertainty.",
                    "evidence_entity_ids": [setup["evidence_claim_id"]],
                    "disposition": "selected",
                }],
                "contributions": [{
                    "local_key": "contribution-primary",
                    "exact_wording": setup["manuscript_claim"]["exact_wording"],
                    "contribution_type": "empirical",
                    "research_question_refs": [setup["rq"].id],
                    "allowed_wording": setup["manuscript_claim"]["allowed_wording"],
                    "prohibited_wording": setup["manuscript_claim"]["prohibited_wording"],
                    "support_ids": [setup["evidence_claim_id"]],
                    "disposition": "selected",
                }],
            },
            origin="user",
            readiness_state="ready",
            created_by="pi",
            reason="Select exact contribution framing.",
            evidence_bindings=[
                {"entity_type": "claim", "entity_id": setup["evidence_claim_id"], "role": "support"},
                {"entity_type": "decision", "entity_id": setup["rq"].id, "role": "context"},
            ],
        ),
    )
    rq_artifact = next(
        item for item in rq_context["effective_artifacts"] if item["stage_type"] == "rq_contribution"
    )
    evaluation = await planning.append_artifact_version(
        branch_id,
        PlanningArtifactVersionAppend(
            expected_branch_revision=2,
            local_key="evaluation-primary",
            stage_type="evaluation",
            lifecycle="selected",
            summary="Primary evidence is still missing.",
            payload={
                **_evaluation_payload(setup),
                "upstream_versions": [{
                    "stage_type": "rq_contribution",
                    "local_key": rq_artifact["local_key"],
                    "artifact_id": rq_artifact["id"],
                    "version_id": rq_artifact["version"]["id"],
                    "version": rq_artifact["version"]["version"],
                }],
            },
            origin="user",
            readiness_state="ready",
            created_by="pi",
            reason="Make the missing evidence executable.",
            evidence_bindings=_bindings(setup),
        ),
    )
    evaluation_artifact = next(
        item for item in evaluation["effective_artifacts"] if item["stage_type"] == "evaluation"
    )
    missing = await planning.evaluation_workflow(branch_id)
    assert missing["verdict"] == "Blocked"
    assert "lacks conclusive located evidence" in " ".join(
        missing["commitments"][0]["blockers"]
    )

    mission_result = await planning.create_evaluation_mission(
        branch_id,
        PlanningEvaluationMissionCreate(
            expected_branch_revision=3,
            artifact_id=evaluation_artifact["id"],
            expected_artifact_version=1,
            commitment_key="bounded-effect-evaluation",
            requirement_key="primary-effect",
            reason="Collect the exact missing primary evidence.",
            actor="pi",
        ),
    )
    assert mission_result["mission"]["motivated_by_decision"] == setup["rq"].id
    with pytest.raises(PlanningConflictError, match="already has"):
        await planning.create_evaluation_mission(
            branch_id,
            PlanningEvaluationMissionCreate(
                expected_branch_revision=3,
                artifact_id=evaluation_artifact["id"],
                expected_artifact_version=1,
                commitment_key="bounded-effect-evaluation",
                requirement_key="primary-effect",
                reason="Do not duplicate exact mission lineage.",
            ),
        )

    observation = await setup["experiments"].create_observation(
        ExperimentObservationCreate(
            run_id=setup["run"].id,
            name="bounded effect",
            kind="comparison",
            direction="positive",
            summary="The bounded effect was positive under the frozen workload.",
            value_real=0.42,
            unit="effect-size",
            sample_size=30,
            uncertainty_note="95% interval excludes zero.",
            observed_at="2026-08-15T12:00:00Z",
            recorded_by="executor",
        )
    )
    locator = await setup["experiments"].add_locator(
        EvidenceLocatorCreate(
            observation_id=observation.id,
            source_kind="artifact",
            artifact_id=setup["artifact_id"],
            locator_kind="json_pointer",
            locator_value="/primary/effect",
            created_by="executor",
        )
    )
    observation_binding = [{
        "observation_id": observation.id,
        "locator_ids": [locator.id],
        "role": "primary",
        "outcome": "supports",
        "claim_effect": "supports_as_worded",
        "interpretation": "Supports the bounded wording under the frozen workload.",
    }]
    evaluation = await planning.append_artifact_version(
        branch_id,
        PlanningArtifactVersionAppend(
            expected_branch_revision=3,
            expected_previous_version=1,
            local_key="evaluation-primary",
            stage_type="evaluation",
            lifecycle="selected",
            summary="The primary evidence is exactly located.",
            payload={
                **_evaluation_payload(setup, observation_binding),
                "upstream_versions": [{
                    "stage_type": "rq_contribution",
                    "local_key": rq_artifact["local_key"],
                    "artifact_id": rq_artifact["id"],
                    "version_id": rq_artifact["version"]["id"],
                    "version": rq_artifact["version"]["version"],
                }],
            },
            origin="user_revised",
            readiness_state="ready",
            created_by="pi",
            reason="Bind the exact observation and locator.",
            evidence_bindings=_bindings(setup, observation.id, locator.id),
        ),
    )
    evaluation_artifact = next(
        item for item in evaluation["effective_artifacts"] if item["stage_type"] == "evaluation"
    )
    resolved = await planning.evaluation_workflow(branch_id)
    assert resolved["verdict"] == "Needs review"
    assert resolved["commitments"][0]["requirements"][0]["verdict"] == "Ready"
    assert resolved["commitments"][0]["requirements"][0]["observations"][0][
        "locators"
    ][0]["id"] == locator.id
    assert "not PI-ratified" in " ".join(resolved["commitments"][0]["warnings"])

    prepared = await planning.prepare_evaluation_result_proposal(
        branch_id,
        PlanningEvaluationResultProposalPrepare(
            expected_branch_revision=4,
            artifact_id=evaluation_artifact["id"],
            expected_artifact_version=2,
            commitment_key="bounded-effect-evaluation",
            manuscript_id=setup["manuscript"]["id"],
            expected_manuscript_revision=2,
            result_unit_local_key="result-primary-effect",
            location="sections/results.tex#primary-effect",
            title="Primary bounded effect",
            artifact_ref=setup["artifact_id"],
            reason="Prepare a bounded result unit for explicit review.",
            actor="pi",
        ),
    )
    proposal = prepared["proposal"]
    assert proposal["status"] == "proposed"
    assert prepared["evaluation_event"]["details"]["observation_ids"] == [observation.id]

    await SemanticPatchService(db_with_project, project_id=PROJECT).apply_proposal(
        proposal["id"],
        SemanticPatchProposalTransition(
            expected_revision=1,
            actor="pi",
            reason="Approve the exact result-unit preview.",
        ),
    )
    context = await NativeManuscriptService(
        db_with_project, project_id=PROJECT
    ).get_context(setup["manuscript"]["id"])
    result_unit = next(item for item in context["units"] if item["local_key"] == "result-primary-effect")
    claim = next(item for item in context["claims"] if item["id"] == setup["manuscript_claim"]["id"])
    assert result_unit["artifact_ref"] == setup["artifact_id"]
    assert next(
        link for link in claim["unit_links"] if link["unit_id"] == result_unit["id"]
    )["relationship"] == "tests"
    actions = [item["action"] for item in await planning.list_evaluation_events(branch_id)]
    assert actions == [
        "missing_evidence_mission_created",
        "result_unit_proposal_prepared",
        "result_unit_proposal_applied",
    ]

    pack_path, _ = await KnowledgePackService(
        db_with_project, project_id=PROJECT
    ).export_pack()
    with open(pack_path, "rb") as pack_file:
        imported = await KnowledgePackService(db_with_project).import_pack(
            pack_file,
            project_id="proj_evaluation_import",
            project_name="Imported Evaluation Contract",
        )
    assert imported.imported_counts["manuscript_evaluation_events"] == 3
    imported_events = await db_with_project.fetchall(
        """SELECT * FROM manuscript_evaluation_events
            WHERE project_id = 'proj_evaluation_import' ORDER BY created_at, id"""
    )
    assert [item["action"] for item in imported_events] == actions
    assert imported_events[0]["target_id"] != mission_result["mission"]["id"]
    assert await KnowledgePackService(
        db_with_project, project_id="proj_evaluation_import"
    ).check_integrity() == []
    assert await db_with_project.fetchall("PRAGMA foreign_key_check") == []
    project_service = ProjectService(db_with_project)
    counts = await project_service.get_project_entity_counts("proj_evaluation_import")
    assert counts["manuscript_evaluation_events"] == 3
    await project_service.delete_project("proj_evaluation_import", confirm=True)
    assert await db_with_project.fetchone(
        "SELECT id FROM manuscript_evaluation_events WHERE project_id = 'proj_evaluation_import'"
    ) is None

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db_with_project.execute(
            "UPDATE manuscript_evaluation_events SET reason = 'rewritten'"
        )


@pytest.mark.asyncio
async def test_adverse_outcomes_remain_visible_and_never_become_support(
    db_with_project,
) -> None:
    setup = await _canonical_setup(db_with_project)
    observation = await setup["experiments"].create_observation(
        ExperimentObservationCreate(
            run_id=setup["run"].id,
            name="bounded effect",
            kind="comparison",
            direction="negative",
            summary="The expected bounded effect was absent.",
            value_real=-0.2,
            unit="effect-size",
            observed_at="2026-08-15T12:00:00Z",
            recorded_by="executor",
        )
    )
    locator = await setup["experiments"].add_locator(
        EvidenceLocatorCreate(
            observation_id=observation.id,
            source_kind="artifact",
            artifact_id=setup["artifact_id"],
            locator_kind="json_pointer",
            locator_value="/primary/effect",
            created_by="executor",
        )
    )
    requirement = _evaluation_payload(setup, [{
        "observation_id": observation.id,
        "locator_ids": [locator.id],
        "role": "falsifier",
        "outcome": "fails_to_support",
        "claim_effect": "negative_result",
        "interpretation": "The claim is not supported in this frozen workload.",
    }])["commitments"][0]["requirements"][0]
    projected = await ManuscriptPlanningService(
        db_with_project, project_id=PROJECT
    )._project_evaluation_requirement(requirement)
    assert projected["verdict"] == "Needs review"
    assert projected["observations"][0]["binding"]["outcome"] == "fails_to_support"
    assert "negative result" in " ".join(projected["warnings"])
    with pytest.raises(ValueError, match="revise or replace the claim"):
        ManuscriptPlanningService._require_claim_aligned_result(
            projected["observations"]
        )


@pytest.mark.asyncio
async def test_spine_export_round_trip_preserves_relationships_roles_and_unit_metadata(
    db_with_project,
) -> None:
    evidence_ids = []
    for index in range(3):
        journal_id = generate_id("journal")
        claim_id = generate_id("claim")
        await db_with_project.execute(
            """INSERT INTO journal
               (id, type, content, source, confidence, project_id)
               VALUES (?, 'finding', ?, 'executor', 'tested', ?)""",
            [journal_id, f"Evidence {index}", PROJECT],
        )
        await db_with_project.execute(
            """INSERT INTO claims
               (id, source_entry_id, claim_type, content, confidence, verified,
                evidence_status, stale, project_id)
               VALUES (?, ?, 'result', ?, 0.9, 1, 'supported', 0, ?)""",
            [claim_id, journal_id, f"Evidence {index}", PROJECT],
        )
        evidence_ids.append(claim_id)
    await db_with_project.commit()
    manuscripts = NativeManuscriptService(db_with_project, project_id=PROJECT)
    manuscript = await manuscripts.create(
        ManuscriptCreate(title="Lossless spine round trip"), actor="pi"
    )
    first = await manuscripts.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine={
            "claims": [{
                "claim_id": "claim-primary",
                "claim_type": "methodological",
                "status": "active",
                "text": "The method enforces the bounded mechanism.",
                "allowed_wording": "The method enforces the bounded mechanism.",
                "prohibited_wording": ["The method is universally sufficient."],
                "evidence_ids": [evidence_ids[0]],
                "qualifier_ids": [evidence_ids[1]],
                "counterevidence_ids": [evidence_ids[2]],
                "unit_links": [{"unit_key": "method-primary", "relationship": "bounds"}],
            }],
            "units": [{
                "unit_id": "method-primary",
                "kind": "method",
                "location": "sections/method.tex#primary",
                "title": "Bounded mechanism",
                "sequence": 37,
                "status": "reviewed",
                "evidence_ids": [evidence_ids[0]],
                "qualifier_ids": [evidence_ids[1]],
                "counterevidence_ids": [evidence_ids[2]],
            }],
        },
        actor="pi",
    )
    exported = await manuscripts.export_spine_projection(manuscript.id)
    assert exported["claims"][0]["unit_links"] == [
        {"unit_key": "method-primary", "relationship": "bounds"}
    ]
    assert exported["units"][0]["title"] == "Bounded mechanism"
    assert exported["units"][0]["sequence"] == 37
    assert exported["units"][0]["qualifier_ids"] == [evidence_ids[1]]
    assert exported["units"][0]["counterevidence_ids"] == [evidence_ids[2]]
    second = await manuscripts.upsert_argument_spine(
        manuscript.id,
        expected_revision=first["manuscript"]["revision"],
        spine=exported,
        actor="pi",
    )
    claim = second["claims"][0]
    unit = second["units"][0]
    assert claim["unit_links"][0]["relationship"] == "bounds"
    assert unit["title"] == "Bounded mechanism"
    assert unit["sequence"] == 37
    assert {item["role"] for item in unit["evidence"]} == {
        "support", "qualifier", "counterevidence"
    }
