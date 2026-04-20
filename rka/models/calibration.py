"""Pydantic models for the calibration loop (migration 018 + Mission 1B-iii).

See ``rka/skills/brain/decision_ux.md`` § Calibration Loop for the protocol.
The models mirror the ``calibration_outcomes`` CHECK constraint exactly so
Pydantic fails fast at the API boundary (HTTP 422) rather than the DB failing
at INSERT time (HTTP 500).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Outcome = Literal["succeeded", "failed", "mixed", "unresolved"]


class CalibrationOutcomeCreate(BaseModel):
    """Create payload for a calibration_outcomes row."""

    model_config = ConfigDict(extra="forbid")

    outcome: Outcome
    outcome_details: str | None = None
    recorded_by: str = "pi"


class CalibrationOutcome(BaseModel):
    """Full calibration_outcomes row as returned by the service and REST API."""

    model_config = ConfigDict(extra="forbid")

    id: str
    decision_id: str
    project_id: str
    outcome: Outcome
    outcome_details: str | None = None
    recorded_at: str
    recorded_by: str


class CalibrationBin(BaseModel):
    """One bin in the reliability-diagram breakdown."""

    model_config = ConfigDict(extra="forbid")

    bin_range: tuple[float, float]
    n: int
    accuracy: float
    mean_confidence: float


class CalibrationMetrics(BaseModel):
    """Calibration summary for a project.

    Two metric families are reported side by side, with **separate N-size guards**:

    **Outcome-based (Brier / ECE)** — eligibility: decision has (a) a
    recommended_option_id with a confidence_numeric AND (b) at least one
    non-``unresolved`` outcome. ``n`` / ``metrics_available`` track this.

    **Selection-based (override rates)** — per Mission 2 (v2.2.x override-rate
    tracking, dec_01KPJXVYZY2Y2HJN5T1WN5KYRN). Eligibility: decision has
    ``recommended_option_id`` AND any form of PI selection
    (``pi_selected_option_id`` OR ``pi_override_rationale``). Outcome is NOT
    required — selection happened regardless of whether the decision has
    been resolved yet. ``qualifying_decisions`` / ``override_metrics_available``
    track this.

    The two N's differ in practice: a decision can have a PI selection
    without a recorded outcome (contributes to override rates but not
    Brier), and a decision can have an outcome recorded after an escape
    hatch (contributes to neither Brier nor the outcome-specific flag).

    When either N<5, the corresponding ``*_available`` flag is False and
    ``warning`` (shared, prioritized by Brier/ECE) explains — tiny samples
    produce misleading numbers.
    """

    model_config = ConfigDict(extra="forbid")

    # Outcome-based metrics (Brier / ECE)
    n: int
    metrics_available: bool
    brier_score: float | None = None
    ece: float | None = None
    bin_breakdown: list[CalibrationBin] = Field(default_factory=list)
    warning: str | None = None
    decisions_covered: list[str] = Field(default_factory=list)

    # Selection-based metrics (override-rate tracking)
    qualifying_decisions: int = 0
    override_metrics_available: bool = False
    override_rate: float | None = None
    escape_hatch_rate: float | None = None
    near_miss_rate: float | None = None
