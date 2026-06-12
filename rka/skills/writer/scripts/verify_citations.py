#!/usr/bin/env python3
"""Citation-key cross-check for Writer drafts (P4).

LLM LaTeX is unreliable on bibliographies: TeXpert reports ~15% accuracy on
complex LaTeX with logical (not typo) errors dominating, and the classic
silent failure is a `\\cite{key}` that does not resolve to a real .bib entry
(rendered as "[?]") or a case-mismatched key (`Smith2024` vs `smith2024`).
This deterministic check feeds the writer's compile-and-fix loop: every
citation key must resolve, case-exact, to an entry in the bibliography.

Verdicts: unresolved citations -> BLOCK; unused bib entries -> WARN.
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
from typing import Optional

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
    unused: list = field(default_factory=list)         # in bib, never cited -> WARN
    verdict: str = "PASS"


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


def audit(tex_texts: list, bib_texts: list) -> Report:
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

    if rep.unresolved or rep.case_mismatch:
        rep.verdict = "BLOCK"
    elif rep.unused:
        rep.verdict = "WARN"
    else:
        rep.verdict = "PASS"
    return rep


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Citation-key cross-check for Writer drafts.")
    parser.add_argument("--tex", nargs="+", type=Path, required=True, help=".tex source files")
    parser.add_argument("--bib", nargs="+", type=Path, required=True, help=".bib / bibliography files")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    tex_texts = [p.read_text(encoding="utf-8") for p in args.tex]
    bib_texts = [p.read_text(encoding="utf-8") for p in args.bib]
    rep = audit(tex_texts, bib_texts)
    rep.tex_files = [str(p) for p in args.tex]
    rep.bib_files = [str(p) for p in args.bib]

    text = json.dumps(asdict(rep), indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    return {"BLOCK": 2, "WARN": 1, "PASS": 0}[rep.verdict]


if __name__ == "__main__":
    sys.exit(main())
