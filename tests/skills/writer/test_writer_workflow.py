"""Phase-0 tests for atomic Writer initialization and read-only readiness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from rka.skills.writer import workflow


PROJECT_ID = "prj_01PPPPPPPPPPPPPPPPPPPPPPPP"
MANUSCRIPT_ID = "jrn_01MMMMMMMMMMMMMMMMMMMMMMMM"


def test_publish_workspace_is_complete_portable_and_atomic(tmp_path: Path) -> None:
    target = tmp_path / "paper"
    result = workflow.publish_workspace(
        target=target,
        template=workflow.workspace_template_dir(),
        project_id=PROJECT_ID,
        manuscript_id=MANUSCRIPT_ID,
        venue="CHI",
        title="Security & AI: 100% grounded",
        api_url="http://localhost:9712",
        cfp_url="https://example.test/cfp",
        registration_mode="verified",
    )

    assert result == target
    metadata = json.loads((target / ".rka" / "manuscript.json").read_text())
    assert metadata["project_id"] == PROJECT_ID
    assert metadata["manuscript_id"] == MANUSCRIPT_ID
    assert metadata["registration_mode"] == "verified"
    manuscript = yaml.safe_load((target / "manuscript.yaml").read_text())
    assert manuscript["title"] == "Security & AI: 100% grounded"
    assert manuscript["cfp_url"] == "https://example.test/cfp"
    assert "Security \\& AI: 100\\% grounded" in (target / "main.tex").read_text()

    mcp = json.loads((target / ".mcp.json").read_text())
    assert "RKA_PROJECT" not in json.dumps(mcp)
    assert "API_KEY" not in json.dumps(mcp)
    assert mcp["mcpServers"]["rka"]["command"] == "rka"
    assert not workflow._unresolved_sentinels(target)


def test_publication_failure_leaves_no_partial_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "paper"
    monkeypatch.setattr(
        workflow, "_unresolved_sentinels", lambda _root: ["main.tex:REPLACE_WITH_X"]
    )

    with pytest.raises(workflow.WriterWorkflowError, match="unresolved"):
        workflow.publish_workspace(
            target=target,
            template=workflow.workspace_template_dir(),
            project_id=PROJECT_ID,
            manuscript_id=MANUSCRIPT_ID,
            venue="CHI",
            title="Title",
            api_url="http://localhost:9712",
            cfp_url=None,
            registration_mode="verified",
        )

    assert not target.exists()
    assert not list(tmp_path.glob(".paper.rka-stage-*"))


def test_nonempty_target_blocks_before_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "paper"
    target.mkdir()
    (target / "owned.txt").write_text("keep")
    calls: list[object] = []
    monkeypatch.setattr(
        workflow,
        "register_or_verify_manuscript",
        lambda **kwargs: calls.append(kwargs),
    )

    with pytest.raises(workflow.WriterWorkflowError, match="not an empty"):
        workflow.initialize_workspace(
            target=target,
            project_id=PROJECT_ID,
            venue="CHI",
            title="Title",
            api_url="http://localhost:9712",
        )

    assert not calls
    assert (target / "owned.txt").read_text() == "keep"


def test_initialize_uses_verified_manifest_before_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    def fake_register(**kwargs):
        calls.append(kwargs)
        return MANUSCRIPT_ID, "registered"

    monkeypatch.setattr(workflow, "register_or_verify_manuscript", fake_register)
    target = tmp_path / "paper"
    result = workflow.initialize_workspace(
        target=target,
        project_id=PROJECT_ID,
        venue="CHI",
        title="A bounded claim",
        api_url="http://localhost:9712",
    )

    assert calls and calls[0]["project_id"] == PROJECT_ID
    assert result["manuscript_id"] == MANUSCRIPT_ID
    assert target.is_dir()


def test_registration_requires_server_attested_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "_http_json",
        lambda *_args, **_kwargs: {"id": MANUSCRIPT_ID},
    )

    with pytest.raises(workflow.WriterWorkflowError, match="attest"):
        workflow.register_or_verify_manuscript(
            api_url="http://localhost:9712",
            project_id=PROJECT_ID,
            venue="CHI",
            title="Title",
        )


def test_valid_packet_and_claim_spine_are_ready(
    claim_spine_fixture_dir: Path,
) -> None:
    report = workflow.evaluate_readiness(
        packet_path=claim_spine_fixture_dir / "rka_entities.json",
        project_id=PROJECT_ID,
        claim_spine_path=claim_spine_fixture_dir / "valid_spine.yaml",
    )

    assert report["ready_for_drafting"] is True
    assert report["blockers"] == []
    assert report["claim_spine"]["verdict"] == "PASS"
    assert MANUSCRIPT_ID in report["inventory"]["registered_manuscripts"]


def test_readiness_without_spine_is_discovery_only(
    claim_spine_fixture_dir: Path,
) -> None:
    report = workflow.evaluate_readiness(
        packet_path=claim_spine_fixture_dir / "rka_entities.json",
        project_id=PROJECT_ID,
        manuscript_id=MANUSCRIPT_ID,
    )

    assert report["ready_for_drafting"] is False
    assert "CLAIM_SPINE_REQUIRED" in {item["code"] for item in report["blockers"]}


def test_unassessed_grounded_claim_is_not_manuscript_ready(
    claim_spine_fixture_dir: Path, tmp_path: Path
) -> None:
    payload = json.loads(
        (claim_spine_fixture_dir / "rka_entities.json").read_text(encoding="utf-8")
    )
    for entity_id, entity in payload["entities"].items():
        if entity_id.startswith("clm_"):
            entity["evidence_status"] = "unassessed"
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps(payload), encoding="utf-8")

    report = workflow.evaluate_readiness(
        packet_path=packet,
        project_id=PROJECT_ID,
        manuscript_id=MANUSCRIPT_ID,
    )
    assert not report["inventory"]["manuscript_ready_claims"]
    assert "NO_MANUSCRIPT_READY_CLAIMS" in {
        item["code"] for item in report["blockers"]
    }


@pytest.mark.parametrize("contradiction_state", [True, None])
def test_contradicted_or_unattested_claim_is_not_manuscript_ready(
    claim_spine_fixture_dir: Path,
    tmp_path: Path,
    contradiction_state: bool | None,
) -> None:
    payload = json.loads(
        (claim_spine_fixture_dir / "rka_entities.json").read_text(encoding="utf-8")
    )
    for entity_id, entity in payload["entities"].items():
        if not entity_id.startswith("clm_"):
            continue
        if contradiction_state is None:
            entity.pop("contradicted", None)
        else:
            entity["contradicted"] = contradiction_state
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps(payload), encoding="utf-8")

    report = workflow.evaluate_readiness(
        packet_path=packet,
        project_id=PROJECT_ID,
        manuscript_id=MANUSCRIPT_ID,
    )
    assert not report["inventory"]["manuscript_ready_claims"]
    assert "NO_MANUSCRIPT_READY_CLAIMS" in {
        item["code"] for item in report["blockers"]
    }


def test_assist_is_candidate_only_and_does_not_ratify(
    claim_spine_fixture_dir: Path,
) -> None:
    proposal = workflow.propose_assist(
        packet_path=claim_spine_fixture_dir / "rka_entities.json",
        project_id=PROJECT_ID,
        manuscript_id=MANUSCRIPT_ID,
    )
    claims = proposal["candidate_spine"]["claims"]
    assert claims
    assert all(claim["status"] == "candidate" for claim in claims)
    assert all(claim["ratified_by"] is None for claim in claims)
    assert proposal["mode"] == "read_only_proposal"


def test_packet_project_mismatch_fails_closed(
    claim_spine_fixture_dir: Path, tmp_path: Path
) -> None:
    payload = json.loads(
        (claim_spine_fixture_dir / "rka_entities.json").read_text(encoding="utf-8")
    )
    payload["project_id"] = "prj_01XXXXXXXXXXXXXXXXXXXXXXXX"
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(workflow.WriterWorkflowError, match="project_id"):
        workflow.load_entity_packet(packet, PROJECT_ID)


def test_entity_without_project_attestation_fails_closed(
    claim_spine_fixture_dir: Path, tmp_path: Path
) -> None:
    payload = json.loads(
        (claim_spine_fixture_dir / "rka_entities.json").read_text(encoding="utf-8")
    )
    first = next(iter(payload["entities"].values()))
    first.pop("project_id")
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(workflow.WriterWorkflowError, match="not attested"):
        workflow.load_entity_packet(packet, PROJECT_ID)
