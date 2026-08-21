"""Unified human/AI proposal, apply, and conflict contracts."""

from __future__ import annotations

import pytest

from rka.config import RKAConfig
from rka.infra.ids import generate_id
from rka.models.manuscript_native import ManuscriptCreate, ManuscriptUpdate
from rka.models.planning import PlanningBranchCreate
from rka.models.semantic_patch import (
    ContextManifestCreate,
    GeneratedProposalDraft,
    LMStudioProposalRequest,
    SemanticPatchProposalCreate,
    SemanticPatchProposalTransition,
)
from rka.services.lm_studio_proposals import (
    LMStudioProposalAdapter,
    _local_base_url,
)
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.planning import ManuscriptPlanningService
from rka.services.semantic_patch import (
    SemanticPatchConflictError,
    SemanticPatchService,
)


def _metadata_proposal(manuscript_id: str, revision: int, title: str):
    return SemanticPatchProposalCreate(
        origin="human",
        intent="Improve the working title.",
        reason="Make the framing easier to scan.",
        created_by="pi",
        operations=[{
            "operation": "manuscript_metadata_update",
            "manuscript_id": manuscript_id,
            "expected_revision": revision,
            "title": title,
        }],
    )


async def _seed_evidence_claim(db) -> str:
    journal_id = generate_id("journal")
    claim_id = generate_id("claim")
    await db.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, status, project_id)
           VALUES (?, 'log', 'Measured lower latency.', 'executor',
                   'tested', 'high', 'active', 'proj_default')""",
        [journal_id],
    )
    await db.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, confidence, verified,
            evidence_status, stale, project_id)
           VALUES (?, ?, 'result', 'Latency was lower.', 0.9, 1,
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
            "text": "Latency was lower in the evaluated testbed.",
            "allowed_wording": "Latency was lower in the evaluated testbed.",
            "prohibited_wording": ["Latency is always lower."],
            "evidence_ids": [evidence_id],
            "qualifier_ids": [],
            "counterevidence_ids": [],
            "unit_links": [{"unit_key": "R1", "relationship": "tests"}],
        }],
        "units": [{
            "unit_id": "R1",
            "kind": "result",
            "location": "sections/results.tex#latency",
            "artifact_ref": "artifacts/latency.csv",
            "allowed_interpretation": "Latency was lower in the tested setting.",
            "prohibited_interpretation": "Latency is lower in every setting.",
            "evidence_ids": [evidence_id],
        }],
    }


@pytest.mark.asyncio
async def test_human_proposal_does_not_mutate_until_explicit_apply(db_with_project) -> None:
    manuscripts = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await manuscripts.create(ManuscriptCreate(title="Before"), actor="pi")
    patches = SemanticPatchService(db_with_project, project_id="proj_default")

    proposal = await patches.create_proposal(
        _metadata_proposal(manuscript.id, 1, "  After  ")
    )
    assert proposal["status"] == "proposed"
    assert proposal["semantic_diff"][0]["changes"] == [{
        "path": "/title", "change": "changed", "before": "Before", "after": "After"
    }]
    assert (await manuscripts.get(manuscript.id)).title == "Before"

    applied = await patches.apply_proposal(
        proposal["id"],
        SemanticPatchProposalTransition(
            expected_revision=1,
            actor="pi",
            reason="Approve after preview.",
        ),
    )
    current = await manuscripts.get(manuscript.id)
    assert applied["status"] == "applied"
    assert applied["revision"] == 2
    assert [event["action"] for event in applied["events"]] == ["proposed", "applied"]
    assert current.title == "After"
    assert current.revision == 2

    with pytest.raises(ValueError, match="no semantic changes"):
        await patches.create_proposal(_metadata_proposal(manuscript.id, 2, "After"))


@pytest.mark.asyncio
async def test_stale_apply_preserves_conflict_and_newer_canonical_value(db_with_project) -> None:
    manuscripts = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await manuscripts.create(ManuscriptCreate(title="Base"), actor="pi")
    patches = SemanticPatchService(db_with_project, project_id="proj_default")
    proposal = await patches.create_proposal(_metadata_proposal(manuscript.id, 1, "Proposal"))

    await manuscripts.update(
        manuscript.id,
        ManuscriptUpdate(expected_revision=1, title="Newer direct edit"),
        actor="pi",
    )
    with pytest.raises(SemanticPatchConflictError, match="both versions were preserved"):
        await patches.apply_proposal(
            proposal["id"],
            SemanticPatchProposalTransition(
                expected_revision=1,
                actor="pi",
                reason="Attempt stale apply.",
            ),
        )

    conflicted = await patches.get_proposal(proposal["id"])
    assert conflicted["status"] == "conflicted"
    assert conflicted["events"][-1]["details"]["expected_bases"]
    assert conflicted["events"][-1]["details"]["current_bases"]
    assert (await manuscripts.get(manuscript.id)).title == "Newer direct edit"


@pytest.mark.asyncio
async def test_planning_edit_uses_same_proposal_and_apply_contract(db_with_project) -> None:
    planning = ManuscriptPlanningService(db_with_project, project_id="proj_default")
    branch = await planning.create_branch(
        PlanningBranchCreate(
            name="primary",
            purpose="Develop the paper framing.",
            created_by="pi",
            reason="Start planning.",
        )
    )
    branch_id = branch["branch"]["id"]
    patches = SemanticPatchService(db_with_project, project_id="proj_default")
    proposal = await patches.create_proposal(
        SemanticPatchProposalCreate(
            origin="human",
            intent="Capture the seed insight.",
            reason="Preserve the first framing.",
            created_by="pi",
            operations=[{
                "operation": "planning_artifact_upsert",
                "branch_id": branch_id,
                "append": {
                    "expected_branch_revision": 1,
                    "expected_previous_version": 0,
                    "local_key": "core-insight",
                    "stage_type": "seed",
                    "summary": "Timing can be a composable security primitive.",
                    "payload": {"insight": "Timing can be a composable security primitive."},
                    "origin": "user",
                    "created_by": "brain",
                    "reason": "Draft proposal only.",
                },
            }],
        )
    )
    assert (await planning.get_branch(branch_id))["effective_artifacts"] == []
    await patches.apply_proposal(
        proposal["id"],
        SemanticPatchProposalTransition(expected_revision=1, actor="pi", reason="Apply seed."),
    )
    context = await planning.get_branch(branch_id)
    assert context["branch"]["revision"] == 2
    version = context["effective_artifacts"][0]["version"]
    assert version["summary"].startswith("Timing")
    assert version["created_by"] == "brain"
    assert version["reason"] == "Draft proposal only."
    applied = await patches.get_proposal(proposal["id"])
    assert applied["events"][-1]["actor"] == "pi"
    assert applied["events"][-1]["reason"] == "Apply seed."


@pytest.mark.asyncio
async def test_argument_spine_proposal_has_keyed_diff_and_explicit_apply(
    db_with_project,
) -> None:
    evidence_id = await _seed_evidence_claim(db_with_project)
    manuscripts = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await manuscripts.create(ManuscriptCreate(title="Spine"), actor="pi")
    patches = SemanticPatchService(db_with_project, project_id="proj_default")

    proposal = await patches.create_proposal(
        SemanticPatchProposalCreate(
            origin="human",
            intent="Add the first bounded claim and result unit.",
            reason="Preview the evidence-backed spine before mutation.",
            created_by="pi",
            operations=[{
                "operation": "argument_spine_replace",
                "manuscript_id": manuscript.id,
                "expected_revision": 1,
                "spine": _spine(evidence_id),
            }],
        )
    )
    paths = {item["path"] for item in proposal["semantic_diff"][0]["changes"]}
    assert paths == {"/claims/C1", "/units/R1"}
    assert (await manuscripts.get_context(manuscript.id))["claims"] == []

    await patches.apply_proposal(
        proposal["id"],
        SemanticPatchProposalTransition(
            expected_revision=1,
            actor="pi",
            reason="Approve the inspected spine.",
        ),
    )
    context = await manuscripts.get_context(manuscript.id)
    assert context["manuscript"]["revision"] == 2
    assert context["claims"][0]["exact_wording"].startswith("Latency was lower")


@pytest.mark.asyncio
async def test_superseding_proposal_preserves_both_versions(db_with_project) -> None:
    manuscripts = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await manuscripts.create(ManuscriptCreate(title="Base"), actor="pi")
    patches = SemanticPatchService(db_with_project, project_id="proj_default")
    first = await patches.create_proposal(_metadata_proposal(manuscript.id, 1, "First"))

    replacement_data = _metadata_proposal(manuscript.id, 1, "Replacement").model_copy(
        update={"supersedes_proposal_id": first["id"]}
    )
    replacement = await patches.create_proposal(replacement_data)
    superseded = await patches.get_proposal(first["id"])

    assert replacement["status"] == "proposed"
    assert replacement["supersedes_proposal_id"] == first["id"]
    assert superseded["status"] == "superseded"
    assert superseded["events"][-1]["details"]["superseded_by"] == replacement["id"]
    assert (await manuscripts.get(manuscript.id)).title == "Base"


@pytest.mark.asyncio
async def test_ai_manifest_and_lm_studio_output_share_proposal_schema(
    db_with_project, monkeypatch
) -> None:
    manuscripts = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await manuscripts.create(ManuscriptCreate(title="Before"), actor="pi")
    patches = SemanticPatchService(db_with_project, project_id="proj_default")
    config = RKAConfig(
        llm_enabled=False,
        embeddings_enabled=False,
        workbench_lm_studio_model="local-model",
    )
    adapter = LMStudioProposalAdapter(patches, config)

    async def fake_request(**_kwargs):
        return GeneratedProposalDraft.model_validate({
            "intent": "Improve title.",
            "reason": "Use the selected manuscript context.",
            "operations": [{
                "operation": "manuscript_metadata_update",
                "manuscript_id": manuscript.id,
                "expected_revision": 1,
                "title": "Local suggestion",
            }],
        })

    monkeypatch.setattr(adapter, "_request_draft", fake_request)
    proposal = await adapter.generate(
        LMStudioProposalRequest(
            instruction="Suggest a clearer title.",
            created_by="pi",
            targets=[{"target_type": "manuscript", "target_id": manuscript.id}],
        )
    )
    assert proposal["origin"] == "lm_studio"
    assert proposal["status"] == "proposed"
    assert proposal["context_manifest"]["boundary"] == "local_loopback"
    assert (await manuscripts.get(manuscript.id)).title == "Before"
    rows = await db_with_project.fetchall(
        "SELECT event FROM semantic_patch_provider_events ORDER BY created_at, rowid"
    )
    assert [row["event"] for row in rows] == ["started", "succeeded"]


@pytest.mark.asyncio
async def test_host_agent_manifest_records_one_provider_call(db_with_project) -> None:
    manuscripts = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await manuscripts.create(ManuscriptCreate(title="Before"), actor="pi")
    patches = SemanticPatchService(db_with_project, project_id="proj_default")
    manifest = await patches.create_context_manifest(
        ContextManifestCreate(
            origin="host_agent",
            provider="  chatgpt  ",
            model="  host-model  ",
            boundary="host_conversation",
            targets=[{"target_type": "manuscript", "target_id": manuscript.id}],
        )
    )
    assert manifest["provider"] == "chatgpt"
    assert manifest["model"] == "host-model"
    assert [event["event"] for event in manifest["provider_events"]] == ["started"]

    proposal_data = SemanticPatchProposalCreate(
        origin="host_agent",
        intent="Improve title.",
        reason="Use the disclosed context.",
        created_by="brain",
        operations=[{
            "operation": "manuscript_metadata_update",
            "manuscript_id": manuscript.id,
            "expected_revision": 1,
            "title": "Host suggestion",
        }],
        provider="chatgpt",
        model="host-model",
        boundary="host_conversation",
        context_manifest_id=manifest["id"],
    )
    proposal = await patches.create_proposal(proposal_data)
    events = proposal["context_manifest"]["provider_events"]
    assert [event["event"] for event in events] == ["started", "succeeded"]
    assert events[0]["call_id"] == events[1]["call_id"]
    assert events[1]["details"]["proposal_id"] == proposal["id"]
    assert (await manuscripts.get(manuscript.id)).title == "Before"

    with pytest.raises(SemanticPatchConflictError, match="no pending provider call"):
        await patches.create_proposal(proposal_data)


@pytest.mark.asyncio
async def test_ai_proposal_must_stay_within_manifest_targets_and_evidence(
    db_with_project,
) -> None:
    manuscripts = NativeManuscriptService(db_with_project, project_id="proj_default")
    disclosed = await manuscripts.create(ManuscriptCreate(title="Disclosed"), actor="pi")
    undisclosed = await manuscripts.create(ManuscriptCreate(title="Undisclosed"), actor="pi")
    patches = SemanticPatchService(db_with_project, project_id="proj_default")
    manifest = await patches.create_context_manifest(
        ContextManifestCreate(
            origin="host_agent",
            provider="chatgpt",
            model="host-model",
            boundary="host_conversation",
            targets=[{"target_type": "manuscript", "target_id": disclosed.id}],
        )
    )
    with pytest.raises(ValueError, match="was not disclosed"):
        await patches.create_proposal(
            SemanticPatchProposalCreate(
                origin="host_agent",
                intent="Edit an undisclosed manuscript.",
                reason="This must fail closed.",
                created_by="brain",
                operations=[{
                    "operation": "manuscript_metadata_update",
                    "manuscript_id": undisclosed.id,
                    "expected_revision": 1,
                    "title": "Should not persist",
                }],
                provider="chatgpt",
                model="host-model",
                boundary="host_conversation",
                context_manifest_id=manifest["id"],
            )
        )

    evidence_id = await _seed_evidence_claim(db_with_project)
    with pytest.raises(ValueError, match="absent from its context manifest"):
        await patches.create_proposal(
            SemanticPatchProposalCreate(
                origin="host_agent",
                intent="Use undisclosed evidence.",
                reason="This must also fail closed.",
                created_by="brain",
                operations=[{
                    "operation": "argument_spine_replace",
                    "manuscript_id": disclosed.id,
                    "expected_revision": 1,
                    "spine": _spine(evidence_id),
                }],
                provider="chatgpt",
                model="host-model",
                boundary="host_conversation",
                context_manifest_id=manifest["id"],
            )
        )

    await manuscripts.update(
        disclosed.id,
        ManuscriptUpdate(expected_revision=1, title="Newer canonical title"),
        actor="pi",
    )
    with pytest.raises(SemanticPatchConflictError, match="changed after"):
        await patches.create_proposal(
            SemanticPatchProposalCreate(
                origin="host_agent",
                intent="Use a stale generation context.",
                reason="The current revision must not disguise stale disclosure.",
                created_by="brain",
                operations=[{
                    "operation": "manuscript_metadata_update",
                    "manuscript_id": disclosed.id,
                    "expected_revision": 2,
                    "title": "Generated from the old snapshot",
                }],
                provider="chatgpt",
                model="host-model",
                boundary="host_conversation",
                context_manifest_id=manifest["id"],
            )
        )


@pytest.mark.asyncio
async def test_proposal_status_filter_is_closed(db_with_project) -> None:
    patches = SemanticPatchService(db_with_project, project_id="proj_default")
    with pytest.raises(ValueError, match="invalid semantic patch proposal status"):
        await patches.list_proposals(status="unknown")


def test_lm_studio_endpoint_must_stay_on_local_machine() -> None:
    assert _local_base_url("http://127.0.0.1:1234/v1/") == "http://127.0.0.1:1234/v1"
    assert _local_base_url("http://host.docker.internal:1234/v1") == (
        "http://host.docker.internal:1234/v1"
    )
    with pytest.raises(ValueError, match="local-machine"):
        _local_base_url("https://api.example.com/v1")
    with pytest.raises(ValueError, match="uncredentialed"):
        _local_base_url("http://user:secret@localhost:1234/v1")
