#!/usr/bin/env python3
"""Citation-key cross-check for Writer drafts (P4).

LLM LaTeX is unreliable on bibliographies: TeXpert reports ~15% accuracy on
complex LaTeX with logical (not typo) errors dominating, and the classic
silent failure is a `\\cite{key}` that does not resolve to a real .bib entry
(rendered as "[?]") or a case-mismatched key (`Smith2024` vs `smith2024`).
This deterministic check feeds the writer's compile-and-fix loop: every
citation key must resolve, case-exact, to an entry in the bibliography *and*
to the current RKA manuscript-reference manifest.  A bibliography entry is
not authorization to cite: the bound literature record's latest validation
must still be current.

Verdicts: missing/invalid RKA manifest, unresolved citations, or citations
outside its approved set -> BLOCK; unused bib entries -> WARN.
Exit codes: 0 PASS, 1 WARN, 2 BLOCK, 3 usage.

Pure-text; fully testable offline.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# \cite, \citep, \citet, \citeauthor, \autocite, \parencite, \textcite, ...
# optionally with [..] option args, and comma-separated multi-keys.
_CITE_RE = re.compile(r"\\[a-zA-Z]*cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]*)\}")
_BIBENTRY_RE = re.compile(r"@\s*[a-zA-Z]+\s*\{\s*([^,\s]+)\s*,")
_BIBITEM_RE = re.compile(r"\\bibitem(?:\[[^\]]*\])?\{([^}]*)\}")


@dataclass
class Report:
    tex_files: list = field(default_factory=list)
    bib_files: list = field(default_factory=list)
    cite_keys: list = field(default_factory=list)
    bib_keys: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)   # cited but not in bib -> BLOCK
    case_mismatch: list = field(default_factory=list)  # resolve only if case-folded -> BLOCK
    manifest_file: Optional[str] = None
    manifest_schema_version: Optional[str] = None
    manifest_project_id: Optional[str] = None
    manifest_manuscript_id: Optional[str] = None
    manifest_revision: Optional[int] = None
    manifest_missing: bool = False
    manifest_errors: list = field(default_factory=list)
    active_manifest_keys: list = field(default_factory=list)
    approved_manifest_keys: list = field(default_factory=list)
    manifest_case_mismatch: list = field(default_factory=list)
    unapproved_citations: list = field(default_factory=list)
    unregistered_bib_entries: list = field(default_factory=list)
    unused: list = field(default_factory=list)         # in bib, never cited -> WARN
    verdict: str = "PASS"


@dataclass
class ManifestProjection:
    """Validated, locally consumable projection of an RKA reference manifest."""

    active_keys: set[str] = field(default_factory=set)
    approved_keys: set[str] = field(default_factory=set)
    schema_version: Optional[str] = None
    project_id: Optional[str] = None
    manuscript_id: Optional[str] = None
    manuscript_revision: Optional[int] = None
    errors: list[str] = field(default_factory=list)


def extract_cite_keys(tex: str) -> list:
    keys = []
    for m in _CITE_RE.finditer(tex):
        for k in m.group(1).split(","):
            k = k.strip()
            if k:
                keys.append(k)
    return keys


def extract_bib_keys(bib: str) -> list:
    keys = [m.group(1).strip() for m in _BIBENTRY_RE.finditer(bib)]
    keys += [m.group(1).strip() for m in _BIBITEM_RE.finditer(bib)]
    return keys


def _casefold_duplicates(values: list[str]) -> list[list[str]]:
    grouped: dict[str, list[str]] = {}
    for value in values:
        grouped.setdefault(value.casefold(), []).append(value)
    return [
        sorted(items)
        for items in grouped.values()
        if len(items) > 1
    ]


def _read_manifest_data(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - dependency is packaged
            raise ValueError(
                "manifest is not JSON and PyYAML is unavailable"
            ) from exc
        return yaml.safe_load(text)


def load_manifest(path: Path) -> ManifestProjection:
    """Load and cross-check the server-exported manifest or claim spine.

    The approved set is derived from member-level ``validation.current``
    values and compared with both declared key lists.  This prevents a stale
    or partially edited projection from silently authorizing a citation.
    """
    projection = ManifestProjection()
    try:
        raw = _read_manifest_data(path)
    except (OSError, ValueError) as exc:
        projection.errors.append(str(exc))
        return projection
    if not isinstance(raw, dict):
        projection.errors.append("manifest root must be an object")
        return projection

    outer = raw
    manifest = raw.get("reference_manifest", raw)
    if not isinstance(manifest, dict):
        projection.errors.append("reference_manifest must be an object")
        return projection

    if manifest.get("authoritative_source") != "rka":
        projection.errors.append("authoritative_source must be 'rka'")
    schema_version = manifest.get("schema_version")
    if schema_version != "rka.manuscript-reference-manifest/v1":
        projection.errors.append(
            "schema_version must be "
            "'rka.manuscript-reference-manifest/v1'"
        )
    projection.schema_version = (
        str(schema_version) if schema_version is not None else None
    )

    for field_name in ("project_id", "manuscript_id"):
        value = manifest.get(field_name)
        if not isinstance(value, str) or not value.strip():
            projection.errors.append(f"{field_name} must be a non-empty string")
        else:
            setattr(projection, field_name, value)
        outer_value = outer.get(field_name)
        if (
            outer is not manifest
            and outer_value is not None
            and outer_value != value
        ):
            projection.errors.append(
                f"outer {field_name} does not match reference_manifest"
            )

    revision = manifest.get("manuscript_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        projection.errors.append(
            "manuscript_revision must be a positive integer"
        )
    else:
        projection.manuscript_revision = revision
    outer_revision = outer.get("manuscript_revision")
    if (
        outer is not manifest
        and outer_revision is not None
        and outer_revision != revision
    ):
        projection.errors.append(
            "outer manuscript_revision does not match reference_manifest"
        )

    members = manifest.get("members")
    if not isinstance(members, list):
        projection.errors.append("members must be a list")
        members = []
    active_keys: list[str] = []
    approved_keys: list[str] = []
    literature_ids: list[str] = []
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            projection.errors.append(f"members[{index}] must be an object")
            continue
        citation_key = member.get("citation_key")
        literature_id = member.get("literature_id")
        if not isinstance(citation_key, str) or not citation_key.strip():
            projection.errors.append(
                f"members[{index}].citation_key must be a non-empty string"
            )
            continue
        if citation_key != citation_key.strip():
            projection.errors.append(
                f"members[{index}].citation_key has surrounding whitespace"
            )
        if not isinstance(literature_id, str) or not literature_id.startswith(
            "lit_"
        ):
            projection.errors.append(
                f"members[{index}].literature_id must be a lit_ identifier"
            )
        else:
            literature_ids.append(literature_id)
        state = member.get("state")
        if state != "active":
            projection.errors.append(
                f"members[{index}] is not active in an active-only manifest"
            )
        active_keys.append(citation_key)
        validation = member.get("validation")
        if not isinstance(validation, dict):
            projection.errors.append(
                f"members[{index}].validation must be an object"
            )
        elif validation.get("current") is True:
            approved_keys.append(citation_key)

    duplicate_keys = _casefold_duplicates(active_keys)
    if duplicate_keys:
        projection.errors.append(
            f"citation keys collide case-insensitively: {duplicate_keys}"
        )
    duplicate_literature = sorted(
        {
            value
            for value in literature_ids
            if literature_ids.count(value) > 1
        }
    )
    if duplicate_literature:
        projection.errors.append(
            f"literature bindings are duplicated: {duplicate_literature}"
        )

    declared_active = manifest.get("active_citation_keys")
    if not isinstance(declared_active, list) or not all(
        isinstance(value, str) for value in declared_active
    ):
        projection.errors.append("active_citation_keys must be a string list")
    elif set(declared_active) != set(active_keys) or len(declared_active) != len(
        active_keys
    ):
        projection.errors.append(
            "active_citation_keys does not match member-level active keys"
        )

    declared_approved = manifest.get("approved_citation_keys")
    if not isinstance(declared_approved, list) or not all(
        isinstance(value, str) for value in declared_approved
    ):
        projection.errors.append("approved_citation_keys must be a string list")
    elif set(declared_approved) != set(approved_keys) or len(
        declared_approved
    ) != len(approved_keys):
        projection.errors.append(
            "approved_citation_keys does not match current member validations"
        )

    declared_all_verified = manifest.get("all_members_verified")
    expected_all_verified = bool(active_keys) and (
        len(approved_keys) == len(active_keys)
    )
    if declared_all_verified is not expected_all_verified:
        projection.errors.append(
            "all_members_verified does not match member validations"
        )

    projection.active_keys = set(active_keys)
    projection.approved_keys = set(approved_keys)
    return projection


def audit(
    tex_texts: list,
    bib_texts: list,
    *,
    manifest: ManifestProjection | None = None,
    expected_project_id: str | None = None,
    expected_manuscript_id: str | None = None,
) -> Report:
    rep = Report()
    cite_keys: list = []
    for t in tex_texts:
        cite_keys.extend(extract_cite_keys(t))
    bib_keys: list = []
    for b in bib_texts:
        bib_keys.extend(extract_bib_keys(b))
    rep.cite_keys = sorted(set(cite_keys))
    rep.bib_keys = sorted(set(bib_keys))
    bib_set = set(bib_keys)
    bib_lower = {k.lower(): k for k in bib_keys}

    for k in rep.cite_keys:
        if k in bib_set:
            continue
        if k.lower() in bib_lower:
            rep.case_mismatch.append({"cited": k, "bib": bib_lower[k.lower()]})
        else:
            rep.unresolved.append(k)

    cited_set = set(cite_keys)
    rep.unused = sorted(k for k in rep.bib_keys if k not in cited_set)

    if manifest is None:
        rep.manifest_missing = True
        rep.manifest_errors.append(
            "an authoritative RKA manuscript-reference manifest is required"
        )
    else:
        rep.manifest_schema_version = manifest.schema_version
        rep.manifest_project_id = manifest.project_id
        rep.manifest_manuscript_id = manifest.manuscript_id
        rep.manifest_revision = manifest.manuscript_revision
        rep.manifest_errors.extend(manifest.errors)
        if not expected_project_id:
            rep.manifest_errors.append(
                "expected_project_id is required to bind manifest scope"
            )
        elif manifest.project_id != expected_project_id:
            rep.manifest_errors.append(
                "manifest project_id does not match expected_project_id"
            )
        if not expected_manuscript_id:
            rep.manifest_errors.append(
                "expected_manuscript_id is required to bind manifest scope"
            )
        elif manifest.manuscript_id != expected_manuscript_id:
            rep.manifest_errors.append(
                "manifest manuscript_id does not match expected_manuscript_id"
            )
        rep.active_manifest_keys = sorted(manifest.active_keys)
        rep.approved_manifest_keys = sorted(manifest.approved_keys)
        active_folded = {
            value.casefold(): value for value in manifest.active_keys
        }
        approved_folded = {
            value.casefold(): value for value in manifest.approved_keys
        }
        for key in rep.cite_keys:
            if key in manifest.approved_keys:
                continue
            if key.casefold() in approved_folded:
                rep.manifest_case_mismatch.append(
                    {
                        "cited": key,
                        "approved": approved_folded[key.casefold()],
                    }
                )
            elif key in manifest.active_keys:
                rep.unapproved_citations.append(
                    {
                        "cited": key,
                        "reason": "validation_not_current",
                    }
                )
            elif key.casefold() in active_folded:
                rep.manifest_case_mismatch.append(
                    {
                        "cited": key,
                        "active": active_folded[key.casefold()],
                    }
                )
            else:
                rep.unapproved_citations.append(
                    {
                        "cited": key,
                        "reason": "not_in_active_manifest",
                    }
                )
        rep.unregistered_bib_entries = sorted(
            key for key in rep.bib_keys if key not in manifest.active_keys
        )

    if (
        rep.unresolved
        or rep.case_mismatch
        or rep.manifest_missing
        or rep.manifest_errors
        or rep.manifest_case_mismatch
        or rep.unapproved_citations
    ):
        rep.verdict = "BLOCK"
    elif rep.unused or rep.unregistered_bib_entries:
        rep.verdict = "WARN"
    else:
        rep.verdict = "PASS"
    return rep


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Citation-key cross-check for Writer drafts.")
    parser.add_argument("--tex", nargs="+", type=Path, required=True, help=".tex source files")
    parser.add_argument("--bib", nargs="+", type=Path, required=True, help=".bib / bibliography files")
    parser.add_argument(
        "--approved-manifest",
        type=Path,
        default=None,
        help=(
            "fresh RKA manuscript spine or "
            "rka.manuscript-reference-manifest/v1 JSON/YAML"
        ),
    )
    parser.add_argument(
        "--project-id",
        required=True,
        help="expected RKA project id for the exported manifest",
    )
    parser.add_argument(
        "--manuscript-id",
        required=True,
        help="expected canonical RKA man_ id for the exported manifest",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    tex_texts = [p.read_text(encoding="utf-8") for p in args.tex]
    bib_texts = [p.read_text(encoding="utf-8") for p in args.bib]
    manifest = (
        load_manifest(args.approved_manifest)
        if args.approved_manifest is not None
        else None
    )
    rep = audit(
        tex_texts,
        bib_texts,
        manifest=manifest,
        expected_project_id=args.project_id,
        expected_manuscript_id=args.manuscript_id,
    )
    rep.tex_files = [str(p) for p in args.tex]
    rep.bib_files = [str(p) for p in args.bib]
    rep.manifest_file = (
        str(args.approved_manifest)
        if args.approved_manifest is not None
        else None
    )

    text = json.dumps(asdict(rep), indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    return {"BLOCK": 2, "WARN": 1, "PASS": 0}[rep.verdict]


if __name__ == "__main__":
    sys.exit(main())
