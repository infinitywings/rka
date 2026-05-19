#!/usr/bin/env python3
"""validate_references.py: 7-stage reference validation pipeline (Phase 1 stub).

Phase 1 implements Stage A only (CSL-JSON pass-through to BibTeX via manubot
if installed). Stages B through G are documented in references/reference_pipeline.md
and raise NotImplementedError here. Phase 2 wires the full pipeline.

CLI:
    python validate_references.py --csl-json input.json --out refs.bib
    python validate_references.py --check    # report manubot availability

Exit codes:
    0: Stage A succeeded
    1: Stage A failed (manubot missing or subprocess error)
    2: Stages B through G called (NotImplementedError; Phase 2 deliverable)
    3: usage error

See references/reference_pipeline.md for the full architecture.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


PHASE_2_REFERENCE = (
    "Phase 2 deliverable. See references/reference_pipeline.md for the full "
    "architecture, including the rka-writer-tools MCP server and per-stage "
    "API contracts. PI ratified the phasing via dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D Q2 "
    "(optional MCP tools deferred) and dec_01KS0AXXASJ5GXV7M0SS39Y066 (SerpAPI "
    "tertiary, Phase 2 integration)."
)


def manubot_available() -> bool:
    """Check whether manubot is installed and callable."""
    return shutil.which("manubot") is not None


def stage_a_csl_to_bibtex(csl_json_path: Path, out_bib: Path) -> int:
    """Stage A: CSL-JSON to BibTeX via manubot.

    Reads CSL-JSON from csl_json_path, extracts DOIs / identifiers, and
    feeds them through manubot's CLI to produce a BibTeX file at out_bib.

    Returns 0 on success, non-zero on failure.
    """
    if not csl_json_path.exists():
        print(f"validate_references: input not found: {csl_json_path}", file=sys.stderr)
        return 1
    if not manubot_available():
        print(
            "validate_references: manubot CLI not on PATH. Install with: "
            "pip install manubot. Stage A requires manubot for the CSL-JSON "
            "to BibTeX conversion.",
            file=sys.stderr,
        )
        return 1

    raw = csl_json_path.read_text(encoding="utf-8")
    try:
        records = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"validate_references: invalid JSON in {csl_json_path}: {exc}",
              file=sys.stderr)
        return 1
    if not isinstance(records, list):
        records = [records]

    identifiers = []
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
            "validate_references: no resolvable identifiers (DOI, PMID, PMC, "
            "arXiv) found in CSL-JSON. Stage A requires at least one.",
            file=sys.stderr,
        )
        return 1

    try:
        result = subprocess.run(
            ["manubot", "cite", "--format=bibtex", *identifiers],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        print("validate_references: manubot disappeared from PATH between checks.",
              file=sys.stderr)
        return 1

    if result.returncode != 0:
        print(f"validate_references: manubot failed (exit {result.returncode})",
              file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1

    out_bib.write_text(result.stdout, encoding="utf-8")
    return 0


def stage_b_resolve_identifiers(*args, **kwargs):
    """Stage B: identifier resolution via Crossref/manubot/OpenAlex/S2/arXiv."""
    raise NotImplementedError("Stage B identifier resolution: " + PHASE_2_REFERENCE)


def stage_c_cross_source_validation(*args, **kwargs):
    """Stage C: cross-source existence validation (>=2 sources concur)."""
    raise NotImplementedError("Stage C cross-source validation: " + PHASE_2_REFERENCE)


def stage_d_retraction_check(*args, **kwargs):
    """Stage D: retraction check via Crossref update-to + RWDB CSV."""
    raise NotImplementedError("Stage D retraction check: " + PHASE_2_REFERENCE)


def stage_e_author_disambiguation(*args, **kwargs):
    """Stage E: author disambiguation via OpenAlex + ORCID; SerpAPI tertiary."""
    raise NotImplementedError("Stage E author disambiguation: " + PHASE_2_REFERENCE)


def stage_f_bibliography_compilation(*args, **kwargs):
    """Stage F: manubot + bibtex-tidy + (optional) betterbib subprocess."""
    raise NotImplementedError("Stage F bibliography compilation: " + PHASE_2_REFERENCE)


def stage_g_niche_citation_rescue(*args, **kwargs):
    """Stage G: SerpAPI google_scholar rescue before HALLUCINATED verdict."""
    raise NotImplementedError("Stage G niche-citation rescue: " + PHASE_2_REFERENCE)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reference validation pipeline (Phase 1: Stage A only)."
    )
    parser.add_argument("--csl-json", type=Path,
                        help="Path to CSL-JSON input (Stage A)")
    parser.add_argument("--out", type=Path, default=Path("refs.bib"),
                        help="Output BibTeX path (Stage A; default refs.bib)")
    parser.add_argument("--check", action="store_true",
                        help="Report manubot availability and exit")
    args = parser.parse_args(argv)

    if args.check:
        available = manubot_available()
        print(f"validate_references.py Phase 1 stub")
        print(f"  manubot CLI available: {available}")
        print(f"  Stage A (CSL-JSON to BibTeX): {'available' if available else 'unavailable'}")
        print(f"  Stages B-G: not implemented (Phase 2 deliverable)")
        return 0 if available else 1

    if not args.csl_json:
        parser.print_usage(sys.stderr)
        print("validate_references: --csl-json required (Stage A) or --check",
              file=sys.stderr)
        return 3

    return stage_a_csl_to_bibtex(args.csl_json, args.out)


if __name__ == "__main__":
    sys.exit(main())
