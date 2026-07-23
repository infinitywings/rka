"""Fail-closed, RKA-authoritative workflow helpers for the RKA Writer.

This module owns three small host-neutral operations:

* atomic workspace initialization after manuscript registration/verification;
* server-authoritative readiness, synchronization, and spine import;
* compatibility evaluation from a fresh, project-scoped entity packet;
* a read-only candidate claim-spine proposal for PI/Brain review.

It never uses a default project. Readiness, synchronization, assist, and
dry-run import never mutate RKA. Applying an import replaces only the native
argument-spine projection and never creates a PI ratification.
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
MANUSCRIPT_RE = re.compile(r"^(?:man|jrn)_[0-9A-Z]{26}$")
CANONICAL_MANUSCRIPT_RE = re.compile(r"^man_[0-9A-Z]{26}$")
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
        raise WriterWorkflowError(
            "manuscript_id must be a canonical man_ identifier or legacy jrn_ alias"
        )


def _http_json_value(
    api_url: str,
    project_id: str,
    method: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
    timeout: float = 20.0,
) -> Any:
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
    return decoded


def _http_json(
    api_url: str,
    project_id: str,
    method: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    decoded = _http_json_value(
        api_url,
        project_id,
        method,
        path,
        payload,
        timeout,
    )
    if not isinstance(decoded, dict):
        raise WriterWorkflowError("RKA returned a non-object response")
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
    """Return canonical ``(manuscript_id, mode)`` after a scoped API check."""
    validate_identity(project_id, manuscript_id)
    if manuscript_id:
        record = _http_json(
            api_url,
            project_id,
            "GET",
            f"/api/manuscripts/{quote(manuscript_id, safe='')}",
            timeout=timeout,
        )
        if record.get("project_id") != project_id:
            raise WriterWorkflowError("RKA manuscript response did not attest the requested project")
        canonical_id = str(record.get("canonical_id") or record.get("id") or "")
        if not CANONICAL_MANUSCRIPT_RE.fullmatch(canonical_id):
            raise WriterWorkflowError(
                "RKA manuscript response did not provide a canonical man_ id"
            )
        requested_id = str(record.get("requested_id") or record.get("id") or "")
        if requested_id != manuscript_id and record.get("id") != manuscript_id:
            raise WriterWorkflowError(
                "RKA manuscript response did not preserve the requested id"
            )
        if record.get("venue") != venue:
            raise WriterWorkflowError(
                f"existing manuscript venue {record.get('venue')!r} does not match {venue!r}"
            )
        if (record.get("title") or "").strip() != title.strip():
            raise WriterWorkflowError("existing manuscript title does not match --title")
        mode = "verified" if manuscript_id == canonical_id else "verified_legacy_alias"
        return canonical_id, mode

    record = _http_json(
        api_url,
        project_id,
        "POST",
        "/api/manuscripts/native",
        {
            "venue": venue,
            "title": title,
            "abstract": abstract,
            "phase": "planning",
            "state": "active",
        },
        timeout=timeout,
    )
    created_id = str(record.get("id") or "")
    if record.get("project_id") != project_id:
        raise WriterWorkflowError("RKA registration did not attest the requested project")
    if not CANONICAL_MANUSCRIPT_RE.fullmatch(created_id):
        raise WriterWorkflowError("RKA registration did not return a canonical man_ id")
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
        for sentinel, value in sorted(
            replacements.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
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
            "schema_version": "rka-writer-workspace/v2",
            "authoritative_source": "rka",
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


def evaluate_server_readiness(
    *,
    api_url: str,
    project_id: str,
    manuscript_id: str,
    target_phase: str = "drafting",
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Read the authoritative readiness verdict from the native aggregate."""
    validate_identity(project_id, manuscript_id)
    encoded_id = quote(manuscript_id, safe="")
    encoded_phase = quote(target_phase, safe="")
    report = _http_json(
        api_url,
        project_id,
        "GET",
        f"/api/manuscripts/{encoded_id}/readiness?target_phase={encoded_phase}",
        timeout=timeout,
    )
    if report.get("project_id") != project_id:
        raise WriterWorkflowError("RKA readiness did not attest the requested project")
    canonical_id = str(report.get("manuscript_id") or "")
    if not CANONICAL_MANUSCRIPT_RE.fullmatch(canonical_id):
        raise WriterWorkflowError("RKA readiness did not identify a canonical man_ manuscript")
    verdict = str(report.get("verdict") or "")
    if verdict not in {"PASS", "WARN", "BLOCK", "ERROR"}:
        raise WriterWorkflowError("RKA readiness returned an unknown verdict")
    ready = report.get("ready") is True and verdict not in {"BLOCK", "ERROR"}
    return {
        "schema_version": "rka-writer-readiness/v2",
        "project_id": project_id,
        "manuscript_id": canonical_id,
        "target_phase": target_phase,
        "ready_for_drafting": ready,
        "blockers": [
            finding
            for finding in report.get("findings", [])
            if isinstance(finding, dict)
            and finding.get("verdict") in {"BLOCK", "ERROR"}
        ],
        "server_readiness": report,
        "authoritative_source": "rka",
        "mode": "server_authoritative_read_only",
    }


def sync_argument_spine(
    *,
    api_url: str,
    project_id: str,
    manuscript_id: str,
    output_path: Path,
    render_dir: Path | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Atomically refresh Writer projections from the RKA aggregate."""
    validate_identity(project_id, manuscript_id)
    from rka.skills.writer.scripts import claim_spine

    # Capture the watermark before reading the aggregate. Changes racing after
    # this read are conservatively rediscovered by the next impact check.
    cursor_page = _http_json(
        api_url,
        project_id,
        "GET",
        "/api/changes?cursor=0&limit=1",
        timeout=timeout,
    )
    latest_cursor = cursor_page.get("latest_cursor")
    if not isinstance(latest_cursor, int) or latest_cursor < 0:
        raise WriterWorkflowError("RKA change cursor returned an invalid watermark")
    projection = _http_json(
        api_url,
        project_id,
        "GET",
        f"/api/manuscripts/{quote(manuscript_id, safe='')}/spine",
        timeout=timeout,
    )
    if projection.get("project_id") != project_id:
        raise WriterWorkflowError("RKA spine projection did not attest the project")
    canonical_id = str(projection.get("manuscript_id") or "")
    if not CANONICAL_MANUSCRIPT_RE.fullmatch(canonical_id):
        raise WriterWorkflowError("RKA spine projection lacks a canonical man_ id")
    if projection.get("authoritative_source") != "rka":
        raise WriterWorkflowError("RKA spine projection lacks authority metadata")
    projection = dict(projection)
    projection["changelog_cursor"] = latest_cursor

    destination = output_path.expanduser().resolve()
    claim_spine._write_data(destination, projection)
    rendered: dict[str, str] = {}
    if render_dir is not None:
        rendered = {
            key: str(path)
            for key, path in claim_spine.render_views(
                projection,
                render_dir.expanduser().resolve(),
            ).items()
        }
    return {
        "status": "synchronized",
        "project_id": project_id,
        "manuscript_id": canonical_id,
        "manuscript_revision": projection.get("manuscript_revision"),
        "changelog_cursor": latest_cursor,
        "projection": str(destination),
        "rendered_views": rendered,
        "authoritative_source": "rka",
    }


def inspect_server_impact(
    *,
    api_url: str,
    project_id: str,
    manuscript_id: str,
    since_cursor: int,
    limit: int = 100,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Read one deterministic page of evidence-to-writing impact."""
    validate_identity(project_id, manuscript_id)
    if (
        isinstance(since_cursor, bool)
        or not isinstance(since_cursor, int)
        or since_cursor < 0
    ):
        raise WriterWorkflowError("since_cursor must be a non-negative integer")
    if not 1 <= limit <= 1000:
        raise WriterWorkflowError("limit must be between 1 and 1000")
    report = _http_json(
        api_url,
        project_id,
        "GET",
        (
            f"/api/manuscripts/{quote(manuscript_id, safe='')}/impact"
            f"?since_cursor={since_cursor}&limit={limit}"
        ),
        timeout=timeout,
    )
    if report.get("project_id") != project_id:
        raise WriterWorkflowError("RKA impact report did not attest the project")
    canonical_id = str(report.get("manuscript_id") or "")
    if not CANONICAL_MANUSCRIPT_RE.fullmatch(canonical_id):
        raise WriterWorkflowError("RKA impact report lacks a canonical man_ id")
    if report.get("impact_state") not in {
        "no_relevant_changes",
        "relevant_changes",
        "partial",
    }:
        raise WriterWorkflowError("RKA impact report returned an unknown state")
    return {
        "schema_version": "rka-writer-impact/v1",
        "project_id": project_id,
        "manuscript_id": canonical_id,
        "requires_resync": report.get("impact_state") in {
            "relevant_changes",
            "partial",
        },
        "server_impact": report,
        "mode": "server_authoritative_read_only",
    }


def import_argument_spine(
    *,
    api_url: str,
    project_id: str,
    manuscript_id: str,
    spine_path: Path,
    apply: bool = False,
    expected_revision: int | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Validate/diff a Writer spine and optionally apply it to native RKA.

    Applying updates claim/unit identities, wording versions, evidence roles,
    and unit bindings only. The server deliberately ignores legacy
    ``ratified_by`` projections; each exact wording still requires a separate
    explicit PI ratification command.
    """
    validate_identity(project_id, manuscript_id)
    from rka.skills.writer.scripts import claim_spine

    local = claim_spine.load_spine(spine_path)
    if str(local.get("project_id") or "") != project_id:
        raise WriterWorkflowError("claim spine project_id does not match --project-id")
    local_manuscript = str(local.get("manuscript_id") or "")
    if local_manuscript and not MANUSCRIPT_RE.fullmatch(local_manuscript):
        raise WriterWorkflowError(
            "claim spine manuscript_id is not a canonical man_ id or jrn_ alias"
        )

    current = _http_json(
        api_url,
        project_id,
        "GET",
        f"/api/manuscripts/{quote(manuscript_id, safe='')}/spine",
        timeout=timeout,
    )
    canonical_id = str(current.get("manuscript_id") or "")
    revision = current.get("manuscript_revision")
    if current.get("project_id") != project_id or not isinstance(revision, int):
        raise WriterWorkflowError("RKA returned an invalid current spine projection")
    if local_manuscript and local_manuscript not in {manuscript_id, canonical_id}:
        local_target = _http_json(
            api_url,
            project_id,
            "GET",
            f"/api/manuscripts/{quote(local_manuscript, safe='')}/spine",
            timeout=timeout,
        )
        if (
            local_target.get("project_id") != project_id
            or local_target.get("manuscript_id") != canonical_id
        ):
            raise WriterWorkflowError(
                "claim spine targets a different canonical manuscript"
            )
    projection_revision = local.get("manuscript_revision")
    if projection_revision is not None and (
        not isinstance(projection_revision, int) or projection_revision < 1
    ):
        raise WriterWorkflowError(
            "claim spine manuscript_revision must be a positive integer"
        )
    selected_revision = (
        expected_revision
        if expected_revision is not None
        else projection_revision
    )
    if selected_revision is not None and selected_revision < 1:
        raise WriterWorkflowError("expected_revision must be at least 1")

    local_claims = local.get("claims") if isinstance(local.get("claims"), list) else []
    local_units = local.get("units") if isinstance(local.get("units"), list) else []
    current_claims = (
        current.get("claims") if isinstance(current.get("claims"), list) else []
    )
    current_units = current.get("units") if isinstance(current.get("units"), list) else []
    preview = {
        "schema_version": "rka-writer-spine-import/v1",
        "project_id": project_id,
        "manuscript_id": canonical_id,
        "expected_revision": selected_revision,
        "projection_revision": projection_revision,
        "current_revision": revision,
        "revision_matches_current": selected_revision == revision,
        "current_claim_count": len(current_claims),
        "proposed_claim_count": len(local_claims),
        "current_unit_count": len(current_units),
        "proposed_unit_count": len(local_units),
        "would_change": (
            local_claims != current_claims or local_units != current_units
        ),
        "ratifications_imported": False,
        "mode": "dry_run",
    }
    if not apply:
        return preview
    if selected_revision is None:
        raise WriterWorkflowError(
            "applying a legacy spine without manuscript_revision requires "
            "--expected-revision"
        )
    if selected_revision != revision:
        raise WriterWorkflowError(
            "claim spine revision is stale: projection expects "
            f"{selected_revision}, but RKA is at {revision}; synchronize, "
            "review the server changes, and rebase the proposal"
        )

    updated = _http_json(
        api_url,
        project_id,
        "PUT",
        f"/api/manuscripts/{quote(canonical_id, safe='')}/argument-spine",
        {"expected_revision": selected_revision, "spine": local},
        timeout=timeout,
    )
    preview.update({
        "mode": "applied",
        "new_revision": (
            updated.get("manuscript", {}).get("revision")
            if isinstance(updated.get("manuscript"), dict)
            else None
        ),
        "result": updated,
    })
    return preview


def propose_server_assist(
    *,
    api_url: str,
    project_id: str,
    manuscript_id: str,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Request RKA's cluster/RQ-smoothed, unratified candidate set."""
    validate_identity(project_id, manuscript_id)
    proposal = _http_json(
        api_url,
        project_id,
        "GET",
        (
            f"/api/manuscripts/{quote(manuscript_id, safe='')}"
            "/writing-candidates"
        ),
        timeout=timeout,
    )
    if (
        proposal.get("project_id") != project_id
        or proposal.get("schema_version")
        != "rka.writing-evidence-candidates/v1"
        or not CANONICAL_MANUSCRIPT_RE.fullmatch(
            str(proposal.get("manuscript_id") or "")
        )
        or not isinstance(proposal.get("candidate_spine"), dict)
    ):
        raise WriterWorkflowError(
            "RKA returned an invalid writing-candidate packet"
        )
    return proposal


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
    currentness = entity.get("currentness")
    if isinstance(currentness, Mapping) and currentness.get("is_current") is not True:
        return False
    status = str(entity.get("status") or "").lower()
    state = str(entity.get("state") or "").lower()
    confidence = str(entity.get("confidence") or "").lower()
    return (
        status not in INACTIVE_STATUSES
        and state not in {"archived", "rejected", "retired", "withdrawn"}
        and confidence not in {"superseded", "retracted"}
        and not entity.get("superseded_by")
        and not bool(entity.get("stale"))
    )


def _manuscripts(entities: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return sorted(
        entity_id
        for entity_id, entity in entities.items()
        if MANUSCRIPT_RE.fullmatch(entity_id)
        and (
            (
                entity_id.startswith("man_")
                and entity.get("type") == "manuscript"
            )
            or (
                entity_id.startswith("jrn_")
                and "manuscript" in (entity.get("tags") or [])
            )
        )
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
    """Inspect a legacy packet without authorizing drafting.

    Entity packets are caller-controlled compatibility inputs: they have no
    server-issued freshness or authenticity proof.  They may still help a
    pre-native workspace discover structural gaps, but only live native RKA
    readiness can authorize phase advancement.
    """
    _payload, entities = load_entity_packet(packet_path, project_id)
    manuscripts = _manuscripts(entities)
    ready_claims = _ready_claims(entities)
    blockers: list[dict[str, str]] = [{
        "code": "ENTITY_PACKET_ADVISORY_ONLY",
        "message": (
            "caller-supplied entity packets are unauthenticated compatibility "
            "inputs and cannot authorize drafting; query native server readiness"
        ),
    }]

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
        "mode": "compatibility_advisory",
    }


def _assist_from_entities(
    entities: Mapping[str, Mapping[str, Any]],
    *,
    project_id: str,
    manuscript_id: str | None,
) -> dict[str, Any]:
    """Build a candidate-only spine from already project-attested entities."""
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
        "schema_version": "rka-writer-assist/v2",
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


def propose_assist(
    *, packet_path: Path, project_id: str, manuscript_id: str | None = None
) -> dict[str, Any]:
    """Compatibility packet mode; propose candidates without any writes."""
    _payload, entities = load_entity_packet(packet_path, project_id)
    return _assist_from_entities(
        entities,
        project_id=project_id,
        manuscript_id=manuscript_id,
    )
