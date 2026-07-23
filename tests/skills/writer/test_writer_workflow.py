"""Phase-0 tests for atomic Writer initialization and read-only readiness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from rka.skills.writer import workflow


PROJECT_ID = "prj_01PPPPPPPPPPPPPPPPPPPPPPPP"
MANUSCRIPT_ID = "jrn_01MMMMMMMMMMMMMMMMMMMMMMMM"
NATIVE_MANUSCRIPT_ID = "man_01MMMMMMMMMMMMMMMMMMMMMMMM"


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


def test_registration_creates_canonical_native_manuscript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict | None]] = []

    def fake_http(
        _url: str,
        project_id: str,
        method: str,
        path: str,
        payload=None,
        timeout: float = 20.0,
    ):
        del timeout
        calls.append((method, path, payload))
        return {
            "id": NATIVE_MANUSCRIPT_ID,
            "project_id": project_id,
            "title": "Title",
            "venue": "CHI",
        }

    monkeypatch.setattr(workflow, "_http_json", fake_http)
    manuscript_id, mode = workflow.register_or_verify_manuscript(
        api_url="http://localhost:9712",
        project_id=PROJECT_ID,
        venue="CHI",
        title="Title",
    )

    assert (manuscript_id, mode) == (NATIVE_MANUSCRIPT_ID, "registered")
    assert calls[0][0:2] == ("POST", "/api/manuscripts/native")
    assert calls[0][2]["phase"] == "planning"


def test_legacy_alias_verification_returns_canonical_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "_http_json",
        lambda *_args, **_kwargs: {
            "id": MANUSCRIPT_ID,
            "requested_id": MANUSCRIPT_ID,
            "canonical_id": NATIVE_MANUSCRIPT_ID,
            "project_id": PROJECT_ID,
            "title": "Title",
            "venue": "CHI",
        },
    )

    manuscript_id, mode = workflow.register_or_verify_manuscript(
        api_url="http://localhost:9712",
        project_id=PROJECT_ID,
        venue="CHI",
        title="Title",
        manuscript_id=MANUSCRIPT_ID,
    )
    assert manuscript_id == NATIVE_MANUSCRIPT_ID
    assert mode == "verified_legacy_alias"


def test_server_readiness_preserves_authoritative_categorical_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "_http_json",
        lambda *_args, **_kwargs: {
            "schema_version": "rka.manuscript-readiness/v1",
            "project_id": PROJECT_ID,
            "manuscript_id": NATIVE_MANUSCRIPT_ID,
            "manuscript_revision": 7,
            "target_phase": "drafting",
            "verdict": "BLOCK",
            "ready": False,
            "findings": [{
                "verdict": "BLOCK",
                "code": "CLAIM_NOT_RATIFIED",
                "message": "wording is not ratified",
            }],
        },
    )
    report = workflow.evaluate_server_readiness(
        api_url="http://localhost:9712",
        project_id=PROJECT_ID,
        manuscript_id=NATIVE_MANUSCRIPT_ID,
    )
    assert report["ready_for_drafting"] is False
    assert report["blockers"][0]["code"] == "CLAIM_NOT_RATIFIED"
    assert report["authoritative_source"] == "rka"


def test_sync_writes_deterministic_server_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = {
        "schema_version": "rka-claim-spine/v2",
        "authoritative_source": "rka",
        "project_id": PROJECT_ID,
        "manuscript_id": NATIVE_MANUSCRIPT_ID,
        "manuscript_revision": 3,
        "claims": [],
        "units": [],
    }

    def fake_http(_url, _project, _method, path, *_args, **_kwargs):
        if path.startswith("/api/changes"):
            return {"project_id": PROJECT_ID, "latest_cursor": 19}
        return projection

    monkeypatch.setattr(workflow, "_http_json", fake_http)
    output = tmp_path / "RKA_CLAIM_SPINE.yaml"

    result = workflow.sync_argument_spine(
        api_url="http://localhost:9712",
        project_id=PROJECT_ID,
        manuscript_id=NATIVE_MANUSCRIPT_ID,
        output_path=output,
    )

    written = yaml.safe_load(output.read_text())
    assert written["changelog_cursor"] == 19
    assert {
        key: value for key, value in written.items() if key != "changelog_cursor"
    } == projection
    assert result["manuscript_revision"] == 3


def test_import_spine_is_dry_run_by_default_and_never_imports_ratification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spine = {
        "schema_version": "rka-claim-spine/v1",
        "project_id": PROJECT_ID,
        "manuscript_id": NATIVE_MANUSCRIPT_ID,
        "claims": [{
            "claim_id": "C1",
            "claim_type": "empirical",
            "status": "ratified",
            "text": "Bounded claim.",
            "allowed_wording": "Bounded claim.",
            "prohibited_wording": ["Universal claim."],
            "ratified_by": "dec_01DDDDDDDDDDDDDDDDDDDDDDDD",
            "evidence_ids": [],
            "manuscript_units": [],
        }],
        "units": [],
    }
    path = tmp_path / "spine.yaml"
    path.write_text(yaml.safe_dump(spine), encoding="utf-8")
    calls: list[tuple[str, str]] = []

    def fake_http(
        _url: str,
        _project_id: str,
        method: str,
        request_path: str,
        payload=None,
        timeout: float = 20.0,
    ):
        del payload, timeout
        calls.append((method, request_path))
        return {
            "schema_version": "rka-claim-spine/v2",
            "authoritative_source": "rka",
            "project_id": PROJECT_ID,
            "manuscript_id": NATIVE_MANUSCRIPT_ID,
            "manuscript_revision": 4,
            "claims": [],
            "units": [],
        }

    monkeypatch.setattr(workflow, "_http_json", fake_http)
    result = workflow.import_argument_spine(
        api_url="http://localhost:9712",
        project_id=PROJECT_ID,
        manuscript_id=NATIVE_MANUSCRIPT_ID,
        spine_path=path,
    )
    assert result["mode"] == "dry_run"
    assert result["ratifications_imported"] is False
    assert result["expected_revision"] is None
    assert result["current_revision"] == 4
    assert result["revision_matches_current"] is False
    assert [method for method, _path in calls] == ["GET"]


def test_import_spine_apply_rejects_stale_local_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spine = {
        "schema_version": "rka-claim-spine/v2",
        "authoritative_source": "rka",
        "project_id": PROJECT_ID,
        "manuscript_id": NATIVE_MANUSCRIPT_ID,
        "manuscript_revision": 3,
        "claims": [],
        "units": [],
    }
    path = tmp_path / "stale-spine.yaml"
    path.write_text(yaml.safe_dump(spine), encoding="utf-8")
    calls: list[tuple[str, str]] = []

    def fake_http(
        _url: str,
        _project_id: str,
        method: str,
        request_path: str,
        payload=None,
        timeout: float = 20.0,
    ):
        del payload, timeout
        calls.append((method, request_path))
        return {
            **spine,
            "manuscript_revision": 4,
        }

    monkeypatch.setattr(workflow, "_http_json", fake_http)
    with pytest.raises(workflow.WriterWorkflowError, match="revision is stale"):
        workflow.import_argument_spine(
            api_url="http://localhost:9712",
            project_id=PROJECT_ID,
            manuscript_id=NATIVE_MANUSCRIPT_ID,
            spine_path=path,
            apply=True,
        )
    assert [method for method, _path in calls] == ["GET"]


def test_import_spine_accepts_server_confirmed_canonical_alias_mix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spine = {
        "schema_version": "rka-claim-spine/v2",
        "authoritative_source": "rka",
        "project_id": PROJECT_ID,
        "manuscript_id": MANUSCRIPT_ID,
        "manuscript_revision": 4,
        "claims": [],
        "units": [],
    }
    path = tmp_path / "legacy-alias-spine.yaml"
    path.write_text(yaml.safe_dump(spine), encoding="utf-8")
    paths: list[str] = []

    def fake_http(
        _url: str,
        _project_id: str,
        _method: str,
        request_path: str,
        *_args,
        **_kwargs,
    ):
        paths.append(request_path)
        return {
            **spine,
            "manuscript_id": NATIVE_MANUSCRIPT_ID,
        }

    monkeypatch.setattr(workflow, "_http_json", fake_http)
    result = workflow.import_argument_spine(
        api_url="http://localhost:9712",
        project_id=PROJECT_ID,
        manuscript_id=NATIVE_MANUSCRIPT_ID,
        spine_path=path,
    )
    assert result["manuscript_id"] == NATIVE_MANUSCRIPT_ID
    assert paths == [
        f"/api/manuscripts/{NATIVE_MANUSCRIPT_ID}/spine",
        f"/api/manuscripts/{MANUSCRIPT_ID}/spine",
    ]


def test_import_legacy_spine_apply_requires_explicit_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spine = {
        "schema_version": "rka-claim-spine/v1",
        "project_id": PROJECT_ID,
        "manuscript_id": NATIVE_MANUSCRIPT_ID,
        "claims": [],
        "units": [],
    }
    path = tmp_path / "legacy-spine.yaml"
    path.write_text(yaml.safe_dump(spine), encoding="utf-8")
    monkeypatch.setattr(
        workflow,
        "_http_json",
        lambda *_args, **_kwargs: {
            "schema_version": "rka-claim-spine/v2",
            "authoritative_source": "rka",
            "project_id": PROJECT_ID,
            "manuscript_id": NATIVE_MANUSCRIPT_ID,
            "manuscript_revision": 4,
            "claims": [],
            "units": [],
        },
    )

    with pytest.raises(workflow.WriterWorkflowError, match="requires --expected-revision"):
        workflow.import_argument_spine(
            api_url="http://localhost:9712",
            project_id=PROJECT_ID,
            manuscript_id=NATIVE_MANUSCRIPT_ID,
            spine_path=path,
            apply=True,
        )


def test_impact_report_exposes_only_server_mapped_writing_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "_http_json",
        lambda *_args, **_kwargs: {
            "schema_version": "rka-manuscript-impact/v1",
            "project_id": PROJECT_ID,
            "manuscript_id": NATIVE_MANUSCRIPT_ID,
            "impact_state": "relevant_changes",
            "from_cursor": 10,
            "next_cursor": 14,
            "latest_cursor": 14,
            "has_more": False,
            "affected_manuscript_claims": [{"id": "mcl_one", "local_key": "C1"}],
            "affected_units": [{
                "id": "mun_one",
                "local_key": "R1",
                "location": "sections/results.tex#r1",
            }],
        },
    )
    result = workflow.inspect_server_impact(
        api_url="http://localhost:9712",
        project_id=PROJECT_ID,
        manuscript_id=NATIVE_MANUSCRIPT_ID,
        since_cursor=10,
    )
    assert result["requires_resync"] is True
    assert result["server_impact"]["affected_units"][0]["local_key"] == "R1"


def test_valid_packet_and_claim_spine_are_advisory_only(
    claim_spine_fixture_dir: Path,
) -> None:
    report = workflow.evaluate_readiness(
        packet_path=claim_spine_fixture_dir / "rka_entities.json",
        project_id=PROJECT_ID,
        claim_spine_path=claim_spine_fixture_dir / "valid_spine.yaml",
    )

    assert report["ready_for_drafting"] is False
    assert {
        blocker["code"] for blocker in report["blockers"]
    } == {"ENTITY_PACKET_ADVISORY_ONLY"}
    assert report["claim_spine"]["verdict"] == "PASS"
    assert MANUSCRIPT_ID in report["inventory"]["registered_manuscripts"]
    assert report["mode"] == "compatibility_advisory"


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


def test_server_assist_uses_smoothed_server_candidates_and_never_ratifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_object(
        _url: str,
        _project_id: str,
        method: str,
        path: str,
        payload=None,
        timeout: float = 20.0,
    ):
        del payload, timeout
        assert method == "GET"
        assert path.endswith("/writing-candidates")
        return {
            "schema_version": "rka.writing-evidence-candidates/v1",
            "project_id": PROJECT_ID,
            "manuscript_id": NATIVE_MANUSCRIPT_ID,
            "candidate_spine": {
                "claims": [{
                    "claim_id": "C1",
                    "status": "candidate",
                    "ratified_by": None,
                }],
                "units": [],
            },
            "mode": "server_attested_read_only_proposal",
        }

    monkeypatch.setattr(workflow, "_http_json", fake_object)
    proposal = workflow.propose_server_assist(
        api_url="http://localhost:9712",
        project_id=PROJECT_ID,
        manuscript_id=NATIVE_MANUSCRIPT_ID,
    )
    assert proposal["candidate_spine"]["claims"][0]["ratified_by"] is None
    assert proposal["candidate_spine"]["claims"][0]["status"] == "candidate"
    assert proposal["mode"] == "server_attested_read_only_proposal"


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
