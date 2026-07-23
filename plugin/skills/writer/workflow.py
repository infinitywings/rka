"""Fail-closed, read-mostly workflow helpers for the RKA Writer.

This module owns three small host-neutral operations:

* atomic workspace initialization after manuscript registration/verification;
* offline readiness evaluation from a fresh, project-scoped entity packet;
* a read-only candidate claim-spine proposal for PI/Brain review.

It never uses a default project.  Readiness and assist never mutate RKA.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


PROJECT_RE = re.compile(r"^prj_[0-9A-Z]{26}$")
MANUSCRIPT_RE = re.compile(r"^jrn_[0-9A-Z]{26}$")
SUPPORTED_EVIDENCE_STATUSES = {"supported", "partially_supported"}
INACTIVE_STATUSES = {"superseded", "retracted", "abandoned", "merged"}

_CORE_SENTINEL_RE = re.compile(
    r"REPLACE_WITH_(?:PROJECT_ID|MANUSCRIPT_ID|VENUE_ID|MANUSCRIPT_TITLE(?:_YAML|_LATEX)?|"
    r"ISO_DATE|RKA_API_URL|CFP_URL_YAML)|prj_REPLACE|jrn_REPLACE|"
    r"<your-|<<replace|populated-by-PI",
    re.IGNORECASE,
)


class WriterWorkflowError(RuntimeError):
    """A user-correctable Writer workflow failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def workspace_template_dir() -> Path:
    return Path(__file__).resolve().parent / "workspace-template"


def supported_venues(template_root: Path | None = None) -> list[str]:
    writer_root = (template_root or workspace_template_dir()).parent
    venue_dir = writer_root / "references" / "venue"
    yaml_venues = sorted(path.stem for path in venue_dir.glob("*.yaml"))
    if yaml_venues:
        return yaml_venues
    return sorted(
        path.stem
        for path in venue_dir.glob("*.md")
        if not path.stem.endswith(".notes")
    )


def default_workspace_path(project_id: str, venue: str) -> Path:
    project_slug = re.sub(r"[^a-zA-Z0-9-]", "-", project_id).lower()
    return (Path.cwd() / "manuscripts" / project_slug / venue).resolve()


def validate_identity(project_id: str, manuscript_id: str | None = None) -> None:
    if not PROJECT_RE.fullmatch(project_id):
        raise WriterWorkflowError("project_id must be an explicit canonical prj_ identifier")
    if manuscript_id is not None and not MANUSCRIPT_RE.fullmatch(manuscript_id):
        raise WriterWorkflowError("manuscript_id must be a canonical jrn_ identifier")


def _http_json(
    api_url: str,
    project_id: str,
    method: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(dict(payload)).encode("utf-8")
    headers = {"Accept": "application/json", "X-RKA-Project": project_id}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        api_url.rstrip("/") + path,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit local URL
            decoded = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")[:500]
        except OSError:
            detail = ""
        raise WriterWorkflowError(
            f"RKA returned HTTP {exc.code} for {method} {path}: {detail}"
        ) from exc
    except (URLError, OSError, json.JSONDecodeError) as exc:
        raise WriterWorkflowError(f"cannot reach or decode RKA at {api_url}: {exc}") from exc
    if not isinstance(decoded, dict):
        raise WriterWorkflowError("RKA returned a non-object manuscript response")
    return decoded


def register_or_verify_manuscript(
    *,
    api_url: str,
    project_id: str,
    venue: str,
    title: str,
    abstract: str | None = None,
    manuscript_id: str | None = None,
    timeout: float = 20.0,
) -> tuple[str, str]:
    """Return ``(manuscript_id, mode)`` after a project-scoped API check."""
    validate_identity(project_id, manuscript_id)
    if manuscript_id:
        record = _http_json(
            api_url,
            project_id,
            "GET",
            f"/api/manuscripts/{quote(manuscript_id, safe='')}",
            timeout=timeout,
        )
        if record.get("id") != manuscript_id:
            raise WriterWorkflowError("RKA manuscript response did not preserve the requested id")
        if record.get("project_id") != project_id:
            raise WriterWorkflowError("RKA manuscript response did not attest the requested project")
        if record.get("venue") != venue:
            raise WriterWorkflowError(
                f"existing manuscript venue {record.get('venue')!r} does not match {venue!r}"
            )
        if (record.get("title") or "").strip() != title.strip():
            raise WriterWorkflowError("existing manuscript title does not match --title")
        return manuscript_id, "verified"

    record = _http_json(
        api_url,
        project_id,
        "POST",
        "/api/manuscripts",
        {"venue": venue, "title": title, "abstract": abstract},
        timeout=timeout,
    )
    created_id = str(record.get("id") or "")
    if not MANUSCRIPT_RE.fullmatch(created_id):
        raise WriterWorkflowError("RKA registration did not return a canonical jrn_ id")
    if record.get("project_id") != project_id:
        raise WriterWorkflowError("RKA registration did not attest the requested project")
    return created_id, "registered"


def _latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in value)


def _replacement_map(
    *,
    project_id: str,
    manuscript_id: str,
    venue: str,
    title: str,
    api_url: str,
    cfp_url: str | None,
    created_at: str,
) -> dict[str, str]:
    return {
        "REPLACE_WITH_PROJECT_ID": project_id,
        "REPLACE_WITH_MANUSCRIPT_ID": manuscript_id,
        "REPLACE_WITH_VENUE_ID": venue,
        "REPLACE_WITH_MANUSCRIPT_TITLE_YAML": json.dumps(title, ensure_ascii=False),
        "REPLACE_WITH_MANUSCRIPT_TITLE_LATEX": _latex_escape(title),
        # Backward-compatible token while all bundled templates migrate.
        "REPLACE_WITH_MANUSCRIPT_TITLE": title,
        "REPLACE_WITH_ISO_DATE": created_at,
        "REPLACE_WITH_RKA_API_URL": api_url.rstrip("/"),
        "REPLACE_WITH_CFP_URL_YAML": (
            "null" if cfp_url is None else json.dumps(cfp_url, ensure_ascii=False)
        ),
    }


def preflight_workspace(
    *, target: Path, venue: str, template_root: Path | None = None
) -> Path:
    template = (template_root or workspace_template_dir()).resolve()
    if not template.is_dir():
        raise WriterWorkflowError(f"workspace template not found: {template}")
    venues = supported_venues(template)
    if venue not in venues:
        raise WriterWorkflowError(
            f"venue {venue!r} is not installed; supported venues: {', '.join(venues)}"
        )
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise WriterWorkflowError(f"target exists and is not an empty directory: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return template


def _copy_and_substitute(template: Path, stage: Path, replacements: Mapping[str, str]) -> None:
    for source in sorted(template.rglob("*")):
        relative = source.relative_to(template)
        destination = stage / relative
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if source.name.startswith("._"):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        raw = source.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            shutil.copy2(source, destination)
            continue
        for sentinel, value in replacements.items():
            text = text.replace(sentinel, value)
        destination.write_text(text, encoding="utf-8")


def _unresolved_sentinels(root: Path) -> list[str]:
    unresolved: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in _CORE_SENTINEL_RE.finditer(text):
            unresolved.append(f"{path.relative_to(root)}:{match.group(0)}")
    return unresolved


def publish_workspace(
    *,
    target: Path,
    template: Path,
    project_id: str,
    manuscript_id: str,
    venue: str,
    title: str,
    api_url: str,
    cfp_url: str | None,
    registration_mode: str,
) -> Path:
    """Render in a sibling stage and atomically publish a complete workspace."""
    created_at = utc_now()
    stage = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.rka-stage-", dir=str(target.parent))
    )
    published = False
    try:
        replacements = _replacement_map(
            project_id=project_id,
            manuscript_id=manuscript_id,
            venue=venue,
            title=title,
            api_url=api_url,
            cfp_url=cfp_url,
            created_at=created_at,
        )
        _copy_and_substitute(template, stage, replacements)
        metadata_dir = stage / ".rka"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "schema_version": "rka-writer-workspace/v1",
            "project_id": project_id,
            "manuscript_id": manuscript_id,
            "venue": venue,
            "title": title,
            "api_url": api_url.rstrip("/"),
            "initialized_at": created_at,
            "registration_mode": registration_mode,
        }
        (metadata_dir / "manuscript.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        unresolved = _unresolved_sentinels(stage)
        if unresolved:
            raise WriterWorkflowError(
                "workspace contains unresolved core sentinels: " + ", ".join(unresolved)
            )
        # An empty pre-created target is harmless but must be removed for an
        # atomic directory rename. Recheck immediately before publication.
        if target.exists():
            if not target.is_dir() or any(target.iterdir()):
                raise WriterWorkflowError(f"target changed during initialization: {target}")
            target.rmdir()
        os.replace(stage, target)
        published = True
        return target
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage)


def initialize_workspace(
    *,
    target: Path,
    project_id: str,
    venue: str,
    title: str,
    api_url: str,
    abstract: str | None = None,
    manuscript_id: str | None = None,
    cfp_url: str | None = None,
    timeout: float = 20.0,
    template_root: Path | None = None,
) -> dict[str, Any]:
    """Preflight, register/verify, stage, then atomically publish."""
    if not title.strip():
        raise WriterWorkflowError("title must not be empty")
    validate_identity(project_id, manuscript_id)
    target = target.expanduser().resolve()
    template = preflight_workspace(target=target, venue=venue, template_root=template_root)
    resolved_id, mode = register_or_verify_manuscript(
        api_url=api_url,
        project_id=project_id,
        venue=venue,
        title=title,
        abstract=abstract,
        manuscript_id=manuscript_id,
        timeout=timeout,
    )
    try:
        publish_workspace(
            target=target,
            template=template,
            project_id=project_id,
            manuscript_id=resolved_id,
            venue=venue,
            title=title,
            api_url=api_url,
            cfp_url=cfp_url,
            registration_mode=mode,
        )
    except Exception as exc:
        if mode == "registered":
            raise WriterWorkflowError(
                f"manuscript {resolved_id} was registered but workspace publication failed; "
                f"rerun with --manuscript-id {resolved_id}: {exc}"
            ) from exc
        raise
    return {
        "status": "ready",
        "project_id": project_id,
        "manuscript_id": resolved_id,
        "registration_mode": mode,
        "workspace": str(target),
    }


def load_entity_packet(path: Path, expected_project: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    validate_identity(expected_project)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WriterWorkflowError(f"cannot read entity packet {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("entities"), dict):
        raise WriterWorkflowError("entity packet must contain an entities mapping")
    if payload.get("project_id") != expected_project:
        raise WriterWorkflowError("entity packet project_id does not match --project-id")
    entities: dict[str, dict[str, Any]] = {}
    for entity_id, raw in payload["entities"].items():
        if not isinstance(entity_id, str) or not isinstance(raw, dict):
            raise WriterWorkflowError("every entity packet entry must be id -> object")
        entity = deepcopy(raw)
        embedded_id = entity.get("id")
        if embedded_id not in (None, entity_id):
            raise WriterWorkflowError(f"entity key/id mismatch for {entity_id}")
        entity_project = entity.get("project_id")
        if entity_project != expected_project:
            raise WriterWorkflowError(
                f"entity {entity_id} is not attested to project {expected_project}"
            )
        entity["id"] = entity_id
        entities[entity_id] = entity
    return payload, entities


def _is_current(entity: Mapping[str, Any]) -> bool:
    status = str(entity.get("status") or "").lower()
    confidence = str(entity.get("confidence") or "").lower()
    return (
        status not in INACTIVE_STATUSES
        and confidence not in {"superseded", "retracted"}
        and not entity.get("superseded_by")
        and not bool(entity.get("stale"))
    )


def _manuscripts(entities: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return sorted(
        entity_id
        for entity_id, entity in entities.items()
        if MANUSCRIPT_RE.fullmatch(entity_id)
        and "manuscript" in (entity.get("tags") or [])
        and _is_current(entity)
    )


def _ready_claims(entities: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return sorted(
        entity_id
        for entity_id, entity in entities.items()
        if entity_id.startswith("clm_")
        and entity.get("verified") is True
        and entity.get("evidence_status") in SUPPORTED_EVIDENCE_STATUSES
        and _is_current(entity)
        and entity.get("contradicted") is False
    )


def _scoped_pi_decisions(
    entities: Mapping[str, Mapping[str, Any]], manuscript_id: str | None
) -> list[str]:
    if not manuscript_id:
        return []
    return sorted(
        entity_id
        for entity_id, entity in entities.items()
        if entity_id.startswith("dec_")
        and entity.get("decided_by") == "pi"
        and entity.get("status") == "active"
        and not entity.get("superseded_by")
        and manuscript_id in (entity.get("related_journal") or [])
    )


def evaluate_readiness(
    *,
    packet_path: Path,
    project_id: str,
    manuscript_id: str | None = None,
    claim_spine_path: Path | None = None,
) -> dict[str, Any]:
    """Evaluate drafting readiness without mutating RKA or workspace state."""
    _payload, entities = load_entity_packet(packet_path, project_id)
    manuscripts = _manuscripts(entities)
    ready_claims = _ready_claims(entities)
    blockers: list[dict[str, str]] = []

    spine: dict[str, Any] | None = None
    if claim_spine_path is not None:
        from rka.skills.writer.scripts import claim_spine

        spine = claim_spine.load_spine(claim_spine_path)
        spine_manuscript = str(spine.get("manuscript_id") or "")
        if manuscript_id and spine_manuscript != manuscript_id:
            blockers.append({
                "code": "MANUSCRIPT_MISMATCH",
                "message": "--manuscript-id does not match the claim-spine manuscript_id",
            })
        manuscript_id = manuscript_id or spine_manuscript or None

    if manuscript_id is not None:
        validate_identity(project_id, manuscript_id)
    elif len(manuscripts) == 1:
        manuscript_id = manuscripts[0]
    elif not manuscripts:
        blockers.append({"code": "NO_MANUSCRIPT", "message": "no current registered manuscript found"})
    else:
        blockers.append({
            "code": "AMBIGUOUS_MANUSCRIPT",
            "message": "multiple manuscripts found; select one explicitly",
        })

    if manuscript_id and manuscript_id not in manuscripts:
        blockers.append({
            "code": "INVALID_MANUSCRIPT",
            "message": f"{manuscript_id} is not a current jrn_ entity tagged manuscript",
        })
    if not ready_claims:
        blockers.append({
            "code": "NO_MANUSCRIPT_READY_CLAIMS",
            "message": "no current claim has verified grounding plus supported evidence status",
        })

    pi_decisions = _scoped_pi_decisions(entities, manuscript_id)
    if manuscript_id and not pi_decisions:
        blockers.append({
            "code": "NO_SCOPED_PI_DECISION",
            "message": "no active PI decision is explicitly scoped to this manuscript",
        })

    spine_report: dict[str, Any] | None = None
    if spine is None:
        blockers.append({
            "code": "CLAIM_SPINE_REQUIRED",
            "message": "a live-validated claim spine is required to authorize drafting",
        })
    else:
        from rka.skills.writer.scripts import claim_spine

        resolver = lambda entity_id: deepcopy(entities.get(entity_id))  # noqa: E731
        report = claim_spine.validate_spine(spine, resolver=resolver, project_id=project_id)
        spine_report = {
            "verdict": report.verdict,
            "findings": [finding.__dict__ for finding in report.findings],
        }
        if not spine.get("claims"):
            blockers.append({"code": "EMPTY_CLAIM_SPINE", "message": "claim spine has no claims"})
        if not spine.get("units"):
            blockers.append({"code": "NO_MANUSCRIPT_UNITS", "message": "claim spine has no units"})
        if report.verdict in {"BLOCK", "ERROR"}:
            blockers.append({
                "code": "CLAIM_SPINE_NOT_READY",
                "message": f"claim-spine validation returned {report.verdict}",
            })

    return {
        "schema_version": "rka-writer-readiness/v1",
        "project_id": project_id,
        "manuscript_id": manuscript_id,
        "ready_for_drafting": not blockers,
        "blockers": blockers,
        "inventory": {
            "registered_manuscripts": manuscripts,
            "manuscript_ready_claims": ready_claims,
            "scoped_pi_decisions": pi_decisions,
        },
        "claim_spine": spine_report,
        "mode": "read_only",
    }


def propose_assist(
    *, packet_path: Path, project_id: str, manuscript_id: str | None = None
) -> dict[str, Any]:
    """Propose a candidate spine from current records; make no writes."""
    _payload, entities = load_entity_packet(packet_path, project_id)
    manuscripts = _manuscripts(entities)
    if manuscript_id is not None:
        validate_identity(project_id, manuscript_id)
    elif len(manuscripts) == 1:
        manuscript_id = manuscripts[0]
    ready_claim_ids = _ready_claims(entities)
    claims: list[dict[str, Any]] = []
    for index, entity_id in enumerate(ready_claim_ids, start=1):
        content = str(entities[entity_id].get("content") or "").strip()
        claims.append({
            "claim_id": f"C{index}",
            "text": content,
            "claim_type": "empirical",
            "status": "candidate",
            "ratified_by": None,
            "evidence_ids": [entity_id],
            "qualifier_ids": [],
            "counterevidence_ids": [],
            "allowed_wording": content,
            "prohibited_wording": [],
            "manuscript_units": [],
        })
    return {
        "schema_version": "rka-writer-assist/v1",
        "project_id": project_id,
        "selected_manuscript_id": manuscript_id,
        "manuscript_candidates": manuscripts,
        "candidate_spine": {
            "schema_version": "rka-claim-spine/v1",
            "project_id": project_id,
            "manuscript_id": manuscript_id,
            "generated_at": utc_now(),
            "changelog_cursor": None,
            "claims": claims,
            "units": [],
            "rka_snapshot": None,
        },
        "required_human_actions": [
            "Select the manuscript if more than one candidate is listed.",
            "Refine each candidate into a bounded contribution claim.",
            "Have the PI ratify the exact wording in an active decision whose related_journal names the manuscript.",
            "Add result units, qualifiers, counterevidence, and interpretation boundaries before validation.",
        ],
        "mode": "read_only_proposal",
    }
