#!/usr/bin/env python3
"""overclaim_lint.py: advisory calibration/overclaim detector for the Writer skill.

Advisory-only (WARN, never BLOCK) per the 2026-07-06 Review and Revision design.
Flags absolute/overclaim wording ("verified", "guaranteed", "eliminates",
"model-agnostic", ...) so the pre-submission review
(references/manuscript_review.md) can surface claim-calibration gaps. Mirrors
ai_tic_lint.py's CLI and report shape.

RKA-confidence ranking: when a `% provenance:` comment precedes the
overclaiming line, an injected `resolver(entity_id) -> dict|None` is consulted;
a claim backed by hypothesis/tested (not verified) evidence is ranked
priority="high". No live RKA call is made when no resolver is given.

CLI:
    python overclaim_lint.py <files>...
    python overclaim_lint.py --config /path/to/overclaim_config.yaml <files>...
    python overclaim_lint.py --output report.json <files>...

Exit codes:
    0: no hits (PASS)
    1: WARN hits present
Never returns 2. This linter does not BLOCK.

See references/manuscript_review.md for how the review consumes this report.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

# Calibration / overclaim terms -> category. Authored from the PI manuscript
# revision prompt template (2026-07-06); extensible per-project via a config
# mapping {term: {"verdict": "disable"}} (mirrors ai_tic_config.yaml).
OVERCLAIM_PATTERNS: dict[str, str] = {
    r"\bverified\b": "guarantee",
    r"\bguarantees?\b": "guarantee",
    r"\bguaranteed\b": "guarantee",
    r"\bprovably\b": "guarantee",
    r"\bcompletely\b": "completeness",
    r"\beliminates?\b": "elimination",
    r"\beliminated\b": "elimination",
    r"\bmodel-agnostic\b": "generality",
    r"\bfully general\b": "generality",
    r"\bgeneralizes?\b": "generality",
    r"\bdominant\b": "superiority",
    r"\bdominates?\b": "superiority",
    r"\bfundamentally\b": "superiority",
    r"\brobust to adaptive\b": "robustness",
    r"\bfull recall\b": "metric-absolute",
    r"\bno false positives?\b": "metric-absolute",
    r"\bzero false positives?\b": "metric-absolute",
    r"\bnever fails?\b": "absolute",
}

_PROV_RE = re.compile(r"^\s*%\s*provenance:\s*(.+)$", re.IGNORECASE)
_ID_RE = re.compile(r"(jrn|dec|lit|mis|clm|ecl)_[0-9A-Z]{26}")
# Backing confidences that make an absolute claim a high-priority gap.
_WEAK_CONFIDENCE = {"hypothesis", "tested"}
_PROV_WINDOW = 4  # lines to look back for a governing provenance comment

Resolver = Callable[[str], Optional[dict]]


@dataclass
class OverclaimHit:
    term: str
    category: str
    file: str
    line: int
    sentence: str
    severity: str = "WARN"
    priority: str = "normal"
    backing_entity: Optional[str] = None
    backing_confidence: Optional[str] = None


@dataclass
class OverclaimReport:
    hits: list = field(default_factory=list)
    verdict: str = "PASS"

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "hits": [asdict(h) for h in self.hits]}


def _nearest_provenance(lines: list, idx: int, resolver: Resolver):
    """Return (entity_id, confidence) for the nearest `% provenance:` comment
    within _PROV_WINDOW lines above `idx`, or (None, None)."""
    lo = max(-1, idx - _PROV_WINDOW - 1)
    for j in range(idx, lo, -1):
        m = _PROV_RE.match(lines[j])
        if m:
            id_match = _ID_RE.search(m.group(1))
            if not id_match:
                return None, None
            ent = id_match.group(0)
            resolved = resolver(ent)
            conf = (resolved or {}).get("confidence")
            return ent, (conf.lower() if isinstance(conf, str) else None)
    return None, None


def lint_file(path, *, resolver: Optional[Resolver] = None,
              config: Optional[dict] = None) -> OverclaimReport:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    disabled = set()
    if config:
        for term, spec in config.items():
            if isinstance(spec, dict) and spec.get("verdict") == "disable":
                disabled.add(term.lower())
    report = OverclaimReport()
    for i, line in enumerate(lines):
        for pat, category in OVERCLAIM_PATTERNS.items():
            for m in re.finditer(pat, line, re.IGNORECASE):
                term = m.group(0)
                if term.lower() in disabled:
                    continue
                hit = OverclaimHit(
                    term=term, category=category, file=str(path),
                    line=i + 1, sentence=line.strip(),
                )
                if resolver is not None:
                    ent, conf = _nearest_provenance(lines, i, resolver)
                    if ent is not None:
                        hit.backing_entity = ent
                        hit.backing_confidence = conf
                        if conf in _WEAK_CONFIDENCE:
                            hit.priority = "high"
                report.hits.append(hit)
    report.verdict = "WARN" if report.hits else "PASS"
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Advisory overclaim/calibration linter (WARN-only)."
    )
    ap.add_argument("files", nargs="+")
    ap.add_argument("--output", help="write JSON report to this path")
    ap.add_argument("--config", help="per-project overclaim_config.yaml")
    args = ap.parse_args(argv)

    config = None
    if args.config:
        import yaml  # optional; only needed with --config
        config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    all_hits = []
    verdict = "PASS"
    for f in args.files:
        rep = lint_file(f, config=config)
        all_hits.extend(rep.hits)
        if rep.verdict == "WARN":
            verdict = "WARN"

    out = {"verdict": verdict, "hits": [asdict(h) for h in all_hits]}
    if args.output:
        Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")
    else:
        print(json.dumps(out, indent=2))
    return 1 if verdict == "WARN" else 0


if __name__ == "__main__":
    sys.exit(main())
