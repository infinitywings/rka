"""Pydantic models for the v2.2 decision_options table (migration 017).

These mirror the schema CHECK constraints so Pydantic fails fast at the API
boundary (HTTP 422) before the DB rejects the row (HTTP 500 from SQLite).

Not to be confused with the legacy ``rka.models.decision.DecisionOption`` which
describes the pre-v2.2 nested ``options`` JSON shape (label / description /
explored). The v2.2 rich model here lives in its own module to avoid symbol
collision.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ConfidenceVerbal = Literal["low", "moderate", "high"]
# EvidenceStrength describes the option's aggregate evidence-quality assessment.
EvidenceStrength = Literal["weak", "moderate", "strong"]
# EvidenceRefStrength is the per-pointer relationship strength between an
# individual claim and the option. Semantically distinct from the aggregate
# quality assessment — a set of "direct" refs can still total to "moderate"
# aggregate strength if the claims are weak individually.
EvidenceRefStrength = Literal["direct", "indirect", "weak"]
EffortTime = Literal["S", "M", "L", "XL"]
EffortReversibility = Literal["reversible", "costly", "irreversible"]


class EvidenceRef(BaseModel):
    """One evidence pointer attached to a decision option.

    Shape formalized in Mission 1B-ii per jrn_01KPEQ57WBXEJC6QV2RSJVDZZ1 Q2.
    Schema stores a list of these as a JSON array in
    ``decision_options.evidence``.

    - ``claim_id``: the referenced claim.
    - ``strength_tier``: how directly the claim supports the option's case.
      ``direct`` = the claim is the core evidence; ``indirect`` = supportive but
      not decisive; ``weak`` = mentioned for completeness.
    - ``weight``: optional fine-grained score in [0, 1]. Used by future
      calibration features; may be None during current Brain workflows.
    """

    claim_id: str
    strength_tier: EvidenceRefStrength
    weight: float | None = None


class DecisionOptionCreate(BaseModel):
    """Create payload for a decision option.

    Validators mirror the SQLite CHECK constraints in migration 017 so input
    errors surface as 422 from the API boundary rather than 500 from the DB.
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    summary: str
    justification: str
    expert_archetype: str | None = None
    explanation: str
    pros: list[str] = Field(..., min_length=3, max_length=3)
    cons: list[str] = Field(..., min_length=3, max_length=3)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    confidence_verbal: ConfidenceVerbal
    confidence_numeric: float = Field(..., ge=0.0, le=1.0)
    confidence_evidence_strength: EvidenceStrength
    confidence_known_unknowns: list[str] = Field(..., min_length=1, max_length=2)
    effort_time: EffortTime
    effort_cost: str | None = None
    effort_reversibility: EffortReversibility
    presentation_order_seed: int

    @field_validator("pros", "cons")
    @classmethod
    def _require_three_non_empty(cls, value: list[str]) -> list[str]:
        if any(not entry or not entry.strip() for entry in value):
            raise ValueError("entries must be non-empty")
        return value

    @field_validator("confidence_known_unknowns")
    @classmethod
    def _require_non_empty_unknowns(cls, value: list[str]) -> list[str]:
        if any(not entry or not entry.strip() for entry in value):
            raise ValueError("known_unknowns entries must be non-empty")
        return value


class DecisionOption(BaseModel):
    """Full decision_options row — all 22 columns."""

    model_config = ConfigDict(extra="forbid")

    id: str
    decision_id: str
    project_id: str
    label: str
    summary: str
    justification: str
    expert_archetype: str | None = None
    explanation: str
    pros: list[str]
    cons: list[str]
    evidence: list[EvidenceRef]
    confidence_verbal: ConfidenceVerbal
    confidence_numeric: float
    confidence_evidence_strength: EvidenceStrength
    confidence_known_unknowns: list[str]
    effort_time: EffortTime
    effort_cost: str | None = None
    effort_reversibility: EffortReversibility
    dominated_by: str | None = None
    presentation_order_seed: int
    is_recommended: bool = False
    created_at: str


class PiSelectionPayload(BaseModel):
    """Input to record_pi_selection — exactly one of the two fields must be set.

    The exclusivity is enforced by the service (which understands the decision
    context). Pydantic here only accepts the shape; the XOR check lives in
    DecisionOptionsService.record_pi_selection so the resulting ValueError
    surfaces with a clear message and consistent exception type.
    """

    model_config = ConfigDict(extra="forbid")

    selected_option_id: str | None = None
    override_rationale: str | None = None


class DominatedByPayload(BaseModel):
    """Input to set_dominated_by endpoint."""

    model_config = ConfigDict(extra="forbid")

    dominator_id: str | None = None
