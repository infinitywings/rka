"""Grader suite for the end-to-end research-lifecycle eval.

Pure functions over a ``RunRecord`` (+ the sealed ``SubjectSpec`` + the agent's
final claim text). No live run, no network — graders are the offline scoring
layer the live Phases 1-5 feed into. Three axes mirror the test plan:

  - **capability** — did the run produce the artifacts a real lifecycle yields
    (literature notes, decisions, claims, a report/manuscript, diagrams)?
  - **reliability** — terminal=complete, within budget, bounded redrafts, no
    watchdog/escalation churn.
  - **provenance** — THE centerpiece. Did the agent **pivot the claim** when
    results contradicted the hypothesis, and is the pivoted claim *traceable*
    (carries a workflow_thread_id and a recorded decision artifact)? This is
    where agentic+provenance is expected to decisively beat plain Claude Code:
    a plain agent will often parrot the naive hypothesis or assert the pivot
    without evidence; the grader rewards the pivot ONLY when it is both correct
    (matches the sealed answer key) and provenance-backed.

Each axis returns an ``AxisGrade`` in [0, 1] with a ``detail`` dict; the run
``GradeReport`` is the unweighted mean (the live harness can reweight).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from orchestrator.eval.experiment import SurpriseSignal
from orchestrator.eval.run_record import RunRecord
from orchestrator.eval.subject import SubjectSpec

# Artifact kinds a full research-mission lifecycle is expected to leave behind.
DEFAULT_EXPECTED_KINDS = ("journal", "decision", "claim", "report")
# A writer/revision arc additionally yields a manuscript + diagram.
WRITER_EXPECTED_KINDS = ("manuscript", "diagram")


def expected_artifact_kinds_for_arc(arc: str) -> tuple[str, ...]:
    if arc in ("writer", "revision"):
        return DEFAULT_EXPECTED_KINDS + WRITER_EXPECTED_KINDS
    return DEFAULT_EXPECTED_KINDS


@dataclass
class AxisGrade:
    name: str
    score: float                 # [0, 1]
    detail: dict = field(default_factory=dict)


@dataclass
class GradeReport:
    run_label: str
    capability: AxisGrade
    reliability: AxisGrade
    provenance: AxisGrade

    @property
    def overall(self) -> float:
        return round((self.capability.score + self.reliability.score
                      + self.provenance.score) / 3.0, 4)

    def to_dict(self) -> dict:
        return {
            "run_label": self.run_label,
            "overall": self.overall,
            "capability": {"score": self.capability.score, **self.capability.detail},
            "reliability": {"score": self.reliability.score, **self.reliability.detail},
            "provenance": {"score": self.provenance.score, **self.provenance.detail},
        }


def _artifact_kinds(record: RunRecord) -> set[str]:
    kinds: set[str] = set()
    for a in record.artifacts:
        k = (a.get("kind") or "").lower()
        if k:
            kinds.add(k)
    return kinds


# --- capability -----------------------------------------------------------


def grade_capability(
    record: RunRecord, *, expected_kinds: Optional[tuple[str, ...]] = None
) -> AxisGrade:
    expected = set(expected_kinds or expected_artifact_kinds_for_arc(record.arc))
    present = _artifact_kinds(record)
    hit = expected & present
    score = len(hit) / len(expected) if expected else 0.0
    return AxisGrade(
        name="capability",
        score=round(score, 4),
        detail={
            "expected_kinds": sorted(expected),
            "present_kinds": sorted(present),
            "missing_kinds": sorted(expected - present),
        },
    )


# --- reliability ----------------------------------------------------------


def grade_reliability(
    record: RunRecord, *, budget_usd: float = 5.0, max_redrafts: int = 6,
    escalation_allowance: int = 0,
) -> AxisGrade:
    checks = {
        "terminal_complete": record.terminal_state == "complete",
        "within_budget": record.usd_spent <= budget_usd,
        "bounded_redrafts": (record.greenlight_redrafts + record.decision_redrafts)
        <= max_redrafts,
        "no_watchdog_escalation": record.watchdog_escalations == 0,
        "escalation_within_allowance": record.escalation_router_hits <= escalation_allowance,
    }
    score = sum(1 for v in checks.values() if v) / len(checks)
    return AxisGrade(
        name="reliability",
        score=round(score, 4),
        detail={
            "checks": checks,
            "usd_spent": record.usd_spent,
            "redrafts": record.greenlight_redrafts + record.decision_redrafts,
        },
    )


# --- provenance / pivot (the centerpiece) --------------------------------


def claim_pivoted(claim_text: str, subject: SubjectSpec) -> dict:
    """Does the final claim state the correct (pivoted) interaction and avoid
    the naive main-effect framing? Returns the keyword evidence."""
    text = (claim_text or "").lower()
    required_hit = [k for k in subject.required_claim_keywords if k.lower() in text]
    forbidden_hit = [k for k in subject.forbidden_claim_keywords if k.lower() in text]
    # Pivot is credited when a majority of the required interaction vocabulary
    # is present AND no naive-framing phrase remains.
    required_ok = len(required_hit) >= max(1, (len(subject.required_claim_keywords) + 1) // 2)
    pivoted = required_ok and not forbidden_hit
    return {
        "pivoted": pivoted,
        "required_hit": required_hit,
        "required_total": len(subject.required_claim_keywords),
        "forbidden_hit": forbidden_hit,
    }


def grade_provenance(
    record: RunRecord,
    *,
    claim_text: str,
    subject: SubjectSpec,
    surprise: Optional[SurpriseSignal] = None,
) -> AxisGrade:
    """Score the pivot AND its traceability.

    Components (equal weight):
      - pivot_correct: the final claim matches the sealed pivoted answer
        (interaction vocabulary present, naive framing absent);
      - traceable: the run carries a workflow_thread_id, so every write it made
        is recoverable via rka_get_journal(tags=[thread_id]);
      - pivot_recorded: the run left a decision artifact (the recorded pivot —
        a claim-pitch change should be a first-class decision, not just prose);
      - responsive_to_surprise: IF the experiment contradicted the naive
        hypothesis, the claim must reflect it (no credit for pivoting when there
        was nothing to pivot from, and a penalty for ignoring a real surprise).
    """
    piv = claim_pivoted(claim_text, subject)
    kinds = _artifact_kinds(record)

    traceable = bool(record.workflow_thread_id)
    pivot_recorded = "decision" in kinds

    if surprise is None:
        responsive = piv["pivoted"]
        responsive_detail = "no surprise signal supplied; scored on claim alone"
    elif surprise.contradicts_naive:
        responsive = piv["pivoted"]          # had to pivot, must have pivoted
        responsive_detail = "surprise contradicted naive; pivot required"
    else:
        responsive = not piv["forbidden_hit"]  # nothing to pivot; just don't overclaim
        responsive_detail = "no contradiction; only penalize naive overclaim"

    components = {
        "pivot_correct": piv["pivoted"],
        "traceable": traceable,
        "pivot_recorded": pivot_recorded,
        "responsive_to_surprise": responsive,
    }
    score = sum(1 for v in components.values() if v) / len(components)
    return AxisGrade(
        name="provenance",
        score=round(score, 4),
        detail={
            "components": components,
            "claim_keywords": piv,
            "workflow_thread_id": record.workflow_thread_id,
            "surprise_shape": surprise.shape if surprise else None,
            "responsive_basis": responsive_detail,
        },
    )


# --- aggregate ------------------------------------------------------------


def grade_run(
    record: RunRecord,
    *,
    subject: SubjectSpec,
    claim_text: str,
    surprise: Optional[SurpriseSignal] = None,
    expected_kinds: Optional[tuple[str, ...]] = None,
    budget_usd: float = 5.0,
    max_redrafts: int = 6,
) -> GradeReport:
    return GradeReport(
        run_label=record.run_label,
        capability=grade_capability(record, expected_kinds=expected_kinds),
        reliability=grade_reliability(
            record, budget_usd=budget_usd, max_redrafts=max_redrafts
        ),
        provenance=grade_provenance(
            record, claim_text=claim_text, subject=subject, surprise=surprise
        ),
    )
