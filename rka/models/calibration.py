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

    Eligibility: a decision counts if it has (a) a recommended_option_id with
    a confidence_numeric and (b) at least one non-``unresolved`` outcome.
    Most-recent outcome per decision is used.

    When ``n < 5``, ``metrics_available`` is False and ``warning`` explains
    why — tiny samples produce misleading calibration numbers.
    """

    model_config = ConfigDict(extra="forbid")

    n: int
    metrics_available: bool
    brier_score: float | None = None
    ece: float | None = None
    bin_breakdown: list[CalibrationBin] = Field(default_factory=list)
    warning: str | None = None
    decisions_covered: list[str] = Field(default_factory=list)
