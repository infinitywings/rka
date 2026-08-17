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
from rka.models.semantic_patch import (
    ContextManifestCreate,
    SemanticPatchProposalTransition,
)
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
        "claims": [
            {
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
            }
        ],
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


def _evidence_ids_by_role(unit: dict) -> dict[str, list[str]]:
    return {
        role: sorted(item["evidence_claim_id"] for item in unit["evidence"] if item["role"] == role)
        for role in ("support", "qualifier", "counterevidence")
    }


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
        "rationale_complete": True,
        "checkpoint_ready": True,
    }
    assert outline["units"][0]["claims"][0]["claim_key"] == "C1"
    assert outline["units"][0]["evidence"][0]["evidence_claim_id"] == evidence_id
    assert outline["units"][0]["completeness"] == "complete"


@pytest.mark.asyncio
async def test_academic_readiness_blocks_only_explicit_claim_bearing_units(
    db_with_project,
) -> None:
    manuscript_id, evidence_id = await _seed_outline(db_with_project)
    native = NativeManuscriptService(db_with_project, project_id="proj_default")
    outlines = ManuscriptOutlineService(db_with_project, project_id="proj_default")

    advisory = await outlines.get_outline(manuscript_id)
    dimensions = {
        item["name"]: item for item in advisory["academic_readiness"]["dimensions"]
    }
    assert advisory["academic_readiness"]["ready"] is True
    assert dimensions["claim_boundaries"]["verdict"] == "warn"
    assert dimensions["claim_boundaries"]["blocking"] is False
    assert dimensions["rhetorical_annotation"]["verdict"] == "warn"

    spine = _spine(evidence_id)
    spine["units"][0]["unit_role"] = "argument_block"
    spine["claims"][0]["unit_links"] = [
        {"unit_key": "METHOD", "relationship": "advances"}
    ]
    await native.upsert_argument_spine(
        manuscript_id,
        expected_revision=2,
        spine=spine,
        actor="pi",
    )
    blocked = await outlines.get_outline(manuscript_id)
    claim_dimension = next(
        item
        for item in blocked["academic_readiness"]["dimensions"]
        if item["name"] == "claim_allocation"
    )
    assert blocked["academic_readiness"]["ready"] is False
    assert claim_dimension["blocking"] is True
    assert claim_dimension["findings"][0]["unit_key"] == "INTRO"

    spine["units"][0]["unit_role"] = "section"
    await native.upsert_argument_spine(
        manuscript_id,
        expected_revision=3,
        spine=spine,
        actor="pi",
    )
    container = await outlines.get_outline(manuscript_id)
    assert container["academic_readiness"]["ready"] is True
    claim_dimension = next(
        item
        for item in container["academic_readiness"]["dimensions"]
        if item["name"] == "claim_allocation"
    )
    assert claim_dimension["verdict"] == "warn"
    assert claim_dimension["blocking"] is False


@pytest.mark.asyncio
async def test_outline_exposes_unallocated_claim_adverse_evidence_as_private_advisory(
    db_with_project,
) -> None:
    support_id = await _evidence_claim(db_with_project)
    qualifier_id = await _evidence_claim(db_with_project)
    counterevidence_id = await _evidence_claim(db_with_project)
    spine = _spine(support_id)
    spine["claims"][0]["qualifier_ids"] = [qualifier_id]
    spine["claims"][0]["counterevidence_ids"] = [counterevidence_id]

    native = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await native.create(ManuscriptCreate(title="Visible private cautions"))
    await native.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine=spine,
        actor="pi",
    )

    outline = await ManuscriptOutlineService(
        db_with_project, project_id="proj_default"
    ).get_outline(manuscript.id)
    claim = outline["units"][0]["claims"][0]
    assert {
        (item["role"], item["evidence_claim_id"])
        for item in claim["unallocated_adverse_evidence"]
    } == {
        ("qualifier", qualifier_id),
        ("counterevidence", counterevidence_id),
    }
    assert len(claim["evidence"]) == 3
    dimension = next(
        item
        for item in outline["academic_readiness"]["dimensions"]
        if item["name"] == "adverse_evidence_allocation"
    )
    assert dimension["verdict"] == "warn"
    assert dimension["blocking"] is False
    assert {
        (item["claim_key"], item["role"], item["evidence_claim_id"])
        for item in dimension["findings"]
    } == {
        ("C1", "qualifier", qualifier_id),
        ("C1", "counterevidence", counterevidence_id),
    }
    assert outline["academic_readiness"]["ready"] is True


@pytest.mark.parametrize("conflict_kind", ["evidence", "citation"])
def test_condense_rejects_colliding_typed_metadata(db_with_project, conflict_kind: str) -> None:
    parent = {
        "unit_id": "PARENT",
        "status": "active",
        "parent_unit_key": None,
        "evidence": {
            "support": [{
                "evidence_claim_id": "clm_shared",
                "supported_proposition": "Parent proposition.",
                "warrant": "Parent warrant.",
            }],
            "qualifier": [],
            "counterevidence": [],
        },
        "citations": [{
            "citation_key": "author2026",
            "citation_role": "baseline",
            "supported_proposition": "Prior baseline.",
            "verification_state": "verified",
            "comparison_axis": "latency",
        }],
    }
    child = {
        "unit_id": "CHILD",
        "status": "active",
        "parent_unit_key": "PARENT",
        "evidence": {
            "support": [dict(parent["evidence"]["support"][0])],
            "qualifier": [],
            "counterevidence": [],
        },
        "citations": [dict(parent["citations"][0])],
    }
    if conflict_kind == "evidence":
        child["evidence"]["support"][0]["warrant"] = "Conflicting child warrant."
    else:
        child["citations"][0]["comparison_axis"] = "throughput"

    service = ManuscriptOutlineService(db_with_project, project_id="proj_default")
    with pytest.raises(ValueError, match=f"condense {conflict_kind} conflict"):
        service._condense(
            [],
            [parent, child],
            OutlineProposalRequest(
                expected_revision=1,
                action="condense",
                unit_key="PARENT",
                descendant_keys=["CHILD"],
                reason="Test conflicting semantics.",
            ),
        )


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
async def test_expand_preserves_explicit_binding_narrowing(db_with_project) -> None:
    support_ids = [
        await _evidence_claim(db_with_project),
        await _evidence_claim(db_with_project),
    ]
    qualifier_id = await _evidence_claim(db_with_project)
    counterevidence_id = await _evidence_claim(db_with_project)
    spine = _spine(support_ids[0])
    for record in (spine["claims"][0], spine["units"][0]):
        record["evidence_ids"] = support_ids
        record["qualifier_ids"] = [qualifier_id]
        record["counterevidence_ids"] = [counterevidence_id]

    native = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await native.create(ManuscriptCreate(title="Narrowed expansion"))
    await native.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine=spine,
        actor="pi",
    )
    outlines = ManuscriptOutlineService(db_with_project, project_id="proj_default")
    patches = SemanticPatchService(db_with_project, project_id="proj_default")
    prepared = await outlines.prepare_proposal(
        manuscript.id,
        OutlineProposalRequest(
            expected_revision=2,
            action="expand",
            unit_key="INTRO",
            reason="Give each child only the evidence it actually uses.",
            children=[
                {
                    "local_key": "INTRO.NARROW",
                    "title": "Narrow child",
                    "location": "sections/introduction.tex#narrow",
                    "communicative_job": "Ground one bounded statement.",
                    "intended_takeaway": "Only one support record is needed.",
                    "evidence_plan": ["Use only the selected support record."],
                    "support_ids": [support_ids[0]],
                    "qualifier_ids": [],
                    "counterevidence_ids": [counterevidence_id],
                },
                {
                    "local_key": "INTRO.INHERIT",
                    "title": "Inherited child",
                    "location": "sections/introduction.tex#inherit",
                    "communicative_job": "Retain the full parent context.",
                    "intended_takeaway": "The full evidence context remains available.",
                    "evidence_plan": ["Review all inherited bindings."],
                },
            ],
        ),
        actor="web_ui",
    )
    narrowing_findings = [
        finding
        for finding in prepared["proposal"]["validation_findings"]
        if finding["code"] == "INHERITED_UNIT_EVIDENCE_NARROWED"
    ]
    assert {
        (finding["unit_key"], finding["parent_unit_key"], finding["role"]): finding["entity_ids"]
        for finding in narrowing_findings
    } == {
        ("INTRO.NARROW", "INTRO", "support"): [support_ids[1]],
        ("INTRO.NARROW", "INTRO", "qualifier"): [qualifier_id],
    }
    await patches.apply_proposal(
        prepared["proposal"]["id"],
        SemanticPatchProposalTransition(
            expected_revision=1,
            actor="web_ui",
            reason="The narrowed binding diff matches the intended child claims.",
        ),
    )

    context = await native.get_context(manuscript.id)
    narrowed = next(unit for unit in context["units"] if unit["local_key"] == "INTRO.NARROW")
    inherited = next(unit for unit in context["units"] if unit["local_key"] == "INTRO.INHERIT")
    assert _evidence_ids_by_role(narrowed) == {
        "support": [support_ids[0]],
        "qualifier": [],
        "counterevidence": [counterevidence_id],
    }
    assert _evidence_ids_by_role(inherited) == {
        "support": sorted(support_ids),
        "qualifier": [qualifier_id],
        "counterevidence": [counterevidence_id],
    }


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
            children=[
                {
                    "local_key": "INTRO.CHILD",
                    "title": "Child",
                    "location": "sections/introduction.tex#child",
                    "communicative_job": "Carry one paragraph job.",
                    "intended_takeaway": "The child preserves the parent promise.",
                    "evidence_plan": ["Use C1 evidence."],
                }
            ],
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
    context = await NativeManuscriptService(db_with_project, project_id="proj_default").get_context(
        manuscript_id
    )
    parent = next(unit for unit in context["units"] if unit["local_key"] == "INTRO")
    child = next(unit for unit in context["units"] if unit["local_key"] == "INTRO.CHILD")
    assert child["status"] == "removed"
    assert parent["evidence"][0]["evidence_claim_id"] == evidence_id


@pytest.mark.asyncio
async def test_condense_unions_distinct_child_evidence_into_parent(db_with_project) -> None:
    parent_evidence = await _evidence_claim(db_with_project)
    child_evidence = await _evidence_claim(db_with_project)
    native = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await native.create(ManuscriptCreate(title="Distinct condensation"))
    spine = _spine(parent_evidence)
    spine["claims"][0]["evidence_ids"] = [parent_evidence, child_evidence]
    spine["units"][0]["evidence_ids"] = [parent_evidence, child_evidence]
    await native.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine=spine,
        actor="pi",
    )
    outlines = ManuscriptOutlineService(db_with_project, project_id="proj_default")
    patches = SemanticPatchService(db_with_project, project_id="proj_default")
    expanded = await outlines.prepare_proposal(
        manuscript.id,
        OutlineProposalRequest(
            expected_revision=2,
            action="expand",
            unit_key="INTRO",
            reason="Create a child with one distinct evidence binding.",
            children=[
                {
                    "local_key": "INTRO.CHILD",
                    "title": "Child",
                    "location": "sections/introduction.tex#child",
                    "communicative_job": "Carry the second evidence-backed beat.",
                    "intended_takeaway": "The child uses distinct evidence.",
                    "evidence_plan": ["Use the second support record."],
                    "support_ids": [child_evidence],
                }
            ],
        ),
        actor="pi",
    )
    await patches.apply_proposal(
        expanded["proposal"]["id"],
        SemanticPatchProposalTransition(
            expected_revision=1,
            actor="pi",
            reason="Approve the child and its narrowed binding.",
        ),
    )

    separated = await native.export_spine_projection(manuscript.id)
    parent = next(unit for unit in separated["units"] if unit["unit_id"] == "INTRO")
    parent["evidence_ids"] = [parent_evidence]
    await native.upsert_argument_spine(
        manuscript.id,
        expected_revision=3,
        spine={"claims": separated["claims"], "units": separated["units"]},
        actor="pi",
    )
    condensed = await outlines.prepare_proposal(
        manuscript.id,
        OutlineProposalRequest(
            expected_revision=4,
            action="condense",
            unit_key="INTRO",
            descendant_keys=["INTRO.CHILD"],
            reason="Collapse the child while retaining its distinct evidence.",
        ),
        actor="pi",
    )
    await patches.apply_proposal(
        condensed["proposal"]["id"],
        SemanticPatchProposalTransition(
            expected_revision=1,
            actor="pi",
            reason="The parent now visibly inherits the child's evidence.",
        ),
    )
    context = await native.get_context(manuscript.id)
    parent = next(unit for unit in context["units"] if unit["local_key"] == "INTRO")
    child = next(unit for unit in context["units"] if unit["local_key"] == "INTRO.CHILD")
    assert _evidence_ids_by_role(parent)["support"] == sorted([parent_evidence, child_evidence])
    assert child["status"] == "removed"


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

    await SemanticPatchService(db_with_project, project_id="proj_default").apply_proposal(
        prepared["proposal"]["id"],
        SemanticPatchProposalTransition(
            expected_revision=1,
            actor="web_ui",
            reason="Approve the reviewed order and predecessor changes.",
        ),
    )
    outline = await outlines.get_outline(manuscript_id)
    assert [unit["local_key"] for unit in outline["units"]] == ["METHOD", "INTRO"]
    assert [unit["sequence"] for unit in outline["units"]] == [0, 10]


@pytest.mark.asyncio
async def test_edit_does_not_create_spurious_sequence_changes(db_with_project) -> None:
    manuscript_id, _evidence_id = await _seed_outline(db_with_project)
    outlines = ManuscriptOutlineService(db_with_project, project_id="proj_default")
    prepared = await outlines.prepare_proposal(
        manuscript_id,
        OutlineProposalRequest(
            expected_revision=2,
            action="edit",
            unit_key="INTRO",
            reason="Clarify one rhetorical field without reordering the outline.",
            patch={"quick_reader_role": "Expose the bounded paper promise."},
        ),
        actor="pi",
    )
    sequence_changes = [
        change
        for change in prepared["proposal"]["semantic_diff"][0]["changes"]
        if change["path"].endswith("/sequence")
    ]
    assert sequence_changes == []


@pytest.mark.asyncio
async def test_reorder_rejects_parent_after_child_and_split_subtree(db_with_project) -> None:
    manuscript_id, _evidence_id = await _seed_outline(db_with_project)
    outlines = ManuscriptOutlineService(db_with_project, project_id="proj_default")
    patches = SemanticPatchService(db_with_project, project_id="proj_default")
    expanded = await outlines.prepare_proposal(
        manuscript_id,
        OutlineProposalRequest(
            expected_revision=2,
            action="expand",
            unit_key="INTRO",
            reason="Create one child for hierarchy-order checks.",
            children=[
                {
                    "local_key": "INTRO.CHILD",
                    "title": "Child",
                    "location": "sections/introduction.tex#child",
                    "communicative_job": "Carry one child beat.",
                    "intended_takeaway": "The child remains under its parent.",
                    "evidence_plan": ["Use the inherited support."],
                }
            ],
        ),
        actor="pi",
    )
    await patches.apply_proposal(
        expanded["proposal"]["id"],
        SemanticPatchProposalTransition(
            expected_revision=1,
            actor="pi",
            reason="Approve hierarchy setup.",
        ),
    )

    with pytest.raises(ValueError, match="before child"):
        await outlines.prepare_proposal(
            manuscript_id,
            OutlineProposalRequest(
                expected_revision=3,
                action="reorder",
                ordered_unit_keys=["INTRO.CHILD", "INTRO", "METHOD"],
                reason="Attempt an invalid child-first order.",
            ),
            actor="pi",
        )
    with pytest.raises(ValueError, match="contiguous"):
        await outlines.prepare_proposal(
            manuscript_id,
            OutlineProposalRequest(
                expected_revision=3,
                action="reorder",
                ordered_unit_keys=["INTRO", "METHOD", "INTRO.CHILD"],
                reason="Attempt to split the parent subtree.",
            ),
            actor="pi",
        )


@pytest.mark.asyncio
async def test_host_agent_outline_proposal_records_ai_provenance_and_waits_for_pi(
    db_with_project,
) -> None:
    manuscript_id, _evidence_id = await _seed_outline(db_with_project)
    patches = SemanticPatchService(db_with_project, project_id="proj_default")
    manifest = await patches.create_context_manifest(
        ContextManifestCreate(
            origin="host_agent",
            provider="openai",
            model="gpt-test",
            boundary="host_conversation",
            targets=[{"target_type": "manuscript", "target_id": manuscript_id}],
            constraints=["Preserve all typed evidence bindings."],
        )
    )
    outlines = ManuscriptOutlineService(db_with_project, project_id="proj_default")
    prepared = await outlines.prepare_proposal(
        manuscript_id,
        OutlineProposalRequest(
            expected_revision=2,
            action="edit",
            reason="AI-proposed clarification for PI review.",
            origin="host_agent",
            provider="openai",
            model="gpt-test",
            boundary="host_conversation",
            context_manifest_id=manifest["id"],
            unit_key="INTRO",
            patch={"quick_reader_role": "Surface the scoped problem immediately."},
        ),
        actor="executor",
    )
    proposal = prepared["proposal"]
    assert proposal["origin"] == "host_agent"
    assert proposal["created_by"] == "executor"
    assert proposal["context_manifest_id"] == manifest["id"]
    assert proposal["status"] == "proposed"
    assert (await outlines.get_outline(manuscript_id))["manuscript_revision"] == 2
    with pytest.raises(ValueError):
        SemanticPatchProposalTransition(
            expected_revision=1,
            actor="executor",
            reason="An AI author must not approve its own proposal.",
        )


@pytest.mark.asyncio
async def test_executor_cannot_mislabel_outline_proposal_as_human(db_with_project) -> None:
    manuscript_id, _evidence_id = await _seed_outline(db_with_project)
    with pytest.raises(ValueError, match="must declare their provider origin"):
        await ManuscriptOutlineService(db_with_project, project_id="proj_default").prepare_proposal(
            manuscript_id,
            OutlineProposalRequest(
                expected_revision=2,
                action="edit",
                unit_key="INTRO",
                reason="Attempt to omit AI provenance.",
                patch={"quick_reader_role": "Misattributed AI proposal."},
            ),
            actor="executor",
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
    assert outline["summary"]["rationale_complete"] is True
    assert outline["summary"]["checkpoint_ready"] is True


@pytest.mark.asyncio
async def test_outline_checkpoint_v2_tracks_typed_evidence_bindings(db_with_project) -> None:
    manuscript_id, evidence_id = await _seed_outline(db_with_project)
    replacement_evidence_id = await _evidence_claim(db_with_project)
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
           VALUES (?, 'paper_writing', 'Approve evidence-bound outline?', 'approved',
                   'Reviewed the exact unit and evidence map.', 'pi', 'active',
                   'proj_default')""",
        [decision_id],
    )
    await db_with_project.commit()
    resolved = await native.resolve_checkpoint(
        checkpoint.id,
        ManuscriptCheckpointResolve(
            decision_id=decision_id,
            status="resolved",
            resolved_at="2026-08-17T12:00:00Z",
        ),
        expected_revision=3,
        actor="pi",
    )
    assert resolved.dependency_snapshot["schema_version"] == "rka.checkpoint-dependencies/v2"

    spine = await native.export_spine_projection(manuscript_id)
    intro = next(unit for unit in spine["units"] if unit["unit_id"] == "INTRO")
    assert intro["evidence_ids"] == [evidence_id]
    # Both helper-created claim rows have identical semantic fields. Swapping
    # only the evidence identity must still invalidate an approved outline.
    intro["evidence_ids"] = [replacement_evidence_id]
    await native.upsert_argument_spine(
        manuscript_id,
        expected_revision=4,
        spine={"claims": spine["claims"], "units": spine["units"]},
        actor="pi",
    )
    outline = await ManuscriptOutlineService(
        db_with_project, project_id="proj_default"
    ).get_outline(manuscript_id)
    assert outline["outline_checkpoint"]["status"] == "superseded"
    assert outline["outline_checkpoint"]["dependency_current"] is False


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

    cyclic = _spine(evidence_id)
    cyclic["units"][0]["parent_unit_key"] = "METHOD"
    cyclic["units"][0]["outline_level"] = 3
    cyclic["units"][1]["parent_unit_key"] = "INTRO"
    cyclic["units"][1]["outline_level"] = 4
    with pytest.raises(ValueError, match="cycle"):
        await native.upsert_argument_spine(
            manuscript_id,
            expected_revision=2,
            spine=cyclic,
            actor="pi",
        )
