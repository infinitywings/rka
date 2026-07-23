"""Persistent audit contract for ManuscriptService reference validation."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from rka.models.literature import LiteratureCreate
from rka.models.project import ProjectCreate
from rka.services.literature import LiteratureService
from rka.services.knowledge_pack import KnowledgePackService
from rka.services.manuscript import ManuscriptService
from rka.services.notes import NoteService
from rka.services.project import ProjectService


PROJECT_ID = "proj_default"
STAGE_TRACE_SCHEMA = "rka.reference-validation.stage-trace.v1"


def _complete_stage_trace() -> dict:
    return {
        "A_extraction": {
            "enabled": True, "reached": True, "completed": True, "outcome": "passed",
        },
        "B_source_resolution": {
            "enabled": True, "reached": True, "completed": True, "outcome": "passed",
        },
        "C_cross_source_confirmation": {
            "enabled": True, "reached": True, "completed": True, "outcome": "passed",
        },
        "D_retraction": {
            "enabled": True, "reached": True, "completed": True, "outcome": "passed",
        },
        "E_author_disambiguation": {
            "enabled": True, "reached": True, "completed": True, "outcome": "passed",
        },
        "F_bibliography_compile": {
            "enabled": True, "reached": True, "completed": True, "outcome": "passed",
        },
        "G_niche_rescue": {
            "enabled": True,
            "reached": False,
            "completed": False,
            "outcome": "not_reached",
        },
    }


def _install_fake_validator(
    monkeypatch,
    tmp_path: Path,
    *,
    payload: dict,
) -> list[list[str]]:
    from rka.services import manuscript as manuscript_module

    script = tmp_path / "validate_references.py"
    script.write_text("# fake validator", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        audit_path = Path(cmd[cmd.index("--audit-out") + 1])
        audit_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="validator stdout", stderr="")

    monkeypatch.setattr(manuscript_module, "_VALIDATE_REFERENCES_SCRIPT", script)
    monkeypatch.setattr(manuscript_module.subprocess, "run", fake_run)
    return calls


async def _service_and_manuscript(db):
    service = ManuscriptService(
        db,
        notes=NoteService(db, project_id=PROJECT_ID),
        project_id=PROJECT_ID,
    )
    manuscript = await service.register(venue="USENIX", title="Attested paper")
    return service, manuscript


@pytest.mark.asyncio
async def test_full_pipeline_persists_complete_immutable_attestation(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    service, manuscript = await _service_and_manuscript(db)
    literature = await LiteratureService(db, project_id=PROJECT_ID).create(
        LiteratureCreate(title="Validated paper", doi="10.1234/example")
    )
    validator_payload = {
        "pipeline_version": "2.1",
        "stage_trace_schema": STAGE_TRACE_SCHEMA,
        "refs": [
            {
                "identifier": "10.1234/example",
                "status": "VERIFIED",
                "csl_json": {"DOI": "10.1234/example", "title": "Validated paper"},
                "sources_tried": ["crossref", "openalex", "semantic_scholar"],
                "sources_confirmed": ["crossref", "openalex"],
                "notes": [],
                "stage_trace": _complete_stage_trace(),
            }
        ],
        "serpapi_budget": 10,
        "serpapi_credits_used": 0,
        "summary": {"total": 1, "verified": 1, "blocking": 0},
    }
    calls = _install_fake_validator(
        monkeypatch,
        tmp_path,
        payload=validator_payload,
    )
    authors = [{"family": "Smith", "given": "Jane"}]

    result = await service.validate_reference(
        {"DOI": "10.1234/example", "title": "Validated paper", "author": authors},
        manuscript_id=manuscript.id,
        literature_id=literature.id,
    )

    assert result["validation_id"].startswith("rvd_")
    assert result["retraction_check_enabled"] is True
    assert result["retraction_checked"] is True
    assert result["stage_trace"]["D_retraction"]["completed"] is True
    assert result["stage_trace"]["E_author_disambiguation"]["completed"] is True
    assert "--no-retraction" not in calls[0]
    assert "--check-disambiguation" in calls[0]
    assert "--bib-out" in calls[0]

    row = await db.fetchone(
        "SELECT * FROM reference_validation_attestations WHERE id = ?",
        [result["validation_id"]],
    )
    assert row is not None
    assert row["project_id"] == PROJECT_ID
    assert row["manuscript_id"] == manuscript.id
    assert row["literature_id"] == literature.id
    assert row["input_doi"] == "10.1234/example"
    assert row["input_title"] == "Validated paper"
    assert json.loads(row["input_authors"]) == authors
    assert row["status"] == "VERIFIED"
    assert row["retraction_check_enabled"] == 1
    assert row["retraction_checked"] == 1
    assert json.loads(row["sources_tried"]) == validator_payload["refs"][0]["sources_tried"]
    assert json.loads(row["sources_confirmed"]) == ["crossref", "openalex"]
    assert json.loads(row["notes"]) == []
    assert json.loads(row["stage_trace"]) == validator_payload["refs"][0]["stage_trace"]
    assert json.loads(row["full_json_payload"])["validator_audit"] == validator_payload
    assert row["pipeline_version"] == "2.1"
    assert row["started_at"]
    assert row["completed_at"]
    assert row["created_at"]

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db.execute(
            "UPDATE reference_validation_attestations SET status = 'UNVERIFIED' WHERE id = ?",
            [result["validation_id"]],
        )


@pytest.mark.asyncio
async def test_service_uses_emitted_trace_instead_of_inferring_completion(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    service, manuscript = await _service_and_manuscript(db)
    emitted_trace = _complete_stage_trace()
    emitted_trace["D_retraction"] = {
        "enabled": True,
        "reached": False,
        "completed": False,
        "outcome": "not_reached",
    }
    emitted_trace["E_author_disambiguation"] = {
        "enabled": False,
        "reached": False,
        "completed": False,
        "outcome": "disabled",
    }
    _install_fake_validator(
        monkeypatch,
        tmp_path,
        payload={
            "pipeline_version": "2.1",
            "stage_trace_schema": STAGE_TRACE_SCHEMA,
            "refs": [{
                "identifier": "10.1234/not-checked",
                "status": "VERIFIED",
                "csl_json": {"DOI": "10.1234/not-checked"},
                "sources_tried": ["crossref", "openalex"],
                "sources_confirmed": ["crossref", "openalex"],
                "notes": [],
                "stage_trace": emitted_trace,
            }],
        },
    )

    result = await service.validate_reference(
        {"DOI": "10.1234/not-checked"},
        manuscript_id=manuscript.id,
    )

    assert result["status"] == "VERIFIED"
    assert result["retraction_checked"] is False
    assert result["stage_trace"] == emitted_trace
    row = await db.fetchone(
        "SELECT retraction_checked, stage_trace FROM reference_validation_attestations "
        "WHERE id = ?",
        [result["validation_id"]],
    )
    assert row["retraction_checked"] == 0
    assert json.loads(row["stage_trace"]) == emitted_trace


@pytest.mark.asyncio
async def test_validation_error_is_attested_when_validator_is_missing(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    from rka.services import manuscript as manuscript_module

    service, manuscript = await _service_and_manuscript(db)
    monkeypatch.setattr(
        manuscript_module,
        "_VALIDATE_REFERENCES_SCRIPT",
        tmp_path / "does-not-exist.py",
    )

    result = await service.validate_reference(
        {"DOI": "10.9999/missing"},
        manuscript_id=manuscript.id,
    )

    assert result["status"] == "error"
    assert result["validation_id"].startswith("rvd_")
    assert result["retraction_check_enabled"] is True
    assert result["retraction_checked"] is False
    row = await db.fetchone(
        "SELECT * FROM reference_validation_attestations WHERE id = ?",
        [result["validation_id"]],
    )
    assert row is not None
    assert row["status"] == "error"
    assert json.loads(row["notes"])[0].startswith("validate_references.py not found")


@pytest.mark.asyncio
async def test_cross_project_literature_is_rejected_before_validation(db) -> None:
    service, manuscript = await _service_and_manuscript(db)
    other_project = "prj_reference_other"
    await ProjectService(db).create_project(
        ProjectCreate(id=other_project, name="Reference Other"),
        actor="system",
    )
    foreign_literature = await LiteratureService(db, project_id=other_project).create(
        LiteratureCreate(title="Foreign paper")
    )

    with pytest.raises(ValueError, match="does not belong to project"):
        await service.validate_reference(
            {"title": "Foreign paper"},
            manuscript_id=manuscript.id,
            literature_id=foreign_literature.id,
        )

    count = await db.fetchone("SELECT COUNT(*) AS n FROM reference_validation_attestations")
    assert count["n"] == 0


@pytest.mark.asyncio
async def test_attestation_round_trips_with_remapped_manuscript_and_literature_ids(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    service, manuscript = await _service_and_manuscript(db)
    literature = await LiteratureService(db, project_id=PROJECT_ID).create(
        LiteratureCreate(title="Portable validation", doi="10.1234/portable")
    )
    _install_fake_validator(
        monkeypatch,
        tmp_path,
        payload={
            "pipeline_version": "2.1",
            "stage_trace_schema": STAGE_TRACE_SCHEMA,
            "refs": [{
                "identifier": "10.1234/portable",
                "status": "VERIFIED",
                "csl_json": {"DOI": "10.1234/portable"},
                "sources_tried": ["crossref", "openalex"],
                "sources_confirmed": ["crossref", "openalex"],
                "notes": [],
                "stage_trace": {
                    **_complete_stage_trace(),
                    "E_author_disambiguation": {
                        "enabled": False,
                        "reached": False,
                        "completed": False,
                        "outcome": "disabled",
                    },
                },
            }],
        },
    )
    original = await service.validate_reference(
        {"DOI": "10.1234/portable"},
        manuscript_id=manuscript.id,
        literature_id=literature.id,
    )

    pack_path, _ = await KnowledgePackService(
        db, project_id=PROJECT_ID
    ).export_pack()
    with Path(pack_path).open("rb") as pack_file:
        imported = await KnowledgePackService(db).import_pack(
            pack_file,
            project_id="prj_attestation_copy",
            project_name="Attestation Copy",
        )

    copied = await db.fetchone(
        "SELECT * FROM reference_validation_attestations WHERE project_id = ?",
        [imported.project_id],
    )
    assert copied is not None
    assert copied["id"] != original["validation_id"]
    assert copied["manuscript_id"] != manuscript.id
    assert copied["literature_id"] != literature.id
    assert await db.fetchone(
        "SELECT id FROM journal WHERE id = ? AND project_id = ?",
        [copied["manuscript_id"], imported.project_id],
    )
    assert await db.fetchone(
        "SELECT id FROM literature WHERE id = ? AND project_id = ?",
        [copied["literature_id"], imported.project_id],
    )
    copied_payload = json.loads(copied["full_json_payload"])
    assert copied_payload["result"]["validation_id"] == copied["id"]
    assert copied_payload["result"]["manuscript_id"] == copied["manuscript_id"]
    assert copied_payload["result"]["literature_id"] == copied["literature_id"]
