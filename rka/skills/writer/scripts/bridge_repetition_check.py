#!/usr/bin/env python3
"""bridge_repetition_check.py: Detect near-duplicate sentences across files.

A common LLM failure pattern: the closing thesis of one section is restated
verbatim or near-verbatim as the opening of the next ("bridge repetition").
This pattern survives lexical sanitization because it is structural rather
than vocabulary. The defense: compare every sentence in file A to every
sentence in file B (for A != B) and flag pairs whose similarity ratio
exceeds a threshold.

Phase 1 implementation per dec_01KS12H9KT1T03DHX2Q6FKTXHH (clean-room from
algorithmic idea only; stdlib difflib API). No code, comments, variable
names, or function structure copied from any external source.

Algorithm:
  1. Read each input file as UTF-8 text.
  2. Strip LaTeX comments (% ...) and citation macros (\\cite{...} et al.)
     so noise is not compared.
  3. Segment into sentences via end-of-sentence punctuation followed by
     whitespace (regex (?<=[.!?])\\s+).
  4. Filter sentences shorter than min_length (default 40 chars) so noise
     and short headings are not paired.
  5. For each unordered pair of sentences (s_i in file_a, s_j in file_b)
     where file_a != file_b, compute difflib.SequenceMatcher(a=s_i, b=s_j,
     autojunk=False).ratio().
  6. If ratio >= threshold, record a BridgeHit.
  7. Return all BridgeHit records sorted by ratio (descending).

CLI:
    python bridge_repetition_check.py sections/*.tex
    python bridge_repetition_check.py --threshold 0.8 --min-length 60 sections/*.tex
    python bridge_repetition_check.py --output bridges.json sections/*.tex

Exit codes:
    0: no bridges detected above threshold
    1: bridges detected
    2: usage error

See references/ai_tics.md "Structural detectors" for the rationale and
threshold derivation.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


DEFAULT_THRESHOLD = 0.7
DEFAULT_MIN_LENGTH = 40

# Strip LaTeX comments and citation/reference macros before comparison.
_COMMENT_RE = re.compile(r"%.*$", re.MULTILINE)
_MACRO_RE = re.compile(r"\\(?:cite|citep|citet|ref|eqref|label|footnote)\{[^}]*\}")
_SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Sentence:
    """A sentence located in a file at a specific line."""
    source: str
    line: int
    text: str


@dataclass(frozen=True)
class BridgeHit:
    """Two sentences in different files whose similarity exceeds threshold."""
    file_a: str
    line_a: int
    text_a: str
    file_b: str
    line_b: int
    text_b: str
    ratio: float


def _strip_noise(raw: str) -> str:
    """Remove LaTeX comments and selected macros that would inflate ratios."""
    no_comments = _COMMENT_RE.sub("", raw)
    no_macros = _MACRO_RE.sub("", no_comments)
    return no_macros


def collect_sentences(path: Path, min_length: int) -> list[Sentence]:
    """Read a file and segment into sentences; track line of each."""
    raw = path.read_text(encoding="utf-8")
    cleaned = _strip_noise(raw)
    out: list[Sentence] = []
    line_no = 0
    for chunk in cleaned.splitlines(keepends=True):
        line_no += 1
        pieces = _SENTENCE_BREAK_RE.split(chunk)
        for piece in pieces:
            stripped = piece.strip()
            if len(stripped) >= min_length:
                out.append(Sentence(source=str(path), line=line_no, text=stripped))
    return out


def similarity(a: Sentence, b: Sentence) -> float:
    """Compute difflib SequenceMatcher ratio between two sentence texts."""
    matcher = difflib.SequenceMatcher(a=a.text, b=b.text, autojunk=False)
    return matcher.ratio()


def find_bridges(
    paths: list[Path],
    threshold: float = DEFAULT_THRESHOLD,
    min_length: int = DEFAULT_MIN_LENGTH,
) -> list[BridgeHit]:
    """Compare sentences across files; return cross-file near-duplicates above threshold.

    Comparisons are only made between sentences in different files (no intra-file
    pairs; bridge repetition is by definition a cross-section phenomenon).
    """
    per_file = [collect_sentences(p, min_length=min_length) for p in paths]
    hits: list[BridgeHit] = []
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            for s_a in per_file[i]:
                for s_b in per_file[j]:
                    r = similarity(s_a, s_b)
                    if r >= threshold:
                        hits.append(BridgeHit(
                            file_a=s_a.source,
                            line_a=s_a.line,
                            text_a=s_a.text,
                            file_b=s_b.source,
                            line_b=s_b.line,
                            text_b=s_b.text,
                            ratio=r,
                        ))
    return sorted(hits, key=lambda h: h.ratio, reverse=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect near-duplicate sentences across files (bridge repetition)."
    )
    parser.add_argument("files", nargs="+", type=Path, help="Files to scan")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"SequenceMatcher ratio threshold (default {DEFAULT_THRESHOLD})")
    parser.add_argument("--min-length", type=int, default=DEFAULT_MIN_LENGTH,
                        help=f"Minimum sentence length in chars (default {DEFAULT_MIN_LENGTH})")
    parser.add_argument("--output", type=Path, default=None,
                        help="Write JSON output to file (default stdout)")
    args = parser.parse_args(argv)

    hits = find_bridges(args.files, threshold=args.threshold, min_length=args.min_length)

    payload = {
        "version": "1.0",
        "threshold": args.threshold,
        "min_length": args.min_length,
        "files_scanned": [str(p) for p in args.files],
        "bridges_found": len(hits),
        "hits": [asdict(h) for h in hits],
    }

    text = json.dumps(payload, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)

    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
