"""Manuscript service: Option 2 manifest model (jrn_ tagged 'manuscript').

Phase 3 deliverable per dec_01KS2WPKMRVSJ2R0PP74722PEH (bookkeeper-exempt
addition). Wraps the existing NoteService surface so manuscripts are
stored as journal entries with tags=['manuscript', f'venue:{venue}',
'phase:draft|review|final'] per the Option 2 representation ratified in
dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D Q1.

Three operational surfaces:
  register(venue, title, abstract, sections): creates a new manuscript
    manifest as a journal entry.
  get(manuscript_id): reads a manuscript manifest; returns None if the
    journal entry is not tagged 'manuscript'.
  validate_reference(reference, manuscript_id): proxies to the Writer
    skill's scripts/validate_references.py Stage B-G full pipeline via
    subprocess; returns the first ReferenceVerdict and appends an immutable
    reference-validation attestation (migration 032).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from rka.infra.database import Database
from rka.infra.ids import generate_id
from rka.models.journal import JournalEntry, JournalEntryCreate
from rka.services.base import BaseService, _now
from rka.services.notes import NoteService

logger = logging.getLogger(__name__)


# Path to the Writer skill's validate_references.py (Phase 2 Stage B-G).
_VALIDATE_REFERENCES_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills" / "writer" / "scripts" / "validate_references.py"
)

_STAGE_TRACE_SCHEMA = "rka.reference-validation.stage-trace.v1"
_STAGE_TRACE_KEYS = {
    "A_extraction",
    "B_source_resolution",
    "C_cross_source_confirmation",
    "D_retraction",
    "E_author_disambiguation",
    "F_bibliography_compile",
    "G_niche_rescue",
}
_STAGE_TRACE_OUTCOMES = {
    "disabled",
    "not_reached",
    "passed",
    "inconclusive",
    "rejected",
    "unavailable",
    "error",
}


def _stage_trace_is_closed(trace: Any) -> bool:
    """Validate the native Writer stage-trace schema without inference."""
    if not isinstance(trace, dict) or set(trace) != _STAGE_TRACE_KEYS:
        return False
    for record in trace.values():
        if not isinstance(record, dict) or set(record) != {
            "enabled", "reached", "completed", "outcome",
        }:
            return False
        if not all(isinstance(record[key], bool) for key in (
            "enabled", "reached", "completed",
        )):
            return False
        if record["outcome"] not in _STAGE_TRACE_OUTCOMES:
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
            "disabled", "not_reached", "unavailable", "error",
        }:
            return False
        elif not record["completed"] and record["outcome"] in {"passed", "rejected"}:
            return False
    return True


def _unreached_stage_trace(
    *,
    check_retraction: bool,
    check_disambiguation: bool,
) -> dict[str, dict[str, bool | str]]:
    """Trace used only when the validator emitted no audit at all."""
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


class ManuscriptService(BaseService):
    """Manuscript manifest CRUD wrapping NoteService.

    Per dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D Q1 Option 2: manuscripts are jrn_
    entries with tags=['manuscript', f'venue:{venue}', 'phase:<phase>'].
    Manuscript identity remains a jrn_ manifest; migration 032 only adds an
    immutable audit table for reference-validation attempts.
    """

    def __init__(
        self,
        db: Database,
        *,
        notes: NoteService | None = None,
        project_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(db=db, project_id=project_id, **kwargs)
        self._notes = notes or NoteService(db, project_id=project_id)

    async def register(
        self,
        venue: str,
        title: str,
        *,
        abstract: str | None = None,
        sections: list[str] | None = None,
        actor: str = "executor",
    ) -> JournalEntry:
        """Create a new manuscript manifest as a journal entry.

        Tags = ['manuscript', f'venue:{venue}', 'phase:draft'].
        verbatim_input carries the title and abstract verbatim per the
        Option 2 schema (the PI's words; should not be paraphrased).
        """
        content_lines = [f"# Manuscript: {title}", "", "## Section index"]
        for sec in sections or []:
            content_lines.append(f"- {sec}: outlined")
        content = "\n".join(content_lines)

        verbatim = title if not abstract else f"{title}\n\n{abstract}"
        entry_data = JournalEntryCreate(
            content=content,
            type="note",
            source="executor",
            verbatim_input=verbatim,
            tags=["manuscript", f"venue:{venue}", "phase:draft"],
        )
        return await self._notes.create(entry_data, actor=actor)

    async def get(self, manuscript_id: str) -> dict[str, Any] | None:
        """Read a manuscript manifest.

        Returns None if the journal entry does not exist OR if it is not
        tagged 'manuscript' (which means it is a regular journal entry,
        not a Writer manifest).
        """
        entry = await self._notes.get(manuscript_id)
        if entry is None:
            return None
        tags = getattr(entry, "tags", None) or []
        if "manuscript" not in tags:
            return None

        title = ""
        abstract = ""
        if entry.verbatim_input:
            parts = entry.verbatim_input.split("\n\n", 1)
            title = parts[0].strip()
            if len(parts) == 2:
                abstract = parts[1].strip()

        venue = None
        phase = None
        for tag in tags:
            if tag.startswith("venue:"):
                venue = tag.split(":", 1)[1]
            elif tag.startswith("phase:"):
                phase = tag.split(":", 1)[1]

        return {
            "id": entry.id,
            "project_id": entry.project_id,
            "title": title,
            "abstract": abstract,
            "venue": venue,
            "phase": phase,
            "content": entry.content,
            "tags": tags,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
        }

    async def validate_reference(
        self,
        reference: dict[str, Any],
        *,
        manuscript_id: str,
        literature_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate and immutably attest one manuscript reference.

        Proxies to scripts/validate_references.py via subprocess. Writes
        the input reference dict to a temp file as a single-element list
        (the script expects a list of CSL-JSON records), invokes
        --validate with retraction checking enabled, and returns the parsed
        audit verdict plus its ``rvd_`` attestation id.

        The reference dict should carry at least one of:
          - DOI: identifier-based lookup (preferred)
          - title: title-based search fallback
        Plus optional author list, year, venue.

        ``retraction_checked`` means Stage D was actually reached, not merely
        enabled. ``retraction_check_enabled`` records that the full pipeline
        was invoked without ``--no-retraction``. When authors are supplied,
        ``--check-disambiguation`` enables Stage E; ``stage_trace`` records
        which stages were reached so downstream users do not overclaim checks.

        Every returned verdict/error is appended to
        ``reference_validation_attestations``. Attestations are immutable at
        the SQLite layer. Invalid manuscript/literature scope is rejected
        before validation because it cannot be truthfully attested to the
        requested project.
        """

        manuscript = await self.get(manuscript_id)
        if manuscript is None:
            raise ValueError(
                f"Manuscript {manuscript_id} does not belong to project "
                f"{self.project_id} or is not tagged 'manuscript'"
            )
        if literature_id is not None:
            literature = await self.db.fetchone(
                "SELECT id FROM literature WHERE id = ? AND project_id = ?",
                [literature_id, self.project_id],
            )
            if literature is None:
                raise ValueError(
                    f"Literature {literature_id} does not belong to project "
                    f"{self.project_id}"
                )

        validation_id = generate_id("reference_validation")
        started_at = _now()
        input_doi = reference.get("DOI") or reference.get("doi")
        input_title = reference.get("title")
        input_authors = reference.get("author") or reference.get("authors") or []
        usable_author_families = [
            author.get("family")
            for author in input_authors
            if isinstance(author, dict) and author.get("family")
        ]
        retraction_check_enabled = True

        async def finalize(
            response: dict[str, Any],
            *,
            validator_audit: dict[str, Any] | None = None,
            stage_trace: dict[str, Any] | None = None,
            subprocess_details: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            trace = (
                stage_trace
                if stage_trace is not None
                else _unreached_stage_trace(
                    check_retraction=retraction_check_enabled,
                    check_disambiguation=bool(usable_author_families),
                )
            )
            retraction_stage = trace.get("D_retraction", {})
            retraction_checked = bool(
                isinstance(retraction_stage, dict)
                and retraction_stage.get("enabled") is True
                and retraction_stage.get("reached") is True
                and retraction_stage.get("completed") is True
            )
            completed_at = _now()
            result = dict(response)
            result.update({
                "validation_id": validation_id,
                "manuscript_id": manuscript_id,
                "retraction_check_enabled": retraction_check_enabled,
                "retraction_checked": retraction_checked,
                "stage_trace": trace,
                "stage_trace_schema": _STAGE_TRACE_SCHEMA,
            })
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

            full_payload = {
                "input": reference,
                "validator_audit": validator_audit,
                "subprocess": subprocess_details,
                "result": result,
            }
            pipeline_version = (
                validator_audit.get("pipeline_version")
                if isinstance(validator_audit, dict)
                else None
            )
            await self.db.execute(
                """INSERT INTO reference_validation_attestations
                   (id, project_id, manuscript_id, literature_id,
                    input_doi, input_title, input_authors, status,
                    retraction_check_enabled, retraction_checked,
                    sources_tried, sources_confirmed, notes, stage_trace,
                    full_json_payload, pipeline_version, started_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    validation_id,
                    self.project_id,
                    manuscript_id,
                    literature_id,
                    input_doi,
                    input_title,
                    json.dumps(input_authors, sort_keys=True, default=str),
                    str(result.get("status", "error")),
                    int(retraction_check_enabled),
                    int(retraction_checked),
                    json.dumps(sources_tried, sort_keys=True, default=str),
                    json.dumps(sources_confirmed, sort_keys=True, default=str),
                    json.dumps(notes, sort_keys=True, default=str),
                    json.dumps(trace, sort_keys=True),
                    json.dumps(full_payload, sort_keys=True, default=str),
                    pipeline_version,
                    started_at,
                    completed_at,
                ],
            )
            await self.db.commit()
            return result

        if not _VALIDATE_REFERENCES_SCRIPT.exists():
            return await finalize({
                "status": "error",
                "message": f"validate_references.py not found at {_VALIDATE_REFERENCES_SCRIPT}",
            })

        python_bin = sys.executable or shutil.which("python3") or "python3"
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "refs.json"
            audit_path = tmp_path / "refs.audit.json"
            bib_path = tmp_path / "verified-references.bib"
            input_path.write_text(json.dumps([reference]), encoding="utf-8")

            cmd = [
                python_bin,
                str(_VALIDATE_REFERENCES_SCRIPT),
                "--validate", str(input_path),
                "--audit-out", str(audit_path),
                "--bib-out", str(bib_path),
            ]
            if usable_author_families:
                cmd.append("--check-disambiguation")
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                return await finalize({
                    "status": "error",
                    "message": f"validate_references subprocess error: {exc}",
                }, subprocess_details={"command": cmd, "error": str(exc)})

            if not audit_path.exists():
                return await finalize({
                    "status": "error",
                    "message": "validate_references did not write audit output",
                    "stdout": result.stdout[:500],
                    "stderr": result.stderr[:500],
                    "exit_code": result.returncode,
                }, subprocess_details={
                    "command": cmd,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                })

            audit_text = audit_path.read_text(encoding="utf-8")
            try:
                payload = json.loads(audit_text)
            except json.JSONDecodeError as exc:
                return await finalize({
                    "status": "error",
                    "message": f"audit JSON parse: {exc}",
                }, subprocess_details={
                    "command": cmd,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "audit_text": audit_text,
                })

        # Return the first verdict (we sent one reference).
        verdicts = payload.get("refs", [])
        if not verdicts:
            return await finalize({
                "status": "error",
                "message": "validate_references returned no verdicts",
                "raw_audit": payload,
            }, validator_audit=payload, subprocess_details={
                "command": cmd,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            })
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
            payload.get("stage_trace_schema") != _STAGE_TRACE_SCHEMA
            or not _stage_trace_is_closed(emitted_trace)
            or not trace_configuration_matches
        ):
            return await finalize(
                {
                    "status": "error",
                    "message": "validate_references returned an invalid stage trace",
                    "raw_verdict": verdict,
                },
                validator_audit=payload,
                subprocess_details={
                    "command": cmd,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )
        return await finalize(
            verdict,
            validator_audit=payload,
            stage_trace=emitted_trace,
            subprocess_details={
                "command": cmd,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
