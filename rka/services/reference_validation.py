"""Durable, worker-owned manuscript reference validation.

The request path performs only deterministic scope validation and enqueues a
``reference_validate`` job.  The background worker owns all filesystem,
subprocess, and network-capable Writer validation work and appends one
immutable attestation when the attempt finishes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from rka.infra.database import Database
from rka.infra.ids import generate_id
from rka.models.reference_validation import normalize_reference_input
from rka.services.base import BaseService, _precise_now
from rka.services.jobs import JobLeaseLost, JobQueue
from rka.services.manuscript_native import NativeManuscriptService

VALIDATE_REFERENCES_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "writer"
    / "scripts"
    / "validate_references.py"
)

STAGE_TRACE_SCHEMA = "rka.reference-validation.stage-trace.v1"
STAGE_TRACE_KEYS = {
    "A_extraction",
    "B_source_resolution",
    "C_cross_source_confirmation",
    "D_retraction",
    "E_author_disambiguation",
    "F_bibliography_compile",
    "G_niche_rescue",
}
STAGE_TRACE_OUTCOMES = {
    "disabled",
    "not_reached",
    "passed",
    "inconclusive",
    "rejected",
    "unavailable",
    "error",
}
REFERENCE_VALIDATE_JOB = "reference_validate"
REFERENCE_VALIDATE_PAYLOAD_SCHEMA = "rka.reference-validation.job.v1"
MAX_VALIDATOR_AUDIT_BYTES = 1_000_000
MAX_DURABLE_RESULT_BYTES = 128 * 1024
MAX_DURABLE_TEXT_CHARS = 4_096
MAX_DURABLE_LIST_ITEMS = 100

_CSL_JSON_FIELDS = {
    "DOI",
    "URL",
    "author",
    "collection-title",
    "container-title",
    "event-title",
    "id",
    "issue",
    "issued",
    "page",
    "publisher",
    "title",
    "type",
    "volume",
}
_CSL_AUTHOR_FIELDS = {"family", "given", "literal", "suffix", "ORCID"}
_REFERENCE_STATUSES = {
    "VERIFIED",
    "FIELD_ERROR",
    "UNVERIFIED",
    "RETRACTED",
    "HALLUCINATED",
    "AUTHOR_MISMATCH",
    "LOW_CONFIDENCE",
    "error",
}
_SAFE_SUMMARY_KEYS = {
    "total",
    "verified",
    "blocking",
    "field_error",
    "unverified",
    "retracted",
    "hallucinated",
    "author_mismatch",
    "low_confidence",
}
_SAFE_SOURCE_LABELS = {
    "arxiv",
    "crossref",
    "openalex",
    "semantic_scholar",
    "serpapi",
}
_SAFE_FIXED_NOTES = {
    "budget-exceeded",
    "missing_doi_and_title",
    "no-serpapi-budget",
    "no-serpapi-installed",
    "reference_input_not_object",
    "retraction_detected_via_crossref_update_to",
    "scholar_empty",
    "scholar-only-source",
    "stage_d_retraction_backend_unavailable",
    "stage_f_betterbib_applied",
    "stage_f_betterbib_unavailable",
    "stage_f_bibtex_tidy_applied",
    "stage_f_bibtex_tidy_unavailable",
    "stage_f_manubot_csljson_converted",
    "stage_f_reference_missing_resolvable_id",
    "stage_f_skipped_no_manubot",
    "stage_f_skipped_no_resolvable_ids",
}
_SAFE_EXIT_NOTE_RE = re.compile(
    r"^stage_f_(?:manubot|bibtex_tidy|betterbib)_exit_[0-9]{1,10}$"
)
_SAFE_METADATA_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,255}$")
_SAFE_INTERNAL_MESSAGES = {
    "validator verdict is not an object",
    "reference validator script is unavailable",
    "reference validator exited unsuccessfully",
    "validate_references did not write audit output",
    "reference validator audit exceeds size limit",
    "reference validator audit is not UTF-8",
    "reference validator audit JSON is malformed",
    "sanitized validator result exceeds durable size limit",
    "validate_references audit root is not an object",
    "validate_references returned no verdicts",
    "validate_references returned an invalid verdict",
    "validate_references returned an invalid stage trace",
}
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(?:"
    r"authorization\s*:|"
    r"bearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S+"
    r")"
)


def _bounded_text(value: Any, *, limit: int = MAX_DURABLE_TEXT_CHARS) -> str | None:
    if not isinstance(value, str):
        return None
    bounded = value[:limit]
    if _SENSITIVE_VALUE_RE.search(bounded):
        return (
            "sensitive_text_omitted:"
            + hashlib.sha256(bounded.encode("utf-8")).hexdigest()[:16]
        )
    return bounded


def _require_bounded_id(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError(f"{label} must be a non-empty identifier up to 128 characters")
    return value


def _normalize_identity_doi(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
            break
    return normalized or None


def _normalize_identity_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).casefold()
    return normalized or None


def _reference_matches_literature(
    reference: dict[str, Any],
    literature: dict[str, Any],
) -> bool:
    """Require the queued lookup identity to match its bound literature row.

    DOI is the durable primary identity when the literature row has one.
    Title is required when DOI is absent, and any title supplied alongside a
    DOI must agree too.  This prevents a successful validation for paper A
    from being attached to the ``literature_id`` for paper B.
    """
    input_doi = _normalize_identity_doi(
        reference.get("DOI") or reference.get("doi")
    )
    input_title = _normalize_identity_title(reference.get("title"))
    literature_doi = _normalize_identity_doi(literature.get("doi"))
    literature_title = _normalize_identity_title(literature.get("title"))
    if literature_doi is not None and input_doi != literature_doi:
        return False
    if literature_doi is None and input_title != literature_title:
        return False
    if input_title is not None and input_title != literature_title:
        return False
    return True


def _require_reference_literature_identity(
    reference: dict[str, Any],
    literature: dict[str, Any],
) -> None:
    if not _reference_matches_literature(reference, literature):
        raise ValueError(
            "Reference validation input does not match the bound literature "
            "identity"
        )


def _bounded_scalar_tree(value: Any, *, depth: int = 0) -> Any:
    """Copy a small JSON tree while discarding arbitrary object keys at depth."""
    if depth > 5:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _bounded_text(value)
    if isinstance(value, list):
        return [
            _bounded_scalar_tree(item, depth=depth + 1)
            for item in value[:MAX_DURABLE_LIST_ITEMS]
        ]
    if isinstance(value, dict):
        # Nested CSL structures such as ``issued.date-parts`` are small, but
        # provider responses can contain credential-bearing arbitrary blobs.
        # Only the one standardized date key is accepted recursively.
        if set(value).issubset({"date-parts"}):
            return {
                "date-parts": _bounded_scalar_tree(
                    value.get("date-parts"),
                    depth=depth + 1,
                )
            }
    return None


def _bounded_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        text
        for item in value[:MAX_DURABLE_LIST_ITEMS]
        if (text := _bounded_text(item)) is not None
    ]


def _safe_label_list(value: Any) -> list[str]:
    return [
        item
        for item in _bounded_string_list(value)
        if item in _SAFE_SOURCE_LABELS
    ]


def _sanitize_notes(value: Any) -> list[str]:
    notes: list[str] = []
    for item in _bounded_string_list(value):
        if item in _SAFE_FIXED_NOTES or _SAFE_EXIT_NOTE_RE.fullmatch(item):
            notes.append(item)
        else:
            notes.append(
                "validator_note_omitted:"
                + hashlib.sha256(item.encode("utf-8")).hexdigest()[:16]
            )
    return notes


def _sanitize_csl_json(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    clean: dict[str, Any] = {}
    for key in _CSL_JSON_FIELDS:
        if key not in value:
            continue
        item = value[key]
        if key == "author":
            if not isinstance(item, list):
                continue
            authors: list[dict[str, str]] = []
            for author in item[:MAX_DURABLE_LIST_ITEMS]:
                if not isinstance(author, dict):
                    continue
                clean_author = {
                    field: text
                    for field in _CSL_AUTHOR_FIELDS
                    if (text := _bounded_text(author.get(field))) is not None
                }
                if clean_author:
                    authors.append(clean_author)
            clean[key] = authors
            continue
        if key == "URL":
            if not isinstance(item, str):
                continue
            parsed = urlsplit(item[:MAX_DURABLE_TEXT_CHARS])
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            scrubbed_url = _bounded_text(urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, "", "")
            ))
            if scrubbed_url is not None:
                clean[key] = scrubbed_url
            continue
        bounded = _bounded_scalar_tree(item)
        if bounded is not None:
            clean[key] = bounded
    return clean


def _sanitize_verdict(value: Any) -> dict[str, Any]:
    """Allowlist the durable verdict shape emitted by the Writer pipeline."""
    if not isinstance(value, dict):
        return {"status": "error", "message": "validator verdict is not an object"}
    clean: dict[str, Any] = {}
    message = _bounded_text(value.get("message"))
    if message is not None:
        if (
            message in _SAFE_INTERNAL_MESSAGES
            or re.fullmatch(
                r"validate_references subprocess error: [A-Za-z][A-Za-z0-9_]{0,63}",
                message,
            )
        ):
            clean["message"] = message
        else:
            clean["message"] = (
                "validator_message_omitted:"
                + hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
            )
    status = value.get("status")
    if isinstance(status, str) and status in _REFERENCE_STATUSES:
        clean["status"] = status
    csl_json = _sanitize_csl_json(value.get("csl_json"))
    if csl_json is not None:
        clean["csl_json"] = csl_json
    for key in ("sources_tried", "sources_confirmed"):
        clean[key] = _safe_label_list(value.get(key))
    clean["notes"] = _sanitize_notes(value.get("notes"))
    trace = value.get("stage_trace")
    if stage_trace_is_closed(trace):
        clean["stage_trace"] = json.loads(json.dumps(trace, sort_keys=True))
    for key in (
        "serpapi_budget",
        "serpapi_credits_used",
        "exit_code",
        "stdout_chars",
        "stderr_chars",
    ):
        number = value.get(key)
        if isinstance(number, int) and not isinstance(number, bool):
            clean[key] = (
                max(-255, min(255, number))
                if key == "exit_code"
                else max(0, number)
            )
    if "status" not in clean:
        clean["status"] = "error"
    return clean


def _sanitize_validator_audit(value: Any) -> dict[str, Any] | None:
    """Retain reproducibility metadata, never raw provider response blobs."""
    if not isinstance(value, dict):
        return None
    clean: dict[str, Any] = {}
    for key in ("pipeline_version", "stage_trace_schema"):
        if (
            (text := _bounded_text(value.get(key), limit=256)) is not None
            and _SAFE_METADATA_LABEL_RE.fullmatch(text)
        ):
            clean[key] = text
    for key in ("serpapi_budget", "serpapi_credits_used"):
        number = value.get(key)
        if isinstance(number, int) and not isinstance(number, bool):
            clean[key] = max(0, number)
    summary = value.get("summary")
    if isinstance(summary, dict):
        clean["summary"] = {
            key: max(0, number)
            for key, number in summary.items()
            if key in _SAFE_SUMMARY_KEYS
            and isinstance(number, int)
            and not isinstance(number, bool)
        }
    batch_trace = value.get("batch_stage_trace")
    if isinstance(batch_trace, dict):
        clean["batch_stage_trace"] = {
            key: {
                field: record[field]
                for field in ("enabled", "reached", "completed", "outcome")
                if field in record
                and (
                    isinstance(record[field], bool)
                    or (
                        field == "outcome"
                        and isinstance(record[field], str)
                        and record[field] in STAGE_TRACE_OUTCOMES
                    )
                )
            }
            for key, record in batch_trace.items()
            if key in STAGE_TRACE_KEYS and isinstance(record, dict)
        }
    return clean


def _subprocess_metadata(
    command: list[str],
    *,
    completed: subprocess.CompletedProcess[str] | None = None,
    error: BaseException | None = None,
    audit_text: str | None = None,
) -> dict[str, Any]:
    """Return bounded diagnostics without persisting process output.

    Provider errors can echo credentials, authorization headers, environment
    values, or unbounded bodies.  Raw stdout, stderr, and malformed audit text
    therefore never enter the durable database.  Lengths and a one-way digest
    retain enough information to correlate an operator-side worker log.
    """
    metadata: dict[str, Any] = {
        "command": [
            value if value.startswith("--") else Path(value).name
            for value in command
        ],
        "captured_output": "omitted",
    }
    if completed is not None:
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        metadata.update(
            {
                "exit_code": completed.returncode,
                "stdout_chars": len(stdout),
                "stderr_chars": len(stderr),
                "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
            }
        )
    if error is not None:
        metadata["error_type"] = type(error).__name__
    if audit_text is not None:
        metadata.update(
            {
                "audit_chars": len(audit_text),
                "audit_sha256": hashlib.sha256(audit_text.encode()).hexdigest(),
            }
        )
    return metadata


def stage_trace_is_closed(trace: Any) -> bool:
    """Return whether ``trace`` exactly satisfies the closed Writer schema."""
    if not isinstance(trace, dict) or set(trace) != STAGE_TRACE_KEYS:
        return False
    for record in trace.values():
        if not isinstance(record, dict) or set(record) != {
            "enabled",
            "reached",
            "completed",
            "outcome",
        }:
            return False
        if not all(
            isinstance(record[key], bool)
            for key in ("enabled", "reached", "completed")
        ):
            return False
        if record["outcome"] not in STAGE_TRACE_OUTCOMES:
            return False
        if not record["enabled"]:
            if record != {
                "enabled": False,
                "reached": False,
                "completed": False,
                "outcome": "disabled",
            }:
                return False
        elif not record["reached"]:
            if record["completed"] or record["outcome"] != "not_reached":
                return False
        elif record["completed"] and record["outcome"] in {
            "disabled",
            "not_reached",
            "unavailable",
            "error",
        }:
            return False
        elif not record["completed"] and record["outcome"] in {
            "passed",
            "rejected",
        }:
            return False
    return True


def unreached_stage_trace(
    *,
    check_retraction: bool,
    check_disambiguation: bool,
) -> dict[str, dict[str, bool | str]]:
    """Build a truthful trace when the validator emitted no audit."""
    enabled_by_stage = {
        "A_extraction": True,
        "B_source_resolution": True,
        "C_cross_source_confirmation": True,
        "D_retraction": check_retraction,
        "E_author_disambiguation": check_disambiguation,
        "F_bibliography_compile": True,
        "G_niche_rescue": True,
    }
    return {
        stage: {
            "enabled": enabled,
            "reached": False,
            "completed": False,
            "outcome": "not_reached" if enabled else "disabled",
        }
        for stage, enabled in enabled_by_stage.items()
    }


class ReferenceValidationService(BaseService):
    """Validate request scope, enqueue work, and expose project-scoped status."""

    async def enqueue(
        self,
        reference: dict[str, Any],
        *,
        manuscript_id: str,
        literature_id: str | None = None,
        actor: str = "executor",
    ) -> dict[str, Any]:
        """Queue one validation attempt and return pending job metadata."""
        self._validate_actor(actor)
        normalized_reference = normalize_reference_input(reference)
        manuscript_id = _require_bounded_id(manuscript_id, label="manuscript_id")
        if literature_id is not None:
            literature_id = _require_bounded_id(
                literature_id,
                label="literature_id",
            )

        native = NativeManuscriptService(self.db, project_id=self.project_id)
        manuscript = await native.get(manuscript_id)
        if manuscript is None:
            raise ValueError(
                f"Manuscript {manuscript_id} does not belong to project "
                f"{self.project_id}"
            )
        if literature_id is not None:
            literature = await self.db.fetchone(
                """SELECT id, doi, title FROM literature
                   WHERE id = ? AND project_id = ?""",
                [literature_id, self.project_id],
            )
            if literature is None:
                raise ValueError(
                    f"Literature {literature_id} does not belong to project "
                    f"{self.project_id}"
                )
            _require_reference_literature_identity(
                normalized_reference,
                dict(literature),
            )

        payload = {
            "schema": REFERENCE_VALIDATE_PAYLOAD_SCHEMA,
            "requested_manuscript_id": manuscript_id,
            "canonical_manuscript_id": manuscript.id,
            "legacy_journal_id": manuscript.legacy_journal_id,
            "literature_id": literature_id,
            "reference": normalized_reference,
        }
        dedupe_material = json.dumps(
            {
                "project_id": self.project_id,
                "canonical_manuscript_id": manuscript.id,
                "literature_id": literature_id,
                "reference": normalized_reference,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        dedupe_key = (
            f"{self.project_id}:{REFERENCE_VALIDATE_JOB}:"
            f"{hashlib.sha256(dedupe_material.encode('utf-8')).hexdigest()}"
        )
        queue = JobQueue(self.db)
        async with self.db.transaction():
            job_id = await queue.enqueue(
                REFERENCE_VALIDATE_JOB,
                project_id=self.project_id,
                entity_type="manuscript",
                entity_id=manuscript.id,
                payload=payload,
                dedupe_key=dedupe_key,
                priority=40,
                max_attempts=3,
            )
            await self.audit(
                "create",
                "reference_validation_job",
                job_id,
                actor,
                {
                    "operation": "enqueue_reference_validation",
                    "manuscript_id": manuscript.id,
                    "literature_id": literature_id,
                },
            )
        status = await self.get_status(manuscript.id, job_id)
        if status is None:  # pragma: no cover - guards impossible queue drift
            raise RuntimeError(f"queued validation job {job_id} was not readable")
        return status

    async def get_status(
        self,
        manuscript_id: str,
        job_id: str,
    ) -> dict[str, Any] | None:
        """Read one validation job after enforcing canonical manuscript scope."""
        if (
            not isinstance(manuscript_id, str)
            or not manuscript_id
            or len(manuscript_id) > 128
            or not isinstance(job_id, str)
            or not job_id
            or len(job_id) > 128
        ):
            return None
        native = NativeManuscriptService(self.db, project_id=self.project_id)
        canonical_id = await native.resolve_id(manuscript_id)
        if canonical_id is None:
            return None
        job = await JobQueue(self.db).get(job_id, project_id=self.project_id)
        if (
            job is None
            or job["job_type"] != REFERENCE_VALIDATE_JOB
            or job.get("entity_type") != "manuscript"
            or job.get("entity_id") != canonical_id
        ):
            return None
        payload = job.get("payload") or {}
        response: dict[str, Any] = {
            "job_id": job["id"],
            "status": job["status"],
            "canonical_manuscript_id": canonical_id,
            "requested_manuscript_id": payload.get("requested_manuscript_id"),
            "attempts": int(job.get("attempts") or 0),
            "max_attempts": int(job.get("max_attempts") or 0),
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
            "completed_at": job.get("completed_at"),
        }
        if job["status"] == "completed":
            response["result"] = job.get("result")
        elif job["status"] == "failed":
            response["error"] = job.get("last_error")
        return response


class ReferenceValidationRunner(BaseService):
    """Execute the slow Writer pipeline and persist an immutable attestation."""

    def __init__(
        self,
        db: Database,
        *,
        project_id: str | None = None,
        script_path: Path | None = None,
        run_command: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        super().__init__(db=db, project_id=project_id)
        self.script_path = script_path or VALIDATE_REFERENCES_SCRIPT
        self.run_command = run_command or subprocess.run

    async def run_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Execute one claimed ``reference_validate`` job idempotently."""
        if job.get("job_type") != REFERENCE_VALIDATE_JOB:
            raise ValueError(f"Unsupported reference-validation job {job.get('job_type')!r}")
        if (
            job.get("project_id") != self.project_id
            or job.get("entity_type") != "manuscript"
        ):
            raise ValueError("Reference-validation job scope is inconsistent")
        existing = await self.db.fetchone(
            """SELECT full_json_payload
               FROM reference_validation_attestations
               WHERE validation_job_id = ? AND project_id = ?""",
            [job["id"], self.project_id],
        )
        if existing is not None:
            payload = json.loads(existing["full_json_payload"])
            result = payload.get("result")
            if not isinstance(result, dict):
                raise ValueError(
                    f"Attestation for job {job['id']} has invalid result payload"
                )
            return result

        payload = job.get("payload")
        if not isinstance(payload, dict) or payload.get("schema") != (
            REFERENCE_VALIDATE_PAYLOAD_SCHEMA
        ):
            raise ValueError("Reference-validation job payload schema is invalid")
        if job.get("entity_id") != payload.get("canonical_manuscript_id"):
            raise ValueError("Reference-validation job manuscript identity is inconsistent")
        reference = payload.get("reference")
        if not isinstance(reference, dict):
            raise ValueError("Reference-validation job reference is invalid")
        if (
            job.get("status") != "running"
            or not job.get("worker_id")
            or not job.get("lease_token")
        ):
            raise JobLeaseLost(
                f"Reference-validation job {job['id']} is not actively claimed"
            )
        reference = normalize_reference_input(reference)
        return await self.validate(
            reference,
            manuscript_id=str(payload["canonical_manuscript_id"]),
            requested_manuscript_id=str(
                payload.get("requested_manuscript_id")
                or payload["canonical_manuscript_id"]
            ),
            legacy_journal_id=payload.get("legacy_journal_id"),
            literature_id=payload.get("literature_id"),
            validation_job_id=job["id"],
            validation_worker_id=str(job["worker_id"]),
            validation_lease_token=str(job["lease_token"]),
            preserve_requested_id=False,
        )

    async def validate(
        self,
        reference: dict[str, Any],
        *,
        manuscript_id: str,
        requested_manuscript_id: str | None = None,
        legacy_journal_id: str | None = None,
        literature_id: str | None = None,
        validation_job_id: str | None = None,
        validation_worker_id: str | None = None,
        validation_lease_token: str | None = None,
        preserve_requested_id: bool = False,
    ) -> dict[str, Any]:
        """Run and attest one validation after re-checking all durable scope."""
        reference = normalize_reference_input(reference)
        manuscript_id = _require_bounded_id(manuscript_id, label="manuscript_id")
        if requested_manuscript_id is not None:
            requested_manuscript_id = _require_bounded_id(
                requested_manuscript_id,
                label="requested_manuscript_id",
            )
        if legacy_journal_id is not None:
            legacy_journal_id = _require_bounded_id(
                legacy_journal_id,
                label="legacy_journal_id",
            )
        if literature_id is not None:
            literature_id = _require_bounded_id(
                literature_id,
                label="literature_id",
            )
        if validation_job_id is not None:
            validation_job_id = _require_bounded_id(
                validation_job_id,
                label="validation_job_id",
            )
            validation_worker_id = _require_bounded_id(
                validation_worker_id or "",
                label="validation_worker_id",
            )
            validation_lease_token = _require_bounded_id(
                validation_lease_token or "",
                label="validation_lease_token",
            )
        elif validation_worker_id is not None or validation_lease_token is not None:
            raise ValueError("Validation lease proof requires validation_job_id")
        native = NativeManuscriptService(self.db, project_id=self.project_id)
        manuscript = await native.get(manuscript_id)
        if manuscript is None:
            raise ValueError(
                f"Manuscript {manuscript_id} does not belong to project "
                f"{self.project_id}"
            )
        canonical_id = manuscript.id
        requested_id = requested_manuscript_id or manuscript_id
        resolved_requested = await native.resolve_id(requested_id)
        if resolved_requested != canonical_id:
            raise ValueError(
                "Requested manuscript alias no longer resolves to the queued "
                "canonical manuscript"
            )
        actual_legacy_id = legacy_journal_id or manuscript.legacy_journal_id
        if actual_legacy_id is not None and actual_legacy_id != manuscript.legacy_journal_id:
            raise ValueError("Queued legacy manuscript alias is inconsistent")
        if literature_id is not None:
            literature = await self.db.fetchone(
                """SELECT id, doi, title FROM literature
                   WHERE id = ? AND project_id = ?""",
                [literature_id, self.project_id],
            )
            if literature is None:
                raise ValueError(
                    f"Literature {literature_id} does not belong to project "
                    f"{self.project_id}"
                )
            _require_reference_literature_identity(reference, dict(literature))

        validation_id = generate_id("reference_validation")
        started_at = _precise_now()
        input_doi = reference.get("DOI") or reference.get("doi")
        input_title = reference.get("title")
        input_authors = reference.get("author") or []
        usable_author_families = [
            author.get("family")
            for author in input_authors
            if isinstance(author, dict) and author.get("family")
        ]
        retraction_check_enabled = True
        attested_id = requested_id if preserve_requested_id else canonical_id

        async def finalize(
            response: dict[str, Any],
            *,
            validator_audit: dict[str, Any] | None = None,
            stage_trace: dict[str, Any] | None = None,
            subprocess_details: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            trace = stage_trace or unreached_stage_trace(
                check_retraction=retraction_check_enabled,
                check_disambiguation=bool(usable_author_families),
            )
            retraction_stage = trace.get("D_retraction", {})
            retraction_checked = bool(
                isinstance(retraction_stage, dict)
                and retraction_stage.get("enabled") is True
                and retraction_stage.get("reached") is True
                and retraction_stage.get("completed") is True
            )
            result = _sanitize_verdict(response)
            result["identifier"] = input_doi or input_title
            result_identity = {
                "validation_id": validation_id,
                "manuscript_id": attested_id,
                "canonical_manuscript_id": canonical_id,
                "requested_manuscript_id": requested_id,
                "retraction_check_enabled": retraction_check_enabled,
                "retraction_checked": retraction_checked,
                "stage_trace": trace,
                "stage_trace_schema": STAGE_TRACE_SCHEMA,
            }
            result.update(result_identity)
            if validation_job_id is not None:
                result["job_id"] = validation_job_id
            if actual_legacy_id is not None:
                result["legacy_journal_id"] = actual_legacy_id
            if literature_id is not None:
                result["literature_id"] = literature_id
            result_bytes = json.dumps(
                result,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            if len(result_bytes) > MAX_DURABLE_RESULT_BYTES:
                result = {
                    "status": "error",
                    "message": (
                        "sanitized validator result exceeds durable size limit"
                    ),
                    "identifier": input_doi or input_title,
                    "sources_tried": [],
                    "sources_confirmed": [],
                    "notes": [],
                    **result_identity,
                }
                if validation_job_id is not None:
                    result["job_id"] = validation_job_id
                if actual_legacy_id is not None:
                    result["legacy_journal_id"] = actual_legacy_id
                if literature_id is not None:
                    result["literature_id"] = literature_id

            notes = result.get("notes")
            if not isinstance(notes, list):
                notes = [result["message"]] if result.get("message") else []
            sources_tried = result.get("sources_tried")
            if not isinstance(sources_tried, list):
                sources_tried = []
            sources_confirmed = result.get("sources_confirmed")
            if not isinstance(sources_confirmed, list):
                sources_confirmed = []
            sanitized_audit = _sanitize_validator_audit(validator_audit)
            full_payload = {
                "input": reference,
                "validator_audit": sanitized_audit,
                "subprocess": subprocess_details,
                "result": result,
            }
            pipeline_version = (
                sanitized_audit.get("pipeline_version")
                if isinstance(sanitized_audit, dict)
                else None
            )
            async with self.db.transaction():
                if literature_id is not None:
                    current_literature = await self.db.fetchone(
                        """SELECT id, doi, title FROM literature
                           WHERE id = ? AND project_id = ?""",
                        [literature_id, self.project_id],
                    )
                    if current_literature is None:
                        raise ValueError(
                            "Bound literature was removed before validation "
                            "attestation"
                        )
                    _require_reference_literature_identity(
                        reference,
                        dict(current_literature),
                    )
                insert_sql = """INSERT OR IGNORE INTO reference_validation_attestations
                   (id, project_id, manuscript_id, canonical_manuscript_id,
                    legacy_journal_id, validation_job_id, literature_id,
                    input_doi, input_title, input_authors, status,
                    retraction_check_enabled, retraction_checked,
                    sources_tried, sources_confirmed, notes, stage_trace,
                    full_json_payload, pipeline_version, started_at, completed_at)
                   SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?"""
                insert_params: list[Any] = [
                        validation_id,
                        self.project_id,
                        attested_id,
                        canonical_id,
                        actual_legacy_id,
                        validation_job_id,
                        literature_id,
                        input_doi,
                        input_title,
                        json.dumps(
                            input_authors,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        str(result.get("status", "error")),
                        int(retraction_check_enabled),
                        int(retraction_checked),
                        json.dumps(sources_tried, sort_keys=True),
                        json.dumps(sources_confirmed, sort_keys=True),
                        json.dumps(notes, sort_keys=True),
                        json.dumps(trace, sort_keys=True),
                        json.dumps(
                            full_payload,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        pipeline_version,
                        started_at,
                        _precise_now(),
                    ]
                if validation_job_id is not None:
                    insert_sql += """
                       WHERE EXISTS (
                           SELECT 1
                           FROM jobs
                           WHERE id = ?
                             AND project_id = ?
                             AND status = 'running'
                             AND worker_id = ?
                             AND lease_token = ?
                             AND lease_until IS NOT NULL
                             AND lease_until > ?
                       )"""
                    insert_params.extend(
                        [
                            validation_job_id,
                            self.project_id,
                            validation_worker_id,
                            validation_lease_token,
                            _precise_now(),
                        ]
                    )
                cursor = await self.db.execute(insert_sql, insert_params)
                if cursor.rowcount != 1:
                    existing = None
                    if validation_job_id is not None:
                        existing = await self.db.fetchone(
                            """SELECT full_json_payload
                               FROM reference_validation_attestations
                               WHERE validation_job_id = ? AND project_id = ?""",
                            [validation_job_id, self.project_id],
                        )
                    if existing is None and validation_job_id is not None:
                        raise JobLeaseLost(
                            f"Reference-validation job {validation_job_id} "
                            "lease was superseded before attestation"
                        )
                    if existing is None:
                        raise RuntimeError(
                            "Reference-validation attestation id collision"
                        )
                    winner_payload = json.loads(existing["full_json_payload"])
                    winner = winner_payload.get("result")
                    if not isinstance(winner, dict):
                        raise RuntimeError(
                            "Reference-validation winner has invalid result"
                        )
                    return winner
            return result

        if not self.script_path.exists():
            return await finalize(
                {
                    "status": "error",
                    "message": "reference validator script is unavailable",
                }
            )

        python_bin = sys.executable or shutil.which("python3") or "python3"
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "refs.json"
            audit_path = tmp_path / "refs.audit.json"
            bib_path = tmp_path / "verified-references.bib"
            input_path.write_text(json.dumps([reference]), encoding="utf-8")
            cmd = [
                python_bin,
                str(self.script_path),
                "--validate",
                str(input_path),
                "--audit-out",
                str(audit_path),
                "--bib-out",
                str(bib_path),
            ]
            if usable_author_families:
                cmd.append("--check-disambiguation")
            try:
                completed = await asyncio.to_thread(
                    self.run_command,
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                return await finalize(
                    {
                        "status": "error",
                        "message": (
                            "validate_references subprocess error: "
                            f"{type(exc).__name__}"
                        ),
                    },
                    subprocess_details=_subprocess_metadata(cmd, error=exc),
                )

            if completed.returncode not in {0, 1}:
                return await finalize(
                    {
                        "status": "error",
                        "message": "reference validator exited unsuccessfully",
                        "exit_code": completed.returncode,
                    },
                    subprocess_details=_subprocess_metadata(
                        cmd,
                        completed=completed,
                    ),
                )
            if not audit_path.exists():
                process_metadata = _subprocess_metadata(cmd, completed=completed)
                return await finalize(
                    {
                        "status": "error",
                        "message": "validate_references did not write audit output",
                        "exit_code": completed.returncode,
                        "stdout_chars": process_metadata["stdout_chars"],
                        "stderr_chars": process_metadata["stderr_chars"],
                    },
                    subprocess_details=process_metadata,
                )
            audit_size = audit_path.stat().st_size
            if audit_size > MAX_VALIDATOR_AUDIT_BYTES:
                process_metadata = _subprocess_metadata(cmd, completed=completed)
                process_metadata["audit_bytes"] = audit_size
                return await finalize(
                    {
                        "status": "error",
                        "message": "reference validator audit exceeds size limit",
                    },
                    subprocess_details=process_metadata,
                )
            audit_bytes = audit_path.read_bytes()
            try:
                audit_text = audit_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                return await finalize(
                    {
                        "status": "error",
                        "message": "reference validator audit is not UTF-8",
                    },
                    subprocess_details=_subprocess_metadata(
                        cmd,
                        completed=completed,
                        error=exc,
                    ),
                )
            try:
                payload = json.loads(audit_text)
            except (json.JSONDecodeError, RecursionError) as exc:
                return await finalize(
                    {
                        "status": "error",
                        "message": "reference validator audit JSON is malformed",
                    },
                    subprocess_details=_subprocess_metadata(
                        cmd,
                        completed=completed,
                        error=exc,
                        audit_text=audit_text,
                    ),
                )
            if not isinstance(payload, dict):
                return await finalize(
                    {
                        "status": "error",
                        "message": "validate_references audit root is not an object",
                    },
                    subprocess_details=_subprocess_metadata(
                        cmd,
                        completed=completed,
                        audit_text=audit_text,
                    ),
                )

        verdicts = payload.get("refs", [])
        subprocess_details = _subprocess_metadata(cmd, completed=completed)
        if not verdicts:
            return await finalize(
                {
                    "status": "error",
                    "message": "validate_references returned no verdicts",
                },
                validator_audit=payload,
                subprocess_details=subprocess_details,
            )
        if not isinstance(verdicts, list) or not isinstance(verdicts[0], dict):
            return await finalize(
                {
                    "status": "error",
                    "message": "validate_references returned an invalid verdict",
                },
                validator_audit=payload,
                subprocess_details=subprocess_details,
            )
        verdict = dict(verdicts[0])
        verdict["serpapi_budget"] = payload.get("serpapi_budget", 0)
        verdict["serpapi_credits_used"] = payload.get("serpapi_credits_used", 0)
        emitted_trace = verdict.get("stage_trace")
        trace_configuration_matches = bool(
            isinstance(emitted_trace, dict)
            and isinstance(emitted_trace.get("D_retraction"), dict)
            and emitted_trace["D_retraction"].get("enabled") is True
            and isinstance(emitted_trace.get("E_author_disambiguation"), dict)
            and emitted_trace["E_author_disambiguation"].get("enabled")
            is bool(usable_author_families)
        )
        if (
            payload.get("stage_trace_schema") != STAGE_TRACE_SCHEMA
            or not stage_trace_is_closed(emitted_trace)
            or not trace_configuration_matches
        ):
            return await finalize(
                {
                    "status": "error",
                    "message": "validate_references returned an invalid stage trace",
                },
                validator_audit=payload,
                subprocess_details=subprocess_details,
            )
        return await finalize(
            verdict,
            validator_audit=payload,
            stage_trace=emitted_trace,
            subprocess_details=subprocess_details,
        )
