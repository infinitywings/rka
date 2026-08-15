"""Typed provisional manuscript-planning branches and artifacts."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PlanningActor = Literal["pi", "brain", "executor", "web_ui", "llm", "import"]
PlanningBranchState = Literal["active", "selected", "archived", "superseded"]
PlanningStage = Literal[
    "seed",
    "paragraph_spine",
    "problem_scope",
    "landscape_gap",
    "response_mechanism",
    "challenge_innovation",
    "rq_contribution",
    "evaluation",
    "outline",
    "review",
]
PlanningLifecycle = Literal["candidate", "reviewed", "selected", "parked", "superseded", "archived"]
PlanningOrigin = Literal["user", "ai_suggested", "imported", "user_revised"]
PlanningReadiness = Literal["blocked", "in_progress", "ready"]
PlanningEvidenceRole = Literal[
    "support", "qualifier", "counterevidence", "context", "inspiration", "unresolved"
]
PlanningEntityType = Literal[
    "journal",
    "literature",
    "decision",
    "claim",
    "claim_scope",
    "cluster",
    "interpretation_candidate",
    "experiment",
    "experiment_plan_version",
    "experiment_run",
    "experiment_observation",
    "evidence_locator",
    "artifact",
    "manuscript",
    "manuscript_claim",
    "manuscript_unit",
]
PlanningLocatorKind = Literal[
    "whole_entity",
    "page",
    "line_range",
    "table",
    "table_cell",
    "json_pointer",
    "notebook_cell",
    "record",
    "section",
    "quote",
]


def _strip(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value must not be blank")
    return value


def _strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeedPayload(_Payload):
    insight: str = Field(min_length=1, max_length=20_000)
    significance: str | None = Field(default=None, max_length=20_000)
    audience: list[str] = Field(default_factory=list, max_length=100)


class ParagraphSpinePayload(_Payload):
    problem: str = Field(min_length=1, max_length=20_000)
    gap: str = Field(min_length=1, max_length=20_000)
    insight: str = Field(min_length=1, max_length=20_000)
    response: str = Field(min_length=1, max_length=20_000)
    evidence: str | None = Field(default=None, max_length=20_000)
    payoff: str | None = Field(default=None, max_length=20_000)


class ProblemScopePayload(_Payload):
    problem: str = Field(min_length=1, max_length=40_000)
    in_scope: list[str] = Field(default_factory=list, max_length=500)
    out_of_scope: list[str] = Field(default_factory=list, max_length=500)
    assumptions: list[str] = Field(default_factory=list, max_length=500)
    key_terms: list[str] = Field(default_factory=list, max_length=500)


class LandscapeGapPayload(_Payload):
    state_of_the_art: list[str] = Field(default_factory=list, max_length=500)
    limitations: list[str] = Field(default_factory=list, max_length=500)
    gap: str = Field(min_length=1, max_length=40_000)
    motivation: str | None = Field(default=None, max_length=40_000)


class ResponseMechanismPayload(_Payload):
    insight: str = Field(min_length=1, max_length=40_000)
    mechanism_steps: list[str] = Field(min_length=1, max_length=500)
    expected_effect: str = Field(min_length=1, max_length=40_000)
    boundary_conditions: list[str] = Field(default_factory=list, max_length=500)


class ChallengeInnovationPair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge: str = Field(min_length=1, max_length=20_000)
    innovation: str = Field(min_length=1, max_length=20_000)
    exploration: str | None = Field(default=None, max_length=20_000)


class ChallengeInnovationPayload(_Payload):
    pairs: list[ChallengeInnovationPair] = Field(min_length=1, max_length=200)


class RQContributionPayload(_Payload):
    research_questions: list[str] = Field(min_length=1, max_length=200)
    contributions: list[str] = Field(min_length=1, max_length=200)
    claim_boundaries: list[str] = Field(default_factory=list, max_length=500)


class EvaluationCommitment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str = Field(min_length=1, max_length=20_000)
    method: str = Field(min_length=1, max_length=40_000)
    evidence_needed: list[str] = Field(default_factory=list, max_length=500)
    baselines: list[str] = Field(default_factory=list, max_length=500)
    metrics: list[str] = Field(default_factory=list, max_length=500)
    success_criteria: list[str] = Field(default_factory=list, max_length=500)


class EvaluationPayload(_Payload):
    commitments: list[EvaluationCommitment] = Field(min_length=1, max_length=200)
    validity_checks: list[str] = Field(default_factory=list, max_length=500)


class OutlineNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_key: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=1000)
    purpose: str = Field(min_length=1, max_length=20_000)
    intended_claims: list[str] = Field(default_factory=list, max_length=500)
    evidence_plan: list[str] = Field(default_factory=list, max_length=500)
    parent_key: str | None = Field(default=None, max_length=200)
    sequence: int = Field(default=0, ge=0)


class OutlinePayload(_Payload):
    units: list[OutlineNode] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_tree(self):
        keys = [unit.local_key.strip() for unit in self.units]
        if len(keys) != len(set(keys)):
            raise ValueError("outline unit local_key values must be unique")
        known = set(keys)
        for unit in self.units:
            if unit.parent_key is not None and unit.parent_key not in known:
                raise ValueError(f"outline parent_key {unit.parent_key!r} is unknown")
            if unit.parent_key == unit.local_key:
                raise ValueError("outline unit cannot be its own parent")
        return self


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["note", "minor", "major", "blocking"]
    finding: str = Field(min_length=1, max_length=20_000)
    action: str | None = Field(default=None, max_length=20_000)


class ReviewPayload(_Payload):
    focus: str = Field(min_length=1, max_length=20_000)
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=1000)


_PAYLOAD_MODELS: dict[str, type[_Payload]] = {
    "seed": SeedPayload,
    "paragraph_spine": ParagraphSpinePayload,
    "problem_scope": ProblemScopePayload,
    "landscape_gap": LandscapeGapPayload,
    "response_mechanism": ResponseMechanismPayload,
    "challenge_innovation": ChallengeInnovationPayload,
    "rq_contribution": RQContributionPayload,
    "evaluation": EvaluationPayload,
    "outline": OutlinePayload,
    "review": ReviewPayload,
}


def validate_planning_payload(stage_type: str, payload: Any) -> dict[str, Any]:
    """Validate and normalize a payload against its closed stage schema."""
    model = _PAYLOAD_MODELS.get(stage_type)
    if model is None:
        raise ValueError(f"unsupported planning stage {stage_type!r}")
    return model.model_validate(payload).model_dump(exclude_none=True)


class PlanningBranchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manuscript_id: str | None = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=500)
    purpose: str = Field(min_length=1, max_length=20_000)
    parent_branch_id: str | None = Field(default=None, max_length=128)
    created_by: PlanningActor
    reason: str = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def normalize(self):
        self.manuscript_id = self.manuscript_id.strip() if self.manuscript_id else None
        self.name = _strip(self.name)
        self.purpose = _strip(self.purpose)
        self.parent_branch_id = self.parent_branch_id.strip() if self.parent_branch_id else None
        self.reason = _strip(self.reason)
        return self


class PlanningBranchTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    target_state: PlanningBranchState
    actor: PlanningActor
    reason: str = Field(min_length=1, max_length=10_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return _strip(value)


class PlanningEvidenceBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: PlanningEntityType
    entity_id: str = Field(min_length=1, max_length=128)
    role: PlanningEvidenceRole
    source_version: str | None = Field(default=None, max_length=200)
    locator_kind: PlanningLocatorKind | None = None
    locator_value: str | None = Field(default=None, max_length=20_000)
    locator_start: int | None = Field(default=None, ge=0)
    locator_end: int | None = Field(default=None, ge=0)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    ordinal: int = Field(default=0, ge=0)
    note: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def validate_locator(self):
        self.entity_id = _strip(self.entity_id)
        self.source_version = self.source_version.strip() if self.source_version else None
        self.locator_value = self.locator_value.strip() if self.locator_value else None
        self.note = self.note.strip() if self.note else None
        locator_values = (self.locator_value, self.locator_start, self.locator_end)
        if self.locator_kind is None and any(value is not None for value in locator_values):
            raise ValueError("locator_kind is required when locator fields are present")
        if self.locator_kind is not None and self.locator_value is None:
            raise ValueError("locator_value is required with locator_kind")
        if (
            self.locator_start is not None
            and self.locator_end is not None
            and self.locator_end < self.locator_start
        ):
            raise ValueError("locator_end must be greater than or equal to locator_start")
        return self


class PlanningArtifactVersionAppend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_branch_revision: int = Field(ge=1)
    expected_previous_version: int = Field(default=0, ge=0)
    local_key: str = Field(min_length=1, max_length=500)
    stage_type: PlanningStage
    lifecycle: PlanningLifecycle = "candidate"
    summary: str = Field(min_length=1, max_length=20_000)
    payload: dict[str, Any]
    origin: PlanningOrigin
    provider: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=500)
    context_hash: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    unresolved_items: list[str] = Field(default_factory=list, max_length=1000)
    readiness_state: PlanningReadiness = "in_progress"
    readiness_missing: list[str] = Field(default_factory=list, max_length=1000)
    readiness_notes: str | None = Field(default=None, max_length=20_000)
    promotion_target_type: (
        Literal["manuscript", "manuscript_claim", "manuscript_unit", "experiment", "decision"]
        | None
    ) = None
    promotion_target_id: str | None = Field(default=None, max_length=128)
    created_by: PlanningActor
    reason: str = Field(min_length=1, max_length=10_000)
    evidence_bindings: list[PlanningEvidenceBindingInput] = Field(
        default_factory=list, max_length=2000
    )

    @model_validator(mode="after")
    def normalize_and_validate(self):
        self.local_key = _strip(self.local_key)
        self.summary = _strip(self.summary)
        self.reason = _strip(self.reason)
        self.provider = self.provider.strip() if self.provider else None
        self.model = self.model.strip() if self.model else None
        self.readiness_notes = self.readiness_notes.strip() if self.readiness_notes else None
        self.promotion_target_id = (
            self.promotion_target_id.strip() if self.promotion_target_id else None
        )
        self.unresolved_items = _strings(self.unresolved_items)
        self.readiness_missing = _strings(self.readiness_missing)
        if self.origin == "ai_suggested" and not all(
            (self.provider, self.model, self.context_hash)
        ):
            raise ValueError("ai_suggested versions require provider, model, and context_hash")
        if (self.promotion_target_type is None) != (self.promotion_target_id is None):
            raise ValueError("promotion target type and id are all-or-none")
        self.payload = validate_planning_payload(self.stage_type, self.payload)
        return self


def parse_json_field(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        return json.loads(value)
    return value
