#!/usr/bin/env python3
"""Validate and render an RKA-backed manuscript claim spine.

The YAML document is a planning projection. RKA remains authoritative for
evidence, PI decisions, and record currency. Generated Markdown views are
deliberately deterministic and read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


SCHEMA_VERSION = "rka-claim-spine/v1"
SNAPSHOT_VERSION = "rka-claim-spine-snapshot/v1"
STALE_STATES = {"abandoned", "retracted", "retired", "stale", "superseded"}
RATIFIED_STATES = {"ratified"}
SEVERITY_RANK = {"PASS": 0, "WARN": 1, "BLOCK": 2, "ERROR": 3}
Resolver = Callable[[str], Mapping[str, Any] | None]


@dataclass(frozen=True)
class Finding:
    """One deterministic claim-spine validation finding."""

    code: str
    severity: str
    message: str
    claim_id: str | None = None
    entity_id: str | None = None


@dataclass
class ValidationReport:
    """Structural and live-RKA validation result."""

    findings: list[Finding] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if not self.findings:
            return "PASS"
        return max(
            (finding.severity for finding in self.findings),
            key=lambda severity: SEVERITY_RANK.get(severity, 3),
        )


@dataclass
class CurrencyReport:
    """Dependency-aware comparison of a saved snapshot with current RKA."""

    verdict: str
    changed_entities: list[str] = field(default_factory=list)
    affected_claims: list[str] = field(default_factory=list)
    affected_units: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def load_spine(path: str | Path) -> dict[str, Any]:
    """Load a claim-spine YAML/JSON document without constructing objects."""

    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read claim-spine document {source}: {exc}") from exc

    try:
        import yaml  # type: ignore[import-not-found]

        loaded = yaml.safe_load(text)
    except ImportError:
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "PyYAML is unavailable; supply the claim spine as JSON-compatible YAML"
            ) from exc
    except Exception as exc:
        raise ValueError(f"invalid or unsafe claim-spine document: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ValueError("claim-spine document must be a mapping/object")
    return loaded


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _entity_prefix(entity_id: str) -> str:
    return entity_id.split("_", 1)[0] if "_" in entity_id else ""


def _is_stale(entity: Mapping[str, Any]) -> bool:
    if entity.get("stale") is True or entity.get("superseded_by"):
        return True
    for key in ("status", "confidence"):
        value = entity.get(key)
        if isinstance(value, str) and value.lower() in STALE_STATES:
            return True
    return False


def _is_verified(entity: Mapping[str, Any]) -> bool:
    verified = entity.get("verified")
    if verified is not None:
        return verified is True
    confidence = entity.get("confidence")
    return isinstance(confidence, str) and confidence.lower() == "verified"


def _stable_payload(entity: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe entity copy without transport-only timestamps."""

    excluded = {"created_at", "updated_at", "last_accessed_at"}
    return {
        str(key): deepcopy(value)
        for key, value in sorted(entity.items(), key=lambda item: str(item[0]))
        if str(key) not in excluded
    }


def _entity_snapshot(entity_id: str, entity: Mapping[str, Any] | None) -> dict[str, Any]:
    if entity is None:
        return {"id": entity_id, "missing": True}
    payload = _stable_payload(entity)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return {
        "id": entity_id,
        "project_id": entity.get("project_id"),
        "source_entry_id": entity.get("source_entry_id"),
        "status": entity.get("status"),
        "confidence": entity.get("confidence"),
        "verified": entity.get("verified"),
        "stale": _is_stale(entity),
        "contradicted": entity.get("contradicted") is True,
        "superseded_by": entity.get("superseded_by"),
        "fingerprint": hashlib.sha256(encoded).hexdigest(),
    }


def _direct_entity_ids(data: Mapping[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    manuscript_id = _text(data.get("manuscript_id"))
    if manuscript_id:
        identifiers.add(manuscript_id)
    for claim in _list(data.get("claims")):
        if not isinstance(claim, Mapping):
            continue
        decision_id = _text(claim.get("ratified_by"))
        if decision_id:
            identifiers.add(decision_id)
        for key in ("evidence_ids", "qualifier_ids", "counterevidence_ids"):
            identifiers.update(
                value for value in _list(claim.get(key)) if isinstance(value, str) and value
            )
    for unit in _list(data.get("units")):
        if not isinstance(unit, Mapping):
            continue
        identifiers.update(
            value
            for value in _list(unit.get("evidence_ids"))
            if isinstance(value, str) and value
        )
    return identifiers


def _resolve_closure(
    identifiers: Iterable[str], resolver: Resolver
) -> dict[str, Mapping[str, Any] | None]:
    resolved: dict[str, Mapping[str, Any] | None] = {}
    pending = sorted(set(identifiers))
    while pending:
        entity_id = pending.pop(0)
        if entity_id in resolved:
            continue
        entity = resolver(entity_id)
        resolved[entity_id] = entity
        if entity is None:
            continue
        source_id = _text(entity.get("source_entry_id"))
        if source_id and source_id not in resolved and source_id not in pending:
            pending.append(source_id)
            pending.sort()
    return resolved


def build_snapshot(data: Mapping[str, Any], resolver: Resolver) -> dict[str, Any]:
    """Build a deterministic snapshot of all claim-spine RKA dependencies."""

    resolved = _resolve_closure(_direct_entity_ids(data), resolver)
    entities = {
        entity_id: _entity_snapshot(entity_id, resolved[entity_id])
        for entity_id in sorted(resolved)
    }
    return {
        "schema_version": SNAPSHOT_VERSION,
        "project_id": data.get("project_id"),
        "entities": entities,
    }


def _add(
    findings: list[Finding],
    code: str,
    message: str,
    *,
    severity: str = "BLOCK",
    claim_id: str | None = None,
    entity_id: str | None = None,
) -> None:
    finding = Finding(code, severity, message, claim_id, entity_id)
    if finding not in findings:
        findings.append(finding)


def _validate_entity(
    findings: list[Finding],
    entity_id: str,
    entity: Mapping[str, Any] | None,
    expected_project: str,
    *,
    claim_id: str | None = None,
    source: bool = False,
) -> None:
    if entity is None:
        _add(
            findings,
            "MISSING_ENTITY",
            f"RKA entity {entity_id} does not resolve",
            claim_id=claim_id,
            entity_id=entity_id,
        )
        return
    actual_project = _text(entity.get("project_id"))
    if expected_project and actual_project != expected_project:
        _add(
            findings,
            "WRONG_PROJECT",
            f"RKA entity {entity_id} belongs to {actual_project or 'no project'}",
            claim_id=claim_id,
            entity_id=entity_id,
        )
    if _is_stale(entity):
        _add(
            findings,
            "STALE_SOURCE" if source else "STALE_ENTITY",
            f"RKA {'source' if source else 'entity'} {entity_id} is not current",
            claim_id=claim_id,
            entity_id=entity_id,
        )


def validate_spine(
    data: Mapping[str, Any],
    resolver: Resolver | None = None,
    project_id: str | None = None,
) -> ValidationReport:
    """Validate structure, evidentiary roles, PI ratification, and currency."""

    findings: list[Finding] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        _add(
            findings,
            "UNSUPPORTED_SCHEMA",
            f"expected schema_version {SCHEMA_VERSION}",
        )

    expected_project = project_id or _text(data.get("project_id"))
    if not expected_project:
        _add(findings, "PROJECT_REQUIRED", "project_id is required")
    elif project_id and _text(data.get("project_id")) != project_id:
        _add(
            findings,
            "WRONG_PROJECT",
            "claim-spine project_id does not match the requested project",
        )

    claims = _list(data.get("claims"))
    units = _list(data.get("units"))
    if not isinstance(data.get("claims"), list):
        _add(findings, "CLAIMS_REQUIRED", "claims must be a list")
    if not isinstance(data.get("units"), list):
        _add(findings, "UNITS_REQUIRED", "units must be a list")

    claim_rows = [row for row in claims if isinstance(row, Mapping)]
    unit_rows = [row for row in units if isinstance(row, Mapping)]
    if len(claim_rows) != len(claims):
        _add(findings, "INVALID_CLAIM", "every claim must be a mapping")
    if len(unit_rows) != len(units):
        _add(findings, "INVALID_UNIT", "every manuscript unit must be a mapping")

    claim_ids = [_text(claim.get("claim_id")) for claim in claim_rows]
    for claim_id in sorted({value for value in claim_ids if value and claim_ids.count(value) > 1}):
        _add(
            findings,
            "DUPLICATE_CLAIM_ID",
            f"claim_id {claim_id} appears more than once",
            claim_id=claim_id,
        )
    unit_ids = [_text(unit.get("unit_id")) for unit in unit_rows]
    for unit_id in sorted({value for value in unit_ids if value and unit_ids.count(value) > 1}):
        _add(findings, "DUPLICATE_UNIT_ID", f"unit_id {unit_id} appears more than once")

    if resolver is None:
        _add(
            findings,
            "RESOLVER_REQUIRED",
            "live RKA resolution is required for a trustworthy validation result",
            severity="ERROR",
        )
        return ValidationReport(findings)

    try:
        resolved = _resolve_closure(_direct_entity_ids(data), resolver)
    except Exception as exc:
        _add(
            findings,
            "RESOLVER_ERROR",
            f"RKA resolver failed: {exc}",
            severity="ERROR",
        )
        return ValidationReport(findings)

    # Validate the manuscript manifest independently of claim-level support.
    manuscript_id = _text(data.get("manuscript_id"))
    if not manuscript_id:
        _add(findings, "MANUSCRIPT_REQUIRED", "manuscript_id is required")
    else:
        _validate_entity(
            findings,
            manuscript_id,
            resolved.get(manuscript_id),
            expected_project,
        )

    units_by_id = {_text(unit.get("unit_id")): unit for unit in unit_rows}
    for claim in claim_rows:
        claim_id = _text(claim.get("claim_id")) or None
        claim_text = _text(claim.get("text"))
        claim_type = _text(claim.get("claim_type")).lower()
        status = _text(claim.get("status")).lower()
        if not claim_id or not claim_text or not claim_type or not status:
            _add(
                findings,
                "CLAIM_FIELDS_REQUIRED",
                "claim_id, text, claim_type, and status are required",
                claim_id=claim_id,
            )
        if status not in RATIFIED_STATES:
            _add(
                findings,
                "RATIFICATION_REQUIRED",
                "candidate wording cannot authorize substantive drafting",
                claim_id=claim_id,
            )

        evidence_ids = [
            value for value in _list(claim.get("evidence_ids")) if isinstance(value, str)
        ]
        qualifier_ids = [
            value for value in _list(claim.get("qualifier_ids")) if isinstance(value, str)
        ]
        counter_ids = [
            value
            for value in _list(claim.get("counterevidence_ids"))
            if isinstance(value, str)
        ]
        if not evidence_ids:
            _add(
                findings,
                "EVIDENCE_REQUIRED",
                "a manuscript claim needs source-backed RKA evidence",
                claim_id=claim_id,
            )
        if not _text(claim.get("allowed_wording")) or not _list(
            claim.get("prohibited_wording")
        ):
            _add(
                findings,
                "CLAIM_BOUNDARY_REQUIRED",
                "allowed_wording and at least one prohibited_wording boundary are required",
                claim_id=claim_id,
            )

        decision_id = _text(claim.get("ratified_by"))
        decision = resolved.get(decision_id) if decision_id else None
        if status in RATIFIED_STATES:
            valid_ratification = (
                bool(decision_id)
                and _entity_prefix(decision_id) == "dec"
                and decision is not None
                and not _is_stale(decision)
                and _text(decision.get("decided_by")).lower() == "pi"
            )
            if not valid_ratification:
                _add(
                    findings,
                    "RATIFICATION_REQUIRED",
                    "ratified wording requires a current PI-authored dec_ record",
                    claim_id=claim_id,
                    entity_id=decision_id or None,
                )
            elif _text(decision.get("chosen")) != claim_text:
                _add(
                    findings,
                    "RATIFICATION_MISMATCH",
                    "claim text differs from the exact wording ratified by the PI",
                    claim_id=claim_id,
                    entity_id=decision_id,
                )

        for entity_id in [decision_id, *evidence_ids, *qualifier_ids, *counter_ids]:
            if not entity_id:
                continue
            entity = resolved.get(entity_id)
            _validate_entity(
                findings,
                entity_id,
                entity,
                expected_project,
                claim_id=claim_id,
            )
            if entity is None:
                continue
            source_id = _text(entity.get("source_entry_id"))
            if source_id:
                _validate_entity(
                    findings,
                    source_id,
                    resolved.get(source_id),
                    expected_project,
                    claim_id=claim_id,
                    source=True,
                )

        if claim_type == "empirical":
            for entity_id in evidence_ids:
                if _entity_prefix(entity_id) not in {"clm", "jrn"}:
                    _add(
                        findings,
                        "INVALID_EVIDENCE_ROLE",
                        f"{entity_id} cannot serve as terminal empirical evidence",
                        claim_id=claim_id,
                        entity_id=entity_id,
                    )
                entity = resolved.get(entity_id)
                if entity is not None and _entity_prefix(entity_id) == "clm":
                    if not _is_verified(entity) or entity.get("contradicted") is True:
                        _add(
                            findings,
                            "UNVERIFIED_EVIDENCE",
                            f"empirical support {entity_id} is not verified and uncontested",
                            claim_id=claim_id,
                            entity_id=entity_id,
                        )

            result_units = [
                unit
                for unit in unit_rows
                if _text(unit.get("kind")).lower() == "result"
                and claim_id in _list(unit.get("claim_ids"))
            ]
            if not result_units:
                _add(
                    findings,
                    "RESULT_COVERAGE_REQUIRED",
                    "an empirical contribution must map to a Results unit",
                    claim_id=claim_id,
                )

        if status in RATIFIED_STATES and counter_ids:
            for entity_id in counter_ids:
                _add(
                    findings,
                    "UNRESOLVED_CONTRADICTION",
                    "ratified wording cannot hide unresolved counterevidence",
                    claim_id=claim_id,
                    entity_id=entity_id,
                )

        declared_units = [
            value
            for value in _list(claim.get("manuscript_units"))
            if isinstance(value, str)
        ]
        for unit_id in declared_units:
            unit = units_by_id.get(unit_id)
            if unit is None or claim_id not in _list(unit.get("claim_ids")):
                _add(
                    findings,
                    "UNIT_LINK_MISMATCH",
                    f"claim and manuscript unit disagree about {unit_id}",
                    claim_id=claim_id,
                )

    known_claims = {value for value in claim_ids if value}
    for unit in unit_rows:
        unit_id = _text(unit.get("unit_id"))
        kind = _text(unit.get("kind")).lower()
        linked_claims = [
            value for value in _list(unit.get("claim_ids")) if isinstance(value, str)
        ]
        if kind == "result" and not linked_claims:
            _add(
                findings,
                "ORPHAN_RESULT",
                f"Results unit {unit_id or '<unknown>'} serves no contribution",
            )
        for claim_id in linked_claims:
            if claim_id not in known_claims:
                _add(
                    findings,
                    "UNKNOWN_CLAIM",
                    f"unit {unit_id} references unknown claim {claim_id}",
                    claim_id=claim_id,
                )
        if kind == "result" and (
            not _text(unit.get("allowed_interpretation"))
            or not _text(unit.get("prohibited_interpretation"))
        ):
            _add(
                findings,
                "RESULT_BOUNDARY_REQUIRED",
                f"Results unit {unit_id} needs allowed and prohibited interpretations",
            )
        for entity_id in _list(unit.get("evidence_ids")):
            if isinstance(entity_id, str):
                _validate_entity(
                    findings,
                    entity_id,
                    resolved.get(entity_id),
                    expected_project,
                )

    return ValidationReport(findings)


def _snapshot_dependencies(data: Mapping[str, Any], claim: Mapping[str, Any]) -> set[str]:
    saved = data.get("rka_snapshot")
    saved_entities = saved.get("entities", {}) if isinstance(saved, Mapping) else {}
    direct: set[str] = set()
    decision_id = _text(claim.get("ratified_by"))
    if decision_id:
        direct.add(decision_id)
    for key in ("evidence_ids", "qualifier_ids", "counterevidence_ids"):
        direct.update(value for value in _list(claim.get(key)) if isinstance(value, str))

    expanded = set(direct)
    pending = list(direct)
    while pending:
        entity_id = pending.pop()
        snapshot = saved_entities.get(entity_id)
        if not isinstance(snapshot, Mapping):
            continue
        source_id = _text(snapshot.get("source_entry_id"))
        if source_id and source_id not in expanded:
            expanded.add(source_id)
            pending.append(source_id)
    return expanded


def check_currency(data: Mapping[str, Any], resolver: Resolver) -> CurrencyReport:
    """Report which claims and manuscript units depend on changed RKA records."""

    saved = data.get("rka_snapshot")
    if not isinstance(saved, Mapping) or not isinstance(saved.get("entities"), Mapping):
        finding = Finding(
            "SNAPSHOT_REQUIRED",
            "ERROR",
            "rka_snapshot is required before currency can be checked",
        )
        return CurrencyReport("ERROR", findings=[finding])

    saved_entities = saved["entities"]
    identifiers = set(saved_entities) | _direct_entity_ids(data)
    try:
        current_resolved = _resolve_closure(identifiers, resolver)
    except Exception as exc:
        finding = Finding("RESOLVER_ERROR", "ERROR", f"RKA resolver failed: {exc}")
        return CurrencyReport("ERROR", findings=[finding])

    current = {
        entity_id: _entity_snapshot(entity_id, current_resolved.get(entity_id))
        for entity_id in sorted(set(current_resolved) | set(saved_entities))
    }
    changed = sorted(
        entity_id
        for entity_id in set(current) | set(saved_entities)
        if current.get(entity_id) != saved_entities.get(entity_id)
    )

    affected_claims: list[str] = []
    for claim in _list(data.get("claims")):
        if not isinstance(claim, Mapping):
            continue
        claim_id = _text(claim.get("claim_id"))
        if claim_id and _snapshot_dependencies(data, claim) & set(changed):
            affected_claims.append(claim_id)

    affected_units: list[str] = []
    affected_claim_set = set(affected_claims)
    for unit in _list(data.get("units")):
        if not isinstance(unit, Mapping):
            continue
        unit_id = _text(unit.get("unit_id"))
        unit_claims = set(value for value in _list(unit.get("claim_ids")) if isinstance(value, str))
        unit_evidence = set(
            value for value in _list(unit.get("evidence_ids")) if isinstance(value, str)
        )
        if unit_id and (unit_claims & affected_claim_set or unit_evidence & set(changed)):
            affected_units.append(unit_id)

    findings: list[Finding] = []
    verdict = "PASS"
    for entity_id in changed:
        state = current.get(entity_id, {})
        if state.get("missing") or state.get("stale"):
            severity = "BLOCK"
            verdict = "BLOCK"
        else:
            severity = "WARN"
            if verdict == "PASS":
                verdict = "WARN"
        findings.append(
            Finding(
                "DEPENDENCY_CHANGED",
                severity,
                f"RKA dependency {entity_id} changed after the saved snapshot",
                entity_id=entity_id,
            )
        )
    return CurrencyReport(
        verdict,
        changed,
        sorted(set(affected_claims)),
        sorted(set(affected_units)),
        findings,
    )


def _md(value: Any) -> str:
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value)
    return str(value or "—").replace("\n", " ").replace("|", "\\|")


def _header(data: Mapping[str, Any], title: str) -> list[str]:
    return [
        f"# {title}",
        "",
        "> Generated, read-only RKA view. Edit `RKA_CLAIM_SPINE.yaml`, then regenerate.",
        "> RKA records and current PI decisions remain authoritative.",
        "",
        f"- Project: `{_md(data.get('project_id'))}`",
        f"- Manuscript: `{_md(data.get('manuscript_id'))}`",
        f"- RKA changelog cursor: `{_md(data.get('changelog_cursor'))}`",
        f"- Source generated at: `{_md(data.get('generated_at'))}`",
        "",
    ]


def _contribution_contract(data: Mapping[str, Any]) -> str:
    lines = _header(data, "Contribution Contract")
    for claim in _list(data.get("claims")):
        if not isinstance(claim, Mapping):
            continue
        claim_id = _md(claim.get("claim_id"))
        lines.extend(
            [
                f"## {claim_id}: {_md(claim.get('text'))}",
                "",
                f"- Type / state: `{_md(claim.get('claim_type'))}` / "
                f"`{_md(claim.get('status'))}`",
                f"- PI ratification: `{_md(claim.get('ratified_by'))}`",
                f"- Evidence: `{_md(claim.get('evidence_ids'))}`",
                f"- Qualifiers: `{_md(claim.get('qualifier_ids'))}`",
                f"- Counterevidence: `{_md(claim.get('counterevidence_ids'))}`",
                f"- Allowed wording: {_md(claim.get('allowed_wording'))}",
                f"- Prohibited wording: {_md(claim.get('prohibited_wording'))}",
                f"- Dependent manuscript units: `{_md(claim.get('manuscript_units'))}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _argument_spine(data: Mapping[str, Any]) -> str:
    lines = _header(data, "Argument Spine")
    lines.extend(
        [
            "| Unit | Kind | Location | Contribution | RKA evidence |",
            "|---|---|---|---|---|",
        ]
    )
    for unit in _list(data.get("units")):
        if isinstance(unit, Mapping):
            lines.append(
                "| "
                + " | ".join(
                    _md(unit.get(key))
                    for key in ("unit_id", "kind", "location", "claim_ids", "evidence_ids")
                )
                + " |"
            )
    lines.append("")
    return "\n".join(lines)


def _results_trace(data: Mapping[str, Any]) -> str:
    lines = _header(data, "Results Trace")
    lines.extend(
        [
            "| Results unit | Contribution | RKA evidence | Artifact | "
            "Allowed interpretation | Prohibited interpretation |",
            "|---|---|---|---|---|---|",
        ]
    )
    for unit in _list(data.get("units")):
        if not isinstance(unit, Mapping) or _text(unit.get("kind")).lower() != "result":
            continue
        lines.append(
            "| "
            + " | ".join(
                _md(unit.get(key))
                for key in (
                    "unit_id",
                    "claim_ids",
                    "evidence_ids",
                    "artifact",
                    "allowed_interpretation",
                    "prohibited_interpretation",
                )
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def render_views(data: Mapping[str, Any], output_dir: str | Path) -> dict[str, Path]:
    """Render the three deterministic, read-only manuscript planning views."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    rendered = {
        "contribution_contract": (
            destination / "CONTRIBUTION_CONTRACT.md",
            _contribution_contract(data),
        ),
        "argument_spine": (destination / "ARGUMENT_SPINE.md", _argument_spine(data)),
        "results_trace": (destination / "RESULTS_TRACE.md", _results_trace(data)),
    }
    paths: dict[str, Path] = {}
    for key, (path, content) in rendered.items():
        path.write_text(content, encoding="utf-8")
        paths[key] = path
    return paths


def _rest_resolver(
    base_url: str,
    timeout: float = 10.0,
    project_id: str | None = None,
) -> Resolver:
    endpoints = {
        "jrn": "/api/notes/{id}",
        "dec": "/api/decisions/{id}",
        "lit": "/api/literature/{id}",
        "mis": "/api/missions/{id}",
        "clm": "/api/claims/{id}",
        "ecl": "/api/clusters/{id}",
    }
    root = base_url.rstrip("/")

    def resolve(entity_id: str) -> Mapping[str, Any] | None:
        template = endpoints.get(_entity_prefix(entity_id))
        if template is None:
            return None
        url = root + template.format(id=quote(entity_id, safe=""))
        headers = {"Accept": "application/json"}
        if project_id:
            headers["X-RKA-Project"] = project_id
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise RuntimeError(f"RKA returned HTTP {exc.code} for {entity_id}") from exc
        except (URLError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot resolve {entity_id} from RKA: {exc}") from exc
        if isinstance(payload, Mapping):
            for key in ("entity", "data", "claim", "note", "decision", "cluster"):
                nested = payload.get(key)
                if isinstance(nested, Mapping):
                    entity = dict(nested)
                    if project_id:
                        entity.setdefault("project_id", project_id)
                    return entity
            entity = dict(payload)
            if project_id:
                entity.setdefault("project_id", project_id)
            return entity
        return None

    return resolve


def _packet_resolver(path: Path, expected_project: str) -> Resolver:
    """Load a fresh entity packet assembled through the project-scoped RKA MCP."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read RKA entity packet {path}: {exc}") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("entities"), Mapping):
        raise ValueError("RKA entity packet must be an object with an entities mapping")
    packet_project = _text(payload.get("project_id"))
    if not packet_project or packet_project != expected_project:
        raise ValueError(
            "RKA entity packet project_id must exactly match the claim-spine project_id"
        )
    entities = payload["entities"]

    def resolve(entity_id: str) -> Mapping[str, Any] | None:
        record = entities.get(entity_id)
        if not isinstance(record, Mapping):
            return None
        entity = deepcopy(dict(record))
        entity.setdefault("project_id", packet_project)
        return entity

    return resolve


def _write_data(path: Path, data: Mapping[str, Any]) -> None:
    if path.suffix.lower() == ".json":
        content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    else:
        try:
            import yaml  # type: ignore[import-not-found]

            content = yaml.safe_dump(dict(data), sort_keys=False)
        except ImportError as exc:
            raise ValueError(
                "PyYAML is required to write YAML; use an output ending in .json"
            ) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _report_json(report: ValidationReport | CurrencyReport) -> str:
    payload: dict[str, Any] = {
        "verdict": report.verdict,
        "findings": [finding.__dict__ for finding in report.findings],
    }
    if isinstance(report, CurrencyReport):
        payload.update(
            changed_entities=report.changed_entities,
            affected_claims=report.affected_claims,
            affected_units=report.affected_units,
        )
    return json.dumps(payload, indent=2, sort_keys=True)


def _exit_code(verdict: str) -> int:
    return {"PASS": 0, "WARN": 1, "BLOCK": 2, "ERROR": 3}.get(verdict, 3)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render", help="render read-only Markdown views")
    render.add_argument("input", type=Path)
    render.add_argument("--output-dir", type=Path, required=True)

    for command, help_text in (
        ("validate", "validate against current RKA"),
        ("snapshot", "save current RKA dependency fingerprints"),
        ("check-currency", "compare a saved snapshot with current RKA"),
    ):
        sub = subparsers.add_parser(command, help=help_text)
        sub.add_argument("input", type=Path)
        resolver_group = sub.add_mutually_exclusive_group()
        resolver_group.add_argument(
            "--entity-packet",
            type=Path,
            help="fresh project-scoped JSON packet assembled through RKA MCP",
        )
        resolver_group.add_argument(
            "--rka-url",
            help="trusted local RKA REST base URL, if intentionally available",
        )
        sub.add_argument("--timeout", type=float, default=10.0)
        if command == "validate":
            sub.add_argument("--project")
        if command == "snapshot":
            sub.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. PASS=0, WARN=1, BLOCK=2, malformed/ERROR=3."""

    try:
        args = _parser().parse_args(argv)
        data = load_spine(args.input)
        if args.command == "render":
            render_views(data, args.output_dir)
            return 0

        selected_project = getattr(args, "project", None) or _text(data.get("project_id"))
        if args.entity_packet:
            resolver = _packet_resolver(args.entity_packet, selected_project)
        elif args.rka_url:
            resolver = _rest_resolver(args.rka_url, args.timeout, selected_project)
        else:
            raise ValueError(
                "validation requires --entity-packet or an intentionally local --rka-url"
            )
        if args.command == "validate":
            report = validate_spine(data, resolver=resolver, project_id=args.project)
            print(_report_json(report))
            return _exit_code(report.verdict)
        if args.command == "check-currency":
            report = check_currency(data, resolver)
            print(_report_json(report))
            return _exit_code(report.verdict)
        if args.command == "snapshot":
            snapshot = build_snapshot(data, resolver)
            updated = deepcopy(data)
            updated["rka_snapshot"] = snapshot
            destination = args.output or args.input
            _write_data(destination, updated)
            return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"claim-spine error: {exc}", file=sys.stderr)
        return 3
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
