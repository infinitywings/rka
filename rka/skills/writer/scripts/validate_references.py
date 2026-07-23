#!/usr/bin/env python3
"""validate_references.py: 7-stage reference validation pipeline (Phase 2 full).

Phase 2 (mis_01KS2S871YPQ3D5RVY5K3PSQY6) upgrades the Phase 1 stub to a full
implementation of all seven stages (A through G) per design doc Section 9 and
references/reference_pipeline.md.

Stages:
  A. CSL-JSON identifier resolution via manubot, followed by deterministic
     local BibTeX serialization (Phase 1 compatibility path).
  B. Provider resolution: DOI lookups query Crossref, OpenAlex, and Semantic
     Scholar; title searches also query arXiv. Never scrape Google Scholar.
  C. Cross-source validation: title-only searches count a source only when
     normalized title metadata and, when supplied, author surnames match.
     At least 2 mutually consistent sources must confirm for VERIFIED;
     1 source -> LOW_CONFIDENCE; 0 -> UNVERIFIED (advances to Stage G).
  D. Retraction check: Crossref update-to metadata. A local RWDB mirror and
     OpenAlex is_retracted are documented future secondary sources, not
     current checks.
  E. Author disambiguation: OpenAlex candidate search with affiliation hints.
     Unmatched authors conditionally fall back to SerpAPI author search
     (one credit per lookup, budget enforced).
  F. Bibliography compile: manubot -> bibtex-tidy -> betterbib subprocess.
     bibtex-tidy and betterbib are optional; skipped gracefully if absent.
     betterbib is GPL-3.0 (never vendored; subprocess only).
  G. Niche-citation rescue: SerpAPI google_scholar lookup before assigning
     HALLUCINATED. Hit -> UNVERIFIED with note=scholar-only-source plus
     PI checkpoint. Miss -> HALLUCINATED with note=budget-exceeded /
     no-serpapi-budget / no-serpapi-installed as applicable.

Output: refs.audit.json with one ReferenceVerdict and closed A-G stage trace
per input reference plus a SerpAPI credit-budget accounting block. Statuses: VERIFIED / FIELD_ERROR /
UNVERIFIED / RETRACTED / HALLUCINATED / AUTHOR_MISMATCH / LOW_CONFIDENCE.

Only VERIFIED references are eligible for bibliography compilation;
LOW_CONFIDENCE and every other non-VERIFIED status block the CLI gate.

CLI:
    # Stage A only (Phase 1 backwards-compat path; CSL-JSON -> BibTeX via manubot):
    python validate_references.py --csl-json input.json --out refs.bib

    # Full pipeline (Phase 2):
    python validate_references.py --validate refs.json \\
        --audit-out refs.audit.json --bib-out refs.bib

    # Backend availability report:
    python validate_references.py --check

Exit codes:
    0: all references are VERIFIED and bibliography compilation completed
    1: any reference ended in a non-VERIFIED status
    2: pipeline error (e.g., manubot subprocess failure during Stage A/F)
    3: usage error

See references/reference_pipeline.md for the full architecture, and
dec_01KS0AXXASJ5GXV7M0SS39Y066 for the SerpAPI tertiary policy.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any


# Lazy imports of backends so this script remains importable even when the
# writer-tools optional dependencies are not installed. Per-backend
# is_available() guards are used at call sites.
try:
    from rka.skills.writer.mcp_tools.backends import crossref as _crossref
    from rka.skills.writer.mcp_tools.backends import openalex as _openalex
    from rka.skills.writer.mcp_tools.backends import semantic_scholar as _s2
    from rka.skills.writer.mcp_tools.backends import arxiv_backend as _arxiv
    from rka.skills.writer.mcp_tools.backends import serpapi_backend as _serpapi
    _BACKENDS_IMPORTABLE = True
except ImportError:
    _crossref = None  # type: ignore
    _openalex = None  # type: ignore
    _s2 = None  # type: ignore
    _arxiv = None  # type: ignore
    _serpapi = None  # type: ignore
    _BACKENDS_IMPORTABLE = False


# ---- Status enum and verdict dataclasses ---------------------------------


class Status(str, Enum):
    VERIFIED = "VERIFIED"
    FIELD_ERROR = "FIELD_ERROR"
    UNVERIFIED = "UNVERIFIED"
    RETRACTED = "RETRACTED"
    HALLUCINATED = "HALLUCINATED"
    AUTHOR_MISMATCH = "AUTHOR_MISMATCH"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class StageOutcome(str, Enum):
    """Closed outcome vocabulary for each audit-trace stage."""

    DISABLED = "disabled"
    NOT_REACHED = "not_reached"
    PASSED = "passed"
    INCONCLUSIVE = "inconclusive"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


STAGE_TRACE_SCHEMA = "rka.reference-validation.stage-trace.v1"
STAGE_KEYS = (
    "A_extraction",
    "B_source_resolution",
    "C_cross_source_confirmation",
    "D_retraction",
    "E_author_disambiguation",
    "F_bibliography_compile",
    "G_niche_rescue",
)


def _stage_record(
    *,
    enabled: bool,
    reached: bool = False,
    completed: bool = False,
    outcome: StageOutcome | None = None,
) -> dict[str, bool | str]:
    """Build one internally consistent stage record.

    ``completed`` means the intended check/action completed, not merely that
    its Python function returned.  For example, an unavailable backend is
    reached but not completed.
    """
    if not enabled:
        reached = False
        completed = False
        outcome = StageOutcome.DISABLED
    elif not reached:
        completed = False
        outcome = StageOutcome.NOT_REACHED
    elif completed and outcome in {
        None,
        StageOutcome.DISABLED,
        StageOutcome.NOT_REACHED,
        StageOutcome.UNAVAILABLE,
        StageOutcome.ERROR,
    }:
        raise ValueError("completed stage requires a terminal outcome")
    elif not completed and outcome in {StageOutcome.PASSED, StageOutcome.REJECTED}:
        raise ValueError("incomplete stage cannot pass or reject")
    elif not completed and outcome is None:
        outcome = StageOutcome.ERROR

    return {
        "enabled": enabled,
        "reached": reached,
        "completed": completed,
        "outcome": (outcome or StageOutcome.NOT_REACHED).value,
    }


def _new_stage_trace(
    *,
    check_retraction: bool,
    check_disambiguation: bool,
) -> dict[str, dict[str, bool | str]]:
    """Create a complete A-G trace before any stage is reached."""
    return {
        "A_extraction": _stage_record(enabled=True),
        "B_source_resolution": _stage_record(enabled=True),
        "C_cross_source_confirmation": _stage_record(enabled=True),
        "D_retraction": _stage_record(enabled=check_retraction),
        "E_author_disambiguation": _stage_record(enabled=check_disambiguation),
        "F_bibliography_compile": _stage_record(enabled=True),
        "G_niche_rescue": _stage_record(enabled=True),
    }


@dataclass
class ReferenceVerdict:
    """The final verdict for a single input reference."""

    identifier: str
    status: Status
    csl_json: dict[str, Any] | None = None
    sources_tried: list[str] = field(default_factory=list)
    sources_confirmed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stage_trace: dict[str, dict[str, bool | str]] = field(default_factory=dict)


@dataclass
class AuditReport:
    """The full pipeline output: one ReferenceVerdict per ref + budget accounting."""

    refs: list[ReferenceVerdict] = field(default_factory=list)
    serpapi_budget: int = 0
    serpapi_credits_used: int = 0
    pipeline_version: str = "2.1"

    def has_any_blocking(self) -> bool:
        """Return True if any verdict would block compile without a PI override."""
        blocking = {
            Status.UNVERIFIED,
            Status.HALLUCINATED,
            Status.RETRACTED,
            Status.AUTHOR_MISMATCH,
            Status.FIELD_ERROR,
            Status.LOW_CONFIDENCE,
        }
        return any(r.status in blocking for r in self.refs)


# ---- Stage A: CSL-JSON to BibTeX via manubot (Phase 1; kept) -------------


_MANUBOT_TIMEOUT_SECONDS = 120


def _first_text(value: Any) -> str:
    """Return a normalized scalar string from common CSL field shapes."""
    if isinstance(value, list):
        return _first_text(value[0]) if value else ""
    return str(value or "").strip()


def _bibtex_escape(value: Any) -> str:
    """Escape metadata for a braced BibTeX value."""
    text = _first_text(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
    }
    return "".join(replacements.get(char, char) for char in text)


def _csl_year(record: dict[str, Any]) -> str:
    date_parts = (record.get("issued") or {}).get("date-parts") or []
    if date_parts and date_parts[0]:
        return str(date_parts[0][0])
    return _first_text(record.get("year"))


def _csl_authors(record: dict[str, Any]) -> str:
    rendered: list[str] = []
    for author in record.get("author") or []:
        if isinstance(author, str):
            if author.strip():
                rendered.append(author.strip())
            continue
        if not isinstance(author, dict):
            continue
        literal = _first_text(author.get("literal"))
        if literal:
            rendered.append(literal)
            continue
        family = _first_text(author.get("family"))
        given = _first_text(author.get("given"))
        if family and given:
            rendered.append(f"{family}, {given}")
        elif family or given:
            rendered.append(family or given)
    return " and ".join(rendered)


def _csl_records_to_bibtex(records: list[dict[str, Any]]) -> str:
    """Serialize Manubot CSL-JSON into deterministic, dependency-free BibTeX."""
    type_map = {
        "article-journal": "article",
        "paper-conference": "inproceedings",
        "chapter": "incollection",
        "book": "book",
        "report": "techreport",
        "thesis": "phdthesis",
    }
    used_keys: set[str] = set()
    entries: list[str] = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError("Manubot CSL output contains a non-object record")
        entry_type = type_map.get(_first_text(record.get("type")).lower(), "misc")
        raw_key = (
            _first_text(record.get("id"))
            or _first_text(record.get("DOI"))
            or f"reference-{index}"
        )
        base_key = re.sub(r"[^A-Za-z0-9:._-]+", "-", raw_key).strip("-") or f"reference-{index}"
        key = base_key
        suffix = 2
        while key in used_keys:
            key = f"{base_key}-{suffix}"
            suffix += 1
        used_keys.add(key)

        container_field = "booktitle" if entry_type in {"inproceedings", "incollection"} else "journal"
        fields: list[tuple[str, Any]] = [
            ("author", _csl_authors(record)),
            ("title", record.get("title")),
            (container_field, record.get("container-title")),
            ("year", _csl_year(record)),
            ("volume", record.get("volume")),
            ("number", record.get("issue")),
            ("pages", record.get("page")),
            ("publisher", record.get("publisher")),
            ("doi", record.get("DOI")),
            ("url", record.get("URL")),
        ]
        rendered_fields = [
            f"  {name} = {{{_bibtex_escape(value)}}}"
            for name, value in fields
            if _first_text(value)
        ]
        entries.append(
            f"@{entry_type}{{{key},\n" + ",\n".join(rendered_fields) + "\n}"
        )
    return "\n\n".join(entries) + ("\n" if entries else "")


def _parse_manubot_csl(stdout: str) -> list[dict[str, Any]]:
    parsed = json.loads(stdout)
    records = parsed if isinstance(parsed, list) else [parsed]
    if not records or not all(isinstance(record, dict) for record in records):
        raise ValueError("Manubot returned no valid CSL records")
    return records


def manubot_available() -> bool:
    """Check whether manubot CLI is installed and callable."""
    return shutil.which("manubot") is not None


def stage_a_csl_to_bibtex(csl_json_path: Path, out_bib: Path) -> int:
    """Phase 1 Stage A: CSL-JSON to BibTeX via manubot subprocess.

    Reads CSL-JSON from csl_json_path, extracts resolvable identifiers
    (DOI, PMID, PMC, arXiv URL), resolves them through `manubot cite
    --format=csljson`, and serializes the returned CSL records to BibTeX.

    Returns 0 on success, non-zero on failure.
    """
    if not csl_json_path.exists():
        print(f"validate_references: input not found: {csl_json_path}", file=sys.stderr)
        return 1
    if not manubot_available():
        print(
            "validate_references: manubot CLI not on PATH. Install with: "
            "pip install manubot. Stage A requires manubot.",
            file=sys.stderr,
        )
        return 1

    raw = csl_json_path.read_text(encoding="utf-8")
    try:
        records = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"validate_references: invalid JSON in {csl_json_path}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(records, list):
        records = [records]

    identifiers: list[str] = []
    for rec in records:
        if "DOI" in rec:
            identifiers.append(f"doi:{rec['DOI']}")
        elif "PMID" in rec:
            identifiers.append(f"pubmed:{rec['PMID']}")
        elif "PMC" in rec:
            identifiers.append(f"pmc:{rec['PMC']}")
        elif "URL" in rec and "arxiv.org/abs/" in rec["URL"]:
            arxiv_id = rec["URL"].split("arxiv.org/abs/")[-1].rstrip("/")
            identifiers.append(f"arxiv:{arxiv_id}")

    if not identifiers:
        print(
            "validate_references: no resolvable identifiers (DOI, PMID, PMC, arXiv) "
            "found in CSL-JSON. Stage A requires at least one.",
            file=sys.stderr,
        )
        return 1

    try:
        result = subprocess.run(
            ["manubot", "cite", "--format=csljson", *identifiers],
            capture_output=True,
            text=True,
            check=False,
            timeout=_MANUBOT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        print("validate_references: manubot disappeared between checks.", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print(
            f"validate_references: manubot timed out after "
            f"{_MANUBOT_TIMEOUT_SECONDS}s.",
            file=sys.stderr,
        )
        return 1

    if result.returncode != 0:
        print(f"validate_references: manubot failed (exit {result.returncode})", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1

    try:
        records = _parse_manubot_csl(result.stdout)
        bib_text = _csl_records_to_bibtex(records)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"validate_references: invalid Manubot CSL output: {exc}", file=sys.stderr)
        return 1
    out_bib.write_text(bib_text, encoding="utf-8")
    return 0


# ---- Stage B: Resolution waterfall ---------------------------------------


def stage_b_resolve(doi: str) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    """Identifier resolution waterfall.

    Tries Crossref -> OpenAlex -> Semantic Scholar -> arXiv. Records which
    sources returned data so Stage C can compute confirmation count.

    Returns (first_hit_csl, sources_tried, sources_that_confirmed).
    """
    sources_tried: list[str] = []
    sources_confirmed: list[str] = []
    first_hit: dict[str, Any] | None = None

    chain = [
        ("crossref", _crossref.resolve_doi if _crossref else None),
        ("openalex", _openalex.resolve_doi if _openalex else None),
        ("semantic_scholar", _s2.resolve_doi if _s2 else None),
    ]
    for name, fn in chain:
        if fn is None:
            continue
        sources_tried.append(name)
        record = fn(doi)
        if record:
            sources_confirmed.append(name)
            if first_hit is None:
                first_hit = record

    return first_hit, sources_tried, sources_confirmed


# ---- Stage C: Cross-source confirmation ----------------------------------


def stage_c_cross_source(sources_confirmed: list[str]) -> Status:
    """Map the count of metadata-qualified confirmations to a status.

    2 or more sources concur -> VERIFIED.
    1 source -> LOW_CONFIDENCE (blocking; not cross-verified).
    0 -> UNVERIFIED (advance to Stage G niche-rescue).
    """
    if len(sources_confirmed) >= 2:
        return Status.VERIFIED
    if len(sources_confirmed) == 1:
        return Status.LOW_CONFIDENCE
    return Status.UNVERIFIED


def _normalize_metadata_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _first_text(value)).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _title_similarity(left: Any, right: Any) -> tuple[float, float]:
    left_norm = _normalize_metadata_text(left)
    right_norm = _normalize_metadata_text(right)
    if not left_norm or not right_norm:
        return 0.0, 0.0
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    return sequence, jaccard


def _author_families(value: Any) -> set[str]:
    families: set[str] = set()
    for author in value or []:
        if isinstance(author, dict):
            name = author.get("family") or author.get("literal")
        else:
            name = author
        normalized = _normalize_metadata_text(name)
        if normalized:
            families.add(normalized.split()[-1])
    return families


def _qualify_title_hit(
    requested_title: str,
    requested_authors: list[str],
    hit: dict[str, Any],
) -> tuple[bool, str]:
    sequence, jaccard = _title_similarity(requested_title, hit.get("title"))
    if sequence < 0.90 and jaccard < 0.85:
        return False, f"title_mismatch:{sequence:.2f}:{jaccard:.2f}"
    expected_authors = _author_families(requested_authors)
    if expected_authors:
        hit_authors = _author_families(hit.get("author"))
        if not hit_authors:
            return False, "author_metadata_missing"
        if not (expected_authors & hit_authors):
            return False, "author_mismatch"
    return True, "matched"


def _title_hits_consistent(left: dict[str, Any], right: dict[str, Any]) -> bool:
    sequence, jaccard = _title_similarity(left.get("title"), right.get("title"))
    return sequence >= 0.90 or jaccard >= 0.85


# ---- Stage D: Retraction check -------------------------------------------


def stage_d_retraction(doi: str) -> tuple[bool, list[dict[str, Any]]]:
    """Retraction check via Crossref update-to metadata.

    Returns ``(is_retracted, raw_updates_list)``. No local RWDB mirror or
    OpenAlex retraction field is consulted by this implementation.
    """
    if not _crossref or not _crossref.is_available():
        return False, []
    updates = _crossref.get_update_to(doi)
    is_retracted = any(
        u.get("type") == "retraction"
        or "retract" in (u.get("type") or "").lower()
        or u.get("source") == "retraction-watch"
        for u in updates
    )
    return is_retracted, updates


# ---- Stage E: Author disambiguation --------------------------------------


def stage_e_disambiguate_authors(
    authors: list[str],
    affiliation_hints: list[str] | None = None,
    *,
    budget=None,
    escalate_to_serpapi: bool = False,
) -> tuple[Status, list[str], int]:
    """Author disambiguation via OpenAlex two-step.

    For each input author surname, attempt to find a single high-confidence
    OpenAlex Authors match. If escalate_to_serpapi is True (caller signals
    LOW_CONFIDENCE or unmatched), one SerpAPI google_scholar_profiles call
    runs per unmatched author and consumes one credit.

    Returns (status, notes, credits_consumed). Status is VERIFIED if all
    authors resolved cleanly, AUTHOR_MISMATCH otherwise, LOW_CONFIDENCE if
    partial resolution.
    """
    notes: list[str] = []
    credits_consumed = 0
    resolved = 0

    if not _openalex or not _openalex.is_available():
        return Status.LOW_CONFIDENCE, ["openalex_unavailable"], 0

    for author_name in authors:
        primary = _openalex.disambiguate_author(author_name, affiliation_hints=affiliation_hints)
        if primary:
            resolved += 1
            continue
        if escalate_to_serpapi and _serpapi and _serpapi.is_available() and budget is not None:
            try:
                fallback = _serpapi.google_scholar_author_search(
                    author_name, budget=budget, affiliation_hints=affiliation_hints
                )
                credits_consumed += 1
                if fallback:
                    resolved += 1
                    notes.append(f"author_resolved_via_serpapi:{author_name}")
                    continue
            except _serpapi.SerpAPIBudgetExceededError:
                notes.append(f"author_serpapi_budget_exceeded:{author_name}")
        notes.append(f"author_unmatched:{author_name}")

    if resolved == len(authors):
        return Status.VERIFIED, notes, credits_consumed
    if resolved > 0:
        return Status.LOW_CONFIDENCE, notes, credits_consumed
    return Status.AUTHOR_MISMATCH, notes, credits_consumed


# ---- Stage F: Bibliography compile ---------------------------------------


def _bibtex_tidy_available() -> bool:
    return shutil.which("bibtex-tidy") is not None


def _betterbib_available() -> bool:
    return shutil.which("betterbib") is not None


def stage_f_compile_bibliography(
    refs: list[dict[str, Any]],
    out_bib: Path,
    *,
    apply_bibtex_tidy: bool = True,
    apply_betterbib: bool = False,
) -> tuple[int, list[str]]:
    """Stage F: produce a polished refs.bib from VERIFIED CSL-JSON records.

    Chain: manubot generates CSL-JSON -> local deterministic BibTeX serializer
    -> bibtex-tidy applies hygiene rules ->
    betterbib (optional) cross-source field sync.

    bibtex-tidy and betterbib are graceful degradations: if absent, that
    step is skipped with a note returned to the caller.

    Returns (exit_code, notes).
    """
    notes: list[str] = []

    if not manubot_available():
        notes.append("stage_f_skipped_no_manubot")
        return 1, notes

    identifiers: list[str] = []
    for rec in refs:
        if "DOI" in rec:
            identifiers.append(f"doi:{rec['DOI']}")
        elif rec.get("URL") and "arxiv.org/abs/" in rec["URL"]:
            arxiv_id = rec["URL"].split("arxiv.org/abs/")[-1].rstrip("/")
            identifiers.append(f"arxiv:{arxiv_id}")

    if not identifiers:
        notes.append("stage_f_skipped_no_resolvable_ids")
        return 1, notes

    try:
        result = subprocess.run(
            ["manubot", "cite", "--format=csljson", *identifiers],
            capture_output=True,
            text=True,
            check=False,
            timeout=_MANUBOT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        notes.append(f"stage_f_manubot_subprocess_error:{exc}")
        return 1, notes

    if result.returncode != 0:
        notes.append(f"stage_f_manubot_exit_{result.returncode}")
        return 1, notes

    try:
        manubot_records = _parse_manubot_csl(result.stdout)
        bib_text = _csl_records_to_bibtex(manubot_records)
    except (json.JSONDecodeError, ValueError) as exc:
        notes.append(f"stage_f_manubot_invalid_csl:{exc}")
        return 1, notes
    notes.append("stage_f_manubot_csljson_converted")

    if apply_bibtex_tidy and _bibtex_tidy_available():
        try:
            tidy = subprocess.run(
                ["bibtex-tidy", "--curly", "--numeric", "--sort=key",
                 "--duplicates=key,doi", "--escape", "--tidy-comments",
                 "--remove-empty-fields", "--enclosing-braces=title",
                 "--no-modify"],
                input=bib_text, capture_output=True, text=True, check=False, timeout=60,
            )
            if tidy.returncode == 0 and tidy.stdout:
                bib_text = tidy.stdout
                notes.append("stage_f_bibtex_tidy_applied")
            else:
                notes.append(f"stage_f_bibtex_tidy_exit_{tidy.returncode}")
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            notes.append(f"stage_f_bibtex_tidy_error:{exc}")
    elif apply_bibtex_tidy:
        notes.append("stage_f_bibtex_tidy_unavailable")

    if apply_betterbib and _betterbib_available():
        # betterbib reads/writes files; we use a temp roundtrip.
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".bib", delete=False) as tmp:
            tmp.write(bib_text)
            tmp_path = tmp.name
        try:
            bb = subprocess.run(
                ["betterbib", "format", tmp_path, "--in-place"],
                capture_output=True, text=True, check=False, timeout=120,
            )
            if bb.returncode == 0:
                bib_text = Path(tmp_path).read_text(encoding="utf-8")
                notes.append("stage_f_betterbib_applied")
            else:
                notes.append(f"stage_f_betterbib_exit_{bb.returncode}")
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            notes.append(f"stage_f_betterbib_error:{exc}")
        finally:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
    elif apply_betterbib:
        notes.append("stage_f_betterbib_unavailable")

    out_bib.write_text(bib_text, encoding="utf-8")
    return 0, notes


# ---- Stage G: SerpAPI niche-citation rescue ------------------------------


def stage_g_niche_rescue(
    query: str,
    *,
    budget,
) -> tuple[dict[str, Any] | None, list[str], int]:
    """One SerpAPI google_scholar lookup before assigning HALLUCINATED.

    Hit produces UNVERIFIED with note='scholar-only-source' (caller decides
    PI override). Miss produces HALLUCINATED. Budget exhaustion produces
    HALLUCINATED with note='budget-exceeded'.

    Returns (csl_json_or_none, notes, credits_consumed).
    """
    notes: list[str] = []
    if not _serpapi:
        notes.append("no-serpapi-installed")
        return None, notes, 0
    if not _serpapi.is_available():
        notes.append("no-serpapi-budget")
        return None, notes, 0

    try:
        results = _serpapi.google_scholar_search(query, budget=budget)
    except _serpapi.SerpAPIBudgetExceededError:
        notes.append("budget-exceeded")
        return None, notes, 0

    credits_consumed = 1
    if not results:
        notes.append("scholar_empty")
        return None, notes, credits_consumed

    top = results[0]
    csl = {
        "title": top.get("title"),
        "URL": top.get("link"),
        # SerpAPI Scholar results carry minimal CSL fields; the PI checkpoint
        # downstream decides whether to accept the citation with full
        # metadata yet to be backfilled.
        "_serpapi_raw": top,
    }
    notes.append("scholar-only-source")
    return csl, notes, credits_consumed


# ---- Full pipeline orchestrator ------------------------------------------


def validate_reference(
    doi: str | None = None,
    *,
    title: str | None = None,
    authors: list[str] | None = None,
    affiliation_hints: list[str] | None = None,
    budget=None,
    check_retraction: bool = True,
    check_disambiguation: bool = False,
) -> ReferenceVerdict:
    """Run the full pipeline for a single reference.

    Pipeline order: B -> C -> D (if VERIFIED + check_retraction) ->
    E (if VERIFIED + check_disambiguation) -> G (if Stage C UNVERIFIED).
    """
    identifier = doi or title or "<unknown>"
    stage_trace = _new_stage_trace(
        check_retraction=check_retraction,
        check_disambiguation=check_disambiguation,
    )
    notes: list[str] = []
    csl: dict[str, Any] | None = None
    sources_tried: list[str] = []
    sources_confirmed: list[str] = []
    title_hits: list[dict[str, Any]] = []

    if not doi and not title:
        stage_trace["A_extraction"] = _stage_record(
            enabled=True,
            reached=True,
            completed=True,
            outcome=StageOutcome.REJECTED,
        )
        return ReferenceVerdict(
            identifier,
            Status.FIELD_ERROR,
            notes=["missing_doi_and_title"],
            stage_trace=stage_trace,
        )

    stage_trace["A_extraction"] = _stage_record(
        enabled=True,
        reached=True,
        completed=True,
        outcome=StageOutcome.PASSED,
    )
    try:
        if doi:
            csl, sources_tried, sources_confirmed = stage_b_resolve(doi)
        else:
            for name, fn in (
                ("crossref", _crossref.search_works if _crossref else None),
                ("openalex", _openalex.search_works if _openalex else None),
                ("semantic_scholar", _s2.search_papers if _s2 else None),
                ("arxiv", _arxiv.search_papers if _arxiv else None),
            ):
                if fn is None:
                    continue
                sources_tried.append(name)
                try:
                    hits = (
                        fn(title, rows=1)
                        if name == "crossref"
                        else fn(title, max_results=1)
                        if name in ("openalex", "arxiv")
                        else fn(title, limit=1)
                    )
                except TypeError:
                    hits = fn(title)
                if hits:
                    hit = hits[0]
                    if not isinstance(hit, dict):
                        notes.append(f"stage_b_{name}_rejected:non_object_hit")
                        continue
                    qualifies, reason = _qualify_title_hit(
                        title,
                        authors or [],
                        hit,
                    )
                    if not qualifies:
                        notes.append(f"stage_b_{name}_rejected:{reason}")
                        continue
                    if title_hits and not _title_hits_consistent(title_hits[0], hit):
                        notes.append(f"stage_b_{name}_rejected:cross_source_title_mismatch")
                        continue
                    title_hits.append(hit)
                    sources_confirmed.append(name)
                    if csl is None:
                        csl = hit
    except Exception as exc:  # backend adapters have heterogeneous error types
        stage_trace["B_source_resolution"] = _stage_record(
            enabled=True,
            reached=True,
            completed=False,
            outcome=StageOutcome.ERROR,
        )
        notes.append(f"stage_b_resolution_error:{type(exc).__name__}")
        return ReferenceVerdict(
            identifier=identifier,
            status=Status.FIELD_ERROR,
            csl_json=csl,
            sources_tried=sources_tried,
            sources_confirmed=sources_confirmed,
            notes=notes,
            stage_trace=stage_trace,
        )

    stage_trace["B_source_resolution"] = _stage_record(
        enabled=True,
        reached=True,
        completed=bool(sources_tried),
        outcome=(
            StageOutcome.PASSED
            if sources_confirmed
            else StageOutcome.INCONCLUSIVE
            if sources_tried
            else StageOutcome.UNAVAILABLE
        ),
    )

    status = stage_c_cross_source(sources_confirmed)
    stage_trace["C_cross_source_confirmation"] = _stage_record(
        enabled=True,
        reached=True,
        completed=True,
        outcome=(
            StageOutcome.PASSED
            if status == Status.VERIFIED
            else StageOutcome.INCONCLUSIVE
        ),
    )

    if status == Status.UNVERIFIED and budget is not None:
        query = doi or title or ""
        if query:
            try:
                rescue_csl, rescue_notes, _ = stage_g_niche_rescue(query, budget=budget)
            except Exception as exc:  # preserve an audit even on adapter failure
                stage_trace["G_niche_rescue"] = _stage_record(
                    enabled=True,
                    reached=True,
                    completed=False,
                    outcome=StageOutcome.ERROR,
                )
                notes.append(f"stage_g_rescue_error:{type(exc).__name__}")
                status = Status.FIELD_ERROR
            else:
                rescue_unavailable = any(
                    note in {
                        "no-serpapi-installed",
                        "no-serpapi-budget",
                        "budget-exceeded",
                    }
                    for note in rescue_notes
                )
                stage_trace["G_niche_rescue"] = _stage_record(
                    enabled=True,
                    reached=True,
                    completed=not rescue_unavailable,
                    outcome=(
                        StageOutcome.PASSED
                        if rescue_csl is not None
                        else StageOutcome.UNAVAILABLE
                        if rescue_unavailable
                        else StageOutcome.REJECTED
                    ),
                )
                notes.extend(rescue_notes)
                if rescue_csl is not None:
                    csl = rescue_csl
                    # Per design Section 9: Stage G hit -> UNVERIFIED with
                    # scholar-only-source (PI checkpoint required).
                    status = Status.UNVERIFIED
                else:
                    status = Status.HALLUCINATED

    if status == Status.VERIFIED and check_retraction and doi:
        try:
            backend_available = bool(_crossref and _crossref.is_available())
        except Exception as exc:  # backend availability probes can perform setup
            stage_trace["D_retraction"] = _stage_record(
                enabled=True,
                reached=True,
                completed=False,
                outcome=StageOutcome.ERROR,
            )
            notes.append(f"stage_d_availability_error:{type(exc).__name__}")
            status = Status.FIELD_ERROR
        else:
            if not backend_available:
                stage_trace["D_retraction"] = _stage_record(
                    enabled=True,
                    reached=True,
                    completed=False,
                    outcome=StageOutcome.UNAVAILABLE,
                )
                notes.append("stage_d_retraction_backend_unavailable")
                status = Status.FIELD_ERROR
            else:
                try:
                    is_retracted, _updates = stage_d_retraction(doi)
                except Exception as exc:  # preserve an audit even on adapter failure
                    stage_trace["D_retraction"] = _stage_record(
                        enabled=True,
                        reached=True,
                        completed=False,
                        outcome=StageOutcome.ERROR,
                    )
                    notes.append(f"stage_d_retraction_error:{type(exc).__name__}")
                    status = Status.FIELD_ERROR
                else:
                    stage_trace["D_retraction"] = _stage_record(
                        enabled=True,
                        reached=True,
                        completed=True,
                        outcome=(
                            StageOutcome.REJECTED if is_retracted else StageOutcome.PASSED
                        ),
                    )
                    if is_retracted:
                        status = Status.RETRACTED
                        notes.append("retraction_detected_via_crossref_update_to")

    if status == Status.VERIFIED and check_disambiguation and authors:
        try:
            author_status, author_notes, _credits = stage_e_disambiguate_authors(
                authors,
                affiliation_hints=affiliation_hints,
                budget=budget,
                escalate_to_serpapi=True,
            )
        except Exception as exc:  # preserve an audit even on adapter failure
            stage_trace["E_author_disambiguation"] = _stage_record(
                enabled=True,
                reached=True,
                completed=False,
                outcome=StageOutcome.ERROR,
            )
            notes.append(f"stage_e_disambiguation_error:{type(exc).__name__}")
            status = Status.FIELD_ERROR
        else:
            backend_unavailable = "openalex_unavailable" in author_notes
            stage_trace["E_author_disambiguation"] = _stage_record(
                enabled=True,
                reached=True,
                completed=not backend_unavailable,
                outcome=(
                    StageOutcome.UNAVAILABLE
                    if backend_unavailable
                    else StageOutcome.PASSED
                    if author_status == Status.VERIFIED
                    else StageOutcome.INCONCLUSIVE
                    if author_status == Status.LOW_CONFIDENCE
                    else StageOutcome.REJECTED
                ),
            )
            notes.extend(author_notes)
            if author_status != Status.VERIFIED:
                status = author_status

    return ReferenceVerdict(
        identifier=identifier,
        status=status,
        csl_json=csl,
        sources_tried=sources_tried,
        sources_confirmed=sources_confirmed,
        notes=notes,
        stage_trace=stage_trace,
    )


def validate_all(
    refs: list[dict[str, Any]],
    *,
    budget=None,
    project_dir=None,
    check_retraction: bool = True,
    check_disambiguation: bool = False,
) -> AuditReport:
    """Run the pipeline on a batch of references; emit an AuditReport.

    Each input ref dict needs at least DOI or title. Additional fields
    (author, affiliation hints) refine Stages D/E.

    Budget resolution order (per dec_01KS2S22VV5P5SWWXNBXQDHMGX T3):
        1. Caller-supplied budget kwarg (highest precedence)
        2. project_dir/ai_tic_config.yaml [serpapi.budget] overlay
        3. SERPAPI_BUDGET env var
        4. DEFAULT_BUDGET constant (200)
    """
    if budget is None and _serpapi is not None:
        budget = _serpapi.resolve_budget(project_dir=project_dir)

    verdicts: list[ReferenceVerdict] = []
    for ref in refs:
        if not isinstance(ref, dict):
            trace = _new_stage_trace(
                check_retraction=check_retraction,
                check_disambiguation=check_disambiguation,
            )
            trace["A_extraction"] = _stage_record(
                enabled=True,
                reached=True,
                completed=True,
                outcome=StageOutcome.REJECTED,
            )
            verdicts.append(ReferenceVerdict(
                identifier="<unknown>",
                status=Status.FIELD_ERROR,
                notes=["reference_input_not_object"],
                stage_trace=trace,
            ))
            continue
        author_families = [
            author.get("family")
            for author in (ref.get("author") or [])
            if isinstance(author, dict) and author.get("family")
        ]
        verdict = validate_reference(
            doi=ref.get("DOI"),
            title=ref.get("title"),
            authors=author_families,
            affiliation_hints=ref.get("_affiliation_hints"),
            budget=budget,
            check_retraction=check_retraction,
            check_disambiguation=check_disambiguation,
        )
        verdicts.append(verdict)

    return AuditReport(
        refs=verdicts,
        serpapi_budget=(budget.budget if budget else 0),
        serpapi_credits_used=(budget.used if budget else 0),
    )


def _verdict_to_jsonable(v: ReferenceVerdict) -> dict[str, Any]:
    out = asdict(v)
    out["status"] = v.status.value
    return out


def _has_resolvable_bibliography_id(record: dict[str, Any]) -> bool:
    """Return whether Stage F can pass this CSL record to manubot."""
    return bool(
        record.get("DOI")
        or (
            record.get("URL")
            and "arxiv.org/abs/" in str(record["URL"])
        )
    )


def _apply_stage_f(
    report: AuditReport,
    out_bib: Path,
) -> tuple[int, dict[str, bool | str]]:
    """Compile VERIFIED references and attach native per-reference traces.

    Stage F is a batch action, but every reference still receives its own
    trace.  A VERIFIED record without a manubot-resolvable identifier is
    explicitly marked incomplete instead of being silently omitted.
    """
    verified = [
        verdict
        for verdict in report.refs
        if verdict.status == Status.VERIFIED and verdict.csl_json
    ]
    if not verified:
        return 0, _stage_record(enabled=True)

    resolvable = [
        verdict
        for verdict in verified
        if _has_resolvable_bibliography_id(verdict.csl_json or {})
    ]
    unresolved = [verdict for verdict in verified if verdict not in resolvable]
    for verdict in unresolved:
        verdict.stage_trace["F_bibliography_compile"] = _stage_record(
            enabled=True,
            reached=True,
            completed=False,
            outcome=StageOutcome.INCONCLUSIVE,
        )
        verdict.notes.append("stage_f_reference_missing_resolvable_id")

    if not resolvable:
        return 1, _stage_record(
            enabled=True,
            reached=True,
            completed=False,
            outcome=StageOutcome.INCONCLUSIVE,
        )

    exit_code, notes = stage_f_compile_bibliography(
        [verdict.csl_json for verdict in resolvable if verdict.csl_json],
        out_bib,
    )
    unavailable = any(
        note == "stage_f_skipped_no_manubot"
        for note in notes
    )
    outcome = (
        StageOutcome.PASSED
        if exit_code == 0
        else StageOutcome.UNAVAILABLE
        if unavailable
        else StageOutcome.ERROR
    )
    completed = exit_code == 0
    for verdict in resolvable:
        verdict.stage_trace["F_bibliography_compile"] = _stage_record(
            enabled=True,
            reached=True,
            completed=completed,
            outcome=outcome,
        )
        verdict.notes.extend(notes)

    if unresolved:
        return 1, _stage_record(
            enabled=True,
            reached=True,
            completed=False,
            outcome=StageOutcome.INCONCLUSIVE,
        )
    return exit_code, _stage_record(
        enabled=True,
        reached=True,
        completed=completed,
        outcome=outcome,
    )


# ---- CLI -----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reference validation pipeline (Phase 2: Stages A through G)."
    )
    parser.add_argument("--csl-json", type=Path,
                        help="Phase 1 backwards-compat path: CSL-JSON -> BibTeX via manubot only")
    parser.add_argument("--out", type=Path, default=Path("refs.bib"),
                        help="Stage A output BibTeX path (default refs.bib)")
    parser.add_argument("--validate", type=Path,
                        help="Phase 2: validate a JSON file (list of CSL-JSON refs) through full pipeline")
    parser.add_argument("--audit-out", type=Path, default=Path("refs.audit.json"),
                        help="Phase 2: audit output (default refs.audit.json)")
    parser.add_argument("--bib-out", type=Path, default=Path("refs.bib"),
                        help="Phase 2: bibliography output from VERIFIED entries")
    parser.add_argument("--check", action="store_true",
                        help="Report backend + manubot availability and exit")
    parser.add_argument("--no-retraction", action="store_true",
                        help="Skip Stage D retraction check")
    parser.add_argument("--check-disambiguation", action="store_true",
                        help="Run Stage E author disambiguation")
    parser.add_argument("--project-dir", type=Path, default=None,
                        help="Manuscript working dir; loads ai_tic_config.yaml SerpAPI budget overlay")
    args = parser.parse_args(argv)

    if args.check:
        print("validate_references.py Phase 2 (Stages A through G)")
        print(f"  manubot CLI available: {manubot_available()}")
        if _BACKENDS_IMPORTABLE:
            print("  Stage backends:")
            print(f"    crossref:        {_crossref.is_available()}")
            print(f"    openalex:        {_openalex.is_available()}")
            print(f"    semantic_scholar: {_s2.is_available()}")
            print(f"    arxiv:           {_arxiv.is_available()}")
            print(f"    serpapi:         {_serpapi.is_available()}")
        else:
            print("  Stage backends: not importable (rka.skills.writer.mcp_tools.backends)")
        print(f"  bibtex-tidy: {_bibtex_tidy_available()}")
        print(f"  betterbib: {_betterbib_available()}")
        return 0

    if args.validate:
        if not args.validate.exists():
            print(f"validate_references: file not found: {args.validate}", file=sys.stderr)
            return 3
        refs = json.loads(args.validate.read_text(encoding="utf-8"))
        if not isinstance(refs, list):
            refs = [refs]
        report = validate_all(
            refs,
            project_dir=args.project_dir,
            check_retraction=not args.no_retraction,
            check_disambiguation=args.check_disambiguation,
        )
        stage_f_exit, batch_stage_f = _apply_stage_f(report, args.bib_out)
        payload = {
            "pipeline_version": report.pipeline_version,
            "stage_trace_schema": STAGE_TRACE_SCHEMA,
            "refs": [_verdict_to_jsonable(v) for v in report.refs],
            "serpapi_budget": report.serpapi_budget,
            "serpapi_credits_used": report.serpapi_credits_used,
            "batch_stage_trace": {
                "F_bibliography_compile": batch_stage_f,
            },
            "summary": {
                "total": len(report.refs),
                "verified": sum(1 for r in report.refs if r.status == Status.VERIFIED),
                "blocking": sum(1 for r in report.refs if r.status in {
                    Status.UNVERIFIED, Status.HALLUCINATED, Status.RETRACTED,
                    Status.AUTHOR_MISMATCH, Status.FIELD_ERROR,
                    Status.LOW_CONFIDENCE,
                }),
            },
        }
        args.audit_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if stage_f_exit != 0:
            return 2
        return 1 if report.has_any_blocking() else 0

    if args.csl_json:
        return stage_a_csl_to_bibtex(args.csl_json, args.out)

    parser.print_usage(sys.stderr)
    print("validate_references: --validate, --csl-json, or --check required.",
          file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
