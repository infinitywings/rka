"""Progressive outline hierarchy, bindings, proposals, and checkpoint tests."""

from __future__ import annotations

import pytest

from rka.infra.ids import generate_id
from rka.models.manuscript_native import (
    ManuscriptCheckpointCreate,
    ManuscriptCheckpointResolve,
    ManuscriptCreate,
)
from rka.models.outline import OutlineProposalRequest
from rka.models.semantic_patch import SemanticPatchProposalTransition
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.outline import ManuscriptOutlineService
from rka.services.semantic_patch import SemanticPatchService


async def _evidence_claim(db) -> str:
    journal_id = generate_id("journal")
    claim_id = generate_id("claim")
    await db.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, status, project_id)
           VALUES (?, 'log', 'Observed bounded behavior.', 'executor',
                   'tested', 'high', 'active', 'proj_default')""",
        [journal_id],
    )
    await db.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, confidence, verified,
            evidence_status, stale, project_id)
           VALUES (?, ?, 'result', 'Bounded behavior was observed.', 0.9, 1,
                   'supported', 0, 'proj_default')""",
        [claim_id, journal_id],
    )
    await db.commit()
    return claim_id


def _spine(evidence_id: str) -> dict:
    return {
        "claims": [{
            "claim_id": "C1",
            "claim_type": "empirical",
            "status": "active",
            "text": "The mechanism produced the bounded effect.",
            "allowed_wording": "The mechanism produced the bounded effect.",
            "prohibited_wording": ["The mechanism always works."],
            "evidence_ids": [evidence_id],
            "unit_links": [
                {"unit_key": "INTRO", "relationship": "advances"},
                {"unit_key": "METHOD", "relationship": "advances"},
            ],
        }],
        "units": [
            {
                "unit_id": "INTRO",
                "kind": "introduction",
                "location": "sections/introduction.tex",
                "title": "Frame the bounded problem",
                "sequence": 0,
                "outline_level": 2,
                "communicative_job": "Establish the problem and paper promise.",
                "intended_takeaway": "The bounded problem matters and is unresolved.",
                "evidence_plan": ["Ground the problem in the measured project claim."],
                "evidence_ids": [evidence_id],
            },
            {
                "unit_id": "METHOD",
                "kind": "method",
                "location": "sections/method.tex",
                "title": "Explain the mechanism",
                "sequence": 10,
                "outline_level": 2,
                "communicative_job": "Explain how the response fills the gap.",
                "intended_takeaway": "The mechanism directly addresses the gap.",
                "evidence_plan": ["Connect the design to the bounded claim."],
                "evidence_ids": [evidence_id],
            },
        ],
    }


async def _seed_outline(db):
    evidence_id = await _evidence_claim(db)
    native = NativeManuscriptService(db, project_id="proj_default")
    manuscript = await native.create(ManuscriptCreate(title="Outline test"), actor="pi")
    await native.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine=_spine(evidence_id),
        actor="pi",
    )
    return manuscript.id, evidence_id


@pytest.mark.asyncio
async def test_outline_projection_joins_rationale_claims_and_evidence(db_with_project) -> None:
    manuscript_id, evidence_id = await _seed_outline(db_with_project)
    outline = await ManuscriptOutlineService(
        db_with_project, project_id="proj_default"
    ).get_outline(manuscript_id)

    assert outline["summary"] == {
        "active_units": 2,
        "complete_units": 2,
        "units_needing_review": 0,
        "levels": [2],
        "checkpoint_ready": True,
    }
    assert outline["units"][0]["claims"][0]["claim_key"] == "C1"
    assert outline["units"][0]["evidence"][0]["evidence_claim_id"] == evidence_id
    assert outline["units"][0]["completeness"] == "complete"


@pytest.mark.asyncio
async def test_expand_is_proposal_first_and_inherits_typed_bindings(db_with_project) -> None:
    manuscript_id, evidence_id = await _seed_outline(db_with_project)
    outlines = ManuscriptOutlineService(db_with_project, project_id="proj_default")
    patches = SemanticPatchService(db_with_project, project_id="proj_default")

    prepared = await outlines.prepare_proposal(
        manuscript_id,
        OutlineProposalRequest(
            expected_revision=2,
            action="expand",
            unit_key="INTRO",
            reason="Split the framing into quick-reader units.",
            children=[
                {
                    "local_key": "INTRO.PROBLEM",
                    "title": "State the concrete problem",
                    "location": "sections/introduction.tex#problem",
                    "communicative_job": "State the scoped problem.",
                    "intended_takeaway": "The exact problem is concrete.",
                    "evidence_plan": ["Use the bounded observation."],
                },
                {
                    "local_key": "INTRO.PROMISE",
                    "title": "State the paper promise",
                    "location": "sections/introduction.tex#promise",
                    "communicative_job": "State the response and promise.",
                    "intended_takeaway": "The paper offers a bounded response.",
                    "evidence_plan": ["Tie the promise to C1."],
                },
            ],
        ),
        actor="web_ui",
    )
    assert prepared["impact"]["canonical_mutation"] is False
    assert prepared["impact"]["parent_retained"] is True
    assert (await outlines.get_outline(manuscript_id))["summary"]["active_units"] == 2

    await patches.apply_proposal(
        prepared["proposal"]["id"],
        SemanticPatchProposalTransition(
            expected_revision=1,
            actor="web_ui",
            reason="Apply after reviewing the semantic diff.",
        ),
    )
    outline = await outlines.get_outline(manuscript_id)
    child = next(unit for unit in outline["units"] if unit["local_key"] == "INTRO.PROBLEM")
    assert child["parent_unit_key"] == "INTRO"
    assert child["outline_level"] == 3
    assert child["claims"][0]["claim_key"] == "C1"
    assert child["evidence"][0]["evidence_claim_id"] == evidence_id
    assert any(unit["local_key"] == "INTRO" for unit in outline["units"])


@pytest.mark.asyncio
async def test_condense_unions_bindings_and_removes_only_selected_descendants(
    db_with_project,
) -> None:
    manuscript_id, evidence_id = await _seed_outline(db_with_project)
    outlines = ManuscriptOutlineService(db_with_project, project_id="proj_default")
    patches = SemanticPatchService(db_with_project, project_id="proj_default")
    expanded = await outlines.prepare_proposal(
        manuscript_id,
        OutlineProposalRequest(
            expected_revision=2,
            action="expand",
            unit_key="INTRO",
            reason="Create one child.",
            children=[{
                "local_key": "INTRO.CHILD",
                "title": "Child",
                "location": "sections/introduction.tex#child",
                "communicative_job": "Carry one paragraph job.",
                "intended_takeaway": "The child preserves the parent promise.",
                "evidence_plan": ["Use C1 evidence."],
            }],
        ),
        actor="pi",
    )
    await patches.apply_proposal(
        expanded["proposal"]["id"],
        SemanticPatchProposalTransition(
            expected_revision=1, actor="pi", reason="Approve expansion."
        ),
    )
    condensed = await outlines.prepare_proposal(
        manuscript_id,
        OutlineProposalRequest(
            expected_revision=3,
            action="condense",
            unit_key="INTRO",
            descendant_keys=["INTRO.CHILD"],
            reason="Collapse the paragraph back into its parent.",
        ),
        actor="pi",
    )
    assert condensed["impact"]["bindings_unioned_to_parent"] is True
    assert any(
        finding["code"] == "OUTLINE_UNIT_REMOVED"
        for finding in condensed["proposal"]["validation_findings"]
    )
    await patches.apply_proposal(
        condensed["proposal"]["id"],
        SemanticPatchProposalTransition(
            expected_revision=1, actor="pi", reason="Approve condensation."
        ),
    )
    context = await NativeManuscriptService(
        db_with_project, project_id="proj_default"
    ).get_context(manuscript_id)
    parent = next(unit for unit in context["units"] if unit["local_key"] == "INTRO")
    child = next(unit for unit in context["units"] if unit["local_key"] == "INTRO.CHILD")
    assert child["status"] == "removed"
    assert parent["evidence"][0]["evidence_claim_id"] == evidence_id


@pytest.mark.asyncio
async def test_reorder_reports_changed_predecessors_without_losing_bindings(
    db_with_project,
) -> None:
    manuscript_id, _evidence_id = await _seed_outline(db_with_project)
    outlines = ManuscriptOutlineService(db_with_project, project_id="proj_default")
    prepared = await outlines.prepare_proposal(
        manuscript_id,
        OutlineProposalRequest(
            expected_revision=2,
            action="reorder",
            ordered_unit_keys=["METHOD", "INTRO"],
            reason="Lead with the mechanism for this audience.",
        ),
        actor="web_ui",
    )
    assert prepared["impact"]["changed_predecessors"] == ["METHOD", "INTRO"]
    assert "typed_evidence_bindings" in prepared["impact"]["preserved"]
    assert any(
        finding["code"] == "OUTLINE_ORDER_CHANGED"
        for finding in prepared["proposal"]["validation_findings"]
    )


@pytest.mark.asyncio
async def test_applied_outline_edit_supersedes_resolved_outline_checkpoint(
    db_with_project,
) -> None:
    manuscript_id, _evidence_id = await _seed_outline(db_with_project)
    native = NativeManuscriptService(db_with_project, project_id="proj_default")
    checkpoint = await native.create_checkpoint(
        ManuscriptCheckpointCreate(manuscript_id=manuscript_id, kind="outline"),
        expected_revision=2,
        actor="pi",
    )
    decision_id = generate_id("decision")
    await db_with_project.execute(
        """INSERT INTO decisions
           (id, phase, question, chosen, rationale, decided_by, status, project_id)
           VALUES (?, 'paper_writing', 'Approve outline?', 'approved',
                   'Reviewed exact outline.', 'pi', 'active', 'proj_default')""",
        [decision_id],
    )
    await db_with_project.commit()
    await native.resolve_checkpoint(
        checkpoint.id,
        ManuscriptCheckpointResolve(
            decision_id=decision_id,
            status="resolved",
            resolved_at="2026-08-15T12:00:00Z",
        ),
        expected_revision=3,
        actor="pi",
    )

    outlines = ManuscriptOutlineService(db_with_project, project_id="proj_default")
    prepared = await outlines.prepare_proposal(
        manuscript_id,
        OutlineProposalRequest(
            expected_revision=4,
            action="edit",
            unit_key="INTRO",
            reason="Clarify the quick-reader job.",
            patch={"quick_reader_role": "Make the promise visible on a fast scan."},
        ),
        actor="pi",
    )
    await SemanticPatchService(db_with_project, project_id="proj_default").apply_proposal(
        prepared["proposal"]["id"],
        SemanticPatchProposalTransition(
            expected_revision=1, actor="pi", reason="Approve the rationale edit."
        ),
    )
    outline = await outlines.get_outline(manuscript_id)
    assert outline["outline_checkpoint"]["status"] == "superseded"
    assert outline["summary"]["checkpoint_ready"] is True


@pytest.mark.asyncio
async def test_hierarchy_rejects_unknown_parent_and_cycles(db_with_project) -> None:
    manuscript_id, evidence_id = await _seed_outline(db_with_project)
    native = NativeManuscriptService(db_with_project, project_id="proj_default")
    invalid = _spine(evidence_id)
    invalid["units"][0]["parent_unit_key"] = "MISSING"
    with pytest.raises(ValueError, match="unknown parent"):
        await native.upsert_argument_spine(
            manuscript_id,
            expected_revision=2,
            spine=invalid,
            actor="pi",
        )
