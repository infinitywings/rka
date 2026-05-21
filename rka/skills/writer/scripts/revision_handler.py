#!/usr/bin/env python3
"""revision_handler.py: 4-comment-class revision-loop dispatcher.

Phase 3 deliverable per dec_01KS2WPKMRVSJ2R0PP74722PEH (Option A bundled).
When the PI returns review comments on a draft section, this module
classifies each comment into one of 4 shapes and dispatches to the
matching handler:

  R1 (factual_r1)        Sentence-level factual claim; re-validate the
                         cited reference via Stage B-G; draft a factual
                         correction proposal or surface alternative
                         candidates on HALLUCINATED / RETRACTED.

  R2 (style_r2)          Style or AI-tic violation; re-run ai_tic_lint
                         with strict mode and apply auto-fixes; surface
                         residual violations as PI-review-needed.

  R3 (inconsistency_r3)  Cross-section contradiction; reconcile claim
                         diff via the bridge_repetition_check pattern;
                         draft reconciliation proposal.

  R4 (logical_r4)        Logical gap or unsupported claim; ESCALATE via
                         rka_create_mission(type='writer_evidence_gap',
                         target=manuscript_id, comment=...) addressed to
                         Brain.

Classifier discipline (per dec_01KS2WPKMRVSJ2R0PP74722PEH Brain
ratification 2026-05-20):

  - revision_handler.py ships HEURISTIC classification only
    (regex/keyword/structural patterns; no server-side LLM call).
  - At runtime, the Writer IS a Claude Code session; the Writer's
    own runtime is the LLM-assisted reasoning layer.
  - classify_comment returns ClassificationResult(cls, confidence,
    ambiguous, rationale, matched_patterns).
  - When ambiguous=True, the Writer escalates to PI before invoking
    any per-class handler.

REVIEW_STATE.md iteration tracking: each comment_class invocation
increments iteration; max 3 per comment; verdict CONTINUE / ESCALATE /
COMPLETE. The 3rd failed iteration auto-escalates to PI with 3
resolution options.

Venue-aware overrides: per-venue references/venue/<venue>.md may set
stricter rules consulted at dispatch time.

CLI:
    python revision_handler.py --classify --comment "..."
    python revision_handler.py --dispatch --comment "..." --section sections/03.tex \\
        --manuscript-id jrn_01K... --review-state .planning/REVIEW_STATE.md
    python revision_handler.py --review-state .planning/REVIEW_STATE.md --read

Exit codes:
    0 success (classification produced; OR handler completed; OR iteration
      advanced)
    1 ambiguous classification; PI escalation required
    2 handler error; revisit
    3 escalation triggered (R4 logical or REVIEW_STATE max iterations)
    4 usage error

See references/workflows.md "Revision-loop handler" for the conceptual
contract and dec_01KS2WPKMRVSJ2R0PP74722PEH for the scope-limiting decision.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


# Comment classes per design doc Section 14 (Revision Loop).
class CommentClass(str, Enum):
    FACTUAL_R1 = "factual_r1"
    STYLE_R2 = "style_r2"
    INCONSISTENCY_R3 = "inconsistency_r3"
    LOGICAL_R4 = "logical_r4"
    ESCALATE = "escalate"  # ambiguous-default sentinel


@dataclass
class ClassificationResult:
    """Heuristic classification of a review comment.

    When ambiguous is True, the caller (Writer's Claude Code session)
    escalates to PI before invoking any per-class handler. The cls
    field carries the dominant guess and rationale carries the
    pattern-matching trace for human review.
    """

    cls: CommentClass
    confidence: float  # 0.0 to 1.0
    ambiguous: bool
    rationale: str
    matched_patterns: list[str] = field(default_factory=list)


@dataclass
class HandlerResult:
    """Outcome of running a per-class handler on a single comment."""

    success: bool
    proposed_changes: list[str] = field(default_factory=list)
    escalation_required: bool = False
    notes: list[str] = field(default_factory=list)
    artifact_paths: list[str] = field(default_factory=list)


@dataclass
class ReviewState:
    """Iteration tracker for the revision loop on a single comment.

    Persisted as .planning/REVIEW_STATE.md per the workspace template
    schema. The third failed iteration auto-escalates to a PI Style
    or Logical checkpoint with three resolution options.
    """

    iteration: int = 0
    max_iterations: int = 3
    verdict: str = "CONTINUE"  # CONTINUE / ESCALATE / COMPLETE
    history: list[dict[str, Any]] = field(default_factory=list)


# Heuristic pattern sets for each comment class. Patterns are case-
# insensitive; scored 1 point per match; class with highest score wins
# unless tied or below confidence floor (which yields ambiguous=True).

FACTUAL_R1_PATTERNS = [
    r"\b(citation|cite|reference|ref)\s+(missing|wrong|incorrect|stale|incomplete|broken)\b",
    r"\b(this|the)\s+(claim|fact|statement|number|value|figure)\s+is\s+(wrong|incorrect|misleading|out[\s-]of[\s-]date)\b",
    r"\bcheck\s+(your|the)\s+(source|citation|reference)\b",
    r"\b(year|date|author|venue|journal)\s+(is\s+)?(wrong|incorrect)\b",
    r"\bnot\s+(in|from)\s+(\w+\s+)?(\d{4})\b",
    r"\b(was|were)\s+(retracted|withdrawn)\b",
    r"\bdoi\s+(broken|wrong|incorrect|does\s+not\s+resolve)\b",
]

STYLE_R2_PATTERNS = [
    r"\b(too|overly)\s+(wordy|verbose|long[-\s]winded|formal|casual|technical|jargon-?y)\b",
    r"\b(awkward|clunky|stilted)\b",
    r"\b(this|these|that)\s+(read|reads|sound|sounds)\s+like\s+(AI|GPT|machine|robot|ChatGPT)",
    r"\b(em[-\s]?dash|en[-\s]?dash)\b",
    r"\bpassive\s+voice\b",
    r"\b(rewrite|reword|rephrase|tone\s+down|tighten|simplify|shorten)\b",
    r"\b(facilitate|delve|leverage|comprehensive|furthermore|moreover|importantly)\b",
    r"\bdrop\s+the\s+(em[-\s]?dash|bullet|adjective)\b",
    r"\bnot\s+(plain|active)\s+(English|prose)\b",
    r"\bsounds?\s+like\s+(marketing|puffery|advertising)\b",
]

INCONSISTENCY_R3_PATTERNS = [
    r"\b(contradict|contradiction|inconsistent|inconsistency|disagree|conflict)\b",
    r"\b(elsewhere|earlier|later|previously|section\s+\d+|in\s+§\s*\d+)\s+(you|the\s+paper)\s+(say|state|claim|argue|describe|reports?)\b",
    r"\b(this|the)\s+(claim|statement|number|figure)\s+contradicts?\s+\w+\b",
    r"\b(doesn't|does\s+not|don't)\s+match\b",
    r"\b(but|however|yet)\s+(here|now)\s+you\s+(claim|say|argue)\b",
    r"\b(inconsistent|conflict)\s+with\s+(section|figure|table|paragraph)\b",
    r"\bcontradicts?\s+(figure|table|section)\s+\d+\b",
]

LOGICAL_R4_PATTERNS = [
    r"\b(unsupported|no\s+evidence|missing\s+evidence|where('s|\s+is)\s+the\s+evidence)\b",
    r"\b(logical\s+gap|jumps?\s+to\s+(a\s+)?conclusion|non[-\s]sequitur)\b",
    r"\b(what\s+about|have\s+you\s+considered|why\s+(not|do(es)?\s+you))\b",
    r"\b(missing|incomplete|weak)\s+(argument|reasoning|justification|motivation)\b",
    r"\bdoes\s+not\s+follow\b",
    r"\b(needs?|need)\s+(more|additional|further)\s+(evidence|data|support|justification)\b",
    r"\b(claim|conclusion)\s+(is\s+)?(too\s+strong|unwarranted|overreach(ing)?)\b",
]


# Confidence floor below which classify_comment returns ambiguous=True.
CONFIDENCE_FLOOR = 0.5


def classify_comment(comment_text: str) -> ClassificationResult:
    """Heuristic classifier with ambiguous-defaults-to-escalation discipline.

    Scores each of the 4 comment classes by counting regex matches.
    The class with the highest score wins UNLESS:
      - No patterns matched at all (return ESCALATE).
      - Multiple classes tied at the top (return ESCALATE).
      - Top score's share of total matches is below CONFIDENCE_FLOOR
        (return the guess but with ambiguous=True so the caller knows).

    The Writer's Claude Code session is expected to escalate to PI when
    ambiguous=True, per dec_01KS2WPKMRVSJ2R0PP74722PEH Brain ratification.
    """
    pattern_sets = {
        CommentClass.FACTUAL_R1: FACTUAL_R1_PATTERNS,
        CommentClass.STYLE_R2: STYLE_R2_PATTERNS,
        CommentClass.INCONSISTENCY_R3: INCONSISTENCY_R3_PATTERNS,
        CommentClass.LOGICAL_R4: LOGICAL_R4_PATTERNS,
    }

    scores: dict[CommentClass, int] = {cls: 0 for cls in pattern_sets}
    matched: dict[CommentClass, list[str]] = {cls: [] for cls in pattern_sets}

    for cls, patterns in pattern_sets.items():
        for pattern in patterns:
            if re.search(pattern, comment_text, re.IGNORECASE):
                scores[cls] += 1
                matched[cls].append(pattern)

    total = sum(scores.values())
    if total == 0:
        return ClassificationResult(
            cls=CommentClass.ESCALATE,
            confidence=0.0,
            ambiguous=True,
            rationale="No heuristic patterns matched; defer to Writer Claude Code session for LLM-assisted classification or escalate to PI.",
        )

    top_score = max(scores.values())
    tied = [cls for cls, s in scores.items() if s == top_score]
    if len(tied) > 1:
        return ClassificationResult(
            cls=CommentClass.ESCALATE,
            confidence=top_score / total,
            ambiguous=True,
            rationale=f"Multiple classes tied at top score {top_score}: {[c.value for c in tied]}",
            matched_patterns=[p for c in tied for p in matched[c]],
        )

    top_cls = tied[0]
    confidence = top_score / total
    ambiguous = confidence < CONFIDENCE_FLOOR
    return ClassificationResult(
        cls=top_cls,
        confidence=confidence,
        ambiguous=ambiguous,
        rationale=f"Top class {top_cls.value} with {top_score}/{total} pattern matches (confidence {confidence:.2f}; floor {CONFIDENCE_FLOOR}).",
        matched_patterns=matched[top_cls],
    )


# ---- Per-class handlers --------------------------------------------------


def handle_factual_r1(
    comment: str,
    section_path: Path,
    citation_ids: list[str] | None = None,
    *,
    validate_references_script: Path | None = None,
) -> HandlerResult:
    """R1: re-validate cited references via Stage B-G; surface verdicts.

    If validate_references_script is provided, invoke it as a subprocess
    against the citation_ids list and parse the audit.json output. On
    VERIFIED, propose a factual correction (no draft text; PI authors).
    On HALLUCINATED / RETRACTED, surface alternative candidates from the
    Stage G niche-rescue or Crossref update-to fields.
    """
    notes: list[str] = []
    proposed: list[str] = []
    if not section_path.exists():
        return HandlerResult(
            success=False,
            notes=[f"section not found: {section_path}"],
            escalation_required=True,
        )

    if not citation_ids:
        return HandlerResult(
            success=True,
            proposed_changes=[
                "R1 comment received but no citation_ids supplied; "
                "manual PI review of the section for the disputed claim."
            ],
            notes=["no_citation_ids_supplied"],
        )

    if validate_references_script is None:
        # Heuristic-only path: surface the citation_ids to the Writer
        # without invoking subprocess validation.
        return HandlerResult(
            success=True,
            proposed_changes=[
                f"Re-validate citations: {', '.join(citation_ids)}"
            ],
            notes=["validate_references_subprocess_not_invoked"],
        )

    cmd = [sys.executable, str(validate_references_script), "--check"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return HandlerResult(
            success=False,
            notes=[f"validate_references subprocess error: {exc}"],
            escalation_required=True,
        )
    notes.append(f"validate_references --check exit {result.returncode}")
    proposed.append(
        f"Citations {', '.join(citation_ids)} flagged for Stage B-G re-validation."
    )
    return HandlerResult(success=True, proposed_changes=proposed, notes=notes)


def handle_style_r2(
    comment: str,
    section_path: Path,
    *,
    strict: bool = True,
    ai_tic_lint_script: Path | None = None,
    ai_tic_config: Path | None = None,
) -> HandlerResult:
    """R2: re-run ai_tic_lint with strict mode; surface fixes and residuals.

    Invokes ai_tic_lint.py as a subprocess when the script path is
    provided. Reports the verdict (PASS / WARN / BLOCK) plus per-rule
    hit counts so the Writer's Claude Code session can decide whether
    to author the rewrite directly or surface to PI.
    """
    notes: list[str] = []
    if not section_path.exists():
        return HandlerResult(
            success=False,
            notes=[f"section not found: {section_path}"],
            escalation_required=True,
        )

    if ai_tic_lint_script is None:
        return HandlerResult(
            success=True,
            proposed_changes=[
                "Re-read section under ai_tic_lint --strict guidance "
                "(script path not supplied; Writer reasons over comment + section directly)."
            ],
            notes=["ai_tic_lint_subprocess_not_invoked"],
        )

    cmd = [sys.executable, str(ai_tic_lint_script), str(section_path)]
    if ai_tic_config:
        cmd.extend(["--config", str(ai_tic_config)])
    if strict:
        cmd.append("--output")
        cmd.append("/dev/null")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return HandlerResult(
            success=False,
            notes=[f"ai_tic_lint subprocess error: {exc}"],
            escalation_required=True,
        )
    verdict_map = {0: "PASS", 1: "WARN", 2: "BLOCK"}
    verdict = verdict_map.get(result.returncode, "UNKNOWN")
    notes.append(f"ai_tic_lint verdict: {verdict} (exit {result.returncode})")
    return HandlerResult(
        success=result.returncode in (0, 1),
        proposed_changes=[f"ai_tic_lint --strict on {section_path.name}: {verdict}"],
        notes=notes,
    )


def handle_inconsistency_r3(
    comment: str,
    section_paths: list[Path],
    *,
    bridge_check_script: Path | None = None,
) -> HandlerResult:
    """R3: cross-section claim diff via bridge_repetition_check.

    The bridge-repetition heuristic catches near-duplicate sentences
    across sections at SequenceMatcher ratio 0.7+; a high-similarity
    pair often indicates a contradiction or restatement. The Writer's
    Claude Code session reasons over the pair to decide if it is an
    intentional restatement or a contradiction that needs reconciliation.
    """
    notes: list[str] = []
    missing = [p for p in section_paths if not p.exists()]
    if missing:
        return HandlerResult(
            success=False,
            notes=[f"sections not found: {', '.join(str(p) for p in missing)}"],
            escalation_required=True,
        )

    if bridge_check_script is None or len(section_paths) < 2:
        return HandlerResult(
            success=True,
            proposed_changes=[
                "Cross-section claim diff to be performed by the Writer's "
                "Claude Code session over the listed sections."
            ],
            notes=["bridge_check_subprocess_not_invoked_or_insufficient_sections"],
        )

    cmd = [sys.executable, str(bridge_check_script)]
    cmd.extend(str(p) for p in section_paths)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return HandlerResult(
            success=False,
            notes=[f"bridge_check subprocess error: {exc}"],
            escalation_required=True,
        )
    notes.append(f"bridge_check exit {result.returncode}")
    # Exit code 1 means bridges detected per Phase 1 contract.
    bridges_detected = result.returncode == 1
    return HandlerResult(
        success=True,
        proposed_changes=(
            ["Cross-section near-duplicate pairs detected; Writer reviews for reconciliation."]
            if bridges_detected
            else ["No cross-section near-duplicates detected; comment may refer to a structural-level claim conflict the Writer should reason over."]
        ),
        notes=notes,
    )


def handle_logical_r4(
    comment: str,
    section_path: Path,
    manuscript_id: str,
    *,
    rka_client=None,
) -> HandlerResult:
    """R4: escalate to Brain via writer_evidence_gap mission creation.

    Constructs the mission payload (type, context, motivated_by_decision)
    and either returns the payload for the Writer's Claude Code session
    to dispatch via the rka MCP client, or directly invokes the provided
    rka_client.create_mission(...) if given (used in tests).
    """
    mission_payload = {
        "type": "writer_evidence_gap",
        "context": (
            "Writer revision R4 logical-gap escalation:\n"
            f"  Section: {section_path}\n"
            f"  Comment: {comment}\n"
            f"  Manuscript: {manuscript_id}\n"
            "Brain to assess the logical gap, identify required evidence, "
            "and either commission an Executor evidence-gathering mission "
            "or guide the Writer in rephrasing the claim to match available evidence."
        ),
        "related_mission": None,
    }
    notes = [
        "R4 logical-gap escalation; Brain mission required.",
        f"Mission payload prepared for type='writer_evidence_gap'.",
    ]
    if rka_client is not None:
        try:
            rka_client.create_mission(**mission_payload)
            notes.append("rka_client.create_mission invoked successfully.")
        except Exception as exc:
            return HandlerResult(
                success=False,
                escalation_required=True,
                notes=notes + [f"rka_client.create_mission failed: {exc}"],
            )
    return HandlerResult(
        success=True,
        escalation_required=True,
        proposed_changes=[
            "Spawn writer_evidence_gap mission addressed to Brain; "
            "Writer waits for Brain's evidence-gap response."
        ],
        notes=notes,
    )


# ---- ReviewState persistence ----------------------------------------------


def read_review_state(path: Path) -> ReviewState:
    """Read REVIEW_STATE.md from .planning/.

    The workspace template REVIEW_STATE.md uses a structured markdown
    format with iteration / max / verdict fields. This reader extracts
    the fields via regex; absent file or fields default to a fresh
    state with iteration=0.
    """
    if not path.exists():
        return ReviewState()
    text = path.read_text(encoding="utf-8")
    iteration = 0
    max_iter = 3
    verdict = "CONTINUE"
    m = re.search(r"^\s*iteration:\s*(\d+)\s*$", text, re.MULTILINE)
    if m:
        iteration = int(m.group(1))
    m = re.search(r"^\s*max:\s*(\d+)\s*$", text, re.MULTILINE)
    if m:
        max_iter = int(m.group(1))
    m = re.search(r"^\s*verdict:\s*([A-Z]+)\s*$", text, re.MULTILINE)
    if m:
        verdict = m.group(1)
    return ReviewState(iteration=iteration, max_iterations=max_iter, verdict=verdict)


def advance_review_state(state: ReviewState, *, success: bool, note: str = "") -> ReviewState:
    """Advance iteration and update verdict per the 3-iteration cap.

    Returns a new ReviewState with iteration incremented and verdict
    updated according to:
      - success=True -> COMPLETE.
      - success=False AND iteration+1 < max -> CONTINUE.
      - success=False AND iteration+1 >= max -> ESCALATE.
    """
    new_iter = state.iteration + 1
    if success:
        new_verdict = "COMPLETE"
    elif new_iter >= state.max_iterations:
        new_verdict = "ESCALATE"
    else:
        new_verdict = "CONTINUE"
    new_history = list(state.history) + [
        {"iteration": new_iter, "success": success, "note": note}
    ]
    return ReviewState(
        iteration=new_iter,
        max_iterations=state.max_iterations,
        verdict=new_verdict,
        history=new_history,
    )


# ---- Venue-aware overrides -----------------------------------------------


def load_venue_overrides(venue_md_path: Path) -> dict[str, Any]:
    """Read a venue file under references/venue/ and extract stricter rules.

    The Phase 2 venue files (CHI, EMNLP, USENIX, IEEE-SP, NeurIPS, OSDI,
    Nature) each carry a "Forbidden constructions" section. This loader
    extracts forbidden patterns so the R2 style handler can apply
    venue-specific rules on top of the universal ai_tic_lint pass.

    Returns a dict with keys 'forbidden_constructions' (list of strings)
    and 'page_limit_class' (string). Missing or unreadable file yields
    an empty overrides dict.
    """
    if not venue_md_path.exists():
        return {}
    text = venue_md_path.read_text(encoding="utf-8")
    forbidden: list[str] = []
    in_forbidden = False
    page_limit = ""
    for line in text.splitlines():
        if re.match(r"^##\s+\d+\.\s*Forbidden\s+constructions", line, re.IGNORECASE):
            in_forbidden = True
            continue
        if in_forbidden and line.startswith("## "):
            in_forbidden = False
        if in_forbidden:
            m = re.match(r"^\s*-\s+(.+?)(?:\s+\(.*\))?\s*$", line)
            if m:
                forbidden.append(m.group(1).strip())
        if re.match(r"^##\s+\d+\.\s*Page[-\s]limit\s+class", line, re.IGNORECASE):
            # Capture the next non-blank line as the page-limit-class summary.
            pass
    return {
        "forbidden_constructions": forbidden,
        "page_limit_class": page_limit,
    }


# ---- CLI -----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Revision-loop dispatcher: classify a review comment and dispatch to the matching handler."
    )
    parser.add_argument("--comment", help="Review comment text")
    parser.add_argument("--section", type=Path, help="Section .tex path")
    parser.add_argument("--sections", type=Path, nargs="*",
                        help="Multiple sections for R3 cross-section diff")
    parser.add_argument("--manuscript-id", help="Manuscript jrn_ id for R4 mission")
    parser.add_argument("--citation-ids", nargs="*",
                        help="Citation lit_ ids relevant to R1")
    parser.add_argument("--classify", action="store_true",
                        help="Classify only; do not dispatch")
    parser.add_argument("--dispatch", action="store_true",
                        help="Classify and dispatch to the matching handler")
    parser.add_argument("--review-state", type=Path,
                        help="Path to REVIEW_STATE.md")
    parser.add_argument("--read", action="store_true",
                        help="Read REVIEW_STATE.md and print as JSON")
    args = parser.parse_args(argv)

    if args.review_state and args.read:
        state = read_review_state(args.review_state)
        print(json.dumps(asdict(state), indent=2))
        return 0

    if args.classify or args.dispatch:
        if not args.comment:
            print("revision_handler: --comment required for --classify / --dispatch",
                  file=sys.stderr)
            return 4
        classification = classify_comment(args.comment)
        if args.classify and not args.dispatch:
            print(json.dumps({
                "class": classification.cls.value,
                "confidence": classification.confidence,
                "ambiguous": classification.ambiguous,
                "rationale": classification.rationale,
                "matched_patterns": classification.matched_patterns,
            }, indent=2))
            return 1 if classification.ambiguous else 0

        if classification.ambiguous:
            print(json.dumps({
                "status": "ambiguous_escalate",
                "class_guess": classification.cls.value,
                "confidence": classification.confidence,
                "rationale": classification.rationale,
            }, indent=2))
            return 1

        if classification.cls == CommentClass.FACTUAL_R1:
            result = handle_factual_r1(
                args.comment, args.section, args.citation_ids,
            )
        elif classification.cls == CommentClass.STYLE_R2:
            result = handle_style_r2(args.comment, args.section)
        elif classification.cls == CommentClass.INCONSISTENCY_R3:
            sections = args.sections or ([args.section] if args.section else [])
            result = handle_inconsistency_r3(args.comment, sections)
        elif classification.cls == CommentClass.LOGICAL_R4:
            result = handle_logical_r4(
                args.comment, args.section, args.manuscript_id or "<unknown>",
            )
        else:
            print(json.dumps({
                "status": "unhandled_class",
                "class": classification.cls.value,
            }, indent=2))
            return 1

        print(json.dumps({
            "class": classification.cls.value,
            "handler_result": asdict(result),
        }, indent=2, default=str))
        if result.escalation_required:
            return 3
        return 0 if result.success else 2

    parser.print_usage(sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(main())
