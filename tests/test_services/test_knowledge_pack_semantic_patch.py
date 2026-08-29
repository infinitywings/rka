"""Knowledge-pack portability for semantic proposals and AI disclosure manifests."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from rka.models.manuscript_native import ManuscriptCreate
from rka.models.semantic_patch import ContextManifestCreate, SemanticPatchProposalCreate
from rka.services.knowledge_pack import (
    KnowledgePackIntegrityError,
    KnowledgePackService,
    PACK_SCHEMA_VERSION,
)
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.semantic_patch import SemanticPatchService


@pytest.mark.asyncio
async def test_pack_v7_rekeys_proposal_manifest_and_provider_events(
    db_with_project, tmp_path: Path
) -> None:
    db = db_with_project
    manuscript = await NativeManuscriptService(db, project_id="proj_default").create(
        ManuscriptCreate(title="Portable proposal"), actor="pi"
    )
    patches = SemanticPatchService(db, project_id="proj_default")
    manifest = await patches.create_context_manifest(
        ContextManifestCreate(
            origin="host_agent",
            provider="chatgpt",
            model="host-model",
            boundary="host_conversation",
            targets=[{"target_type": "manuscript", "target_id": manuscript.id}],
            constraints=["Preserve the evidence boundary."],
        )
    )
    proposal = await patches.create_proposal(
        SemanticPatchProposalCreate(
            origin="host_agent",
            intent="Clarify the title.",
            reason="Improve quick-reader comprehension.",
            created_by="pi",
            operations=[{
                "operation": "manuscript_metadata_update",
                "manuscript_id": manuscript.id,
                "expected_revision": 1,
                "title": "Portable proposal with a clearer title",
            }],
            provider="chatgpt",
            model="host-model",
            boundary="host_conversation",
            context_manifest_id=manifest["id"],
        )
    )
    completed_manifest = proposal["context_manifest"]
    assert [event["event"] for event in completed_manifest["provider_events"]] == [
        "started",
        "succeeded",
    ]
    assert len({event["call_id"] for event in completed_manifest["provider_events"]}) == 1

    pack_path, _ = await KnowledgePackService(db, project_id="proj_default").export_pack()
    with open(pack_path, "rb") as source:
        result = await KnowledgePackService(db).import_pack(
            source,
            project_id="proj_semantic_patch_import",
            project_name="Semantic Patch Import",
        )
    assert PACK_SCHEMA_VERSION == 8
    assert result.imported_counts["semantic_patch_context_manifests"] == 1
    assert result.imported_counts["semantic_patch_proposals"] == 1
    assert result.imported_counts["semantic_patch_proposal_events"] == 1
    assert result.imported_counts["semantic_patch_provider_events"] == 2

    imported = SemanticPatchService(db, project_id="proj_semantic_patch_import")
    imported_proposal = (await imported.list_proposals())[0]
    assert imported_proposal["id"] != proposal["id"]
    assert imported_proposal["operations"][0]["manuscript_id"] != manuscript.id
    imported_manifest = imported_proposal["context_manifest"]
    assert imported_manifest["id"] != manifest["id"]
    assert imported_manifest["project_id"] == "proj_semantic_patch_import"
    assert len({event["call_id"] for event in imported_manifest["provider_events"]}) == 1
    assert imported_manifest["provider_events"][0]["call_id"] != (
        completed_manifest["provider_events"][0]["call_id"]
    )

    payload = {
        "schema_version": "rka.context-manifest/v1",
        "project_id": imported_manifest["project_id"],
        "origin": imported_manifest["origin"],
        "provider": imported_manifest["provider"],
        "model": imported_manifest["model"],
        "boundary": imported_manifest["boundary"],
        "selected_context": imported_manifest["selected_context"],
        "resolved_context": imported_manifest["resolved_context"],
        "target_bases": imported_manifest["target_bases"],
        "constraints": imported_manifest["constraints"],
        "omissions": imported_manifest["omissions"],
        "truncation_notes": imported_manifest["truncation_notes"],
    }
    expected_hash = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    assert imported_manifest["manifest_hash"] == expected_hash

    # Untrusted packs cannot present an AI proposal without the terminal
    # provider event that attributes it to the disclosed call.
    with zipfile.ZipFile(pack_path) as source:
        raw_manifest = json.loads(source.read("manifest.json"))
    raw_manifest["tables"]["semantic_patch_provider_events"] = [
        event
        for event in raw_manifest["tables"]["semantic_patch_provider_events"]
        if event["event"] == "started"
    ]
    raw_manifest["table_counts"]["semantic_patch_provider_events"] = 1
    tampered_path = tmp_path / "missing-provider-success.rka-pack.zip"
    with zipfile.ZipFile(tampered_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(raw_manifest))
    with tampered_path.open("rb") as source:
        with pytest.raises(KnowledgePackIntegrityError) as excinfo:
            await KnowledgePackService(db).import_pack(
                source,
                project_id="proj_semantic_patch_invalid",
                project_name="Invalid Semantic Patch Import",
            )
    assert {issue["category"] for issue in excinfo.value.issues} == {
        "semantic_patch_provider_event_chain_invalid"
    }
    assert await db.fetchone(
        "SELECT id FROM projects WHERE id = 'proj_semantic_patch_invalid'"
    ) is None
