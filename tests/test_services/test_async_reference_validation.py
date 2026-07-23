"""Durable asynchronous reference-validation contract."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from rka.models.manuscript_native import ManuscriptCreate
from rka.services.jobs import JobQueue
from rka.services.manuscript import ManuscriptService
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.notes import NoteService
from rka.services.reference_validation import ReferenceValidationService
from rka.services.worker import EnrichmentWorker


PROJECT_ID = "proj_default"


def _trace() -> dict:
    trace = {
        stage: {
            "enabled": True,
            "reached": True,
            "completed": True,
            "outcome": "passed",
        }
        for stage in (
            "A_extraction",
            "B_source_resolution",
            "C_cross_source_confirmation",
            "D_retraction",
            "E_author_disambiguation",
            "F_bibliography_compile",
            "G_niche_rescue",
        )
    }
    trace["E_author_disambiguation"] = {
        "enabled": False,
        "reached": False,
        "completed": False,
        "outcome": "disabled",
    }
    trace["G_niche_rescue"] = {
        "enabled": True,
        "reached": False,
        "completed": False,
        "outcome": "not_reached",
    }
    return trace


def _fake_validator(monkeypatch, tmp_path: Path) -> None:
    from rka.services import reference_validation as module

    script = tmp_path / "validate_references.py"
    script.write_text("# worker-owned fake validator", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        del kwargs
        audit_path = Path(cmd[cmd.index("--audit-out") + 1])
        audit_path.write_text(
            json.dumps(
                {
                    "pipeline_version": "async-test",
                    "stage_trace_schema": (
                        "rka.reference-validation.stage-trace.v1"
                    ),
                    "refs": [
                        {
                            "status": "VERIFIED",
                            "sources_tried": ["crossref", "openalex"],
                            "sources_confirmed": ["crossref", "openalex"],
                            "notes": [],
                            "stage_trace": _trace(),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(module, "VALIDATE_REFERENCES_SCRIPT", script)
    monkeypatch.setattr(module.subprocess, "run", fake_run)


@pytest.mark.asyncio
async def test_native_only_request_is_pending_until_worker_attests(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    manuscript = await NativeManuscriptService(
        db, project_id=PROJECT_ID
    ).create(ManuscriptCreate(title="Native-only paper", venue="USENIX"))
    service = ReferenceValidationService(db, project_id=PROJECT_ID)

    pending = await service.enqueue(
        {"DOI": "10.1234/async"},
        manuscript_id=manuscript.id,
    )

    assert pending["status"] == "pending"
    assert pending["canonical_manuscript_id"] == manuscript.id
    assert pending["requested_manuscript_id"] == manuscript.id
    assert pending["attempts"] == 0
    assert await db.fetchone(
        "SELECT id FROM reference_validation_attestations WHERE validation_job_id = ?",
        [pending["job_id"]],
    ) is None

    _fake_validator(monkeypatch, tmp_path)
    worker = EnrichmentWorker(
        db=db,
        embeddings=None,
        worker_id="reference-test-worker",
    )
    assert await worker.run_once() is True

    completed = await service.get_status(manuscript.id, pending["job_id"])
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["result"]["status"] == "VERIFIED"
    assert completed["result"]["manuscript_id"] == manuscript.id
    assert completed["result"]["canonical_manuscript_id"] == manuscript.id
    row = await db.fetchone(
        "SELECT * FROM reference_validation_attestations WHERE validation_job_id = ?",
        [pending["job_id"]],
    )
    assert row is not None
    assert row["manuscript_id"] == manuscript.id
    assert row["canonical_manuscript_id"] == manuscript.id
    assert row["legacy_journal_id"] is None
    assert row["pipeline_version"] == "async-test"


@pytest.mark.asyncio
async def test_legacy_alias_is_resolved_and_rechecked_by_worker(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    legacy = await ManuscriptService(
        db,
        notes=NoteService(db, project_id=PROJECT_ID),
        project_id=PROJECT_ID,
    ).register(venue="CCS", title="Compatibility paper")
    canonical = await NativeManuscriptService(
        db, project_id=PROJECT_ID
    ).resolve_id(legacy.id)
    assert canonical is not None

    service = ReferenceValidationService(db, project_id=PROJECT_ID)
    pending = await service.enqueue({"title": "A paper"}, manuscript_id=legacy.id)
    assert pending["requested_manuscript_id"] == legacy.id
    assert pending["canonical_manuscript_id"] == canonical

    _fake_validator(monkeypatch, tmp_path)
    worker = EnrichmentWorker(db=db, embeddings=None, worker_id="legacy-worker")
    assert await worker.run_once() is True

    completed = await service.get_status(legacy.id, pending["job_id"])
    assert completed is not None
    assert completed["result"]["manuscript_id"] == canonical
    assert completed["result"]["requested_manuscript_id"] == legacy.id
    assert completed["result"]["legacy_journal_id"] == legacy.id
    row = await db.fetchone(
        "SELECT * FROM reference_validation_attestations WHERE validation_job_id = ?",
        [pending["job_id"]],
    )
    assert row["canonical_manuscript_id"] == canonical
    assert row["legacy_journal_id"] == legacy.id


@pytest.mark.asyncio
async def test_status_is_scoped_to_the_jobs_manuscript(db) -> None:
    native = NativeManuscriptService(db, project_id=PROJECT_ID)
    first = await native.create(ManuscriptCreate(title="First"))
    second = await native.create(ManuscriptCreate(title="Second"))
    service = ReferenceValidationService(db, project_id=PROJECT_ID)
    pending = await service.enqueue({"title": "Scoped"}, manuscript_id=first.id)

    assert await service.get_status(second.id, pending["job_id"]) is None
    assert await service.get_status(first.id, "job_missing") is None


@pytest.mark.asyncio
async def test_service_revalidates_untrusted_reference_mappings(db) -> None:
    manuscript = await NativeManuscriptService(
        db, project_id=PROJECT_ID
    ).create(ManuscriptCreate(title="Service boundary"))
    service = ReferenceValidationService(db, project_id=PROJECT_ID)

    with pytest.raises(ValueError):
        await service.enqueue(
            {
                "title": "Looks bounded",
                "provider_response": {"authorization": "Bearer secret"},
            },
            manuscript_id=manuscript.id,
        )
    with pytest.raises(ValueError, match="credential"):
        await service.enqueue(
            {"title": "Authorization: Bearer abcdefghijklmnop"},
            manuscript_id=manuscript.id,
        )
    with pytest.raises(ValueError):
        await service.enqueue(
            {
                "title": "Looks bounded",
                "author": [{"family": "Smith", "credential": "secret"}],
            },
            manuscript_id=manuscript.id,
        )
    with pytest.raises(ValueError, match="64 KiB"):
        await service.enqueue(
            {
                "title": "Aggregate byte limit",
                "author": [{"literal": "研" * 512}] * 100,
            },
            manuscript_id=manuscript.id,
        )

    count = await db.fetchone(
        "SELECT COUNT(*) AS n FROM jobs WHERE job_type = 'reference_validate'"
    )
    assert count["n"] == 0


@pytest.mark.asyncio
async def test_bound_validation_requires_matching_literature_identity(db) -> None:
    manuscript = await NativeManuscriptService(
        db, project_id=PROJECT_ID
    ).create(ManuscriptCreate(title="Identity binding"))
    await db.execute(
        """INSERT INTO literature
           (id, title, doi, status, added_by, project_id)
           VALUES ('lit_identity', 'Bound paper', '10.1234/bound',
                   'cited', 'pi', ?)""",
        [PROJECT_ID],
    )
    await db.commit()
    service = ReferenceValidationService(db, project_id=PROJECT_ID)

    with pytest.raises(ValueError, match="bound literature identity"):
        await service.enqueue(
            {"DOI": "10.1234/different"},
            manuscript_id=manuscript.id,
            literature_id="lit_identity",
        )
    with pytest.raises(ValueError, match="bound literature identity"):
        await service.enqueue(
            {
                "DOI": "10.1234/bound",
                "title": "A conflicting title",
            },
            manuscript_id=manuscript.id,
            literature_id="lit_identity",
        )
    count = await db.fetchone(
        "SELECT COUNT(*) AS n FROM jobs WHERE job_type = 'reference_validate'"
    )
    assert count["n"] == 0


@pytest.mark.asyncio
async def test_worker_rechecks_literature_identity_after_enqueue(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    manuscript = await NativeManuscriptService(
        db, project_id=PROJECT_ID
    ).create(ManuscriptCreate(title="Identity drift"))
    await db.execute(
        """INSERT INTO literature
           (id, title, doi, status, added_by, project_id)
           VALUES ('lit_identity_drift', 'Bound paper', '10.1234/original',
                   'cited', 'pi', ?)""",
        [PROJECT_ID],
    )
    await db.commit()
    service = ReferenceValidationService(db, project_id=PROJECT_ID)
    pending = await service.enqueue(
        {"DOI": "10.1234/original"},
        manuscript_id=manuscript.id,
        literature_id="lit_identity_drift",
    )
    job = await JobQueue(db).claim_next("identity-runner")
    assert job is not None and job["id"] == pending["job_id"]
    await db.execute(
        """UPDATE literature
           SET doi = '10.1234/replaced'
           WHERE id = 'lit_identity_drift' AND project_id = ?""",
        [PROJECT_ID],
    )
    await db.commit()

    _fake_validator(monkeypatch, tmp_path)
    from rka.services.reference_validation import ReferenceValidationRunner

    with pytest.raises(ValueError, match="bound literature identity"):
        await ReferenceValidationRunner(
            db,
            project_id=PROJECT_ID,
        ).run_job(job)
    assert await db.fetchone(
        """SELECT id FROM reference_validation_attestations
           WHERE validation_job_id = ?""",
        [pending["job_id"]],
    ) is None


@pytest.mark.asyncio
async def test_worker_retry_is_idempotent_after_attestation(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    manuscript = await NativeManuscriptService(
        db, project_id=PROJECT_ID
    ).create(ManuscriptCreate(title="Retry paper"))
    service = ReferenceValidationService(db, project_id=PROJECT_ID)
    pending = await service.enqueue({"DOI": "10.1234/retry"}, manuscript_id=manuscript.id)
    job = await JobQueue(db).claim_next("idempotency-runner")
    assert job is not None
    assert job["id"] == pending["job_id"]

    _fake_validator(monkeypatch, tmp_path)
    from rka.services.reference_validation import ReferenceValidationRunner

    runner = ReferenceValidationRunner(db, project_id=PROJECT_ID)
    first = await runner.run_job(job)
    second = await runner.run_job(job)

    assert second == first
    count = await db.fetchone(
        """SELECT COUNT(*) AS n
           FROM reference_validation_attestations
           WHERE validation_job_id = ?""",
        [pending["job_id"]],
    )
    assert count["n"] == 1


@pytest.mark.asyncio
async def test_worker_omits_unbounded_or_secret_process_output(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    from rka.services import reference_validation as module

    manuscript = await NativeManuscriptService(
        db, project_id=PROJECT_ID
    ).create(ManuscriptCreate(title="Bounded diagnostics"))
    pending = await ReferenceValidationService(
        db, project_id=PROJECT_ID
    ).enqueue({"title": "Output safety"}, manuscript_id=manuscript.id)
    script = tmp_path / "validate_references.py"
    script.write_text("# intentionally emits no audit", encoding="utf-8")
    secret = "never-persist-this-provider-token"

    def noisy_run(cmd, **kwargs):
        del kwargs
        return subprocess.CompletedProcess(
            cmd,
            2,
            stdout=(f"Authorization: Bearer {secret}\n" * 10_000),
            stderr=(f"API_KEY={secret}\n" * 10_000),
        )

    monkeypatch.setattr(module, "VALIDATE_REFERENCES_SCRIPT", script)
    monkeypatch.setattr(module.subprocess, "run", noisy_run)
    worker = EnrichmentWorker(db=db, embeddings=None, worker_id="safe-output-worker")
    assert await worker.run_once() is True

    row = await db.fetchone(
        """SELECT full_json_payload
           FROM reference_validation_attestations
           WHERE validation_job_id = ?""",
        [pending["job_id"]],
    )
    assert row is not None
    durable_payload = row["full_json_payload"]
    assert secret not in durable_payload
    assert len(durable_payload) < 5_000
    metadata = json.loads(durable_payload)["subprocess"]
    assert metadata["captured_output"] == "omitted"
    assert metadata["stdout_chars"] > 100_000
    assert metadata["stderr_chars"] > 100_000
    assert len(metadata["stdout_sha256"]) == 64
    assert len(metadata["stderr_sha256"]) == 64


@pytest.mark.asyncio
async def test_active_enqueue_dedupes_across_pending_running_and_retry(db) -> None:
    manuscript = await NativeManuscriptService(
        db, project_id=PROJECT_ID
    ).create(ManuscriptCreate(title="Dedupe paper"))
    service = ReferenceValidationService(db, project_id=PROJECT_ID)
    reference = {
        "DOI": " 10.1234/dedupe ",
        "title": "  Stable title ",
        "author": [{"family": " Smith ", "given": " J. "}],
    }

    first = await service.enqueue(reference, manuscript_id=manuscript.id)
    pending_duplicate = await service.enqueue(
        {
            "DOI": "HTTPS://doi.org/10.1234/DEDUPE",
            "title": "Stable title",
            "author": [{"family": "Smith", "given": "J."}],
        },
        manuscript_id=manuscript.id,
    )
    assert pending_duplicate["job_id"] == first["job_id"]

    queue = JobQueue(db)
    claimed = await queue.claim_next("dedupe-worker")
    assert claimed is not None
    running_duplicate = await service.enqueue(
        reference,
        manuscript_id=manuscript.id,
    )
    assert running_duplicate["job_id"] == first["job_id"]

    await queue.fail(claimed, "transient")
    retry_duplicate = await service.enqueue(
        reference,
        manuscript_id=manuscript.id,
    )
    assert retry_duplicate["job_id"] == first["job_id"]

    await db.execute(
        "UPDATE jobs SET run_after = '1970-01-01T00:00:00Z' WHERE id = ?",
        [first["job_id"]],
    )
    await db.commit()
    retried = await queue.claim_next("dedupe-worker")
    assert retried is not None
    await queue.complete(retried, {"status": "error"})

    fresh = await service.enqueue(reference, manuscript_id=manuscript.id)
    assert fresh["job_id"] != first["job_id"]


@pytest.mark.asyncio
async def test_duplicate_runner_attempts_return_one_attestation_winner(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    manuscript = await NativeManuscriptService(
        db, project_id=PROJECT_ID
    ).create(ManuscriptCreate(title="Attestation race"))
    pending = await ReferenceValidationService(
        db, project_id=PROJECT_ID
    ).enqueue({"DOI": "10.1234/race"}, manuscript_id=manuscript.id)
    raw_job = await JobQueue(db).claim_next("attestation-race-runner")
    assert raw_job is not None
    assert raw_job["id"] == pending["job_id"]

    _fake_validator(monkeypatch, tmp_path)
    from rka.services.reference_validation import ReferenceValidationRunner

    first_runner = ReferenceValidationRunner(db, project_id=PROJECT_ID)
    second_runner = ReferenceValidationRunner(db, project_id=PROJECT_ID)
    first, second = await asyncio.gather(
        first_runner.run_job(dict(raw_job)),
        second_runner.run_job(dict(raw_job)),
    )

    assert first == second
    count = await db.fetchone(
        """SELECT COUNT(*) AS n
           FROM reference_validation_attestations
           WHERE validation_job_id = ?""",
        [pending["job_id"]],
    )
    assert count["n"] == 1


@pytest.mark.asyncio
async def test_reclaimed_worker_cannot_publish_an_attestation(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    from rka.services.jobs import JobLeaseLost
    from rka.services.reference_validation import ReferenceValidationRunner

    manuscript = await NativeManuscriptService(
        db, project_id=PROJECT_ID
    ).create(ManuscriptCreate(title="Fenced attestation"))
    pending = await ReferenceValidationService(
        db, project_id=PROJECT_ID
    ).enqueue({"DOI": "10.1234/fenced"}, manuscript_id=manuscript.id)
    queue = JobQueue(db)
    stale = await queue.claim_next("stale-validator")
    assert stale is not None
    await db.execute(
        "UPDATE jobs SET lease_until = '1970-01-01T00:00:00Z' WHERE id = ?",
        [pending["job_id"]],
    )
    await db.commit()
    current = await queue.claim_next("current-validator")
    assert current is not None
    assert current["lease_token"] != stale["lease_token"]

    _fake_validator(monkeypatch, tmp_path)
    runner = ReferenceValidationRunner(db, project_id=PROJECT_ID)
    with pytest.raises(JobLeaseLost, match="superseded before attestation"):
        await runner.run_job(stale)
    count = await db.fetchone(
        """SELECT COUNT(*) AS n
           FROM reference_validation_attestations
           WHERE validation_job_id = ?""",
        [pending["job_id"]],
    )
    assert count["n"] == 0

    winner = await runner.run_job(current)
    assert winner["status"] == "VERIFIED"
    count = await db.fetchone(
        """SELECT COUNT(*) AS n
           FROM reference_validation_attestations
           WHERE validation_job_id = ?""",
        [pending["job_id"]],
    )
    assert count["n"] == 1


@pytest.mark.asyncio
async def test_oversized_audit_is_rejected_before_read(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    from rka.services import reference_validation as module

    manuscript = await NativeManuscriptService(
        db, project_id=PROJECT_ID
    ).create(ManuscriptCreate(title="Audit bound"))
    pending = await ReferenceValidationService(
        db, project_id=PROJECT_ID
    ).enqueue({"title": "Bounded audit"}, manuscript_id=manuscript.id)
    script = tmp_path / "validate_references.py"
    script.write_text("# oversized fake audit", encoding="utf-8")
    secret = "oversized-provider-secret"

    def oversized_run(cmd, **kwargs):
        del kwargs
        audit_path = Path(cmd[cmd.index("--audit-out") + 1])
        audit_path.write_bytes(
            (secret.encode("utf-8") + b"x" * 1_000_001)
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "VALIDATE_REFERENCES_SCRIPT", script)
    monkeypatch.setattr(module.subprocess, "run", oversized_run)
    worker = EnrichmentWorker(db=db, embeddings=None, worker_id="audit-bound-worker")
    assert await worker.run_once() is True

    row = await db.fetchone(
        """SELECT full_json_payload
           FROM reference_validation_attestations
           WHERE validation_job_id = ?""",
        [pending["job_id"]],
    )
    assert row is not None
    assert secret not in row["full_json_payload"]
    durable = json.loads(row["full_json_payload"])
    assert durable["result"]["status"] == "error"
    assert durable["result"]["message"] == (
        "reference validator audit exceeds size limit"
    )
    assert durable["subprocess"]["audit_bytes"] > 1_000_000


@pytest.mark.asyncio
async def test_allowlisted_but_oversized_result_is_compacted(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    from rka.services import reference_validation as module

    manuscript = await NativeManuscriptService(
        db, project_id=PROJECT_ID
    ).create(ManuscriptCreate(title="Durable result bound"))
    pending = await ReferenceValidationService(
        db, project_id=PROJECT_ID
    ).enqueue({"DOI": "10.1234/result-bound"}, manuscript_id=manuscript.id)
    script = tmp_path / "validate_references.py"
    script.write_text("# large allowlisted fake validator", encoding="utf-8")

    def large_result_run(cmd, **kwargs):
        del kwargs
        audit_path = Path(cmd[cmd.index("--audit-out") + 1])
        audit_path.write_text(
            json.dumps(
                {
                    "pipeline_version": "large-result-test",
                    "stage_trace_schema": (
                        "rka.reference-validation.stage-trace.v1"
                    ),
                    "refs": [
                        {
                            "status": "VERIFIED",
                            "csl_json": {
                                "DOI": "10.1234/result-bound",
                                "author": [
                                    {
                                        "family": "F" * 2_000,
                                        "given": "G" * 2_000,
                                    }
                                    for _ in range(40)
                                ],
                            },
                            "sources_tried": ["crossref", "openalex"],
                            "sources_confirmed": ["crossref", "openalex"],
                            "notes": [],
                            "stage_trace": _trace(),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "VALIDATE_REFERENCES_SCRIPT", script)
    monkeypatch.setattr(module.subprocess, "run", large_result_run)
    worker = EnrichmentWorker(db=db, embeddings=None, worker_id="result-bound-worker")
    assert await worker.run_once() is True

    row = await db.fetchone(
        """SELECT full_json_payload
           FROM reference_validation_attestations
           WHERE validation_job_id = ?""",
        [pending["job_id"]],
    )
    assert row is not None
    durable = json.loads(row["full_json_payload"])
    assert durable["result"]["status"] == "error"
    assert durable["result"]["message"] == (
        "sanitized validator result exceeds durable size limit"
    )
    assert len(row["full_json_payload"].encode("utf-8")) < 20_000


@pytest.mark.asyncio
async def test_provider_raw_fields_and_secret_notes_are_not_durable(
    db,
    monkeypatch,
    tmp_path,
) -> None:
    from rka.services import reference_validation as module

    manuscript = await NativeManuscriptService(
        db, project_id=PROJECT_ID
    ).create(ManuscriptCreate(title="Sanitized result"))
    pending = await ReferenceValidationService(
        db, project_id=PROJECT_ID
    ).enqueue({"DOI": "10.1234/safe"}, manuscript_id=manuscript.id)
    script = tmp_path / "validate_references.py"
    script.write_text("# provider-raw fake validator", encoding="utf-8")
    secret = "never-store-provider-credential"

    def raw_provider_run(cmd, **kwargs):
        del kwargs
        audit_path = Path(cmd[cmd.index("--audit-out") + 1])
        audit_path.write_text(
            json.dumps(
                {
                    "pipeline_version": "safe-test",
                    "stage_trace_schema": (
                        "rka.reference-validation.stage-trace.v1"
                    ),
                    "api_key": secret,
                    "summary": {
                        "total": 1,
                        "verified": 1,
                        f"credential:{secret}": 1,
                    },
                    "refs": [
                        {
                            "identifier": "10.1234/safe",
                            "status": "VERIFIED",
                            "csl_json": {
                                "DOI": "10.1234/safe",
                                "title": "Safe citation",
                                "URL": (
                                    "https://example.test/paper"
                                    f"?api_key={secret}"
                                ),
                                "provider_response": {"token": secret},
                            },
                            "sources_tried": ["crossref", "openalex"],
                            "sources_confirmed": ["crossref", "openalex"],
                            "notes": [f"Authorization: Bearer {secret}"],
                            "stage_trace": _trace(),
                            "_serpapi_raw": {"token": secret},
                            "raw_audit": secret,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "VALIDATE_REFERENCES_SCRIPT", script)
    monkeypatch.setattr(module.subprocess, "run", raw_provider_run)
    worker = EnrichmentWorker(db=db, embeddings=None, worker_id="scrub-worker")
    assert await worker.run_once() is True

    row = await db.fetchone(
        """SELECT full_json_payload
           FROM reference_validation_attestations
           WHERE validation_job_id = ?""",
        [pending["job_id"]],
    )
    assert row is not None
    assert secret not in row["full_json_payload"]
    assert "_serpapi_raw" not in row["full_json_payload"]
    assert "provider_response" not in row["full_json_payload"]
    durable = json.loads(row["full_json_payload"])
    assert durable["result"]["status"] == "VERIFIED"
    assert durable["result"]["csl_json"] == {
        "DOI": "10.1234/safe",
        "title": "Safe citation",
        "URL": "https://example.test/paper",
    }
    assert durable["validator_audit"]["summary"] == {
        "total": 1,
        "verified": 1,
    }
    assert durable["result"]["notes"][0].startswith(
        "validator_note_omitted:"
    )
