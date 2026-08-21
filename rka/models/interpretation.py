"""Typed Interpretation Staging models.

Candidates separate source interpretation from canonical claim promotion.
They are intentionally project-scoped and revision guarded.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rka.models.claim import ClaimType


InterpretationSourceType = Literal[
    "journal", "literature", "artifact", "experiment_observation"
]
LocatorKind = Literal[
    "text_offset", "page", "line_range", "section", "url_fragment", "record"
]
EpistemicKind = Literal[
    "observation", "reported_fact", "inference", "hypothesis", "plan", "author_intent"
]
UncertaintyLevel = Literal["none", "low", "medium", "high", "unknown"]
InterpretationActor = Literal["pi", "brain", "executor", "web_ui", "llm", "import"]
ReviewActor = Literal["pi", "brain", "executor", "web_ui"]
ReviewStatus = Literal["pending", "in_review", "resolved"]
CandidateDisposition = Literal[
    "promoted",
    "merged",
    "deferred",
    "rejected",
    "classified_decision",
    "classified_plan",
    "classified_author_intent",
    "evidence_mission_requested",
    "classified_evidence",
]
HintKind = Literal["duplicate", "conflict"]
TriageAction = Literal[
    "start_review",
    "promote",
    "merge",
    "defer",
    "reject",
    "classify_decision",
    "classify_plan",
    "classify_author_intent",
    "request_evidence_mission",
    "reopen",
    "revoke_promotion",
    "classify_evidence",
    "revoke_evidence",
]
EvidenceRole = Literal["support", "qualifier", "counterevidence", "context"]


class InterpretationCandidateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: InterpretationSourceType
    source_id: str = Field(min_length=1, max_length=128)
    locator_kind: LocatorKind
    locator_start: int | None = Field(default=None, ge=0)
    locator_end: int | None = Field(default=None, ge=0)
    locator_value: str | None = Field(default=None, max_length=2048)
    statement: str = Field(min_length=1, max_length=20_000)
    epistemic_kind: EpistemicKind
    scope_conditions: list[str] = Field(default_factory=list, max_length=100)
    uncertainty: UncertaintyLevel = "unknown"
    uncertainty_note: str | None = Field(default=None, max_length=4000)
    falsifier: str | None = Field(default=None, max_length=10_000)
    proposed_claim_type: ClaimType | None = None
    created_by: InterpretationActor
    extraction_tool: str = Field(min_length=1, max_length=256)
    extraction_model: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_locator(self) -> "InterpretationCandidateCreate":
        numeric = {"text_offset", "page", "line_range"}
        textual = {"section", "url_fragment", "record"}
        if self.locator_kind in numeric:
            if self.locator_start is None:
                raise ValueError(f"{self.locator_kind} requires locator_start")
            if self.locator_end is not None and self.locator_end < self.locator_start:
                raise ValueError("locator_end must be greater than or equal to locator_start")
        elif self.locator_kind in textual:
            if not self.locator_value or not self.locator_value.strip():
                raise ValueError(f"{self.locator_kind} requires locator_value")
        return self

    @model_validator(mode="after")
    def normalize_strings(self) -> "InterpretationCandidateCreate":
        self.source_id = self.source_id.strip()
        self.statement = self.statement.strip()
        self.extraction_tool = self.extraction_tool.strip()
        if self.locator_value is not None:
            self.locator_value = self.locator_value.strip()
        self.scope_conditions = [item.strip() for item in self.scope_conditions if item.strip()]
        return self


class InterpretationCandidate(BaseModel):
    id: str
    project_id: str
    source_type: str
    source_id: str
    locator_kind: str
    locator_start: int | None = None
    locator_end: int | None = None
    locator_value: str | None = None
    statement: str
    epistemic_kind: str
    scope_conditions: list[str] = Field(default_factory=list)
    uncertainty: str
    uncertainty_note: str | None = None
    falsifier: str | None = None
    proposed_claim_type: str | None = None
    created_by: str
    extraction_tool: str
    extraction_model: str | None = None
    review_status: str
    disposition: str | None = None
    disposition_reason: str | None = None
    disposition_target_type: str | None = None
    disposition_target_id: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    revision: int
    duplicate_hint_count: int = 0
    conflict_hint_count: int = 0
    active_claim_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class InterpretationHintCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    related_candidate_id: str = Field(min_length=1, max_length=128)
    kind: HintKind
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=10_000)
    created_by: InterpretationActor
    expected_revision: int = Field(ge=1)


class InterpretationHint(BaseModel):
    id: str
    project_id: str
    candidate_id: str
    related_candidate_id: str
    kind: str
    confidence: float
    rationale: str
    created_by: str
    created_at: str | None = None


class InterpretationTriage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: TriageAction
    expected_revision: int = Field(ge=1)
    actor: ReviewActor
    reason: str | None = Field(default=None, max_length=10_000)
    target_candidate_id: str | None = Field(default=None, max_length=128)
    target_entity_id: str | None = Field(default=None, max_length=128)
    evidence_role: EvidenceRole | None = None
    grounding_verified: bool = False
    claim_confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "InterpretationTriage":
        if self.action != "start_review":
            if not self.reason or not self.reason.strip():
                raise ValueError(f"{self.action} requires reason")
            self.reason = self.reason.strip()
        if self.action == "merge" and not self.target_candidate_id:
            raise ValueError("merge requires target_candidate_id")
        if self.action == "promote" and not self.grounding_verified:
            raise ValueError("promote requires grounding_verified=true")
        if self.action == "classify_evidence":
            if not self.target_entity_id:
                raise ValueError("classify_evidence requires target_entity_id (claim id)")
            if self.evidence_role is None:
                raise ValueError("classify_evidence requires evidence_role")
        elif self.evidence_role is not None:
            raise ValueError("evidence_role is only valid for classify_evidence")
        return self


class InterpretationReviewEvent(BaseModel):
    id: str
    project_id: str
    candidate_id: str
    action: str
    from_status: str | None = None
    to_status: str
    disposition: str | None = None
    actor: str
    reason: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    candidate_revision: int
    created_at: str | None = None


class InterpretationPromotion(BaseModel):
    id: str
    project_id: str
    candidate_id: str
    claim_id: str
    status: str
    promoted_by: str
    promotion_reason: str
    promoted_at: str | None = None
    revoked_by: str | None = None
    revocation_reason: str | None = None
    revoked_at: str | None = None


class InterpretationCandidateDetail(InterpretationCandidate):
    hints: list[InterpretationHint] = Field(default_factory=list)
    review_events: list[InterpretationReviewEvent] = Field(default_factory=list)
    promotions: list[InterpretationPromotion] = Field(default_factory=list)
