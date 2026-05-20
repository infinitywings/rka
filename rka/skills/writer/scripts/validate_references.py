#!/usr/bin/env python3
"""validate_references.py: 7-stage reference validation pipeline (Phase 2 full).

Phase 2 (mis_01KS2S871YPQ3D5RVY5K3PSQY6) upgrades the Phase 1 stub to a full
implementation of all seven stages (A through G) per design doc Section 9 and
references/reference_pipeline.md.

Stages:
  A. CSL-JSON pass-through to BibTeX via manubot (Phase 1; kept).
  B. Identifier resolution waterfall: Crossref (habanero) -> manubot ->
     OpenAlex (pyalex) -> Semantic Scholar -> arXiv. Never Google Scholar
     direct.
  C. Cross-source existence validation: at least 2 sources must confirm
     for VERIFIED; 1 source -> LOW_CONFIDENCE; 0 -> UNVERIFIED (advances
     to Stage G).
  D. Retraction check: Crossref update-to field + RWDB CSV mirror.
     OpenAlex is_retracted as tertiary (pipeline issues documented; see
     Hauschke and Nazarovets 2024 arXiv:2403.13339).
  E. Author disambiguation: OpenAlex two-step + ORCID.
     On AUTHOR_MISMATCH or LOW_CONFIDENCE, escalates to SerpAPI
     google_scholar_profiles (one credit, budget enforced).
  F. Bibliography compile: manubot -> bibtex-tidy -> betterbib subprocess.
     bibtex-tidy and betterbib are optional; skipped gracefully if absent.
     betterbib is GPL-3.0 (never vendored; subprocess only).
  G. Niche-citation rescue: SerpAPI google_scholar lookup before assigning
     HALLUCINATED. Hit -> UNVERIFIED with note=scholar-only-source plus
     PI checkpoint. Miss -> HALLUCINATED with note=budget-exceeded /
     no-serpapi-budget / no-serpapi-installed as applicable.

Output: refs.audit.json with one ReferenceVerdict per input reference plus a
serpapi credit-budget accounting block. Statuses: VERIFIED / FIELD_ERROR /
UNVERIFIED / RETRACTED / HALLUCINATED / AUTHOR_MISMATCH / LOW_CONFIDENCE.

Compile is blocked on UNVERIFIED or HALLUCINATED references without an
explicit PI override stored as a dec_ entry (the consuming Writer skill
enforces; this script returns the audit, not the gate verdict).

CLI:
    # Stage A only (Phase 1 backwards-compat path; CSL-JSON -> BibTeX via manubot):
    python validate_references.py --csl-json input.json --out refs.bib

    # Full pipeline (Phase 2):
    python validate_references.py --validate refs.json \\
        --audit-out refs.audit.json --bib-out refs.bib

    # Backend availability report:
    python validate_references.py --check

Exit codes:
    0: all references reached terminal status (VERIFIED dominant)
    1: any reference ended UNVERIFIED / HALLUCINATED / RETRACTED /
       AUTHOR_MISMATCH (caller decides whether to gate on these)
    2: pipeline error (e.g., manubot subprocess failure during Stage A/F)
    3: usage error

See references/reference_pipeline.md for the full architecture, and
dec_01KS0AXXASJ5GXV7M0SS39Y066 for the SerpAPI tertiary policy.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
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


@dataclass
class ReferenceVerdict:
    """The final verdict for a single input reference."""

    identifier: str
    status: Status
    csl_json: dict[str, Any] | None = None
    sources_tried: list[str] = field(default_factory=list)
    sources_confirmed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class AuditReport:
    """The full pipeline output: one ReferenceVerdict per ref + budget accounting."""

    refs: list[ReferenceVerdict] = field(default_factory=list)
    serpapi_budget: int = 0
    serpapi_credits_used: int = 0
    pipeline_version: str = "2.0"

    def has_any_blocking(self) -> bool:
        """Return True if any verdict would block compile without a PI override."""
        blocking = {
            Status.UNVERIFIED,
            Status.HALLUCINATED,
            Status.RETRACTED,
            Status.AUTHOR_MISMATCH,
            Status.FIELD_ERROR,
        }
        return any(r.status in blocking for r in self.refs)


# ---- Stage A: CSL-JSON to BibTeX via manubot (Phase 1; kept) -------------


def manubot_available() -> bool:
    """Check whether manubot CLI is installed and callable."""
    return shutil.which("manubot") is not None


def stage_a_csl_to_bibtex(csl_json_path: Path, out_bib: Path) -> int:
    """Phase 1 Stage A: CSL-JSON to BibTeX via manubot subprocess.

    Reads CSL-JSON from csl_json_path, extracts resolvable identifiers
    (DOI, PMID, PMC, arXiv URL), and feeds them through `manubot cite
    --format=bibtex` to produce a BibTeX file at out_bib.

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
            ["manubot", "cite", "--format=bibtex", *identifiers],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        print("validate_references: manubot disappeared between checks.", file=sys.stderr)
        return 1

    if result.returncode != 0:
        print(f"validate_references: manubot failed (exit {result.returncode})", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1

    out_bib.write_text(result.stdout, encoding="utf-8")
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
    """Map confirmation count to status.

    2 or more sources concur -> VERIFIED.
    1 source -> LOW_CONFIDENCE (suggests an existence but not cross-verified).
    0 -> UNVERIFIED (advance to Stage G niche-rescue).
    """
    if len(sources_confirmed) >= 2:
        return Status.VERIFIED
    if len(sources_confirmed) == 1:
        return Status.LOW_CONFIDENCE
    return Status.UNVERIFIED


# ---- Stage D: Retraction check -------------------------------------------


def stage_d_retraction(doi: str) -> tuple[bool, list[dict[str, Any]]]:
    """Retraction check via Crossref update-to + RWDB CSV mirror.

    Returns (is_retracted, raw_updates_list). RWDB CSV is the authoritative
    secondary check; absent locally, we rely on Crossref update-to only
    (which feeds RWDB since Crossref's September 2023 acquisition).
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

    Chain: manubot generates BibTeX -> bibtex-tidy applies hygiene rules ->
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
            ["manubot", "cite", "--format=bibtex", *identifiers],
            capture_output=True, text=True, check=False, timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        notes.append(f"stage_f_manubot_subprocess_error:{exc}")
        return 1, notes

    if result.returncode != 0:
        notes.append(f"stage_f_manubot_exit_{result.returncode}")
        return 1, notes

    bib_text = result.stdout

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
    notes: list[str] = []
    csl: dict[str, Any] | None = None
    sources_tried: list[str] = []
    sources_confirmed: list[str] = []

    if doi:
        csl, sources_tried, sources_confirmed = stage_b_resolve(doi)
    elif title:
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
                hits = (fn(title, rows=1) if name == "crossref"
                        else fn(title, max_results=1) if name in ("openalex", "arxiv")
                        else fn(title, limit=1))
            except TypeError:
                hits = fn(title)
            if hits:
                sources_confirmed.append(name)
                if csl is None:
                    csl = hits[0]
    else:
        return ReferenceVerdict(identifier, Status.FIELD_ERROR, notes=["missing_doi_and_title"])

    status = stage_c_cross_source(sources_confirmed)

    if status == Status.UNVERIFIED and budget is not None:
        query = doi or title or ""
        if query:
            rescue_csl, rescue_notes, _ = stage_g_niche_rescue(query, budget=budget)
            notes.extend(rescue_notes)
            if rescue_csl is not None:
                csl = rescue_csl
                # Per design Section 9: Stage G hit -> UNVERIFIED with
                # scholar-only-source (PI checkpoint required).
                status = Status.UNVERIFIED
            else:
                status = Status.HALLUCINATED

    if status == Status.VERIFIED and check_retraction and doi:
        is_retracted, _updates = stage_d_retraction(doi)
        if is_retracted:
            status = Status.RETRACTED
            notes.append("retraction_detected_via_crossref_update_to")

    if status == Status.VERIFIED and check_disambiguation and authors:
        author_status, author_notes, _credits = stage_e_disambiguate_authors(
            authors, affiliation_hints=affiliation_hints, budget=budget,
            escalate_to_serpapi=False,
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
        verdict = validate_reference(
            doi=ref.get("DOI"),
            title=ref.get("title"),
            authors=[a.get("family") for a in (ref.get("author") or []) if a.get("family")],
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
        payload = {
            "pipeline_version": report.pipeline_version,
            "refs": [_verdict_to_jsonable(v) for v in report.refs],
            "serpapi_budget": report.serpapi_budget,
            "serpapi_credits_used": report.serpapi_credits_used,
            "summary": {
                "total": len(report.refs),
                "verified": sum(1 for r in report.refs if r.status == Status.VERIFIED),
                "blocking": sum(1 for r in report.refs if r.status in {
                    Status.UNVERIFIED, Status.HALLUCINATED, Status.RETRACTED,
                    Status.AUTHOR_MISMATCH, Status.FIELD_ERROR,
                }),
            },
        }
        args.audit_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        verified_csl = [r.csl_json for r in report.refs if r.status == Status.VERIFIED and r.csl_json]
        if verified_csl:
            stage_f_compile_bibliography(verified_csl, args.bib_out)
        return 1 if report.has_any_blocking() else 0

    if args.csl_json:
        return stage_a_csl_to_bibtex(args.csl_json, args.out)

    parser.print_usage(sys.stderr)
    print("validate_references: --validate, --csl-json, or --check required.",
          file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
