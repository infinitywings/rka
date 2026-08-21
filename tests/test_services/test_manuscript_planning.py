"""Planning-branch recovery, isolation, concurrency, and provenance tests."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from rka.infra.ids import generate_id
from rka.models.planning import (
    PlanningArtifactVersionAppend,
    PlanningBranchCreate,
    PlanningBranchTransition,
    PlanningContributionProposalPrepare,
    PlanningContributionRatification,
    PlanningResearchQuestionPromotion,
)
from rka.models.manuscript_native import ManuscriptCreate
from rka.models.semantic_patch import SemanticPatchProposalTransition
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.planning import (
    ManuscriptPlanningService,
    PlanningConflictError,
    PlanningNotFoundError,
)
from rka.services.semantic_patch import SemanticPatchService


def _seed_version(
    *,
    branch_revision: int,
    insight: str,
    expected_previous_version: int = 0,
    lifecycle: str = "candidate",
    bindings: list[dict] | None = None,
) -> PlanningArtifactVersionAppend:
    return PlanningArtifactVersionAppend(
        expected_branch_revision=branch_revision,
        expected_previous_version=expected_previous_version,
        local_key="core-insight",
        stage_type="seed",
        lifecycle=lifecycle,
        summary=insight,
        payload={"insight": insight, "significance": "It changes the design trade-off."},
        origin="user_revised" if expected_previous_version else "user",
        unresolved_items=["Validate the boundary condition."],
        readiness_state="in_progress",
        readiness_missing=["Boundary evidence"],
        created_by="pi",
        reason="Preserve the current framing with exact provenance.",
        evidence_bindings=bindings or [],
    )


async def _journal(db, project_id: str, content: str = "Observed bounded effect.") -> str:
    journal_id = generate_id("journal")
    await db.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, status, project_id)
           VALUES (?, 'log', ?, 'executor', 'tested', 'high', 'active', ?)""",
        [journal_id, content, project_id],
    )
    await db.commit()
    return journal_id


@pytest.mark.asyncio
async def test_project_only_versions_resume_and_immutable_provenance(db_with_project) -> None:
    journal_id = await _journal(db_with_project, "proj_default")
    service = ManuscriptPlanningService(db_with_project, project_id="proj_default")
    created = await service.create_branch(
        PlanningBranchCreate(
            name="primary",
            purpose="Develop the paper argument before a manuscript exists.",
            created_by="pi",
            reason="Start a recoverable project-level exploration.",
        )
    )
    branch_id = created["branch"]["id"]
    assert created["branch"]["state"] == "selected"
    assert created["branch"]["manuscript_id"] is None

    updated = await service.append_artifact_version(
        branch_id,
        _seed_version(
            branch_revision=1,
            insight="Timing can be treated as a composable security primitive.",
            bindings=[
                {
                    "entity_type": "journal",
                    "entity_id": journal_id,
                    "role": "support",
                    "locator_kind": "quote",
                    "locator_value": "Observed bounded effect.",
                    "ordinal": 0,
                }
            ],
        ),
    )
    artifact = updated["effective_artifacts"][0]
    assert updated["branch"]["revision"] == 2
    assert artifact["version"]["version"] == 1
    assert artifact["version"]["created_by"] == "pi"
    assert artifact["version"]["evidence_bindings"][0]["entity_id"] == journal_id

    restarted = ManuscriptPlanningService(db_with_project, project_id="proj_default")
    resumed = await restarted.resume()
    assert resumed is not None
    assert resumed["branch"]["id"] == branch_id
    assert resumed["effective_artifacts"][0]["version"]["id"] == artifact["version"]["id"]

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db_with_project.execute(
            """UPDATE manuscript_planning_artifact_versions
               SET summary = 'rewritten' WHERE id = ?""",
            [artifact["version"]["id"]],
        )
    with pytest.raises(PlanningConflictError, match="branch revision"):
        await service.append_artifact_version(
            branch_id,
            _seed_version(branch_revision=1, insight="Stale write."),
        )


@pytest.mark.asyncio
async def test_fork_is_revision_pinned_and_compare_select_archive(db_with_project) -> None:
    service = ManuscriptPlanningService(db_with_project, project_id="proj_default")
    primary = await service.create_branch(
        PlanningBranchCreate(
            name="primary",
            purpose="Primary framing.",
            created_by="pi",
            reason="Create primary framing.",
        )
    )
    primary_id = primary["branch"]["id"]
    primary = await service.append_artifact_version(
        primary_id,
        _seed_version(branch_revision=1, insight="Original insight."),
    )

    alternative = await service.create_branch(
        PlanningBranchCreate(
            name="mechanism-first",
            purpose="Test a mechanism-first framing.",
            parent_branch_id=primary_id,
            created_by="pi",
            reason="Preserve an alternative framing.",
        )
    )
    alternative_id = alternative["branch"]["id"]
    assert alternative["branch"]["parent_branch_revision"] == 2
    assert alternative["effective_artifacts"][0]["is_inherited"] is True

    # Parent evolution after the fork must not alter the child snapshot.
    primary = await service.append_artifact_version(
        primary_id,
        _seed_version(
            branch_revision=2,
            expected_previous_version=1,
            insight="Parent changed after fork.",
        ),
    )
    unchanged_child = await service.get_branch(alternative_id)
    assert unchanged_child["effective_artifacts"][0]["version"]["summary"] == "Original insight."

    alternative = await service.append_artifact_version(
        alternative_id,
        _seed_version(branch_revision=1, insight="Mechanism-first insight."),
    )
    comparison = await service.compare_branches(primary_id, alternative_id)
    assert comparison["summary"] == {
        "added": 0,
        "removed": 0,
        "changed": 1,
        "unchanged": 0,
    }

    alternative = await service.transition_branch(
        alternative_id,
        PlanningBranchTransition(
            expected_revision=2,
            target_state="selected",
            actor="pi",
            reason="Select the clearer mechanism-first framing.",
        ),
    )
    assert alternative["branch"]["state"] == "selected"
    primary = await service.get_branch(primary_id)
    assert primary["branch"]["state"] == "active"
    assert primary["branch"]["revision"] == 4

    archived = await service.transition_branch(
        primary_id,
        PlanningBranchTransition(
            expected_revision=4,
            target_state="archived",
            actor="pi",
            reason="Keep the alternative recoverable but out of the active set.",
        ),
    )
    assert archived["branch"]["state"] == "archived"
    assert (await service.resume())["branch"]["id"] == alternative_id

    with pytest.raises(ValueError, match="select another branch"):
        await service.transition_branch(
            alternative_id,
            PlanningBranchTransition(
                expected_revision=3,
                target_state="archived",
                actor="pi",
                reason="This must be rejected while selected.",
            ),
        )


@pytest.mark.asyncio
async def test_parking_is_a_recoverable_version_and_scope_is_enforced(db_with_project) -> None:
    await db_with_project.execute(
        "INSERT INTO projects (id, name) VALUES ('proj_planning_other', 'Other')"
    )
    await db_with_project.execute(
        """INSERT INTO project_states (project_id, project_name)
           VALUES ('proj_planning_other', 'Other')"""
    )
    await db_with_project.commit()
    foreign_journal = await _journal(db_with_project, "proj_planning_other", "Foreign.")

    service = ManuscriptPlanningService(db_with_project, project_id="proj_default")
    branch = await service.create_branch(
        PlanningBranchCreate(
            name="parking",
            purpose="Exercise the non-destructive parking lot.",
            created_by="brain",
            reason="Start planning.",
        )
    )
    branch_id = branch["branch"]["id"]
    branch = await service.append_artifact_version(
        branch_id,
        _seed_version(branch_revision=1, insight="Candidate insight."),
    )
    artifact_id = branch["effective_artifacts"][0]["id"]
    branch = await service.append_artifact_version(
        branch_id,
        _seed_version(
            branch_revision=2,
            expected_previous_version=1,
            insight="Candidate insight.",
            lifecycle="parked",
        ),
    )
    assert [item["id"] for item in branch["parking_lot"]] == [artifact_id]
    versions = await service.list_artifact_versions(artifact_id)
    assert [item["lifecycle"] for item in versions] == ["candidate", "parked"]

    foreign = ManuscriptPlanningService(db_with_project, project_id="proj_planning_other")
    with pytest.raises(PlanningNotFoundError):
        await foreign.get_branch(branch_id)
    with pytest.raises(ValueError, match="not available in this project"):
        await service.append_artifact_version(
            branch_id,
            PlanningArtifactVersionAppend(
                expected_branch_revision=3,
                expected_previous_version=2,
                local_key="core-insight",
                stage_type="seed",
                summary="Invalid cross-project binding.",
                payload={"insight": "Invalid cross-project binding."},
                origin="user_revised",
                created_by="pi",
                reason="Exercise isolation.",
                evidence_bindings=[
                    {
                        "entity_type": "journal",
                        "entity_id": foreign_journal,
                        "role": "support",
                    }
                ],
            ),
        )


def test_stage_payloads_are_closed_and_ai_provenance_is_required() -> None:
    with pytest.raises(ValidationError, match="gap"):
        PlanningArtifactVersionAppend(
            expected_branch_revision=1,
            local_key="gap",
            stage_type="landscape_gap",
            summary="Missing required gap.",
            payload={"state_of_the_art": ["Prior work."]},
            origin="user",
            created_by="pi",
            reason="Reject unconstrained payloads.",
        )
    with pytest.raises(ValidationError, match="provider, model, and context_hash"):
        PlanningArtifactVersionAppend(
            expected_branch_revision=1,
            local_key="seed",
            stage_type="seed",
            summary="AI proposal.",
            payload={"insight": "AI proposal."},
            origin="ai_suggested",
            created_by="llm",
            reason="Require reproducible AI provenance.",
        )


def test_rq_contribution_payload_requires_stable_bound_candidates() -> None:
    claim_id = "clm_01BOUND"
    decision_id = "dec_01RQ"
    parsed = PlanningArtifactVersionAppend(
        expected_branch_revision=1,
        local_key="portfolio",
        stage_type="rq_contribution",
        lifecycle="selected",
        summary="One bounded RQ and contribution.",
        payload={
            "research_questions": [{
                "local_key": "rq-composability",
                "question": "When do timing primitives compose?",
                "scope": "Two-agent workflows under bounded jitter.",
                "rationale": "Composition is the central scientific uncertainty.",
                "evidence_entity_ids": [claim_id],
                "disposition": "selected",
            }],
            "contributions": [{
                "local_key": "contribution-composition",
                "exact_wording": "We characterize bounded timing composition.",
                "contribution_type": "theoretical",
                "research_question_refs": ["rq-composability", decision_id],
                "allowed_wording": "Characterizes the tested composition boundary.",
                "prohibited_wording": ["Universal composition guarantee."],
                "support_ids": [claim_id],
                "disposition": "selected",
            }],
        },
        origin="user",
        readiness_state="ready",
        created_by="pi",
        reason="Capture an exact candidate portfolio.",
        evidence_bindings=[
            {"entity_type": "claim", "entity_id": claim_id, "role": "support"},
            {"entity_type": "decision", "entity_id": decision_id, "role": "context"},
        ],
    )
    assert parsed.payload["research_questions"][0]["local_key"] == "rq-composability"

    with pytest.raises(ValidationError, match="absent from evidence bindings"):
        PlanningArtifactVersionAppend.model_validate(
            parsed.model_dump(exclude={"evidence_bindings"})
        )


@pytest.mark.asyncio
async def test_argument_workflow_is_deterministic_and_pins_upstream_heads(
    db_with_project,
) -> None:
    service = ManuscriptPlanningService(db_with_project, project_id="proj_default")
    branch = await service.create_branch(
        PlanningBranchCreate(
            name="guided",
            purpose="Exercise deterministic argument guidance.",
            created_by="pi",
            reason="Start a guided branch.",
        )
    )
    branch_id = branch["branch"]["id"]
    branch = await service.append_artifact_version(
        branch_id,
        PlanningArtifactVersionAppend(
            expected_branch_revision=1,
            local_key="core-insight",
            stage_type="seed",
            lifecycle="selected",
            summary="Timing is composable.",
            payload={"insight": "Treat timing as a composable primitive."},
            origin="user",
            readiness_state="ready",
            created_by="pi",
            reason="Select the seed.",
        ),
    )
    seed = branch["effective_artifacts"][0]
    branch = await service.append_artifact_version(
        branch_id,
        PlanningArtifactVersionAppend(
            expected_branch_revision=2,
            local_key="quick-reader",
            stage_type="paragraph_spine",
            lifecycle="selected",
            summary="A bounded quick-reader spine.",
            payload={
                "problem": "Timing defenses are difficult to compose.",
                "gap": "Existing analyses isolate one timing mechanism.",
                "insight": "Treat timing as a composable primitive.",
                "response": "Model and combine bounded timing transformations.",
                "payoff": "Readers can reason about end-to-end timing defenses.",
                "upstream_versions": [{
                    "stage_type": "seed",
                    "local_key": seed["local_key"],
                    "artifact_id": seed["id"],
                    "version_id": seed["version"]["id"],
                    "version": seed["version"]["version"],
                }],
            },
            origin="user",
            readiness_state="ready",
            created_by="pi",
            reason="Select the paragraph spine.",
        ),
    )

    workflow = await service.argument_workflow(branch_id)
    stages = {item["stage_type"]: item for item in workflow["stages"]}
    assert stages["seed"]["verdict"] == "Ready"
    assert stages["paragraph_spine"]["verdict"] == "Ready"
    assert stages["problem_scope"]["verdict"] == "Blocked"
    assert workflow["next_recommended_stage"] == "problem_scope"
    assert [slot["slot"] for slot in workflow["quick_reader"]["slots"]] == [
        "problem",
        "gap",
        "insight",
        "response",
        "reader_payoff",
    ]
    assert workflow["authority"]["llm_at_view_time"] is False


@pytest.mark.asyncio
async def test_selected_candidates_promote_through_auditable_guarded_lineage(
    db_with_project,
) -> None:
    journal_id = await _journal(db_with_project, "proj_default")
    claim_id = generate_id("claim")
    await db_with_project.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, confidence, verified,
            evidence_status, stale, project_id)
           VALUES (?, ?, 'result', 'Composition held under bounded jitter.',
                   0.9, 1, 'supported', 0, 'proj_default')""",
        [claim_id, journal_id],
    )
    await db_with_project.commit()

    manuscripts = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await manuscripts.create(
        ManuscriptCreate(title="Promotion contract"), actor="pi"
    )
    planning = ManuscriptPlanningService(db_with_project, project_id="proj_default")
    branch = await planning.create_branch(
        PlanningBranchCreate(
            manuscript_id=manuscript.id,
            name="selected",
            purpose="Exercise independent RQ and contribution promotion.",
            created_by="pi",
            reason="Create a selected manuscript planning branch.",
        )
    )
    branch_id = branch["branch"]["id"]
    branch = await planning.append_artifact_version(
        branch_id,
        PlanningArtifactVersionAppend(
            expected_branch_revision=1,
            local_key="rq-contribution-portfolio",
            stage_type="rq_contribution",
            lifecycle="selected",
            summary="One bounded RQ and one evidence-backed contribution.",
            payload={
                "research_questions": [{
                    "local_key": "rq-composition",
                    "question": "When do bounded timing primitives compose?",
                    "scope": "Two-stage workflows under bounded jitter.",
                    "rationale": "Composition is the central uncertainty.",
                    "evidence_entity_ids": [claim_id],
                    "disposition": "selected",
                }],
                "contributions": [{
                    "local_key": "contribution-composition",
                    "exact_wording": "We characterize bounded timing composition.",
                    "contribution_type": "theoretical",
                    "research_question_refs": ["rq-composition"],
                    "allowed_wording": "Characterizes the evaluated composition boundary.",
                    "prohibited_wording": ["Guarantees universal timing composition."],
                    "support_ids": [claim_id],
                    "disposition": "selected",
                }],
            },
            origin="user",
            readiness_state="ready",
            created_by="pi",
            reason="Select exact candidates before promotion.",
            evidence_bindings=[
                {"entity_type": "claim", "entity_id": claim_id, "role": "support"}
            ],
        ),
    )
    artifact = branch["effective_artifacts"][0]

    promoted = await planning.promote_research_question(
        branch_id,
        PlanningResearchQuestionPromotion(
            expected_branch_revision=2,
            artifact_id=artifact["id"],
            expected_artifact_version=1,
            candidate_key="rq-composition",
            phase="paper_framing",
            reason="PI selected the bounded question.",
        ),
    )
    assert promoted["decision"]["kind"] == "research_question"
    assert promoted["promotion_event"]["action"] == "rq_promoted"
    with pytest.raises(PlanningConflictError, match="already has"):
        await planning.promote_research_question(
            branch_id,
            PlanningResearchQuestionPromotion(
                expected_branch_revision=2,
                artifact_id=artifact["id"],
                expected_artifact_version=1,
                candidate_key="rq-composition",
                phase="paper_framing",
                reason="Duplicate promotion must fail.",
            ),
        )

    prepared = await planning.prepare_contribution_proposal(
        branch_id,
        PlanningContributionProposalPrepare(
            expected_branch_revision=2,
            artifact_id=artifact["id"],
            expected_artifact_version=1,
            candidate_key="contribution-composition",
            manuscript_id=manuscript.id,
            expected_manuscript_revision=1,
            reason="Prepare exact contribution wording for review.",
            actor="pi",
        ),
    )
    proposal_id = prepared["proposal"]["id"]
    assert prepared["proposal"]["status"] == "proposed"
    assert (await manuscripts.get_context(manuscript.id))["claims"] == []

    await SemanticPatchService(
        db_with_project, project_id="proj_default"
    ).apply_proposal(
        proposal_id,
        SemanticPatchProposalTransition(
            expected_revision=1,
            actor="pi",
            reason="Apply after inspecting the semantic diff.",
        ),
    )
    context = await manuscripts.get_context(manuscript.id)
    assert context["manuscript"]["revision"] == 2
    assert context["claims"][0]["exact_wording"] == (
        "We characterize bounded timing composition."
    )
    claim = context["claims"][0]

    decision_id = generate_id("decision")
    await db_with_project.execute(
        """INSERT INTO decisions
           (id, phase, question, chosen, rationale, decided_by, status, project_id)
           VALUES (?, 'paper_writing', 'Ratify contribution wording?', ?,
                   'PI selected the exact wording.', 'pi', 'active', 'proj_default')""",
        [decision_id, claim["exact_wording"]],
    )
    await db_with_project.commit()
    ratified = await planning.ratify_contribution(
        branch_id,
        PlanningContributionRatification(
            expected_branch_revision=2,
            artifact_id=artifact["id"],
            expected_artifact_version=1,
            candidate_key="contribution-composition",
            manuscript_id=manuscript.id,
            claim_ref="contribution-composition",
            expected_manuscript_revision=2,
            proposal_id=proposal_id,
            decision_id=decision_id,
            reason="PI ratified the exact applied contribution wording.",
        ),
    )
    assert ratified["promotion_event"]["action"] == "contribution_ratified"
    events = await planning.list_promotion_events(branch_id)
    assert [event["action"] for event in events] == [
        "rq_promoted",
        "contribution_proposal_prepared",
        "contribution_proposal_applied",
        "contribution_ratified",
    ]
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db_with_project.execute(
            "UPDATE manuscript_planning_promotion_events SET reason = 'rewrite' WHERE id = ?",
            [events[-1]["id"]],
        )
