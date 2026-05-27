#!/usr/bin/env python3
"""venue_loader.py — parse, validate, and merge venue.yaml specs.

Loads `references/venue/<id>.yaml` files (and proposal inheritance for
`kind=proposal` solicitations) into typed Venue dataclasses. Provides:

  - `load_venue(id) -> Venue`              read + validate one venue
  - `load_all_venues() -> dict[str, Venue]` read every venue in the tree
  - `merge_inheritance(child, base)`        proposal-overlay (W1 NSF feature)
  - CLI:
      python venue_loader.py list                 # list all venues
      python venue_loader.py show <id>            # dump one venue
      python venue_loader.py validate [--strict]  # validate all
      python venue_loader.py validate <id>        # validate one
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------------------
# Module paths
# ---------------------------------------------------------------------------

SKILL_ROOT = Path(__file__).resolve().parent.parent
VENUE_DIR = SKILL_ROOT / "references" / "venue"
PROPOSAL_DIR = VENUE_DIR / "proposals"
PROPOSAL_SOL_DIR = PROPOSAL_DIR / "solicitations"

SCHEMA_VERSION = "v1"


# ---------------------------------------------------------------------------
# Enums (Phase W1 — narrow enums; expanded as new venues land)
# ---------------------------------------------------------------------------

KIND_VALUES = ("conference", "journal", "proposal")
DOMAIN_VALUES = (
    # Computer science families (Phase W1 + W3 expansion)
    "cs-ml", "cs-systems", "cs-security", "cs-hci", "cs-pl",
    "cs-db", "cs-net", "cs-arch", "cs-se",
    "cs-nlp", "cs-cv", "cs-ir", "cs-ai", "cs-web",
    # General-science journals
    "sci-general",
    # FT50 business journals (narrowed scope: accounting, finance, management)
    "acct", "fin", "mgmt",
    # Funding proposals (Phase W4)
    "proposal",
)
STATUS_VALUES = ("active", "deprecated", "year-specific")
ANONYMIZATION_VALUES = ("none", "required", "required_pre_camera_ready")
VOICE_VALUES = ("first-person-plural", "third-person", "passive", "mixed")
HEDGING_VALUES = ("low", "moderate", "high")
MARKETING_VALUES = ("encouraged", "neutral", "discouraged")
MATH_DENSITY_VALUES = ("low", "moderate", "high")
REPRODUCIBILITY_VALUES = ("low", "moderate", "high")
WEIGHT_VALUES = ("high", "medium", "low")
SEVERITY_VALUES = ("block", "warn", "info")
CITATION_STYLE_VALUES = (
    "numeric",
    "numeric-cite-order",
    "numeric-author-year-mixed",
    "name-year",
    "author-year",
    "vancouver",
)
BIB_STYLE_VALUES = ("alphabetical", "numeric-cite-order", "name-year")
ENGINE_VALUES = ("pdflatex", "lualatex", "xelatex")
QUERY_METHOD_VALUES = ("openalex", "semantic-scholar", "arxiv", "crossref")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Submission:
    page_limit_main: Optional[int] = None
    page_limit_camera_ready: Optional[int] = None
    references_counted: bool = False
    appendix_counted: bool = False
    appendix_limit: Optional[int] = None
    has_required_checklist: bool = False
    anonymization: str = "none"


@dataclass
class Format:
    template_id: Optional[str] = None
    engine_default: str = "pdflatex"
    engines_supported: list[str] = field(default_factory=lambda: ["pdflatex"])
    citation_style: Optional[str] = None
    bibliography_style: Optional[str] = None


@dataclass
class Structure:
    required_sections: list[str] = field(default_factory=list)
    optional_sections: list[str] = field(default_factory=list)
    appendix_sections: list[str] = field(default_factory=list)
    section_order: list[str] = field(default_factory=list)
    abstract_word_min: Optional[int] = None
    abstract_word_target: Optional[int] = None
    abstract_word_max: Optional[int] = None


@dataclass
class Tone:
    voice: str = "mixed"
    hedging: str = "moderate"
    marketing_language: str = "neutral"
    math_density: str = "moderate"
    numerical_claims_dominate: bool = False
    ablation_studies_expected: bool = False
    multi_seed_required: bool = False
    reproducibility_floor: str = "moderate"


@dataclass
class ReviewDimension:
    name: str
    weight: str  # high | medium | low


@dataclass
class ForbiddenConstruction:
    pattern: str
    reason: str
    severity: str = "warn"


@dataclass
class SampleCorpus:
    query_method: str = "openalex"
    filter_template: str = ""
    recommended_year_range: list[int] = field(default_factory=list)
    diversity_topics: list[str] = field(default_factory=list)
    rka_tag: str = ""


@dataclass
class CFP:
    primary_url: Optional[str] = None
    author_guide_url: Optional[str] = None
    checklist_url: Optional[str] = None
    last_verified: Optional[str] = None  # ISO date


@dataclass
class Provenance:
    schema_origin: Optional[str] = None  # decision/journal RKA id
    last_updated: Optional[str] = None   # ISO date


@dataclass
class Venue:
    schema_version: str
    id: str
    name: str
    kind: str
    domain: str
    status: str = "active"
    pin_year: Optional[int] = None

    submission: Submission = field(default_factory=Submission)
    format: Format = field(default_factory=Format)
    structure: Structure = field(default_factory=Structure)
    tone: Tone = field(default_factory=Tone)
    review_dimensions: list[ReviewDimension] = field(default_factory=list)
    forbidden_constructions: list[ForbiddenConstruction] = field(default_factory=list)
    sample_corpus: Optional[SampleCorpus] = None
    cfp: CFP = field(default_factory=CFP)
    provenance: Provenance = field(default_factory=Provenance)

    # Proposal-only: base spec to merge under this delta.
    inherits_from: Optional[str] = None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class VenueValidationError(ValueError):
    """Raised when a venue.yaml fails schema validation."""


def _check_enum(value: Any, allowed: tuple, field_path: str) -> None:
    if value not in allowed:
        raise VenueValidationError(
            f"{field_path}: expected one of {list(allowed)}, got {value!r}"
        )


def _validate_venue(v: Venue, *, source: str) -> None:
    """Raise VenueValidationError on schema mismatches."""
    if v.schema_version != SCHEMA_VERSION:
        raise VenueValidationError(
            f"{source}: schema_version must be {SCHEMA_VERSION!r}, "
            f"got {v.schema_version!r}"
        )
    if not v.id:
        raise VenueValidationError(f"{source}: id is required")
    if not v.name:
        raise VenueValidationError(f"{source}: name is required")
    _check_enum(v.kind, KIND_VALUES, f"{source}.kind")
    _check_enum(v.domain, DOMAIN_VALUES, f"{source}.domain")
    _check_enum(v.status, STATUS_VALUES, f"{source}.status")

    _check_enum(
        v.submission.anonymization,
        ANONYMIZATION_VALUES,
        f"{source}.submission.anonymization",
    )
    if v.submission.page_limit_main is not None and v.submission.page_limit_main <= 0:
        raise VenueValidationError(
            f"{source}.submission.page_limit_main must be positive or null"
        )

    _check_enum(v.format.engine_default, ENGINE_VALUES, f"{source}.format.engine_default")
    if v.format.citation_style is not None:
        _check_enum(
            v.format.citation_style,
            CITATION_STYLE_VALUES,
            f"{source}.format.citation_style",
        )
    if v.format.bibliography_style is not None:
        _check_enum(
            v.format.bibliography_style,
            BIB_STYLE_VALUES,
            f"{source}.format.bibliography_style",
        )
    for e in v.format.engines_supported:
        _check_enum(e, ENGINE_VALUES, f"{source}.format.engines_supported[]")

    _check_enum(v.tone.voice, VOICE_VALUES, f"{source}.tone.voice")
    _check_enum(v.tone.hedging, HEDGING_VALUES, f"{source}.tone.hedging")
    _check_enum(
        v.tone.marketing_language,
        MARKETING_VALUES,
        f"{source}.tone.marketing_language",
    )
    _check_enum(v.tone.math_density, MATH_DENSITY_VALUES, f"{source}.tone.math_density")
    _check_enum(
        v.tone.reproducibility_floor,
        REPRODUCIBILITY_VALUES,
        f"{source}.tone.reproducibility_floor",
    )

    for rd in v.review_dimensions:
        _check_enum(rd.weight, WEIGHT_VALUES, f"{source}.review_dimensions[].weight")

    for fc in v.forbidden_constructions:
        _check_enum(fc.severity, SEVERITY_VALUES, f"{source}.forbidden_constructions[].severity")
        if not fc.pattern.strip():
            raise VenueValidationError(
                f"{source}.forbidden_constructions[].pattern must be non-empty"
            )

    if v.sample_corpus is not None:
        _check_enum(
            v.sample_corpus.query_method,
            QUERY_METHOD_VALUES,
            f"{source}.sample_corpus.query_method",
        )

    # Proposal inheritance: only meaningful for kind=proposal.
    if v.inherits_from is not None and v.kind != "proposal":
        raise VenueValidationError(
            f"{source}.inherits_from is only allowed for kind=proposal venues"
        )


# ---------------------------------------------------------------------------
# YAML → dataclass conversion
# ---------------------------------------------------------------------------


def _build_review_dimensions(raw: Any) -> list[ReviewDimension]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise VenueValidationError("review_dimensions must be a list")
    out: list[ReviewDimension] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise VenueValidationError("review_dimensions[] must be a mapping")
        out.append(
            ReviewDimension(
                name=str(entry.get("name", "")),
                weight=str(entry.get("weight", "medium")),
            )
        )
    return out


def _build_forbidden(raw: Any) -> list[ForbiddenConstruction]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise VenueValidationError("forbidden_constructions must be a list")
    out: list[ForbiddenConstruction] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise VenueValidationError("forbidden_constructions[] must be a mapping")
        out.append(
            ForbiddenConstruction(
                pattern=str(entry.get("pattern", "")),
                reason=str(entry.get("reason", "")),
                severity=str(entry.get("severity", "warn")),
            )
        )
    return out


def _build_sample_corpus(raw: Any) -> Optional[SampleCorpus]:
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise VenueValidationError("sample_corpus must be a mapping")
    return SampleCorpus(
        query_method=str(raw.get("query_method", "openalex")),
        filter_template=str(raw.get("filter_template", "")),
        recommended_year_range=list(raw.get("recommended_year_range") or []),
        diversity_topics=list(raw.get("diversity_topics") or []),
        rka_tag=str(raw.get("rka_tag", "")),
    )


def _build_submission(raw: Any) -> Submission:
    if not raw:
        return Submission()
    if not isinstance(raw, dict):
        raise VenueValidationError("submission must be a mapping")
    return Submission(
        page_limit_main=raw.get("page_limit_main"),
        page_limit_camera_ready=raw.get("page_limit_camera_ready"),
        references_counted=bool(raw.get("references_counted", False)),
        appendix_counted=bool(raw.get("appendix_counted", False)),
        appendix_limit=raw.get("appendix_limit"),
        has_required_checklist=bool(raw.get("has_required_checklist", False)),
        anonymization=str(raw.get("anonymization", "none")),
    )


def _build_format(raw: Any) -> Format:
    if not raw:
        return Format()
    if not isinstance(raw, dict):
        raise VenueValidationError("format must be a mapping")
    return Format(
        template_id=raw.get("template_id"),
        engine_default=str(raw.get("engine_default", "pdflatex")),
        engines_supported=list(raw.get("engines_supported") or ["pdflatex"]),
        citation_style=raw.get("citation_style"),
        bibliography_style=raw.get("bibliography_style"),
    )


def _build_structure(raw: Any) -> Structure:
    if not raw:
        return Structure()
    if not isinstance(raw, dict):
        raise VenueValidationError("structure must be a mapping")
    return Structure(
        required_sections=list(raw.get("required_sections") or []),
        optional_sections=list(raw.get("optional_sections") or []),
        appendix_sections=list(raw.get("appendix_sections") or []),
        section_order=list(raw.get("section_order") or []),
        abstract_word_min=raw.get("abstract_word_min"),
        abstract_word_target=raw.get("abstract_word_target"),
        abstract_word_max=raw.get("abstract_word_max"),
    )


def _build_tone(raw: Any) -> Tone:
    if not raw:
        return Tone()
    if not isinstance(raw, dict):
        raise VenueValidationError("tone must be a mapping")
    return Tone(
        voice=str(raw.get("voice", "mixed")),
        hedging=str(raw.get("hedging", "moderate")),
        marketing_language=str(raw.get("marketing_language", "neutral")),
        math_density=str(raw.get("math_density", "moderate")),
        numerical_claims_dominate=bool(raw.get("numerical_claims_dominate", False)),
        ablation_studies_expected=bool(raw.get("ablation_studies_expected", False)),
        multi_seed_required=bool(raw.get("multi_seed_required", False)),
        reproducibility_floor=str(raw.get("reproducibility_floor", "moderate")),
    )


def _build_cfp(raw: Any) -> CFP:
    if not raw:
        return CFP()
    if not isinstance(raw, dict):
        raise VenueValidationError("cfp must be a mapping")
    return CFP(
        primary_url=raw.get("primary_url"),
        author_guide_url=raw.get("author_guide_url"),
        checklist_url=raw.get("checklist_url"),
        last_verified=raw.get("last_verified"),
    )


def _build_provenance(raw: Any) -> Provenance:
    if not raw:
        return Provenance()
    if not isinstance(raw, dict):
        raise VenueValidationError("provenance must be a mapping")
    return Provenance(
        schema_origin=raw.get("schema_origin"),
        last_updated=raw.get("last_updated"),
    )


def venue_from_dict(data: dict, *, source: str = "<dict>") -> Venue:
    """Build a Venue dataclass from a raw YAML dict; validates strictly."""
    if not isinstance(data, dict):
        raise VenueValidationError(f"{source}: top-level must be a mapping")

    venue = Venue(
        schema_version=str(data.get("schema_version", "")),
        id=str(data.get("id", "")),
        name=str(data.get("name", "")),
        kind=str(data.get("kind", "")),
        domain=str(data.get("domain", "")),
        status=str(data.get("status", "active")),
        pin_year=data.get("pin_year"),
        submission=_build_submission(data.get("submission")),
        format=_build_format(data.get("format")),
        structure=_build_structure(data.get("structure")),
        tone=_build_tone(data.get("tone")),
        review_dimensions=_build_review_dimensions(data.get("review_dimensions")),
        forbidden_constructions=_build_forbidden(data.get("forbidden_constructions")),
        sample_corpus=_build_sample_corpus(data.get("sample_corpus")),
        cfp=_build_cfp(data.get("cfp")),
        provenance=_build_provenance(data.get("provenance")),
        inherits_from=data.get("inherits_from"),
    )
    _validate_venue(venue, source=source)
    return venue


# ---------------------------------------------------------------------------
# File discovery + load
# ---------------------------------------------------------------------------


def _find_yaml(venue_id: str) -> Optional[Path]:
    """Locate <venue_id>.yaml in venue/, proposals/, or proposals/solicitations/.
    Returns the first match (deterministic search order)."""
    for root in (VENUE_DIR, PROPOSAL_DIR, PROPOSAL_SOL_DIR):
        candidate = root / f"{venue_id}.yaml"
        if candidate.is_file():
            return candidate
    return None


def load_venue(venue_id: str, *, resolve_inheritance: bool = True) -> Venue:
    """Load + validate a single venue. If kind=proposal and inherits_from
    is set, transparently merge the base spec's fields under this delta
    (delta wins; sequence fields replace rather than append unless empty).
    """
    path = _find_yaml(venue_id)
    if path is None:
        raise VenueValidationError(f"venue {venue_id!r}: no YAML file found")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    # Path may live outside SKILL_ROOT during tests (monkey-patched
    # VENUE_DIR pointed at tmp_path); fall back to the absolute path
    # in that case.
    try:
        source = str(path.relative_to(SKILL_ROOT))
    except ValueError:
        source = str(path)
    venue = venue_from_dict(raw, source=source)

    if resolve_inheritance and venue.inherits_from:
        base = load_venue(venue.inherits_from, resolve_inheritance=True)
        venue = merge_inheritance(child=venue, base=base)
    return venue


def merge_inheritance(*, child: Venue, base: Venue) -> Venue:
    """Overlay child onto base. Used for NSF solicitation inheritance.

    Rule: scalar fields from child win when set (non-None / non-empty);
    list/dict fields from child REPLACE the base entirely when non-empty
    (so a solicitation can prune the base's required_sections, not just
    extend it). This matches how grant solicitations actually work —
    they override broadly, not merge incrementally.

    The child keeps its own id/name/kind/domain/pin_year/cfp/provenance
    — only the body sub-objects (submission/format/structure/tone/
    review_dimensions/forbidden_constructions/sample_corpus) are
    candidates for base-borrowing.
    """

    def _pick(c, b):
        # For dataclasses, build a merged instance: child field wins iff
        # it differs from the dataclass default; otherwise borrow base.
        default = type(c)()  # type: ignore[misc]
        merged_kwargs = {}
        for f in dataclasses.fields(c):
            c_val = getattr(c, f.name)
            b_val = getattr(b, f.name)
            d_val = getattr(default, f.name)
            # Child explicitly set this field? Take child.
            if c_val != d_val and c_val not in (None, [], {}):
                merged_kwargs[f.name] = c_val
            else:
                merged_kwargs[f.name] = b_val
        return type(c)(**merged_kwargs)

    return dataclasses.replace(
        child,
        submission=_pick(child.submission, base.submission),
        format=_pick(child.format, base.format),
        structure=_pick(child.structure, base.structure),
        tone=_pick(child.tone, base.tone),
        review_dimensions=(
            child.review_dimensions if child.review_dimensions else base.review_dimensions
        ),
        forbidden_constructions=(
            child.forbidden_constructions
            if child.forbidden_constructions
            else base.forbidden_constructions
        ),
        sample_corpus=child.sample_corpus or base.sample_corpus,
    )


def load_all_venues() -> dict[str, Venue]:
    """Walk VENUE_DIR + proposals/ + solicitations/ and load every
    <id>.yaml. Returns dict keyed by venue.id."""
    out: dict[str, Venue] = {}
    for root in (VENUE_DIR, PROPOSAL_DIR, PROPOSAL_SOL_DIR):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.yaml")):
            stem = path.stem
            venue = load_venue(stem)
            if venue.id in out:
                raise VenueValidationError(
                    f"duplicate venue id {venue.id!r} "
                    f"(found at {path} and {out[venue.id].id})"
                )
            out[venue.id] = venue
    return out


def venue_to_dict(v: Venue) -> dict:
    """Convert back to a plain dict (useful for JSON dump in tests)."""
    return dataclasses.asdict(v)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_list(_args) -> int:
    venues = load_all_venues()
    if not venues:
        print("(no venues found)")
        return 0
    print(f"{'ID':<20} {'KIND':<12} {'DOMAIN':<14} {'NAME'}")
    for vid, v in sorted(venues.items()):
        print(f"{vid:<20} {v.kind:<12} {v.domain:<14} {v.name}")
    return 0


def _cmd_show(args) -> int:
    v = load_venue(args.venue_id)
    print(json.dumps(venue_to_dict(v), indent=2, default=str))
    return 0


def _cmd_validate(args) -> int:
    if args.venue_id:
        try:
            load_venue(args.venue_id)
        except VenueValidationError as e:
            print(f"INVALID: {e}", file=sys.stderr)
            return 1
        print(f"OK: {args.venue_id}")
        return 0

    errors: list[str] = []
    for root in (VENUE_DIR, PROPOSAL_DIR, PROPOSAL_SOL_DIR):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.yaml")):
            stem = path.stem
            try:
                load_venue(stem)
            except VenueValidationError as e:
                errors.append(f"  {path.relative_to(SKILL_ROOT)}: {e}")
    if errors:
        print(f"INVALID ({len(errors)}):", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    print("OK")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list all venues").set_defaults(func=_cmd_list)

    show = sub.add_parser("show", help="dump one venue as JSON")
    show.add_argument("venue_id")
    show.set_defaults(func=_cmd_show)

    val = sub.add_parser("validate", help="validate one or all venues")
    val.add_argument("venue_id", nargs="?", default=None)
    val.add_argument("--strict", action="store_true", help="alias; validation is always strict")
    val.set_defaults(func=_cmd_validate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
