"""Conflict-safe local Markdown/LaTeX synchronization for native manuscripts."""

from __future__ import annotations

import asyncio
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from rka.config import RKAConfig
from rka.infra.ids import generate_id
from rka.models.manuscript_source import (
    ManuscriptSourceProposalCreate,
    ManuscriptSourceProposalTransition,
)
from rka.services.base import BaseService, _now
from rka.services.manuscript_native import ManuscriptNotFoundError, NativeManuscriptService


SOURCE_SCHEMA_VERSION = "rka.manuscript-source/v1"
SOURCE_PROPOSAL_SCHEMA_VERSION = "rka.manuscript-source-proposal/v1"
_SOURCE_SUFFIXES = {".md": "markdown", ".markdown": "markdown", ".tex": "latex"}
_SOURCE_STATUSES = {
    "proposed", "applied", "rejected", "conflicted", "superseded", "expired"
}
_MARKDOWN_ANCHOR_RE = re.compile(
    r"^\s*<!--\s*rka:unit\s+(mun_[0-9A-Z]+)\s+(begin|end)\s*-->\s*$"
)
_LATEX_ANCHOR_RE = re.compile(
    r"^\s*%\s*rka:unit\s+(mun_[0-9A-Z]+)\s+(begin|end)\s*$"
)
_MARKDOWN_PROVENANCE_RE = re.compile(
    r"<!--\s*rka:provenance\s+(.+?)\s*-->", re.IGNORECASE
)
_LATEX_PROVENANCE_RE = re.compile(r"%\s*rka:provenance\s+(.+?)\s*$", re.IGNORECASE)
_PROVENANCE_FIELD_RE = re.compile(r"(?:^|\s)(claim|evidence|citation)=([^\s>]+)")
_SAFE_STORAGE_COMPONENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class ManuscriptSourceNotFoundError(ValueError):
    """The manuscript, source file, or source proposal is absent."""


class ManuscriptSourceConflictError(ValueError):
    """The proposal or file optimistic guard is stale."""

    def __init__(
        self,
        message: str,
        *,
        transient_exchange: bool = False,
        recovery_state: str | None = None,
    ):
        super().__init__(message)
        self.transient_exchange = transient_exchange
        self.recovery_state = recovery_state


class ManuscriptSourceSecurityError(ValueError):
    """A workspace or relative path violates the local filesystem boundary."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _loads(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    return json.loads(value) if isinstance(value, str) else value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ManuscriptSourceService(BaseService):
    """Project-scoped source proposal, inspection, and recovery service."""

    def __init__(self, db, *, config: RKAConfig, project_id: str):
        super().__init__(db=db, project_id=project_id)
        self.config = config

    async def list_files(self, manuscript_id: str) -> dict[str, Any]:
        manuscript, workspace = await self._resolve_workspace(manuscript_id)
        files: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for root, dirs, names in os.walk(workspace, followlinks=False):
            root_path = Path(root)
            safe_dirs = []
            for name in sorted(dirs):
                candidate = root_path / name
                if name.startswith(".") or candidate.is_symlink():
                    continue
                safe_dirs.append(name)
            dirs[:] = safe_dirs
            for name in sorted(names):
                candidate = root_path / name
                suffix = candidate.suffix.lower()
                if name.startswith(".") or suffix not in _SOURCE_SUFFIXES:
                    continue
                relative = candidate.relative_to(workspace).as_posix()
                try:
                    snapshot = self._read_current(workspace, relative)
                except (OSError, UnicodeError, ValueError) as exc:
                    warnings.append(
                        {"relative_path": relative, "code": "SOURCE_UNREADABLE", "message": str(exc)}
                    )
                    continue
                if snapshot[0] is None:
                    continue
                files.append(
                    {
                        "relative_path": relative,
                        "source_format": _SOURCE_SUFFIXES[suffix],
                        "content_hash": _sha256(snapshot[0]),
                        "size_bytes": len(snapshot[0]),
                    }
                )
                if len(files) >= 500:
                    warnings.append(
                        {
                            "code": "SOURCE_FILE_CAP_REACHED",
                            "message": "Only the first 500 manuscript source files are listed.",
                        }
                    )
                    break
            if len(files) >= 500:
                break
        return {
            "schema_version": SOURCE_SCHEMA_VERSION,
            "project_id": self.project_id,
            "manuscript_id": manuscript["id"],
            "workspace_ref": manuscript["workspace_ref"],
            "files": files,
            "warnings": warnings,
        }

    async def read_file(self, manuscript_id: str, relative_path: str) -> dict[str, Any]:
        manuscript, workspace = await self._resolve_workspace(manuscript_id)
        normalized, source_format = self._normalize_source_path(relative_path)
        raw, mode = self._read_current(workspace, normalized)
        if raw is None:
            raise ManuscriptSourceNotFoundError(f"source file {normalized!r} not found")
        content = self._decode(raw)
        inspection = await self.inspect_content(
            manuscript["id"], normalized, source_format, content
        )
        return {
            "schema_version": SOURCE_SCHEMA_VERSION,
            "project_id": self.project_id,
            "manuscript_id": manuscript["id"],
            "relative_path": normalized,
            "source_format": source_format,
            "content": content,
            "content_hash": _sha256(raw),
            "size_bytes": len(raw),
            "mode": mode,
            **inspection,
        }

    async def get_overview(self, manuscript_id: str) -> dict[str, Any]:
        manuscript, _ = await self._resolve_workspace(manuscript_id)
        listing = await self.list_files(manuscript["id"])
        anchor_locations: dict[str, list[dict[str, Any]]] = defaultdict(list)
        file_summaries: list[dict[str, Any]] = []
        for item in listing["files"]:
            snapshot = await self.read_file(manuscript["id"], item["relative_path"])
            file_summaries.append(
                {
                    **item,
                    "anchor_count": len(snapshot["anchors"]),
                    "finding_count": len(snapshot["findings"]),
                    "blocking": any(
                        finding["severity"] == "error" for finding in snapshot["findings"]
                    ),
                }
            )
            for anchor in snapshot["anchors"]:
                anchor_locations[anchor["unit_id"]].append(
                    {
                        "relative_path": item["relative_path"],
                        "start_line": anchor["start_line"],
                        "end_line": anchor["end_line"],
                        "content_hash": anchor["content_hash"],
                    }
                )

        context = await NativeManuscriptService(
            self.db, project_id=self.project_id
        ).get_context(manuscript["id"])
        claims = {claim["id"]: claim for claim in context["claims"]}
        active_units = [unit for unit in context["units"] if unit["status"] != "removed"]
        allocated_adverse_by_role = {
            role: {
                str(binding["evidence_claim_id"])
                for unit in active_units
                for binding in unit.get("evidence", [])
                if binding.get("role") == role
            }
            for role in ("qualifier", "counterevidence")
        }
        quick_reader = []
        private_risks: list[dict[str, Any]] = []
        for unit in sorted(active_units, key=lambda value: (value["sequence"], value["id"])):
            unit_claims = [
                claim
                for claim in claims.values()
                if any(link["unit_id"] == unit["id"] for link in claim.get("unit_links", []))
            ]
            quick_reader.append(
                {
                    "unit_id": unit["id"],
                    "local_key": unit["local_key"],
                    "title": unit.get("title"),
                    "communicative_job": unit.get("communicative_job"),
                    "intended_takeaway": unit.get("intended_takeaway"),
                    "quick_reader_role": unit.get("quick_reader_role"),
                    "anchors": anchor_locations.get(unit["id"], []),
                    "anchor_state": "linked" if anchor_locations.get(unit["id"]) else "missing",
                }
            )
            for claim in unit_claims:
                if claim.get("prohibited_wording"):
                    private_risks.append(
                        {
                            "kind": "claim_boundary",
                            "unit_id": unit["id"],
                            "claim_id": claim["id"],
                            "items": claim["prohibited_wording"],
                            "message": "Prohibited wording is private review context, not draft prose.",
                        }
                    )
                for binding in claim.get("evidence", []):
                    role = binding.get("role")
                    evidence_claim_id = str(binding.get("evidence_claim_id"))
                    if (
                        role in allocated_adverse_by_role
                        and evidence_claim_id not in allocated_adverse_by_role[role]
                    ):
                        private_risks.append(
                            {
                                "kind": f"unallocated_{role}",
                                "unit_id": unit["id"],
                                "claim_id": claim["id"],
                                "evidence_claim_id": evidence_claim_id,
                                "content": binding.get("content"),
                                "message": (
                                    "Claim-level adverse evidence is not allocated to an "
                                    "active manuscript unit and requires deliberate treatment."
                                ),
                            }
                        )
            for binding in unit.get("evidence", []):
                if binding["role"] in {"qualifier", "counterevidence"}:
                    private_risks.append(
                        {
                            "kind": binding["role"],
                            "unit_id": unit["id"],
                            "evidence_claim_id": binding["evidence_claim_id"],
                            "content": binding.get("content"),
                            "message": "Adverse evidence requires deliberate treatment.",
                        }
                    )
            for citation in unit.get("citations", []):
                if (
                    citation.get("verification_state") != "verified"
                    or not citation.get("verification_current", False)
                ):
                    private_risks.append(
                        {
                            "kind": "citation_verification",
                            "unit_id": unit["id"],
                            "citation_key": citation["citation_key"],
                            "verification_state": citation.get("verification_state"),
                            "verification_current": bool(
                                citation.get("verification_current", False)
                            ),
                            "message": "Citation use is not currently verified.",
                        }
                    )
        return {
            "schema_version": SOURCE_SCHEMA_VERSION,
            "project_id": self.project_id,
            "manuscript_id": manuscript["id"],
            "workspace_ref": manuscript["workspace_ref"],
            "files": file_summaries,
            "warnings": listing["warnings"],
            "quick_reader": quick_reader,
            "private_reviewer_risks": private_risks,
            "public_private_boundary": {
                "draft_source": "public authoring artifact",
                "private_reviewer_risks": "private planning context; never copied automatically",
            },
        }

    async def inspect_content(
        self,
        manuscript_id: str,
        relative_path: str,
        source_format: str,
        content: str,
    ) -> dict[str, Any]:
        lines = content.splitlines(keepends=True)
        anchor_re = _MARKDOWN_ANCHOR_RE if source_format == "markdown" else _LATEX_ANCHOR_RE
        provenance_re = (
            _MARKDOWN_PROVENANCE_RE if source_format == "markdown" else _LATEX_PROVENANCE_RE
        )
        findings: list[dict[str, Any]] = []
        internal_anchors: list[dict[str, Any]] = []
        opened: tuple[str, int] | None = None
        for index, line in enumerate(lines):
            match = anchor_re.match(line.rstrip("\r\n"))
            if match is None:
                continue
            unit_id, action = match.groups()
            if action == "begin":
                if opened is not None:
                    findings.append(
                        {
                            "severity": "error",
                            "code": "NESTED_UNIT_ANCHOR",
                            "message": f"unit anchor {unit_id} begins inside {opened[0]}",
                            "line": index + 1,
                        }
                    )
                else:
                    opened = (unit_id, index)
                continue
            if opened is None:
                findings.append(
                    {
                        "severity": "error",
                        "code": "UNMATCHED_UNIT_ANCHOR_END",
                        "message": f"unit anchor {unit_id} ends without a begin marker",
                        "line": index + 1,
                    }
                )
                continue
            if opened[0] != unit_id:
                findings.append(
                    {
                        "severity": "error",
                        "code": "MISMATCHED_UNIT_ANCHOR",
                        "message": f"unit anchor {opened[0]} closes as {unit_id}",
                        "line": index + 1,
                    }
                )
                opened = None
                continue
            body = "".join(lines[opened[1] + 1:index])
            internal_anchors.append(
                {
                    "unit_id": unit_id,
                    "start_line": opened[1] + 1,
                    "content_start_line": opened[1] + 2,
                    "content_end_line": index,
                    "end_line": index + 1,
                    "content_hash": _sha256(body.encode("utf-8")),
                    "_body_start": opened[1] + 1,
                    "_body_end": index,
                }
            )
            opened = None
        if opened is not None:
            findings.append(
                {
                    "severity": "error",
                    "code": "UNCLOSED_UNIT_ANCHOR",
                    "message": f"unit anchor {opened[0]} has no end marker",
                    "line": opened[1] + 1,
                }
            )
        duplicates = [
            unit_id
            for unit_id, count in Counter(anchor["unit_id"] for anchor in internal_anchors).items()
            if count > 1
        ]
        for unit_id in sorted(duplicates):
            findings.append(
                {
                    "severity": "error",
                    "code": "DUPLICATE_UNIT_ANCHOR",
                    "message": f"unit {unit_id} appears in more than one range in this file",
                    "unit_id": unit_id,
                }
            )

        units = await self.db.fetchall(
            """SELECT id, local_key, status FROM manuscript_units
               WHERE manuscript_id = ? AND project_id = ?""",
            [manuscript_id, self.project_id],
        )
        unit_map = {row["id"]: dict(row) for row in units}
        claim_rows = await self.db.fetchall(
            """SELECT cu.unit_id, cu.manuscript_claim_id
               FROM manuscript_claim_units AS cu
               WHERE cu.manuscript_id = ? AND cu.project_id = ?""",
            [manuscript_id, self.project_id],
        )
        evidence_rows = await self.db.fetchall(
            """SELECT unit_id, evidence_claim_id FROM manuscript_unit_evidence
               WHERE manuscript_id = ? AND project_id = ?""",
            [manuscript_id, self.project_id],
        )
        citation_rows = await self.db.fetchall(
            """SELECT uc.unit_id, mr.citation_key
               FROM manuscript_unit_citations AS uc
               JOIN manuscript_reference_members AS mr
                 ON mr.id = uc.reference_member_id AND mr.project_id = uc.project_id
               WHERE uc.manuscript_id = ? AND uc.project_id = ?""",
            [manuscript_id, self.project_id],
        )
        claims_by_unit: dict[str, set[str]] = defaultdict(set)
        evidence_by_unit: dict[str, set[str]] = defaultdict(set)
        citations_by_unit: dict[str, set[str]] = defaultdict(set)
        for row in claim_rows:
            claims_by_unit[row["unit_id"]].add(row["manuscript_claim_id"])
        for row in evidence_rows:
            evidence_by_unit[row["unit_id"]].add(row["evidence_claim_id"])
        for row in citation_rows:
            citations_by_unit[row["unit_id"]].add(row["citation_key"])

        provenance: list[dict[str, Any]] = []
        for anchor in internal_anchors:
            unit_id = anchor["unit_id"]
            unit = unit_map.get(unit_id)
            if unit is None:
                findings.append(
                    {
                        "severity": "error",
                        "code": "FOREIGN_OR_UNKNOWN_UNIT_ANCHOR",
                        "message": f"unit {unit_id} does not belong to this manuscript",
                        "unit_id": unit_id,
                    }
                )
            elif unit["status"] == "removed":
                findings.append(
                    {
                        "severity": "error",
                        "code": "REMOVED_UNIT_ANCHOR",
                        "message": f"unit {unit_id} is removed from the active outline",
                        "unit_id": unit_id,
                    }
                )
            anchor_refs = 0
            for line_number in range(anchor["_body_start"], anchor["_body_end"]):
                line = lines[line_number].rstrip("\r\n")
                for match in provenance_re.finditer(line):
                    fields = _PROVENANCE_FIELD_RE.findall(match.group(1))
                    if not fields:
                        findings.append(
                            {
                                "severity": "error",
                                "code": "EMPTY_PROVENANCE_COMMENT",
                                "message": "provenance comment has no claim, evidence, or citation field",
                                "unit_id": unit_id,
                                "line": line_number + 1,
                            }
                        )
                        continue
                    anchor_refs += len(fields)
                    for kind, value in fields:
                        allowed = (
                            claims_by_unit[unit_id]
                            if kind == "claim"
                            else evidence_by_unit[unit_id]
                            if kind == "evidence"
                            else citations_by_unit[unit_id]
                        )
                        verified = value in allowed
                        item = {
                            "unit_id": unit_id,
                            "kind": kind,
                            "value": value,
                            "line": line_number + 1,
                            "verified": verified,
                        }
                        provenance.append(item)
                        if not verified:
                            findings.append(
                                {
                                    "severity": "error",
                                    "code": "UNBOUND_PROVENANCE_REFERENCE",
                                    "message": f"{kind} {value!r} is not currently bound to unit {unit_id}",
                                    **item,
                                }
                            )
            if (
                unit is not None
                and unit["status"] != "removed"
                and anchor_refs == 0
                and (
                    claims_by_unit[unit_id]
                    or evidence_by_unit[unit_id]
                    or citations_by_unit[unit_id]
                )
            ):
                findings.append(
                    {
                        "severity": "warning",
                        "code": "PROVENANCE_COMMENT_MISSING",
                        "message": f"unit {unit_id} has semantic bindings but no provenance comment",
                        "unit_id": unit_id,
                    }
                )

        anchors = [
            {key: value for key, value in anchor.items() if not key.startswith("_")}
            for anchor in internal_anchors
        ]
        if not anchors:
            findings.append(
                {
                    "severity": "warning",
                    "code": "NO_UNIT_ANCHORS",
                    "message": f"{relative_path} is not yet linked to a manuscript unit",
                }
            )
        return {
            "anchors": anchors,
            "provenance": provenance,
            "findings": findings,
        }

    async def create_proposal(
        self,
        manuscript_id: str,
        data: ManuscriptSourceProposalCreate,
    ) -> dict[str, Any]:
        manuscript, workspace = await self._resolve_workspace(manuscript_id)
        relative_path, source_format = self._normalize_source_path(data.relative_path)
        proposed = data.content.encode("utf-8")
        self._assert_size(proposed)
        async with self._source_lock(manuscript["id"], relative_path):
            current, _ = self._read_current(workspace, relative_path)
            current_hash = _sha256(current) if current is not None else None
            if current_hash != data.expected_content_hash:
                raise ManuscriptSourceConflictError(
                    "source hash conflict: "
                    f"expected {data.expected_content_hash!r}, found {current_hash!r}"
                )
            proposed_hash = _sha256(proposed)
            if proposed_hash == current_hash:
                raise ValueError("source proposal has no content changes")
            inspection = await self.inspect_content(
                manuscript["id"], relative_path, source_format, data.content
            )
            if any(item["severity"] == "error" for item in inspection["findings"]):
                raise ValueError(
                    "source proposal contains blocking anchor or provenance findings"
                )

            proposal_id = generate_id("manuscript_source_proposal")
            async with self.db.transaction():
                context_manifest_id = None
                if data.origin != "human":
                    await self._validate_ai_context(
                        manuscript,
                        str(data.context_manifest_id),
                        origin=data.origin,
                        provider=str(data.provider),
                        model=str(data.model),
                        boundary=data.boundary,
                    )
                    context_manifest_id = data.context_manifest_id
                if data.supersedes_proposal_id:
                    previous = await self._require_proposal_row(
                        data.supersedes_proposal_id
                    )
                    if previous["status"] not in {"proposed", "conflicted"}:
                        raise ManuscriptSourceConflictError(
                            "only proposed or conflicted source proposals may be superseded"
                        )
                    if (
                        previous["manuscript_id"] != manuscript["id"]
                        or previous["relative_path"] != relative_path
                    ):
                        raise ValueError(
                            "a source proposal may supersede only the same file"
                        )
                    close_details = self._assert_not_written_before_close(
                        previous, workspace, action="supersede"
                    )
                    await self._transition_row(
                        previous,
                        status="superseded",
                        actor=data.created_by,
                        reason=f"Superseded by {proposal_id}: {data.reason}",
                        details={"superseded_by": proposal_id, **close_details},
                    )
                await self.db.execute(
                    """INSERT INTO manuscript_source_proposals
                       (id, project_id, manuscript_id, origin, relative_path,
                        source_format, base_content_hash, proposed_content,
                        proposed_content_hash, created_by, reason,
                        validation_findings, context_manifest_id, provider, model,
                        boundary, supersedes_proposal_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        proposal_id,
                        self.project_id,
                        manuscript["id"],
                        data.origin,
                        relative_path,
                        source_format,
                        current_hash,
                        data.content,
                        proposed_hash,
                        data.created_by,
                        data.reason,
                        _canonical_json(inspection["findings"]),
                        context_manifest_id,
                        data.provider,
                        data.model,
                        data.boundary,
                        data.supersedes_proposal_id,
                    ],
                )
                await self._insert_event(
                    proposal_id,
                    revision=1,
                    action="proposed",
                    actor=data.created_by,
                    reason=data.reason,
                    details={
                        "relative_path": relative_path,
                        "base_content_hash": current_hash,
                        "proposed_content_hash": proposed_hash,
                        "finding_count": len(inspection["findings"]),
                    },
                )
        return await self.get_proposal(proposal_id)

    async def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        row = await self._require_proposal_row(proposal_id)
        result = dict(row)
        result["validation_findings"] = _loads(result["validation_findings"], [])
        events = await self.db.fetchall(
            """SELECT * FROM manuscript_source_events
               WHERE proposal_id = ? AND project_id = ?
               ORDER BY proposal_revision""",
            [proposal_id, self.project_id],
        )
        result["events"] = []
        for event in events:
            item = dict(event)
            item["details"] = _loads(item["details"], {})
            result["events"].append(item)
        result["schema_version"] = SOURCE_PROPOSAL_SCHEMA_VERSION
        return result

    async def list_proposals(
        self,
        manuscript_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        canonical_id = await NativeManuscriptService(
            self.db, project_id=self.project_id
        ).resolve_id(manuscript_id)
        if canonical_id is None:
            raise ManuscriptNotFoundError(f"manuscript {manuscript_id!r} not found")
        if status is not None and status not in _SOURCE_STATUSES:
            raise ValueError("invalid manuscript source proposal status")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        sql = """SELECT id, project_id, manuscript_id, status, revision, origin,
                        relative_path, source_format, base_content_hash,
                        proposed_content_hash, created_by, reason,
                        validation_findings, recovery_manifest_path,
                        created_at, updated_at
                 FROM manuscript_source_proposals
                 WHERE project_id = ? AND manuscript_id = ?"""
        params: list[Any] = [self.project_id, canonical_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = await self.db.fetchall(sql, params)
        result = []
        for raw in rows:
            row = dict(raw)
            row["validation_findings"] = _loads(row["validation_findings"], [])
            row["schema_version"] = SOURCE_PROPOSAL_SCHEMA_VERSION
            result.append(row)
        return result

    async def apply_proposal(
        self,
        proposal_id: str,
        data: ManuscriptSourceProposalTransition,
    ) -> dict[str, Any]:
        row = await self._require_proposal_row(proposal_id)
        self._assert_open(row, data.expected_revision)
        manuscript, workspace = await self._resolve_workspace(row["manuscript_id"])
        relative_path, _ = self._normalize_source_path(row["relative_path"])
        async with self._source_lock(manuscript["id"], relative_path):
            row = await self._require_proposal_row(proposal_id)
            self._assert_open(row, data.expected_revision)
            current, mode = self._read_current(workspace, relative_path)
            current_hash = _sha256(current) if current is not None else None
            proposed = row["proposed_content"].encode("utf-8")
            proposed_hash = _sha256(proposed)
            recovery_path = self._recovery_manifest_path(row)
            has_valid_recovery = self._valid_recovery_manifest(recovery_path, row)

            if has_valid_recovery:
                if current_hash == proposed_hash:
                    try:
                        recovery_state = self._reconcile_replaced_source(
                            workspace,
                            relative_path,
                            proposal_id=str(row["id"]),
                            expected_content_hash=row["base_content_hash"],
                            proposed_content_hash=proposed_hash,
                        )
                    except ManuscriptSourceConflictError as exc:
                        latest, _ = self._read_current(workspace, relative_path)
                        latest_hash = _sha256(latest) if latest is not None else None
                        await self._mark_conflicted(
                            row,
                            data,
                            current_content_hash=latest_hash,
                            transient_exchange=exc.transient_exchange,
                            recovery_state=exc.recovery_state,
                        )
                        raise
                    await self._complete_applied_transition(
                        row,
                        data,
                        recovery_path,
                        recovered_after_restart=True,
                        source_recovery_state=recovery_state,
                    )
                    return await self.get_proposal(proposal_id)
                swap_state = self._source_swap_state(
                    workspace,
                    relative_path,
                    proposal_id=str(row["id"]),
                    expected_content_hash=row["base_content_hash"],
                    proposed_content_hash=proposed_hash,
                )
                if not (
                    current_hash == row["base_content_hash"]
                    and swap_state == "missing"
                ):
                    # A previous attempt may have restored an external object
                    # or retained a displaced inode but failed before the ledger
                    # transition. Preserve every pre-existing recovery object,
                    # fsync its naming state, and durably close as conflicted.
                    recovery_state = self._finalize_conflicted_source_state(
                        workspace,
                        relative_path,
                        proposal_id=str(row["id"]),
                        expected_content_hash=row["base_content_hash"],
                        proposed_content_hash=proposed_hash,
                    )
                    await self._mark_conflicted(
                        row,
                        data,
                        current_content_hash=current_hash,
                        transient_exchange=None,
                        recovery_state=recovery_state,
                    )
                    raise ManuscriptSourceConflictError(
                        "source changed after a recoverable apply attempt; current, "
                        "proposed, and retained versions were preserved"
                    )

            if current_hash != row["base_content_hash"]:
                await self._mark_conflicted(
                    row,
                    data,
                    current_content_hash=current_hash,
                    transient_exchange=False,
                )
                raise ManuscriptSourceConflictError(
                    "source changed after proposal creation; current and proposed versions were preserved"
                )

            inspection = await self.inspect_content(
                manuscript["id"], relative_path, row["source_format"], row["proposed_content"]
            )
            if any(item["severity"] == "error" for item in inspection["findings"]):
                raise ValueError("source proposal no longer passes anchor/provenance validation")

            # Validation awaits database reads. Re-read afterwards so an editor
            # change during that await is never recovered as the wrong base.
            current, mode = self._read_current(workspace, relative_path)
            current_hash = _sha256(current) if current is not None else None
            if current_hash != row["base_content_hash"]:
                await self._mark_conflicted(
                    row,
                    data,
                    current_content_hash=current_hash,
                )
                raise ManuscriptSourceConflictError(
                    "source changed during proposal validation; current and proposed "
                    "versions were preserved"
                )

            self._write_recovery(row, current, mode, recovery_path)
            try:
                self._atomic_replace(
                    workspace,
                    relative_path,
                    proposed,
                    mode,
                    proposal_id=str(row["id"]),
                    expected_content_hash=row["base_content_hash"],
                )
            except ManuscriptSourceConflictError as exc:
                latest, _ = self._read_current(workspace, relative_path)
                latest_hash = _sha256(latest) if latest is not None else None
                await self._mark_conflicted(
                    row,
                    data,
                    current_content_hash=latest_hash,
                    transient_exchange=exc.transient_exchange,
                    recovery_state=exc.recovery_state,
                )
                raise
            swap_state = self._source_swap_state(
                workspace,
                relative_path,
                proposal_id=str(row["id"]),
                expected_content_hash=row["base_content_hash"],
                proposed_content_hash=proposed_hash,
            )
            await self._complete_applied_transition(
                row,
                data,
                recovery_path,
                recovered_after_restart=False,
                source_recovery_state=self._retention_state_from_swap_state(
                    swap_state
                ),
            )
        return await self.get_proposal(proposal_id)

    async def reject_proposal(
        self,
        proposal_id: str,
        data: ManuscriptSourceProposalTransition,
    ) -> dict[str, Any]:
        row = await self._require_proposal_row(proposal_id)
        self._assert_open(row, data.expected_revision)
        manuscript, workspace = await self._resolve_workspace(row["manuscript_id"])
        relative_path, _ = self._normalize_source_path(row["relative_path"])
        async with self._source_lock(manuscript["id"], relative_path):
            row = await self._require_proposal_row(proposal_id)
            self._assert_open(row, data.expected_revision)
            close_details = self._assert_not_written_before_close(
                row, workspace, action="reject"
            )
            async with self.db.transaction():
                row = await self._require_proposal_row(proposal_id)
                self._assert_open(row, data.expected_revision)
                await self._transition_row(
                    row,
                    status="rejected",
                    actor=data.actor,
                    reason=data.reason,
                    details=close_details,
                )
        return await self.get_proposal(proposal_id)

    async def _mark_conflicted(
        self,
        row: Mapping[str, Any],
        data: ManuscriptSourceProposalTransition,
        *,
        current_content_hash: str | None,
        transient_exchange: bool | None = False,
        recovery_state: str | None = None,
    ) -> None:
        async with self.db.transaction():
            current = await self._require_proposal_row(str(row["id"]))
            self._assert_open(current, data.expected_revision)
            await self._transition_row(
                current,
                status="conflicted",
                actor=data.actor,
                reason=data.reason,
                details={
                    "relative_path": row["relative_path"],
                    "expected_content_hash": row["base_content_hash"],
                    "current_content_hash": current_content_hash,
                    "proposed_content_hash": row["proposed_content_hash"],
                    "file_written": transient_exchange,
                    "transient_exchange": transient_exchange,
                    "transient_exchange_state": (
                        "possible"
                        if transient_exchange is None
                        else "observed"
                        if transient_exchange
                        else "not_observed"
                    ),
                    "final_target_preserved": True,
                    **self._source_recovery_event_details(row, recovery_state),
                },
            )

    async def _complete_applied_transition(
        self,
        row: Mapping[str, Any],
        data: ManuscriptSourceProposalTransition,
        recovery_path: Path,
        *,
        recovered_after_restart: bool,
        source_recovery_state: str,
    ) -> None:
        recovery_relative = recovery_path.relative_to(
            Path(self.db.db_path).resolve().parent
        ).as_posix()
        recovery_details = self._source_recovery_event_details(
            row, source_recovery_state
        )
        async with self.db.transaction():
            current = await self._require_proposal_row(str(row["id"]))
            self._assert_open(current, data.expected_revision)
            await self._transition_row(
                current,
                status="applied",
                actor=data.actor,
                reason=data.reason,
                details={
                    "relative_path": row["relative_path"],
                    "before_content_hash": row["base_content_hash"],
                    "after_content_hash": row["proposed_content_hash"],
                    "recovery_manifest_path": recovery_relative,
                    "displaced_source_path": (
                        recovery_details["retained_source_path"]
                        if row["base_content_hash"] is not None
                        else None
                    ),
                    **recovery_details,
                    "recovered_after_restart": recovered_after_restart,
                    "git_operation": False,
                },
                recovery_manifest_path=recovery_relative,
            )

    async def _validate_ai_context(
        self,
        manuscript: Mapping[str, Any],
        manifest_id: str,
        *,
        origin: str,
        provider: str,
        model: str,
        boundary: str,
    ) -> str:
        row = await self.db.fetchone(
            """SELECT * FROM semantic_patch_context_manifests
               WHERE id = ? AND project_id = ?""",
            [manifest_id, self.project_id],
        )
        if row is None:
            raise ValueError("AI source proposal context manifest not found")
        if (
            row["origin"] != origin
            or row["provider"] != provider
            or row["model"] != model
            or row["boundary"] != boundary
        ):
            raise ValueError("AI source proposal boundary does not match its context manifest")
        targets = _loads(row["target_bases"], [])
        target = next(
            (
                item
                for item in targets
                if item.get("target", {}).get("type") == "manuscript"
                and item.get("target", {}).get("id") == manuscript["id"]
            ),
            None,
        )
        if target is None:
            raise ValueError("AI context manifest does not disclose the target manuscript")
        if int(target.get("revision", -1)) != int(manuscript["revision"]):
            raise ManuscriptSourceConflictError("AI context manuscript revision is stale")

    async def _resolve_workspace(self, manuscript_id: str) -> tuple[dict[str, Any], Path]:
        manuscript = await NativeManuscriptService(
            self.db, project_id=self.project_id
        ).get(manuscript_id)
        if manuscript is None:
            raise ManuscriptNotFoundError(f"manuscript {manuscript_id!r} not found")
        record = manuscript.model_dump()
        workspace_ref = record.get("workspace_ref")
        if not workspace_ref:
            raise ManuscriptSourceSecurityError("manuscript has no workspace_ref")
        roots = self._configured_roots()
        if not roots:
            raise ManuscriptSourceSecurityError(
                "manuscript source access is disabled; configure RKA_MANUSCRIPT_WORKSPACE_ROOTS"
            )
        workspace = Path(os.path.abspath(os.path.expanduser(str(workspace_ref))))
        matching_root = next(
            (root for root in roots if workspace == root or root in workspace.parents),
            None,
        )
        if matching_root is None:
            raise ManuscriptSourceSecurityError("workspace_ref is outside configured roots")
        if not workspace.exists() or not workspace.is_dir():
            raise ManuscriptSourceSecurityError("workspace_ref is not an existing directory")
        self._assert_no_symlink_components(matching_root, workspace)
        return record, workspace

    def _configured_roots(self) -> list[Path]:
        result = []
        for value in self.config.manuscript_workspace_roots.split(os.pathsep):
            value = value.strip()
            if not value:
                continue
            configured = Path(os.path.abspath(os.path.expanduser(value)))
            if not configured.exists() or not configured.is_dir():
                continue
            # Canonicalize the explicitly trusted root once. A workspace_ref
            # that reaches the same location through a symlink will not match
            # this path and therefore cannot smuggle a symlink into later
            # descriptor-relative traversal.
            root = configured.resolve()
            result.append(root)
        return result

    @staticmethod
    def _assert_no_symlink_components(root: Path, candidate: Path) -> None:
        relative = candidate.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ManuscriptSourceSecurityError(
                    f"workspace contains symlink component {part!r}"
                )

    @staticmethod
    def _normalize_source_path(relative_path: str) -> tuple[str, str]:
        value = relative_path.strip()
        if "\\" in value:
            raise ManuscriptSourceSecurityError("relative_path must use POSIX separators")
        path = PurePosixPath(value)
        if path.is_absolute() or not path.parts or any(
            part in {"", ".", ".."} or part.startswith(".") for part in path.parts
        ):
            raise ManuscriptSourceSecurityError("relative_path is not a safe visible path")
        source_format = _SOURCE_SUFFIXES.get(path.suffix.lower())
        if source_format is None:
            raise ManuscriptSourceSecurityError("only .md, .markdown, and .tex files are supported")
        return path.as_posix(), source_format

    def _read_current(self, workspace: Path, relative_path: str) -> tuple[bytes | None, int | None]:
        normalized, _ = self._normalize_source_path(relative_path)
        parent_fd, name = self._open_parent_fd(workspace, PurePosixPath(normalized))
        try:
            return self._read_source_entry_at(parent_fd, name, missing_ok=True)
        finally:
            os.close(parent_fd)

    def _read_source_entry_at(
        self,
        directory_fd: int,
        name: str,
        *,
        missing_ok: bool,
        validate_utf8: bool = True,
    ) -> tuple[bytes | None, int | None]:
        try:
            file_fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            if missing_ok:
                return None, None
            raise
        try:
            file_stat = os.fstat(file_fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise ManuscriptSourceSecurityError("source target is not a regular file")
            if file_stat.st_size > self.config.manuscript_source_max_bytes:
                raise ValueError("manuscript source file exceeds configured size limit")
            chunks = []
            remaining = self.config.manuscript_source_max_bytes + 1
            while remaining > 0:
                chunk = os.read(file_fd, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            value = b"".join(chunks)
            self._assert_size(value)
            if validate_utf8:
                self._decode(value)
            return value, stat.S_IMODE(file_stat.st_mode)
        finally:
            os.close(file_fd)

    @staticmethod
    def _open_parent_fd(workspace: Path, relative_path: PurePosixPath) -> tuple[int, str]:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        current_fd = ManuscriptSourceService._open_absolute_directory_fd(workspace)
        try:
            for part in relative_path.parts[:-1]:
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            return current_fd, relative_path.name
        except Exception:
            os.close(current_fd)
            raise

    @staticmethod
    def _open_absolute_directory_fd(path: Path) -> int:
        """Open every absolute path component without following symlinks."""
        absolute = Path(os.path.abspath(path))
        parts = absolute.parts
        if not parts or not absolute.is_absolute():
            raise ManuscriptSourceSecurityError("source directory is not absolute")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        current_fd = os.open(parts[0], flags)
        try:
            for part in parts[1:]:
                next_fd = os.open(part, flags, dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except Exception:
            os.close(current_fd)
            raise

    def _assert_size(self, value: bytes) -> None:
        if len(value) > self.config.manuscript_source_max_bytes:
            raise ValueError("manuscript source content exceeds configured size limit")

    @staticmethod
    def _decode(value: bytes) -> str:
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("manuscript source must be valid UTF-8") from exc

    def _recovery_root(self) -> Path:
        return Path(self.db.db_path).resolve().parent / "manuscript-source-recovery"

    def _open_lock_fd(self, manuscript_id: str, relative_path: str) -> int:
        digest = _sha256(f"{self.project_id}\0{manuscript_id}\0{relative_path}".encode())
        directory_fd, _ = self._open_recovery_directory(("locks",), create=True)
        try:
            return os.open(
                f"{digest}.lock",
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
        finally:
            os.close(directory_fd)

    @asynccontextmanager
    async def _source_lock(self, manuscript_id: str, relative_path: str):
        """Serialize same-file state transitions without blocking the event loop."""
        lock_fd = self._open_lock_fd(manuscript_id, relative_path)
        try:
            while True:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.01)
            yield
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def _assert_not_written_before_close(
        self,
        row: Mapping[str, Any],
        workspace: Path,
        *,
        action: str,
    ) -> dict[str, Any]:
        """Keep a crash-applied proposal open until Apply reconciles its ledger."""
        current, _ = self._read_current(workspace, str(row["relative_path"]))
        current_hash = _sha256(current) if current is not None else None
        recovery_path = self._recovery_manifest_path(row)
        has_valid_recovery = self._valid_recovery_manifest(recovery_path, row)
        if current_hash == row["proposed_content_hash"] and has_valid_recovery:
            raise ManuscriptSourceConflictError(
                "proposal content is already on disk with valid recovery metadata; "
                f"retry apply to reconcile the ledger before {action}"
            )
        if has_valid_recovery:
            recovery_state = self._finalize_conflicted_source_state(
                workspace,
                str(row["relative_path"]),
                proposal_id=str(row["id"]),
                expected_content_hash=row["base_content_hash"],
                proposed_content_hash=str(row["proposed_content_hash"]),
            )
            return self._source_recovery_event_details(row, recovery_state)
        return {}

    def _recovery_components(self, row: Mapping[str, Any]) -> tuple[str, str, str]:
        components = (
            self.project_id,
            str(row["manuscript_id"]),
            str(row["id"]),
        )
        for value in components:
            if value in {".", ".."} or not _SAFE_STORAGE_COMPONENT_RE.fullmatch(value):
                raise ManuscriptSourceSecurityError(
                    "source recovery identity is not safe for managed storage"
                )
        return components

    def _open_recovery_directory(
        self,
        components: tuple[str, ...],
        *,
        create: bool,
    ) -> tuple[int, Path]:
        """Open a managed recovery directory without following any symlink."""
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        parent = Path(self.db.db_path).resolve().parent
        current_fd = self._open_absolute_directory_fd(parent)
        current_path = parent
        try:
            for component in ("manuscript-source-recovery", *components):
                if component in {".", ".."} or not _SAFE_STORAGE_COMPONENT_RE.fullmatch(
                    component
                ):
                    raise ManuscriptSourceSecurityError(
                        "source recovery path contains an unsafe component"
                    )
                if create:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                    # Persist every hierarchy edge, including an edge whose
                    # preceding fsync failed and is being retried. Merely
                    # fsyncing the leaf cannot make newly created ancestors
                    # durable across a power loss.
                    os.fsync(current_fd)
                try:
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                except OSError as exc:
                    raise ManuscriptSourceSecurityError(
                        "source recovery path is missing, unsafe, or not a directory"
                    ) from exc
                if not stat.S_ISDIR(os.fstat(next_fd).st_mode):
                    os.close(next_fd)
                    raise ManuscriptSourceSecurityError(
                        "source recovery component is not a directory"
                    )
                os.close(current_fd)
                current_fd = next_fd
                current_path = current_path / component
            return current_fd, current_path
        except Exception:
            os.close(current_fd)
            raise

    def _recovery_manifest_path(self, row: Mapping[str, Any]) -> Path:
        return self._recovery_root().joinpath(
            *self._recovery_components(row), "manifest.json"
        )

    def _write_recovery(
        self,
        row: Mapping[str, Any],
        before: bytes | None,
        mode: int | None,
        manifest_path: Path,
    ) -> None:
        components = self._recovery_components(row)
        directory_fd, directory = self._open_recovery_directory(
            components, create=True
        )
        if directory / "manifest.json" != manifest_path:
            os.close(directory_fd)
            raise ManuscriptSourceSecurityError("source recovery path changed")
        manifest = {
            "schema_version": "rka.manuscript-source-recovery/v1",
            "proposal_id": row["id"],
            "project_id": self.project_id,
            "manuscript_id": row["manuscript_id"],
            "relative_path": row["relative_path"],
            "before_existed": before is not None,
            "before_content_hash": _sha256(before) if before is not None else None,
            "before_mode": mode,
            "after_content_hash": row["proposed_content_hash"],
            "displaced_source_path": (
                self._retained_source_relative_path(row)
                if before is not None
                else None
            ),
            "created_at": _now(),
        }
        try:
            if before is not None:
                existing_before = self._read_managed_file(
                    directory_fd, "before.bin", missing_ok=True
                )
                if existing_before is None:
                    self._write_new_durable_at(
                        directory_fd, "before.bin", before, mode=0o600
                    )
                elif _sha256(existing_before) != _sha256(before):
                    raise ManuscriptSourceSecurityError(
                        "existing source recovery copy does not match the current base"
                    )
            existing_manifest = self._read_managed_file(
                directory_fd, "manifest.json", missing_ok=True
            )
            if existing_manifest is not None:
                try:
                    payload = json.loads(existing_manifest.decode("utf-8"))
                except (ValueError, UnicodeError) as exc:
                    raise ManuscriptSourceSecurityError(
                        "existing source recovery manifest is invalid"
                    ) from exc
                if not self._recovery_manifest_matches(payload, row):
                    raise ManuscriptSourceSecurityError(
                        "existing source recovery manifest does not match this proposal"
                    )
            else:
                self._write_new_durable_at(
                    directory_fd,
                    "manifest.json",
                    (_canonical_json(manifest) + "\n").encode("utf-8"),
                    mode=0o600,
                )
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _write_new_durable_at(
        directory_fd: int,
        name: str,
        value: bytes,
        *,
        mode: int,
    ) -> None:
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode,
            dir_fd=directory_fd,
        )
        try:
            view = memoryview(value)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _read_managed_file(
        directory_fd: int,
        name: str,
        *,
        missing_ok: bool,
    ) -> bytes | None:
        try:
            fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            if missing_ok:
                return None
            raise
        try:
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise ManuscriptSourceSecurityError(
                    "source recovery entry is not a regular file"
                )
            if file_stat.st_size > 32 * 1024 * 1024:
                raise ManuscriptSourceSecurityError("source recovery entry is oversized")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 64 * 1024)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
        finally:
            os.close(fd)

    def _valid_recovery_manifest(self, path: Path, row: Mapping[str, Any]) -> bool:
        expected = self._recovery_manifest_path(row)
        if path != expected:
            return False
        try:
            directory_fd, directory = self._open_recovery_directory(
                self._recovery_components(row), create=False
            )
            try:
                if directory / "manifest.json" != path:
                    return False
                raw = self._read_managed_file(
                    directory_fd, "manifest.json", missing_ok=False
                )
            finally:
                os.close(directory_fd)
            assert raw is not None
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError, UnicodeError, ManuscriptSourceSecurityError):
            return False
        return self._recovery_manifest_matches(payload, row)

    def _recovery_manifest_matches(
        self,
        payload: Mapping[str, Any],
        row: Mapping[str, Any],
    ) -> bool:
        return bool(
            payload.get("schema_version") == "rka.manuscript-source-recovery/v1"
            and payload.get("proposal_id") == row["id"]
            and payload.get("project_id") == self.project_id
            and payload.get("manuscript_id") == row["manuscript_id"]
            and payload.get("relative_path") == row["relative_path"]
            and payload.get("before_content_hash") == row["base_content_hash"]
            and payload.get("after_content_hash") == row["proposed_content_hash"]
        )

    def _atomic_replace(
        self,
        workspace: Path,
        relative_path: str,
        value: bytes,
        previous_mode: int | None,
        *,
        proposal_id: str,
        expected_content_hash: str | None,
    ) -> None:
        normalized, _ = self._normalize_source_path(relative_path)
        parent_fd, name = self._open_parent_fd(workspace, PurePosixPath(normalized))
        swap_name = self._source_swap_name(proposal_id)
        exchanged = False
        proposal_swap_owned = False
        try:
            proposal_swap_owned = self._prepare_source_swap(
                parent_fd,
                swap_name,
                value,
                previous_mode if previous_mode is not None else 0o644,
            )
            # Cleanup is safe only after preparation proves that this name
            # contains the immutable proposal bytes. A pre-existing retained
            # base or external inode must never be removed by this invocation.

            if expected_content_hash is None:
                try:
                    os.link(
                        swap_name,
                        name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError as exc:
                    raise ManuscriptSourceConflictError(
                        "source appeared immediately before creation; current and "
                        "proposed versions were preserved",
                        recovery_state=(
                            None if proposal_swap_owned else "retained_proposal"
                        ),
                    ) from exc
                os.unlink(swap_name, dir_fd=parent_fd)
                proposal_swap_owned = False
                os.fsync(parent_fd)
                return

            try:
                self._atomic_exchange_at(parent_fd, swap_name, parent_fd, name)
            except OSError as exc:
                if exc.errno in {errno.ENOENT, errno.ENOTDIR}:
                    raise ManuscriptSourceConflictError(
                        "source changed immediately before replacement; current and "
                        "proposed versions were preserved",
                        recovery_state=(
                            None if proposal_swap_owned else "retained_proposal"
                        ),
                    ) from exc
                raise
            exchanged = True
            proposal_swap_owned = False
            try:
                installed, _ = self._read_source_entry_at(
                    parent_fd,
                    name,
                    missing_ok=False,
                    validate_utf8=False,
                )
            except (OSError, ValueError, ManuscriptSourceSecurityError) as exc:
                raise ManuscriptSourceConflictError(
                    "installed source became unsafe at the replacement boundary; "
                    "the prior target will be restored",
                    transient_exchange=True,
                ) from exc
            assert installed is not None
            if _sha256(installed) != _sha256(value):
                raise ManuscriptSourceConflictError(
                    "proposal swap changed at the replacement boundary; the prior "
                    "target will be restored",
                    transient_exchange=True,
                )
            try:
                displaced, _ = self._read_source_entry_at(
                    parent_fd,
                    swap_name,
                    missing_ok=False,
                    validate_utf8=False,
                )
            except (OSError, ValueError, ManuscriptSourceSecurityError) as exc:
                raise ManuscriptSourceConflictError(
                    "source became unsafe immediately before replacement; the exact "
                    "displaced version will be restored",
                    transient_exchange=True,
                ) from exc
            assert displaced is not None
            if _sha256(displaced) != expected_content_hash:
                raise ManuscriptSourceConflictError(
                    "source changed immediately before replacement; the exact "
                    "displaced version will be restored",
                    transient_exchange=True,
                )

            # Keep the exact displaced inode linked at its deterministic hidden
            # name. An editor that opened the original target before exchange
            # can still write through that descriptor; retaining the inode is
            # the only way to ensure those later bytes remain recoverable.
            exchanged = False
            os.fsync(parent_fd)
        except Exception as original_error:
            if exchanged:
                try:
                    self._atomic_exchange_at(parent_fd, swap_name, parent_fd, name)
                    exchanged = False
                    restored_swap, _ = self._read_source_entry_at(
                        parent_fd,
                        swap_name,
                        missing_ok=False,
                        validate_utf8=False,
                    )
                    assert restored_swap is not None
                    rollback_state = (
                        "retained_proposal"
                        if _sha256(restored_swap) == _sha256(value)
                        else "retained_unclassified"
                    )
                    os.fsync(parent_fd)
                    if isinstance(original_error, ManuscriptSourceConflictError):
                        original_error.recovery_state = rollback_state
                except Exception as rollback_error:
                    raise ManuscriptSourceSecurityError(
                        "source exchange failed and could not be rolled back safely"
                    ) from rollback_error
            raise
        finally:
            # Remove only a name positively classified as this operation's
            # immutable proposal bytes. If preparation rejected a pre-existing
            # retained or unknown inode, ownership remains false.
            try:
                if proposal_swap_owned:
                    try:
                        os.unlink(swap_name, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
                    os.fsync(parent_fd)
            finally:
                os.close(parent_fd)

    def _reconcile_replaced_source(
        self,
        workspace: Path,
        relative_path: str,
        *,
        proposal_id: str,
        expected_content_hash: str | None,
        proposed_content_hash: str,
    ) -> None:
        """Finish a crash-interrupted replacement before updating its ledger."""
        normalized, _ = self._normalize_source_path(relative_path)
        parent_fd, name = self._open_parent_fd(workspace, PurePosixPath(normalized))
        swap_name = self._source_swap_name(proposal_id)
        try:
            try:
                displaced, _ = self._read_source_entry_at(
                    parent_fd,
                    swap_name,
                    missing_ok=True,
                    validate_utf8=False,
                )
            except (OSError, ValueError, ManuscriptSourceSecurityError) as exc:
                # The deterministic swap name can only contain the object that
                # was about to replace the target or the exact target displaced
                # by the exchange. Restore the latter even when it cannot be
                # decoded or bounded safely enough to inspect.
                try:
                    self._atomic_exchange_at(parent_fd, swap_name, parent_fd, name)
                    os.fsync(parent_fd)
                except Exception as rollback_error:
                    raise ManuscriptSourceSecurityError(
                        "interrupted source exchange could not be reconciled safely"
                    ) from rollback_error
                raise ManuscriptSourceConflictError(
                    "an unsafe external source version was restored after an "
                    "interrupted replacement",
                    transient_exchange=True,
                    recovery_state="retained_proposal",
                ) from exc

            if displaced is None:
                # The rename/link and cleanup completed, but a previous source
                # directory fsync or the SQLite transition may have failed.
                os.fsync(parent_fd)
                return "missing"

            displaced_hash = _sha256(displaced)
            if expected_content_hash is None or displaced_hash == proposed_content_hash:
                # A restart cannot prove that a pre-existing proposal-valued
                # inode has no descriptor opened while it was public. Retain
                # the deterministic name; normal missing-file creation removes
                # its redundant link before returning from the original call.
                os.fsync(parent_fd)
                return "retained_proposal"
            if displaced_hash == expected_content_hash:
                # Exchange completed and the exact reviewed base is retained at
                # the hidden recovery name. Keep that inode linked permanently:
                # a pre-opened editor descriptor may still write through it.
                os.fsync(parent_fd)
                return "retained_base"

            # An external editor won the race immediately before the exchange.
            # Restore that exact displaced inode and leave the proposal conflicted.
            self._atomic_exchange_at(parent_fd, swap_name, parent_fd, name)
            os.fsync(parent_fd)
            raise ManuscriptSourceConflictError(
                "an external source version was restored after an interrupted replacement",
                transient_exchange=True,
                recovery_state="retained_proposal",
            )
        finally:
            os.close(parent_fd)

    def _finalize_conflicted_source_state(
        self,
        workspace: Path,
        relative_path: str,
        *,
        proposal_id: str,
        expected_content_hash: str | None,
        proposed_content_hash: str,
    ) -> str:
        """Durably preserve a restart state before closing it as conflicted."""
        normalized, _ = self._normalize_source_path(relative_path)
        parent_fd, _ = self._open_parent_fd(workspace, PurePosixPath(normalized))
        swap_name = self._source_swap_name(proposal_id)
        try:
            swap_state = self._classify_source_swap_at(
                parent_fd,
                swap_name,
                expected_content_hash=expected_content_hash,
                proposed_content_hash=proposed_content_hash,
            )
            os.fsync(parent_fd)
            return self._retention_state_from_swap_state(swap_state)
        finally:
            os.close(parent_fd)

    def _source_swap_state(
        self,
        workspace: Path,
        relative_path: str,
        *,
        proposal_id: str,
        expected_content_hash: str | None,
        proposed_content_hash: str,
    ) -> str:
        """Classify, but never mutate, one deterministic source-side recovery name."""
        normalized, _ = self._normalize_source_path(relative_path)
        parent_fd, _ = self._open_parent_fd(workspace, PurePosixPath(normalized))
        try:
            return self._classify_source_swap_at(
                parent_fd,
                self._source_swap_name(proposal_id),
                expected_content_hash=expected_content_hash,
                proposed_content_hash=proposed_content_hash,
            )
        finally:
            os.close(parent_fd)

    def _classify_source_swap_at(
        self,
        parent_fd: int,
        swap_name: str,
        *,
        expected_content_hash: str | None,
        proposed_content_hash: str,
    ) -> str:
        """Boundedly classify recovery bytes without rejecting an oversized inode."""
        try:
            swap, _ = self._read_source_entry_at(
                parent_fd,
                swap_name,
                missing_ok=True,
                validate_utf8=False,
            )
        except ValueError as exc:
            if "exceeds configured size limit" not in str(exc):
                raise
            return "oversized"
        if swap is None:
            return "missing"
        swap_hash = _sha256(swap)
        if swap_hash == proposed_content_hash:
            return "proposal"
        if expected_content_hash is not None and swap_hash == expected_content_hash:
            return "reviewed_base"
        return "unclassified"

    @staticmethod
    def _retention_state_from_swap_state(swap_state: str) -> str:
        return {
            "missing": "missing",
            "proposal": "retained_proposal",
            "reviewed_base": "retained_base",
            "unclassified": "retained_unclassified",
            "oversized": "retained_oversized",
        }[swap_state]

    def _source_recovery_event_details(
        self,
        row: Mapping[str, Any],
        recovery_state: str | None,
    ) -> dict[str, Any]:
        observed = {
            None: None,
            "missing": "missing",
            "retained_proposal": "proposal",
            "retained_base": "reviewed_base",
            "retained_unclassified": "unclassified",
            "retained_oversized": "oversized",
        }[recovery_state]
        retained = bool(recovery_state and recovery_state.startswith("retained_"))
        return {
            "source_recovery_state": (
                "retained" if retained else "missing" if recovery_state else "not_checked"
            ),
            "source_recovery_last_observed": observed,
            "retained_source_path": (
                self._retained_source_relative_path(row) if retained else None
            ),
        }

    @staticmethod
    def _source_swap_name(proposal_id: str) -> str:
        return f".rka-source-{_sha256(proposal_id.encode())[:32]}.recovery"

    def _retained_source_relative_path(self, row: Mapping[str, Any]) -> str:
        source = PurePosixPath(str(row["relative_path"]))
        return (source.parent / self._source_swap_name(str(row["id"]))).as_posix()

    def _prepare_source_swap(
        self,
        parent_fd: int,
        swap_name: str,
        value: bytes,
        mode: int,
    ) -> bool:
        try:
            temp_fd = os.open(
                swap_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
        except FileExistsError:
            existing, _ = self._read_source_entry_at(
                parent_fd,
                swap_name,
                missing_ok=False,
                validate_utf8=False,
            )
            assert existing is not None
            if _sha256(existing) != _sha256(value):
                raise ManuscriptSourceSecurityError(
                    "existing source swap does not match this proposal"
                )
            created = False
        else:
            created = True
            try:
                try:
                    view = memoryview(value)
                    while view:
                        written = os.write(temp_fd, view)
                        view = view[written:]
                    os.fchmod(temp_fd, mode)
                    os.fsync(temp_fd)
                finally:
                    os.close(temp_fd)
            except Exception:
                try:
                    os.unlink(swap_name, dir_fd=parent_fd)
                    os.fsync(parent_fd)
                except Exception as cleanup_error:
                    raise ManuscriptSourceSecurityError(
                        "incomplete source proposal swap could not be removed safely"
                    ) from cleanup_error
                raise
        # Make the proposed swap name durable before exchanging it. A crash can
        # then leave either the pre- or post-exchange naming state, both recoverable.
        os.fsync(parent_fd)
        return created

    @staticmethod
    def _atomic_exchange_at(
        old_directory_fd: int,
        old_name: str,
        new_directory_fd: int,
        new_name: str,
    ) -> None:
        """Atomically exchange two names or fail closed on unsupported platforms."""
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin":
            function_name = "renameatx_np"
        elif sys.platform.startswith("linux"):
            function_name = "renameat2"
        else:
            raise ManuscriptSourceSecurityError(
                "atomic source exchange is unsupported on this platform"
            )
        try:
            exchange = getattr(libc, function_name)
        except AttributeError as exc:
            raise ManuscriptSourceSecurityError(
                "atomic source exchange is unavailable; refusing an unsafe replacement"
            ) from exc
        exchange.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        exchange.restype = ctypes.c_int
        result = exchange(
            old_directory_fd,
            os.fsencode(old_name),
            new_directory_fd,
            os.fsencode(new_name),
            0x2,
        )
        if result != 0:
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number))

    async def _require_proposal_row(self, proposal_id: str) -> dict[str, Any]:
        row = await self.db.fetchone(
            "SELECT * FROM manuscript_source_proposals WHERE id = ? AND project_id = ?",
            [proposal_id, self.project_id],
        )
        if row is None:
            raise ManuscriptSourceNotFoundError(
                f"manuscript source proposal {proposal_id!r} not found"
            )
        return dict(row)

    @staticmethod
    def _assert_open(row: Mapping[str, Any], expected_revision: int) -> None:
        if row["status"] != "proposed":
            raise ManuscriptSourceConflictError(f"proposal is already {row['status']!r}")
        if int(row["revision"]) != expected_revision:
            raise ManuscriptSourceConflictError(
                f"proposal revision conflict: expected {expected_revision}, found {row['revision']}"
            )

    async def _transition_row(
        self,
        row: Mapping[str, Any],
        *,
        status: str,
        actor: str,
        reason: str,
        details: dict[str, Any],
        recovery_manifest_path: str | None = None,
    ) -> None:
        revision = int(row["revision"]) + 1
        timestamp = _now()
        cursor = await self.db.execute(
            """UPDATE manuscript_source_proposals
               SET status = ?, revision = revision + 1, updated_at = ?,
                   applied_at = CASE WHEN ? = 'applied' THEN ? ELSE applied_at END,
                   closed_at = ?,
                   recovery_manifest_path = CASE WHEN ? = 'applied' THEN ? ELSE recovery_manifest_path END
               WHERE id = ? AND project_id = ? AND status = ? AND revision = ?""",
            [
                status,
                timestamp,
                status,
                timestamp,
                timestamp,
                status,
                recovery_manifest_path,
                row["id"],
                self.project_id,
                row["status"],
                row["revision"],
            ],
        )
        if cursor.rowcount != 1:
            raise ManuscriptSourceConflictError("source proposal changed concurrently")
        await self._insert_event(
            str(row["id"]),
            revision=revision,
            action=status,
            actor=actor,
            reason=reason,
            details=details,
        )

    async def _insert_event(
        self,
        proposal_id: str,
        *,
        revision: int,
        action: str,
        actor: str,
        reason: str,
        details: dict[str, Any],
    ) -> None:
        await self.db.execute(
            """INSERT INTO manuscript_source_events
               (id, proposal_id, project_id, proposal_revision, action, actor, reason, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                generate_id("manuscript_source_event"),
                proposal_id,
                self.project_id,
                revision,
                action,
                actor,
                reason,
                _canonical_json(details),
            ],
        )
