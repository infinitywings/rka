#!/usr/bin/env python3
"""Provenance verifier for Writer drafts (P0/P1/P6).

The Writer skill's Iron Law ("draft but do not assert; every claim carries a
lit_/jrn_/dec_ anchor") was, until now, an aspiration: the `% provenance:`
comments are written by the drafting model and never checked. Empirically
(eval-v3 writer test, 2026-06-12) a capable model navigated a trap-laden
corpus correctly, but only by careful reading, with no mechanical gate; the
literature shows that diligence fails at scale (LLMs miss retractions >50% of
the time; degrade 6-31% on superseded facts; "citation present" diverges from
"citation supports the claim" ~50% of the time even for top models).

This script turns the Iron Law into an enforced invariant. For every
`% provenance: <entity_id> ...` comment in a .tex file it checks, against the
live RKA knowledge base:

  EXISTS      the cited entity is real (catches fabrication / wrong project)
  CURRENT     its status is not superseded / retracted / abandoned
              (P1: catches citing overturned or retracted knowledge)
  SUPPORTED   its content lexically supports the claim that follows
              (Phase-1 token-overlap heuristic; NLI entailment is the
               documented Phase-2 upgrade, mirroring the reference pipeline)
  UNCONTESTED the entity has no `contradicts` edge, or the draft surfaces
              the disagreement (P6)

Verdicts per citation: OK | LOW_SUPPORT (WARN) | CONTRADICTED (WARN) |
MISSING (BLOCK) | STALE (BLOCK) | RETRACTED (BLOCK). Coverage findings are
MALFORMED, ORPHAN, and UNCOVERED (all BLOCK). A superseded/retracted
entity may be cited deliberately (e.g. a "Design Evolution" paragraph) by
adding an acknowledgement token to the comment: `superseded-ack` or
`retracted-ack`; the verdict downgrades to OK with a note.

Exit codes (matching ai_tic_lint.py): 0 PASS, 1 WARN, 2 BLOCK, 3 usage/unreachable.

The audit logic operates on an injected `resolver` callable so it is fully
testable offline; the CLI builds a REST-backed resolver against RKA.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

# entity_id -> resolver returns this shape (or None when the entity is absent)
#   {"type": "decision"|"journal"|..., "status": "active"|"superseded"|...,
#    "content": "<text used for support check>", "contradicted": bool}
Resolver = Callable[[str], Optional[dict]]

_PROV_RE = re.compile(r"^\s*%\s*provenance:\s*(.*)$", re.IGNORECASE)
_ID_RE = re.compile(r"(jrn|dec|lit|mis|clm|ecl)_[0-9A-Z]{26}")
_ACK_RE = re.compile(r"\b(superseded-ack|retracted-ack|status-ack)\b", re.IGNORECASE)

# Entity states that mean "do not assert from this" unless acknowledged.
_STALE_STATES = {"superseded", "abandoned", "merged"}
_RETRACTED_STATES = {"retracted"}

_STOPWORDS = set(
    "a an the and or of to in on at for with about from into over is are was were "
    "be been being do does did have has had can could should would will may might "
    "must this that these those it its they them their there we our as by not no "
    "than then so such also more most some any each per via using used use".split()
)


@dataclass
class CitationResult:
    entity_id: str
    line: int
    verdict: str  # citation verdict or a fail-closed coverage finding
    detail: str = ""
    support: Optional[float] = None
    acknowledged: bool = False


@dataclass
class FileReport:
    path: str
    total_citations: int = 0
    total_markers: int = 0
    substantive_blocks: int = 0
    uncovered_blocks: int = 0
    citations: list = field(default_factory=list)
    verdict: str = "PASS"  # PASS | WARN | BLOCK
    counts: dict = field(default_factory=dict)


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
            if t not in _STOPWORDS and len(t) > 2}


def _next_prose(lines: list, idx: int) -> str:
    """The claim text a provenance comment governs: the prose lines that follow
    it up to the next blank line or next comment, with LaTeX markup stripped."""
    out = []
    for line in lines[idx + 1:]:
        s = line.strip()
        if not s:
            break
        # Multiple contiguous provenance comments may govern the same prose
        # block.  Skip those peers, but stop at any other comment.
        if _PROV_RE.match(line):
            continue
        if s.startswith("%"):
            break
        out.append(s)
    prose = " ".join(out)
    # strip common LaTeX so the support heuristic sees words, not markup
    prose = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ", prose)
    prose = prose.replace("\\%", "%").replace("~", " ").replace("{,}", ",")
    return prose


_STRUCTURAL_COMMAND_RE = re.compile(
    r"^\\(?:documentclass|usepackage|RequirePackage|newcommand|renewcommand|"
    r"providecommand|DeclareMathOperator|title|author|date|thanks|institute|"
    r"affiliation|email|keywords|maketitle|tableofcontents|bibliography|"
    r"bibliographystyle|addbibresource|printbibliography|input|include|label|"
    r"section\*?|subsection\*?|subsubsection\*?|paragraph\*?|"
    r"begin|end|centering|vspace|hspace|pagestyle|thispagestyle|"
    r"setlength|hypersetup|graphicspath)\b",
    re.IGNORECASE,
)


def _is_substantive_line(line: str) -> bool:
    """Return True for manuscript prose, not LaTeX scaffolding.

    This intentionally errs toward treating ordinary text (including text
    containing inline LaTeX) as prose.  Pure declarations, section headings,
    labels, inputs, comments, and environment delimiters are scaffolding.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("%"):
        return False
    if _STRUCTURAL_COMMAND_RE.match(stripped):
        return False
    # Standalone braces, math delimiters, and alignment punctuation are not
    # assertions.  A line containing a letter or number after markup removal is.
    plain = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?", " ", stripped)
    plain = re.sub(r"[{}$&_^~\\]", " ", plain)
    return bool(re.search(r"[A-Za-z0-9]", plain))


def _substantive_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Return inclusive ``(start, end)`` line indexes for prose blocks."""
    blocks: list[tuple[int, int]] = []
    start: Optional[int] = None
    end: Optional[int] = None
    for idx, line in enumerate(lines):
        if _is_substantive_line(line):
            if start is None:
                start = idx
            end = idx
            continue
        if start is not None:
            blocks.append((start, end if end is not None else start))
            start = end = None
    if start is not None:
        blocks.append((start, end if end is not None else start))
    return blocks


def _governing_marker_indexes(lines: list[str], prose_start: int) -> list[int]:
    """Find the contiguous provenance-comment group before a prose block."""
    indexes: list[int] = []
    idx = prose_start - 1
    while idx >= 0 and lines[idx].strip().startswith("%"):
        if _PROV_RE.match(lines[idx]):
            indexes.append(idx)
        idx -= 1
    return indexes


# Below this many content-tokens the cited entity is too thin for the lexical
# heuristic to judge support (e.g. a literature entry with no abstract); the
# check is skipped rather than firing a false LOW_SUPPORT.
_MIN_SCORABLE_TOKENS = 12
# Phase-1 lexical support is ADVISORY: good academic prose paraphrases its
# sources, so moderate token overlap is expected. Only a NEAR-ZERO overlap
# against a substantial entity is a credible "this citation is unrelated"
# signal. The Phase-2 NLI-entailment backend replaces this heuristic and
# tightens the threshold (mirrors the reference-pipeline Phase-1/2 split).
_LOW_SUPPORT_THRESHOLD = 0.08


def support_score(claim: str, content: str):
    """Phase-1 lexical support. Returns (score, scorable).

    score = fraction of claim content-tokens present in the cited entity's
    content; scorable is False when the entity content is too thin to judge."""
    ct = _tokens(claim)
    et = _tokens(content)
    if not ct:
        return 1.0, False
    if len(et) < _MIN_SCORABLE_TOKENS:
        return None, False
    return len(ct & et) / len(ct), True


# Phase-2 support backend: an entailment judge (claim, evidence) ->
# True (supported) | False (unsupported) | None (abstain -> lexical fallback).
# Wired to an LLM via make_llm_judge(); injectable for tests.
Judge = Callable[[str, str], Optional[bool]]


def make_llm_judge(model: Optional[str] = None) -> Optional[Judge]:
    """Build an LLM entailment judge via litellm, or None when unavailable.

    Model resolution: explicit arg > RKA_WRITER_JUDGE_MODEL > RKA_LLM_MODEL.
    Judge errors abstain (return None) so the lexical heuristic remains the
    floor; the LLM tightens, never loosens, the gate.
    """
    resolved = model or os.environ.get("RKA_WRITER_JUDGE_MODEL") \
        or os.environ.get("RKA_LLM_MODEL")
    if not resolved:
        return None
    try:
        import litellm  # optional dependency ([llm] extra)
    except ImportError:
        return None

    def judge(claim: str, evidence: str) -> Optional[bool]:
        try:
            resp = litellm.completion(
                model=resolved,
                messages=[{
                    "role": "user",
                    "content": (
                        "Does the EVIDENCE support the CLAIM? Answer with exactly "
                        "one word: SUPPORTED or UNSUPPORTED.\n\n"
                        f"CLAIM: {claim}\n\nEVIDENCE: {evidence}"
                    ),
                }],
                temperature=0,
                max_tokens=5,
            )
            verdict = (resp.choices[0].message.content or "").strip().upper()
            if "UNSUPPORTED" in verdict:
                return False
            if "SUPPORTED" in verdict:
                return True
            return None
        except Exception:
            return None

    return judge


def audit_text(text: str, resolver: Resolver, *, support_threshold: float = _LOW_SUPPORT_THRESHOLD,
               surfaced_terms: Optional[set] = None, judge: Optional[Judge] = None) -> FileReport:
    """Audit provenance comments in `text`. `resolver` maps entity_id -> dict|None.

    `surfaced_terms` is the set of content-tokens appearing anywhere in the
    draft prose; a CONTRADICTED entity is downgraded to OK only if the draft
    also mentions disagreement vocabulary (so the writer surfaced the conflict).
    """
    lines = text.splitlines()
    report = FileReport(path="<text>")
    disagreement_vocab = {"contradict", "contradicts", "disagree", "disagreement",
                          "conflict", "conflicting", "however", "whereas", "revised",
                          "superseded", "earlier", "estimate"}
    draft_surfaces_disagreement = bool((surfaced_terms or set()) & disagreement_vocab)

    marker_indexes: set[int] = set()
    valid_marker_indexes: set[int] = set()

    for i, line in enumerate(lines):
        m = _PROV_RE.match(line)
        if not m:
            continue
        marker_indexes.add(i)
        body = m.group(1)
        id_match = _ID_RE.search(body)
        if not id_match:
            report.citations.append(CitationResult(
                "<invalid>", i + 1, "MALFORMED",
                "provenance marker does not contain a valid RKA entity ID",
            ))
            continue
        valid_marker_indexes.add(i)
        eid = id_match.group(0)
        ack = bool(_ACK_RE.search(body))
        claim = _next_prose(lines, i)

        if not claim.strip():
            report.citations.append(CitationResult(
                eid, i + 1, "ORPHAN",
                "provenance marker is not followed by a substantive prose block",
                None, ack,
            ))
            continue

        ent = resolver(eid)
        if ent is None:
            report.citations.append(CitationResult(eid, i + 1, "MISSING",
                "entity not found in project (fabricated or wrong project)", None, ack))
            continue

        status = (ent.get("status") or "").lower()
        if status in _RETRACTED_STATES:
            if ack:
                report.citations.append(CitationResult(eid, i + 1, "OK",
                    "retracted entity cited with retracted-ack", None, True))
            else:
                report.citations.append(CitationResult(eid, i + 1, "RETRACTED",
                    "cites a retracted entity without retracted-ack", None, ack))
            continue
        if status in _STALE_STATES:
            if ack:
                report.citations.append(CitationResult(eid, i + 1, "OK",
                    f"{status} entity cited with status-ack", None, True))
            else:
                report.citations.append(CitationResult(eid, i + 1, "STALE",
                    f"cites a {status} entity without superseded-ack", None, ack))
            continue

        sup, scorable = support_score(claim, ent.get("content", ""))
        judged: Optional[bool] = None
        if judge is not None and claim.strip() and ent.get("content"):
            judged = judge(claim, ent["content"])
        if judged is True:
            sup, scorable = 1.0, True
        elif judged is False:
            sup, scorable = 0.0, True
        sup_round = round(sup, 2) if sup is not None else None
        if ent.get("contradicted") and not draft_surfaces_disagreement:
            report.citations.append(CitationResult(eid, i + 1, "CONTRADICTED",
                "cited entity has a contradicts edge; draft does not surface the disagreement",
                sup_round, ack))
        elif scorable and sup < support_threshold:
            report.citations.append(CitationResult(eid, i + 1, "LOW_SUPPORT",
                ("entailment judge: evidence does not support the claim" if judged is False
                 else f"claim shares only {sup:.0%} of content tokens with the cited entity "
                      "(advisory; NLI entailment is the Phase-2 check)"),
                sup_round, ack))
        else:
            note = "" if scorable else "support unscored (thin entity content; NLI Phase-2)"
            report.citations.append(CitationResult(eid, i + 1, "OK", note, sup_round, ack))

    blocks = _substantive_blocks(lines)
    report.total_markers = len(marker_indexes)
    report.total_citations = len(valid_marker_indexes)
    report.substantive_blocks = len(blocks)
    for start, _end in blocks:
        governors = _governing_marker_indexes(lines, start)
        if not any(idx in valid_marker_indexes for idx in governors):
            report.uncovered_blocks += 1
            preview = lines[start].strip()
            report.citations.append(CitationResult(
                "<uncovered>", start + 1, "UNCOVERED",
                "substantive prose is not immediately governed by a valid "
                f"% provenance marker: {preview[:120]}",
            ))

    counts: dict = {}
    for c in report.citations:
        counts[c.verdict] = counts.get(c.verdict, 0) + 1
    report.counts = counts
    if any(c.verdict in (
        "MISSING", "STALE", "RETRACTED", "MALFORMED", "ORPHAN", "UNCOVERED"
    ) for c in report.citations):
        report.verdict = "BLOCK"
    elif any(c.verdict in ("LOW_SUPPORT", "CONTRADICTED") for c in report.citations):
        report.verdict = "WARN"
    else:
        report.verdict = "PASS"
    return report


def audit_file(path: Path, resolver: Resolver, **kw) -> FileReport:
    text = path.read_text(encoding="utf-8")
    surfaced = _tokens(text)
    rep = audit_text(text, resolver, surfaced_terms=surfaced, **kw)
    rep.path = str(path)
    return rep


# --------------------------------------------------------------------------
# REST-backed resolver (CLI path; not exercised by offline tests)
# --------------------------------------------------------------------------
_PREFIX_PATH = {
    "jrn": ("notes", "content", "confidence"),
    "dec": ("decisions", "rationale", "status"),
    "lit": ("literature", "abstract", "status"),
    "mis": ("missions", "objective", "status"),
    "clm": ("claims", "content", "status"),
    "ecl": ("clusters", "synthesis", "status"),
}


def make_rest_resolver(base_url: str, project_id: str) -> Resolver:
    import urllib.request
    import urllib.error

    cache: dict = {}

    def _get(path: str):
        req = urllib.request.Request(base_url + path, headers={"X-RKA-Project": project_id})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)

    def resolve(eid: str):
        if eid in cache:
            return cache[eid]
        prefix = eid.split("_", 1)[0]
        spec = _PREFIX_PATH.get(prefix)
        if not spec:
            cache[eid] = None
            return None
        endpoint, content_field, status_field = spec
        try:
            row = _get(f"/api/{endpoint}/{eid}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                cache[eid] = None
                return None
            raise
        if row.get("project_id") != project_id:
            raise RuntimeError(
                f"RKA did not attest {eid} to requested project {project_id}"
            )
        status = row.get(status_field) or ""
        # journal stores lifecycle in `confidence`; superseded_by also signals stale
        if row.get("superseded_by"):
            if status not in _RETRACTED_STATES:
                status = "superseded"
        # Graph availability is part of the UNCONTESTED gate. A failed graph
        # lookup must abort the audit rather than silently assert "no
        # contradiction".
        contradicted = False
        ego = _get(f"/api/graph/ego/{eid}")
        for edge in ego.get("edges", []):
            if edge.get("link_type") == "contradicts" or edge.get("relation") == "contradicts":
                contradicted = True
                break
        ent = {"type": endpoint, "status": status,
               "content": row.get(content_field) or row.get("content") or "",
               "contradicted": contradicted}
        cache[eid] = ent
        return ent

    return resolve


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Provenance verifier for Writer drafts.")
    parser.add_argument("files", nargs="+", type=Path, help=".tex files to verify")
    parser.add_argument("--rka-url", default=os.environ.get("RKA_API_URL", "http://localhost:9712"))
    parser.add_argument("--project", required=True,
                        help="Explicit RKA project ID (prj_...)")
    parser.add_argument("--support-threshold", type=float, default=_LOW_SUPPORT_THRESHOLD)
    parser.add_argument("--support-backend", choices=("lexical", "llm"), default="lexical",
                        help="llm: entailment judge via litellm (RKA_WRITER_JUDGE_MODEL "
                             "or RKA_LLM_MODEL); judge errors fall back to lexical")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        resolver = make_rest_resolver(args.rka_url, args.project)
        # fail fast if RKA is unreachable
        import urllib.request
        urllib.request.urlopen(args.rka_url + "/api/health", timeout=10).read()
    except Exception as e:
        print(f"error: cannot reach RKA at {args.rka_url}: {e}", file=sys.stderr)
        return 3

    judge = make_llm_judge() if args.support_backend == "llm" else None
    if args.support_backend == "llm" and judge is None:
        print("warning: --support-backend llm requested but no judge available "
              "(set RKA_WRITER_JUDGE_MODEL and install the [llm] extra); "
              "using lexical", file=sys.stderr)
    reports = [audit_file(f, resolver, support_threshold=args.support_threshold,
                          judge=judge)
               for f in args.files]
    output = {
        "version": "1.0",
        "files": [asdict(r) for r in reports],
        "summary": {
            "blocks": sum(1 for r in reports if r.verdict == "BLOCK"),
            "warns": sum(1 for r in reports if r.verdict == "WARN"),
            "passes": sum(1 for r in reports if r.verdict == "PASS"),
        },
    }
    text = json.dumps(output, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    if output["summary"]["blocks"]:
        return 2
    if output["summary"]["warns"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
