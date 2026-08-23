#!/usr/bin/env python3
"""Validate Writer style-profile and section discourse-plan artifacts.

This validator enforces structural, coverage, and handoff invariants. It does
not score prose quality or claim that a section is coherent; that judgment
remains a fresh-context review surfaced to the PI.

Exit codes: 0 PASS, 2 BLOCK, 3 invalid input or usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

STYLE_SCHEMA = "rka.writer-style-profile/v1"
DISCOURSE_SCHEMA = "rka.writer-discourse-plan/v1"
COHERENCE_QUESTIONS = {
    "single_takeaway",
    "paragraph_sequence",
    "one_job_per_paragraph",
    "challenge_response",
    "idea_before_mechanism",
    "evidence_advances_argument",
    "opening_promise_delivered",
    "prose_self_contained",
}


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    field: str | None = None
    severity: str = "BLOCK"


@dataclass
class ValidationReport:
    findings: list[Finding]

    @property
    def verdict(self) -> str:
        return "BLOCK" if self.findings else "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "findings": [asdict(finding) for finding in self.findings],
            "note": "Structural validation does not establish prose coherence.",
        }


def load_document(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read {source}: {exc}") from exc

    try:
        import yaml  # type: ignore[import-not-found]

        loaded = yaml.safe_load(text)
    except ImportError:
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("PyYAML is unavailable; supply JSON-compatible YAML") from exc
    except Exception as exc:
        raise ValueError(f"invalid or unsafe YAML/JSON document: {exc}") from exc

    if not isinstance(loaded, dict):
        raise TypeError("artifact must be a mapping/object")
    return loaded


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _duplicate(values: list[str]) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


def validate_style_profile(data: Mapping[str, Any]) -> ValidationReport:
    findings: list[Finding] = []
    if data.get("schema_version") != STYLE_SCHEMA:
        findings.append(Finding("STYLE_SCHEMA", f"schema_version must be {STYLE_SCHEMA}"))

    status = _text(data.get("status"))
    if status not in {"not_started", "draft", "approved"}:
        findings.append(Finding("STYLE_STATUS", "status must be not_started, draft, or approved"))

    samples_registered = data.get("samples_registered") is True
    inventory = _string_list(data.get("sample_inventory"))
    patterns = _mapping(data.get("positive_patterns"))
    prohibitions = _string_list(data.get("prohibitions"))
    approval = _mapping(data.get("approval"))

    if samples_registered:
        if not inventory:
            findings.append(
                Finding("STYLE_SAMPLES", "registered samples require sample_inventory entries")
            )
        if not patterns:
            findings.append(
                Finding("STYLE_PATTERNS", "registered samples require positive_patterns")
            )
        if not prohibitions:
            findings.append(
                Finding("STYLE_PROHIBITIONS", "registered samples require prohibitions")
            )
        if status != "approved":
            findings.append(
                Finding("STYLE_APPROVAL", "a sample-derived profile must be PI-approved")
            )

    if status == "approved" and (
        not _text(approval.get("approved_by"))
        or not _text(approval.get("approved_at"))
    ):
        findings.append(
            Finding(
                "STYLE_APPROVAL_RECORD",
                "approved profiles require approved_by and approved_at",
                "approval",
            )
        )

    return ValidationReport(findings)


def validate_discourse_plan(data: Mapping[str, Any]) -> ValidationReport:
    findings: list[Finding] = []
    if data.get("schema_version") != DISCOURSE_SCHEMA:
        findings.append(
            Finding("DISCOURSE_SCHEMA", f"schema_version must be {DISCOURSE_SCHEMA}")
        )
    if data.get("status") != "reviewed":
        findings.append(
            Finding("DISCOURSE_STATUS", "status must be reviewed before drafting advances")
        )
    if not _text(data.get("section_id")):
        findings.append(Finding("SECTION_ID", "section_id is required"))
    if not _text(data.get("takeaway")):
        findings.append(Finding("TAKEAWAY", "a reader-facing section takeaway is required"))

    required_units = _string_list(data.get("required_unit_keys"))
    if not required_units:
        findings.append(Finding("REQUIRED_UNITS", "required_unit_keys cannot be empty"))
    if duplicate := _duplicate(required_units):
        findings.append(Finding("DUPLICATE_UNIT", f"duplicate required unit key: {duplicate}"))

    propositions_raw = data.get("propositions")
    propositions = propositions_raw if isinstance(propositions_raw, list) else []
    proposition_ids = [
        _text(item.get("id")) for item in propositions if isinstance(item, Mapping)
    ]
    if not propositions or any(not item for item in proposition_ids):
        findings.append(Finding("PROPOSITIONS", "each proposition requires a non-empty id"))
    if duplicate := _duplicate([item for item in proposition_ids if item]):
        findings.append(Finding("DUPLICATE_PROPOSITION", f"duplicate proposition id: {duplicate}"))

    for index, proposition in enumerate(propositions):
        if not isinstance(proposition, Mapping):
            findings.append(Finding("PROPOSITION_SHAPE", "propositions must be mappings"))
            continue
        if not _text(proposition.get("statement")) or not _text(proposition.get("role")):
            findings.append(
                Finding(
                    "PROPOSITION_CONTENT",
                    "each proposition requires statement and role",
                    f"propositions[{index}]",
                )
            )
        if proposition.get("role") == "prior_work" and not _string_list(
            proposition.get("citation_keys")
        ):
            findings.append(
                Finding(
                    "PRIOR_WORK_CITATION",
                    "prior_work propositions must retain citation_keys during drafting",
                    f"propositions[{index}].citation_keys",
                )
            )

    paragraphs_raw = data.get("paragraphs")
    paragraphs = paragraphs_raw if isinstance(paragraphs_raw, list) else []
    paragraph_ids = [
        _text(item.get("id")) for item in paragraphs if isinstance(item, Mapping)
    ]
    if not paragraphs or any(not item for item in paragraph_ids):
        findings.append(Finding("PARAGRAPHS", "each paragraph card requires a non-empty id"))
    if duplicate := _duplicate([item for item in paragraph_ids if item]):
        findings.append(Finding("DUPLICATE_PARAGRAPH", f"duplicate paragraph id: {duplicate}"))

    known_propositions = set(proposition_ids)
    known_units = set(required_units)
    used_propositions: set[str] = set()
    mapped_units: set[str] = set()
    for index, paragraph in enumerate(paragraphs):
        if not isinstance(paragraph, Mapping):
            findings.append(Finding("PARAGRAPH_SHAPE", "paragraph cards must be mappings"))
            continue
        field = f"paragraphs[{index}]"
        if not all(
            _text(paragraph.get(name)) for name in ("job", "opening", "bridge", "takeaway")
        ):
            findings.append(
                Finding(
                    "PARAGRAPH_CONTENT",
                    "each paragraph card requires job, opening, bridge, and takeaway",
                    field,
                )
            )
        card_propositions = set(_string_list(paragraph.get("proposition_ids")))
        card_units = set(_string_list(paragraph.get("unit_keys")))
        if not card_propositions:
            findings.append(
                Finding("PARAGRAPH_PROPOSITIONS", "paragraph card has no propositions", field)
            )
        if not card_units:
            findings.append(Finding("PARAGRAPH_UNITS", "paragraph card has no unit_keys", field))
        unknown_propositions = card_propositions - known_propositions
        unknown_units = card_units - known_units
        if unknown_propositions:
            findings.append(
                Finding(
                    "UNKNOWN_PROPOSITION",
                    f"unknown proposition ids: {sorted(unknown_propositions)}",
                    field,
                )
            )
        if unknown_units:
            findings.append(
                Finding("UNKNOWN_UNIT", f"unknown unit keys: {sorted(unknown_units)}", field)
            )
        used_propositions.update(card_propositions)
        mapped_units.update(card_units)

    missing_propositions = known_propositions - used_propositions
    if missing_propositions:
        findings.append(
            Finding(
                "UNMAPPED_PROPOSITIONS",
                f"propositions absent from paragraph cards: {sorted(missing_propositions)}",
            )
        )
    if mapped_units != known_units:
        findings.append(
            Finding(
                "UNIT_COVERAGE",
                "the union of paragraph-card unit_keys must equal required_unit_keys",
            )
        )

    required_disclosures = set(_string_list(data.get("mandatory_disclosure_ids")))
    disclosure_map = _mapping(data.get("mandatory_disclosure_map"))
    mapped_disclosures = {str(key) for key in disclosure_map}
    if mapped_disclosures != required_disclosures:
        findings.append(
            Finding(
                "DISCLOSURE_COVERAGE",
                "mandatory_disclosure_map keys must exactly equal mandatory_disclosure_ids",
            )
        )
    for disclosure_id, locations in disclosure_map.items():
        if not _string_list(locations):
            findings.append(
                Finding(
                    "DISCLOSURE_LOCATION",
                    f"mandatory disclosure {disclosure_id} requires a public location",
                    "mandatory_disclosure_map",
                )
            )

    style_profile = _mapping(data.get("style_profile"))
    if style_profile.get("required") is True and (
        style_profile.get("status") != "approved"
        or not _text(style_profile.get("path"))
    ):
        findings.append(
            Finding(
                "STYLE_PROFILE_LINK",
                "a required style profile must have an approved status and path",
                "style_profile",
            )
        )

    review = _mapping(data.get("coherence_review"))
    if review.get("status") != "pass" or not _text(review.get("reviewer")):
        findings.append(
            Finding(
                "COHERENCE_REVIEW",
                "a fresh-context reviewer must record a pass and reviewer identifier",
                "coherence_review",
            )
        )
    answers = _mapping(review.get("answers"))
    missing_answers = COHERENCE_QUESTIONS - set(answers)
    failed_answers = {key for key in COHERENCE_QUESTIONS if answers.get(key) is not True}
    if missing_answers or failed_answers:
        findings.append(
            Finding(
                "COHERENCE_ANSWERS",
                "all eight coherence answers must be present and true",
                "coherence_review.answers",
            )
        )

    return ValidationReport(findings)


def validate_profile_linkage(
    style_profile: Mapping[str, Any], discourse_plan: Mapping[str, Any]
) -> ValidationReport:
    """Require a section to load an approved profile when samples exist."""

    findings: list[Finding] = []
    plan_profile = _mapping(discourse_plan.get("style_profile"))
    if style_profile.get("samples_registered") is True and (
        plan_profile.get("required") is not True
        or plan_profile.get("status") != "approved"
        or not _text(plan_profile.get("path"))
    ):
        findings.append(
            Finding(
                "STYLE_PROFILE_REQUIRED",
                "registered samples require the section to link the approved style profile",
                "style_profile",
            )
        )
    return ValidationReport(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--style-profile", type=Path)
    parser.add_argument("--discourse-plan", type=Path)
    args = parser.parse_args(argv)
    if args.style_profile is None and args.discourse_plan is None:
        parser.error("provide --style-profile and/or --discourse-plan")

    reports: dict[str, Any] = {}
    try:
        style_data: dict[str, Any] | None = None
        discourse_data: dict[str, Any] | None = None
        if args.style_profile is not None:
            style_data = load_document(args.style_profile)
            reports["style_profile"] = validate_style_profile(style_data).as_dict()
        if args.discourse_plan is not None:
            discourse_data = load_document(args.discourse_plan)
            reports["discourse_plan"] = validate_discourse_plan(discourse_data).as_dict()
        if style_data is not None and discourse_data is not None:
            reports["profile_linkage"] = validate_profile_linkage(
                style_data, discourse_data
            ).as_dict()
    except (TypeError, ValueError) as exc:
        print(json.dumps({"verdict": "ERROR", "error": str(exc)}, indent=2))
        return 3

    verdict = "BLOCK" if any(item["verdict"] == "BLOCK" for item in reports.values()) else "PASS"
    print(json.dumps({"verdict": verdict, "artifacts": reports}, indent=2, sort_keys=True))
    return 2 if verdict == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
