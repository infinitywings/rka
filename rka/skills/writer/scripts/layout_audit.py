#!/usr/bin/env python3
"""layout_audit.py: 12-field LaTeX layout audit per references/latex_audit.md.

Runs after a successful latexmk render. Parses .log, .blg, .aux, and pdfinfo
output to compute PASS, WARN, or BLOCK verdicts per field. Emits audit.json
suitable for attachment to the manuscript manifest's related_journal.

CLI:
    python layout_audit.py --venue CHI
    python layout_audit.py --venue EMNLP --pdf paper.pdf --log paper.log
    python layout_audit.py --venue CHI --output audit.json

Exit codes:
    0: all fields PASS
    1: at least one WARN, no BLOCK
    2: at least one BLOCK
    3: missing input file (compile probably failed)
    4: usage error

See references/latex_audit.md for the field reference and regex patterns.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# Phase W1: page limits are now sourced from venue.yaml via venue_loader.
# The dict below is the legacy fallback — kept for back-compat with the
# `--venue NAME` flag for venues not yet migrated to YAML (and short-track
# variants like EMNLP_SHORT / ACL_SHORT, which the YAML registry doesn't
# yet model — Phase W3 adds dedicated short-paper variants).
VENUE_PAGE_LIMITS_LEGACY = {
    "CSCW": 25,
    "UIST": 12,
    "EMNLP_SHORT": 4,
    "ACL": 9,
    "ACL_SHORT": 5,
}


def _resolve_page_limit(venue: str) -> int:
    """Resolve page_limit_main for `venue` from (in priority order):
      1. venue.yaml via venue_loader (preferred — the Phase W1 path)
      2. VENUE_PAGE_LIMITS_LEGACY (fallback for short-track variants)
      3. 0 (unknown venue; the page-limit gate fails closed)
    """
    try:
        # Phase W1: ensure the sibling venue_loader.py is importable
        # under both standalone CLI invocation and importlib loading
        # (where this script's dir isn't on sys.path).
        _scripts_dir = Path(__file__).resolve().parent
        if str(_scripts_dir) not in sys.path:
            sys.path.insert(0, str(_scripts_dir))
        # Lazy import — venue_loader pulls PyYAML which is otherwise
        # only required when actually using the YAML path.
        from venue_loader import load_venue, VenueValidationError
    except Exception:  # noqa: BLE001
        return VENUE_PAGE_LIMITS_LEGACY.get(venue, 0)
    try:
        v = load_venue(venue)
    except (VenueValidationError, FileNotFoundError, Exception):  # noqa: BLE001
        return VENUE_PAGE_LIMITS_LEGACY.get(venue, 0)
    if v.submission.page_limit_main is not None:
        return v.submission.page_limit_main
    return VENUE_PAGE_LIMITS_LEGACY.get(venue, 0)


def _resolve_from_manuscript_yaml(manuscript_yaml_path: Path) -> tuple[str, int]:
    """Read venue_id + resolved page limit from a workspace's manuscript.yaml.

    Resolution order (most-specific wins):
      1. `manuscript.yaml -> overrides.page_limit_main`
      2. sibling `cfp_overrides.yaml` -> `overrides.submission.page_limit_main`
         (Phase W2: year-specific CFP deltas)
      3. venue.yaml baseline via venue_loader
      4. legacy short-track table

    Returns (venue_id, page_limit). Raises FileNotFoundError or
    ValueError on parse failure.
    """
    import yaml  # local import; only needed when called

    data = yaml.safe_load(manuscript_yaml_path.read_text(encoding="utf-8")) or {}
    venue_id = str(data.get("venue_id") or "").strip()
    if not venue_id or venue_id.startswith("REPLACE_WITH_"):
        raise ValueError(
            f"{manuscript_yaml_path}: venue_id is missing or unfilled placeholder"
        )
    override = (data.get("overrides") or {}).get("page_limit_main")
    if isinstance(override, int) and override > 0:
        return venue_id, override

    cfp_path = manuscript_yaml_path.parent / "cfp_overrides.yaml"
    if cfp_path.is_file():
        cfp_data = yaml.safe_load(cfp_path.read_text(encoding="utf-8")) or {}
        if cfp_data.get("base_venue_id") == venue_id:
            cfp_page = (
                ((cfp_data.get("overrides") or {}).get("submission") or {})
                .get("page_limit_main")
            )
            if isinstance(cfp_page, int) and cfp_page > 0:
                return venue_id, cfp_page

    return venue_id, _resolve_page_limit(venue_id)

# Compiled regex patterns per field.
RE_UNDEFINED_CITATION = re.compile(
    r"^LaTeX Warning: Citation [`'](.+?)' .* undefined", re.MULTILINE
)
RE_UNDEFINED_REF = re.compile(
    r"^LaTeX Warning: Reference [`'](.+?)' on page .* undefined", re.MULTILINE
)
RE_MISSING_BIB_KEY = re.compile(
    r'^Warning--I didn\'t find a database entry for "(.+?)"', re.MULTILINE
)
RE_OVERFULL_HBOX = re.compile(
    r"^Overfull \\hbox \(([\d.]+)pt too wide\)", re.MULTILINE
)
RE_OVERFULL_VBOX = re.compile(r"^Overfull \\vbox", re.MULTILINE)
RE_FLOAT_TOO_LARGE = re.compile(r"Float too large for page", re.MULTILINE)
RE_UNDERFULL_HBOX = re.compile(
    r"^Underfull \\hbox \(badness (\d+)\)", re.MULTILINE
)
RE_QUESTION_MARK_CITATION = re.compile(r"\[\?\]")
RE_AUX_LABEL = re.compile(r"\\newlabel\{([^}]+)\}")
RE_TEX_REF = re.compile(r"\\(?:ref|eqref)\{([^}]+)\}")


@dataclass
class FieldVerdict:
    """Verdict for a single audit field."""
    field_name: str
    verdict: str  # PASS, WARN, BLOCK
    value: int | float | str
    threshold: Optional[int | float | str] = None
    matches: list = field(default_factory=list)


@dataclass
class AuditReport:
    """Full audit result over the input gate plus 12 layout fields."""
    manuscript: str
    rendered_at: str
    pdf_path: str
    venue: str
    page_limit: int
    pages_rendered: int
    fields: dict[str, dict] = field(default_factory=dict)
    summary: dict = field(default_factory=dict)


def _read_or_empty(path: Path) -> str:
    """Read a file if it exists; empty string otherwise."""
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def get_pdf_page_count(pdf_path: Path) -> int:
    """Run pdfinfo and parse the Pages line.

    Returns 0 if pdfinfo is unavailable or the PDF does not exist.
    """
    if pdf_path is None or not pdf_path.exists():
        return 0
    try:
        result = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return 0
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                return 0
    return 0


def check_audit_inputs(
    pdf_path: Optional[Path],
    log_path: Optional[Path],
    tex_path: Optional[Path],
    pages: int,
) -> FieldVerdict:
    """Fail closed unless the render artifacts needed by the audit exist.

    A missing input is not equivalent to an empty, warning-free artifact.  The
    old behavior silently converted absent PDF/log/TeX inputs to empty values
    and could therefore report PASS without auditing a render at all.
    """
    missing = [
        name
        for name, path in (("pdf", pdf_path), ("log", log_path), ("tex", tex_path))
        if path is None or not path.is_file()
    ]
    unreadable: list[str] = []
    for name, path in (("log", log_path), ("tex", tex_path)):
        if path is None or not path.is_file():
            continue
        try:
            path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            unreadable.append(name)
    if pdf_path is not None and pdf_path.is_file() and pages <= 0:
        unreadable.append("pdf_pages")

    failures = [*(f"missing:{name}" for name in missing),
                *(f"unreadable:{name}" for name in unreadable)]
    verdict = "BLOCK" if failures else "PASS"
    return FieldVerdict("audit_inputs", verdict, len(failures), 0, failures)


def check_pages_over_limit(pages: int, limit: int) -> FieldVerdict:
    if limit <= 0:
        return FieldVerdict(
            "pages_over_limit",
            "BLOCK",
            pages,
            limit,
            ["page_limit_unresolved"],
        )
    if pages > limit:
        return FieldVerdict("pages_over_limit", "BLOCK", pages, limit)
    return FieldVerdict("pages_over_limit", "PASS", pages, limit)


def check_pages_equals_limit(pages: int, limit: int) -> FieldVerdict:
    if pages == limit:
        return FieldVerdict("pages_equals_limit", "WARN", pages, limit)
    return FieldVerdict("pages_equals_limit", "PASS", pages, limit)


def check_undefined_citations(log_text: str) -> FieldVerdict:
    matches = RE_UNDEFINED_CITATION.findall(log_text)
    verdict = "BLOCK" if matches else "PASS"
    return FieldVerdict("undefined_citations", verdict, len(matches), 0, matches)


def check_undefined_refs(log_text: str) -> FieldVerdict:
    matches = RE_UNDEFINED_REF.findall(log_text)
    verdict = "BLOCK" if matches else "PASS"
    return FieldVerdict("undefined_refs", verdict, len(matches), 0, matches)


def check_missing_bib_keys(blg_text: str) -> FieldVerdict:
    matches = RE_MISSING_BIB_KEY.findall(blg_text)
    verdict = "BLOCK" if matches else "PASS"
    return FieldVerdict("missing_bib_keys", verdict, len(matches), 0, matches)


def check_question_mark_citations(pdf_path: Path) -> FieldVerdict:
    """Scan the rendered PDF text for [?] (unresolved citation placeholder)."""
    if pdf_path is None or not pdf_path.exists():
        return FieldVerdict("question_mark_citations", "PASS", 0, 0)
    try:
        result = subprocess.run(
            ["pdftotext", str(pdf_path), "-"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return FieldVerdict("question_mark_citations", "PASS", 0, 0,
                            ["pdftotext unavailable; skipped"])
    matches = RE_QUESTION_MARK_CITATION.findall(result.stdout)
    verdict = "BLOCK" if matches else "PASS"
    return FieldVerdict("question_mark_citations", verdict, len(matches), 0)


def check_orphan_refs(aux_text: str, tex_text: str) -> FieldVerdict:
    """A \\ref{label} exists in the .tex source but no matching \\newlabel in the .aux."""
    if not aux_text and not tex_text:
        return FieldVerdict("orphan_refs", "PASS", 0, 0)
    labels = set(RE_AUX_LABEL.findall(aux_text))
    refs = set(RE_TEX_REF.findall(tex_text))
    orphans = sorted(refs - labels)
    verdict = "BLOCK" if orphans else "PASS"
    return FieldVerdict("orphan_refs", verdict, len(orphans), 0, orphans)


def check_overfull_hboxes_over_10pt(log_text: str) -> FieldVerdict:
    raw_matches = RE_OVERFULL_HBOX.findall(log_text)
    over_10pt = [m for m in raw_matches if float(m) > 10.0]
    verdict = "WARN" if over_10pt else "PASS"
    return FieldVerdict(
        "overfull_hboxes_over_10pt", verdict, len(over_10pt), 10.0,
        [{"overflow_pt": float(m)} for m in over_10pt],
    )


def check_overfull_vboxes(log_text: str) -> FieldVerdict:
    matches = RE_OVERFULL_VBOX.findall(log_text)
    verdict = "WARN" if matches else "PASS"
    return FieldVerdict("overfull_vboxes", verdict, len(matches), 0)


def check_float_too_large(log_text: str) -> FieldVerdict:
    matches = RE_FLOAT_TOO_LARGE.findall(log_text)
    verdict = "WARN" if matches else "PASS"
    return FieldVerdict("float_too_large", verdict, len(matches), 0)


def check_underfull_badness_over_5000(log_text: str) -> FieldVerdict:
    raw_matches = RE_UNDERFULL_HBOX.findall(log_text)
    over_5000 = [int(m) for m in raw_matches if int(m) > 5000]
    verdict = "WARN" if over_5000 else "PASS"
    return FieldVerdict(
        "underfull_badness_over_5000", verdict, len(over_5000), 5000,
        over_5000,
    )


def check_chktex_warnings_over_10(tex_path: Path) -> FieldVerdict:
    """Run chktex on the tex source. WARN if total warnings exceed 10."""
    if tex_path is None or not tex_path.exists():
        return FieldVerdict("chktex_warnings_over_10", "PASS", 0, 10)
    try:
        result = subprocess.run(
            ["chktex", "-q", str(tex_path)],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return FieldVerdict("chktex_warnings_over_10", "PASS", 0, 10,
                            ["chktex unavailable; skipped"])
    warning_count = sum(
        1 for line in result.stdout.splitlines() if line.strip()
    )
    verdict = "WARN" if warning_count > 10 else "PASS"
    return FieldVerdict("chktex_warnings_over_10", verdict, warning_count, 10)


def audit(
    pdf_path: Optional[Path],
    log_path: Optional[Path],
    blg_path: Optional[Path],
    aux_path: Optional[Path],
    tex_path: Optional[Path],
    venue: str,
    page_limit_override: Optional[int] = None,
) -> AuditReport:
    """Run the required-input gate and all 12 checks.

    Phase W1: page_limit_override lets the caller (or
    --manuscript-yaml CLI path) supply a per-manuscript override that
    wins over the venue baseline.
    """
    import datetime

    page_limit = (
        page_limit_override
        if page_limit_override is not None
        else _resolve_page_limit(venue)
    )
    log_text = _read_or_empty(log_path)
    blg_text = _read_or_empty(blg_path)
    aux_text = _read_or_empty(aux_path)
    tex_text = _read_or_empty(tex_path)
    pages = get_pdf_page_count(pdf_path) if pdf_path else 0
    rendered_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    verdicts = [
        check_audit_inputs(pdf_path, log_path, tex_path, pages),
        check_pages_over_limit(pages, page_limit),
        check_undefined_citations(log_text),
        check_undefined_refs(log_text),
        check_missing_bib_keys(blg_text),
        check_question_mark_citations(pdf_path),
        check_orphan_refs(aux_text, tex_text),
        check_overfull_hboxes_over_10pt(log_text),
        check_overfull_vboxes(log_text),
        check_float_too_large(log_text),
        check_underfull_badness_over_5000(log_text),
        check_chktex_warnings_over_10(tex_path),
        check_pages_equals_limit(pages, page_limit),
    ]

    report = AuditReport(
        manuscript=str(tex_path) if tex_path else "",
        rendered_at=rendered_at,
        pdf_path=str(pdf_path) if pdf_path else "",
        venue=venue,
        page_limit=page_limit,
        pages_rendered=pages,
        fields={v.field_name: asdict(v) for v in verdicts},
    )

    blocks = sum(1 for v in verdicts if v.verdict == "BLOCK")
    warns = sum(1 for v in verdicts if v.verdict == "WARN")
    passes = sum(1 for v in verdicts if v.verdict == "PASS")
    overall = "BLOCK" if blocks else ("WARN" if warns else "PASS")
    report.summary = {
        "blocks": blocks,
        "warns": warns,
        "passes": passes,
        "overall_verdict": overall,
    }

    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "LaTeX layout audit: required-input gate plus 12-field "
            "PASS/WARN/BLOCK report."
        )
    )
    parser.add_argument(
        "--venue",
        default=None,
        help=(
            "Venue id (e.g., NeurIPS, CHI). Resolves page limit via "
            "venue.yaml; falls back to legacy short-track table for "
            "names not yet migrated. Mutually exclusive with "
            "--manuscript-yaml."
        ),
    )
    parser.add_argument(
        "--manuscript-yaml",
        type=Path,
        default=None,
        help=(
            "Path to a workspace's manuscript.yaml. Reads venue_id + "
            "overrides.page_limit_main; preferred over --venue."
        ),
    )
    parser.add_argument("--pdf", type=Path, default=Path("main.pdf"))
    parser.add_argument("--log", type=Path, default=Path("main.log"))
    parser.add_argument("--blg", type=Path, default=Path("main.blg"))
    parser.add_argument("--aux", type=Path, default=Path("main.aux"))
    parser.add_argument("--tex", type=Path, default=Path("main.tex"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.venue and args.manuscript_yaml:
        print(
            "layout_audit: --venue and --manuscript-yaml are mutually exclusive",
            file=sys.stderr,
        )
        return 4
    if not args.venue and not args.manuscript_yaml:
        print(
            "layout_audit: provide either --venue NAME or --manuscript-yaml PATH",
            file=sys.stderr,
        )
        return 4

    page_limit_override: Optional[int] = None
    if args.manuscript_yaml:
        try:
            args.venue, page_limit_override = _resolve_from_manuscript_yaml(
                args.manuscript_yaml
            )
        except (FileNotFoundError, ValueError) as e:
            print(f"layout_audit: {e}", file=sys.stderr)
            return 4

    # An unknown venue yields page_limit=0; check_pages_over_limit turns that
    # into an explicit BLOCK so a missing or stale venue policy cannot pass.

    report = audit(
        # Preserve the requested paths even when absent so the report can name
        # the missing prerequisites rather than silently replacing them.
        pdf_path=args.pdf,
        log_path=args.log,
        blg_path=args.blg,
        aux_path=args.aux,
        tex_path=args.tex,
        venue=args.venue,
        page_limit_override=page_limit_override,
    )

    text = json.dumps(asdict(report), indent=2, default=str)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)

    overall = report.summary["overall_verdict"]
    if overall == "BLOCK":
        return 2
    if overall == "WARN":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
