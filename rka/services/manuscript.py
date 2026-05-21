"""Manuscript service: Option 2 manifest model (jrn_ tagged 'manuscript').

Phase 3 deliverable per dec_01KS2WPKMRVSJ2R0PP74722PEH (bookkeeper-exempt
addition). Wraps the existing NoteService surface so manuscripts are
stored as journal entries with tags=['manuscript', f'venue:{venue}',
'phase:draft|review|final'] per the Option 2 representation ratified in
dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D Q1.

Three operations:
  register(venue, title, abstract, sections): creates a new manuscript
    manifest as a journal entry.
  get(manuscript_id): reads a manuscript manifest; returns None if the
    journal entry is not tagged 'manuscript'.
  validate_reference(reference, manuscript_id): proxies to the Writer
    skill's scripts/validate_references.py Stage B-G full pipeline via
    subprocess; returns the first ReferenceVerdict.
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
from rka.models.journal import JournalEntry, JournalEntryCreate
from rka.services.base import BaseService
from rka.services.notes import NoteService

logger = logging.getLogger(__name__)


# Path to the Writer skill's validate_references.py (Phase 2 Stage B-G).
_VALIDATE_REFERENCES_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills" / "writer" / "scripts" / "validate_references.py"
)


class ManuscriptService(BaseService):
    """Manuscript manifest CRUD wrapping NoteService.

    Per dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D Q1 Option 2: manuscripts are jrn_
    entries with tags=['manuscript', f'venue:{venue}', 'phase:<phase>'].
    No new entity type; no schema migration.
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
        manuscript_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate a single reference via the Writer's Stage B-G pipeline.

        Proxies to scripts/validate_references.py via subprocess. Writes
        the input reference dict to a temp file as a single-element list
        (the script expects a list of CSL-JSON records), invokes
        --validate, and returns the parsed audit payload.

        The reference dict should carry at least one of:
          - DOI: identifier-based lookup (preferred)
          - title: title-based search fallback
        Plus optional author list, year, venue.

        Returns a dict with status / sources_tried / sources_confirmed /
        notes / serpapi_budget accounting per the validate_references
        contract. On script-not-found or subprocess error, returns
        status='error' with a diagnostic message.
        """
        if not _VALIDATE_REFERENCES_SCRIPT.exists():
            return {
                "status": "error",
                "message": f"validate_references.py not found at {_VALIDATE_REFERENCES_SCRIPT}",
            }

        python_bin = sys.executable or shutil.which("python3") or "python3"
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "refs.json"
            audit_path = tmp_path / "refs.audit.json"
            input_path.write_text(json.dumps([reference]), encoding="utf-8")

            cmd = [
                python_bin,
                str(_VALIDATE_REFERENCES_SCRIPT),
                "--validate", str(input_path),
                "--audit-out", str(audit_path),
                "--no-retraction",
            ]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                return {
                    "status": "error",
                    "message": f"validate_references subprocess error: {exc}",
                }

            if not audit_path.exists():
                return {
                    "status": "error",
                    "message": "validate_references did not write audit output",
                    "stdout": result.stdout[:500],
                    "stderr": result.stderr[:500],
                    "exit_code": result.returncode,
                }

            try:
                payload = json.loads(audit_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return {
                    "status": "error",
                    "message": f"audit JSON parse: {exc}",
                }

        # Return the first verdict (we sent one reference).
        verdicts = payload.get("refs", [])
        if not verdicts:
            return {
                "status": "error",
                "message": "validate_references returned no verdicts",
                "raw_audit": payload,
            }
        verdict = verdicts[0]
        verdict["serpapi_budget"] = payload.get("serpapi_budget", 0)
        verdict["serpapi_credits_used"] = payload.get("serpapi_credits_used", 0)
        if manuscript_id:
            verdict["manuscript_id"] = manuscript_id
        return verdict
