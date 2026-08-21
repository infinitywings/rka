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
PlanningCandidateDisposition = Literal["candidate", "selected", "parked"]


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

    upstream_versions: list[PlanningUpstreamVersion] | None = Field(
        default=None,
        max_length=50,
        description="Exact upstream planning heads reviewed for this version.",
    )


class PlanningUpstreamVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage_type: PlanningStage
    local_key: str = Field(min_length=1, max_length=500)
    artifact_id: str = Field(min_length=1, max_length=128)
    version_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def normalize(self):
        self.local_key = _strip(self.local_key)
        self.artifact_id = _strip(self.artifact_id)
        self.version_id = _strip(self.version_id)
        return self


class SeedPayload(_Payload):
    insight: str = Field(min_length=1, max_length=20_000)
    significance: str | None = Field(default=None, max_length=20_000)
    audience: list[str] = Field(default_factory=list, max_length=100)
    problem_signal: str | None = Field(default=None, max_length=20_000)
    mechanism_intuition: str | None = Field(default=None, max_length=20_000)
    expected_effect: str | None = Field(default=None, max_length=20_000)
    initial_boundary: list[str] | None = Field(default=None, max_length=500)
    evidence_hints: list[str] | None = Field(default=None, max_length=500)
    unresolved_questions: list[str] | None = Field(default=None, max_length=500)


class ParagraphSpinePayload(_Payload):
    problem: str = Field(min_length=1, max_length=20_000)
    gap: str = Field(min_length=1, max_length=20_000)
    insight: str = Field(min_length=1, max_length=20_000)
    response: str = Field(min_length=1, max_length=20_000)
    challenge_innovation: str | None = Field(default=None, max_length=20_000)
    evidence: str | None = Field(default=None, max_length=20_000)
    payoff: str | None = Field(default=None, max_length=20_000)


class ProblemScopePayload(_Payload):
    problem: str = Field(min_length=1, max_length=40_000)
    in_scope: list[str] = Field(default_factory=list, max_length=500)
    out_of_scope: list[str] = Field(default_factory=list, max_length=500)
    assumptions: list[str] = Field(default_factory=list, max_length=500)
    key_terms: list[str] = Field(default_factory=list, max_length=500)


class LandscapeRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_key: str = Field(min_length=1, max_length=500)
    literature_ids: list[str] = Field(default_factory=list, max_length=500)
    comparison_axis: str = Field(min_length=1, max_length=20_000)
    capability: str = Field(min_length=1, max_length=40_000)
    relevant_limitation: str | None = Field(default=None, max_length=40_000)
    limitation_status: Literal["supported", "inferred", "search_question"] = "search_question"
    candidate_gap: str | None = Field(default=None, max_length=40_000)
    novelty_risk: str | None = Field(default=None, max_length=40_000)

    @field_validator("local_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return _strip(value)


class LandscapeGapPayload(_Payload):
    state_of_the_art: list[str] = Field(default_factory=list, max_length=500)
    limitations: list[str] = Field(default_factory=list, max_length=500)
    gap: str = Field(min_length=1, max_length=40_000)
    motivation: str | None = Field(default=None, max_length=40_000)
    comparison_axes: list[str] | None = Field(default=None, max_length=500)
    rows: list[LandscapeRow] | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def unique_rows(self):
        keys = [row.local_key for row in self.rows or []]
        if len(keys) != len(set(keys)):
            raise ValueError("landscape row local_key values must be unique")
        return self


class ResponseMechanismPayload(_Payload):
    insight: str = Field(min_length=1, max_length=40_000)
    mechanism_steps: list[str] = Field(min_length=1, max_length=500)
    expected_effect: str = Field(min_length=1, max_length=40_000)
    boundary_conditions: list[str] = Field(default_factory=list, max_length=500)


class ChallengeInnovationPair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_key: str | None = Field(default=None, max_length=500)
    gap: str | None = Field(default=None, max_length=20_000)
    challenge: str = Field(min_length=1, max_length=20_000)
    design_insight: str | None = Field(default=None, max_length=20_000)
    innovation: str = Field(min_length=1, max_length=20_000)
    expected_mechanism: str | None = Field(default=None, max_length=20_000)
    required_evidence: list[str] | None = Field(default=None, max_length=500)
    observed_result: str | None = Field(default=None, max_length=20_000)
    boundary: str | None = Field(default=None, max_length=20_000)
    rejected_alternatives: list[str] | None = Field(default=None, max_length=500)
    exploration: str | None = Field(default=None, max_length=20_000)

    @field_validator("local_key")
    @classmethod
    def normalize_key(cls, value: str | None) -> str | None:
        return _strip(value) if value is not None else None


class ChallengeInnovationPayload(_Payload):
    pairs: list[ChallengeInnovationPair] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_pairs(self):
        keys = [pair.local_key for pair in self.pairs if pair.local_key]
        if len(keys) != len(set(keys)):
            raise ValueError("challenge/innovation local_key values must be unique")
        return self


class ResearchQuestionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_key: str = Field(min_length=1, max_length=500)
    question: str = Field(min_length=1, max_length=40_000)
    scope: str = Field(min_length=1, max_length=40_000)
    rationale: str = Field(min_length=1, max_length=40_000)
    assumptions: list[str] = Field(default_factory=list, max_length=500)
    evidence_entity_ids: list[str] = Field(default_factory=list, max_length=500)
    missing_evidence: list[str] = Field(default_factory=list, max_length=500)
    disposition: PlanningCandidateDisposition = "candidate"

    @field_validator("local_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return _strip(value)


class ContributionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_key: str = Field(min_length=1, max_length=500)
    exact_wording: str = Field(min_length=1, max_length=40_000)
    contribution_type: Literal[
        "empirical", "methodological", "theoretical", "survey", "position"
    ]
    research_question_refs: list[str] = Field(min_length=1, max_length=200)
    allowed_wording: str = Field(min_length=1, max_length=40_000)
    prohibited_wording: list[str] = Field(min_length=1, max_length=500)
    support_ids: list[str] = Field(default_factory=list, max_length=500)
    qualifier_ids: list[str] = Field(default_factory=list, max_length=500)
    counterevidence_ids: list[str] = Field(default_factory=list, max_length=500)
    conditions: list[str] = Field(default_factory=list, max_length=500)
    novelty_risk: str | None = Field(default=None, max_length=40_000)
    significance: str | None = Field(default=None, max_length=40_000)
    intended_units: list[str] = Field(default_factory=list, max_length=500)
    missing_evidence: list[str] = Field(default_factory=list, max_length=500)
    disposition: PlanningCandidateDisposition = "candidate"

    @field_validator("local_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return _strip(value)


class RQContributionPayload(_Payload):
    research_questions: list[str | ResearchQuestionCandidate] = Field(
        min_length=1, max_length=200
    )
    contributions: list[str | ContributionCandidate] = Field(min_length=1, max_length=200)
    claim_boundaries: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_candidates(self):
        rq_keys = [item.local_key for item in self.research_questions if not isinstance(item, str)]
        contribution_keys = [
            item.local_key for item in self.contributions if not isinstance(item, str)
        ]
        if len(rq_keys) != len(set(rq_keys)):
            raise ValueError("research-question candidate local_key values must be unique")
        if len(contribution_keys) != len(set(contribution_keys)):
            raise ValueError("contribution candidate local_key values must be unique")
        known_rqs = set(rq_keys)
        for contribution in self.contributions:
            if isinstance(contribution, str):
                continue
            unknown = [
                ref
                for ref in contribution.research_question_refs
                if not ref.startswith("dec_") and ref not in known_rqs
            ]
            if unknown:
                raise ValueError(
                    "contribution references unknown research-question candidates: "
                    + ", ".join(sorted(unknown))
                )
        return self


EvaluationRequirementKind = Literal[
    "support", "falsification", "qualifier", "validity", "exploratory"
]
EvaluationObservationRole = Literal[
    "primary", "replication", "robustness", "falsifier", "qualifier", "context"
]
EvaluationOutcome = Literal[
    "supports", "partially_supports", "fails_to_support", "inconclusive", "exploratory"
]
EvaluationClaimEffect = Literal[
    "supports_as_worded",
    "requires_narrowing",
    "negative_result",
    "exploratory_only",
    "unresolved",
]


class LegacyEvaluationCommitment(BaseModel):
    """Read-compatible pre-ADR-0008 commitment; never promotion-ready."""

    model_config = ConfigDict(extra="forbid")
    claim: str = Field(min_length=1, max_length=20_000)
    method: str = Field(min_length=1, max_length=40_000)
    evidence_needed: list[str] = Field(default_factory=list, max_length=500)
    baselines: list[str] = Field(default_factory=list, max_length=500)
    metrics: list[str] = Field(default_factory=list, max_length=500)
    success_criteria: list[str] = Field(default_factory=list, max_length=500)


class EvaluationObservationBinding(BaseModel):
    """Explicit interpretation of one exact canonical observation."""

    model_config = ConfigDict(extra="forbid")
    observation_id: str = Field(pattern=r"^obs_.+", max_length=128)
    locator_ids: list[str] = Field(min_length=1, max_length=500)
    role: EvaluationObservationRole
    outcome: EvaluationOutcome
    claim_effect: EvaluationClaimEffect
    interpretation: str = Field(min_length=1, max_length=40_000)

    @model_validator(mode="after")
    def normalize_and_validate(self):
        self.observation_id = _strip(self.observation_id)
        self.locator_ids = _strings(self.locator_ids)
        self.interpretation = _strip(self.interpretation)
        if not self.locator_ids or any(not item.startswith("elc_") for item in self.locator_ids):
            raise ValueError("observation bindings require one or more elc_ locator IDs")
        compatible = {
            "supports": {"supports_as_worded", "requires_narrowing"},
            "partially_supports": {"requires_narrowing", "supports_as_worded"},
            "fails_to_support": {"requires_narrowing", "negative_result", "unresolved"},
            "inconclusive": {"exploratory_only", "unresolved", "requires_narrowing"},
            "exploratory": {"exploratory_only", "unresolved"},
        }
        if self.claim_effect not in compatible[self.outcome]:
            raise ValueError(
                f"{self.outcome} is incompatible with claim effect {self.claim_effect}"
            )
        return self


class EvaluationEvidenceRequirement(BaseModel):
    """One stable evidence slot used to support, qualify, or falsify a claim."""

    model_config = ConfigDict(extra="forbid")
    local_key: str = Field(min_length=1, max_length=500)
    kind: EvaluationRequirementKind
    description: str = Field(min_length=1, max_length=40_000)
    required: bool = True
    experiment_id: str | None = Field(default=None, pattern=r"^exp_.+", max_length=128)
    plan_version_id: str | None = Field(default=None, pattern=r"^epv_.+", max_length=128)
    plan_version: int | None = Field(default=None, ge=1)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=500)
    failure_criteria: list[str] = Field(default_factory=list, max_length=500)
    observations: list[EvaluationObservationBinding] = Field(
        default_factory=list, max_length=1000
    )
    missing_evidence: str | None = Field(default=None, max_length=40_000)

    @model_validator(mode="after")
    def normalize_and_validate(self):
        self.local_key = _strip(self.local_key)
        self.description = _strip(self.description)
        self.experiment_id = _strip(self.experiment_id) if self.experiment_id else None
        self.plan_version_id = _strip(self.plan_version_id) if self.plan_version_id else None
        self.acceptance_criteria = _strings(self.acceptance_criteria)
        self.failure_criteria = _strings(self.failure_criteria)
        self.missing_evidence = (
            self.missing_evidence.strip() if self.missing_evidence else None
        )
        plan_fields = (self.experiment_id, self.plan_version_id, self.plan_version)
        if any(value is not None for value in plan_fields) and not all(
            value is not None for value in plan_fields
        ):
            raise ValueError(
                "experiment_id, plan_version_id, and plan_version are all-or-none"
            )
        if self.observations and self.experiment_id is None:
            raise ValueError("located observations require an exact experiment plan")
        observation_ids = [item.observation_id for item in self.observations]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("observation IDs must be unique within an evidence requirement")
        return self


class EvaluationCommitment(BaseModel):
    """Claim-centered evaluation contract introduced by ADR 0008."""

    model_config = ConfigDict(extra="forbid")
    local_key: str = Field(min_length=1, max_length=500)
    claim_id: str = Field(pattern=r"^mcl_.+", max_length=128)
    claim_version: int = Field(ge=1)
    research_question_refs: list[str] = Field(min_length=1, max_length=200)
    method: str = Field(min_length=1, max_length=40_000)
    requirements: list[EvaluationEvidenceRequirement] = Field(min_length=1, max_length=500)
    baselines: list[str] = Field(default_factory=list, max_length=500)
    metrics: list[str] = Field(default_factory=list, max_length=500)
    conditions: list[str] = Field(default_factory=list, max_length=500)
    success_criteria: list[str] = Field(default_factory=list, max_length=500)
    failure_criteria: list[str] = Field(default_factory=list, max_length=500)
    allowed_interpretation: str = Field(min_length=1, max_length=40_000)
    prohibited_interpretation: list[str] = Field(min_length=1, max_length=500)
    disposition: PlanningCandidateDisposition = "candidate"

    @model_validator(mode="after")
    def normalize_and_validate(self):
        self.local_key = _strip(self.local_key)
        self.claim_id = _strip(self.claim_id)
        self.research_question_refs = _strings(self.research_question_refs)
        self.method = _strip(self.method)
        self.baselines = _strings(self.baselines)
        self.metrics = _strings(self.metrics)
        self.conditions = _strings(self.conditions)
        self.success_criteria = _strings(self.success_criteria)
        self.failure_criteria = _strings(self.failure_criteria)
        self.allowed_interpretation = _strip(self.allowed_interpretation)
        self.prohibited_interpretation = _strings(self.prohibited_interpretation)
        if not self.research_question_refs or any(
            not item.startswith("dec_") for item in self.research_question_refs
        ):
            raise ValueError("research_question_refs must contain one or more dec_ IDs")
        if not self.prohibited_interpretation:
            raise ValueError("prohibited_interpretation must not be empty")
        requirement_keys = [item.local_key for item in self.requirements]
        if len(requirement_keys) != len(set(requirement_keys)):
            raise ValueError("evaluation requirement local_key values must be unique")
        return self


class EvaluationPayload(_Payload):
    commitments: list[LegacyEvaluationCommitment | EvaluationCommitment] = Field(
        min_length=1, max_length=200
    )
    validity_checks: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_commitments(self):
        keys = [
            item.local_key for item in self.commitments if isinstance(item, EvaluationCommitment)
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("evaluation commitment local_key values must be unique")
        exact_claims = [
            (item.claim_id, item.claim_version)
            for item in self.commitments
            if isinstance(item, EvaluationCommitment)
        ]
        if len(exact_claims) != len(set(exact_claims)):
            raise ValueError("an exact claim version may have only one evaluation commitment")
        self.validity_checks = _strings(self.validity_checks)
        return self


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
        bound_ids = {binding.entity_id for binding in self.evidence_bindings}
        referenced_ids: set[str] = set()
        if self.stage_type == "landscape_gap":
            for row in self.payload.get("rows", []):
                referenced_ids.update(row.get("literature_ids", []))
        if self.stage_type == "rq_contribution":
            for rq in self.payload.get("research_questions", []):
                if isinstance(rq, dict):
                    referenced_ids.update(rq.get("evidence_entity_ids", []))
            for contribution in self.payload.get("contributions", []):
                if not isinstance(contribution, dict):
                    continue
                referenced_ids.update(contribution.get("support_ids", []))
                referenced_ids.update(contribution.get("qualifier_ids", []))
                referenced_ids.update(contribution.get("counterevidence_ids", []))
                referenced_ids.update(
                    ref
                    for ref in contribution.get("research_question_refs", [])
                    if ref.startswith("dec_")
                )
        if self.stage_type == "evaluation":
            for commitment in self.payload.get("commitments", []):
                if not isinstance(commitment, dict) or "local_key" not in commitment:
                    continue
                referenced_ids.add(commitment["claim_id"])
                referenced_ids.update(commitment.get("research_question_refs", []))
                for requirement in commitment.get("requirements", []):
                    if requirement.get("experiment_id"):
                        referenced_ids.add(requirement["experiment_id"])
                    if requirement.get("plan_version_id"):
                        referenced_ids.add(requirement["plan_version_id"])
                    for observation in requirement.get("observations", []):
                        referenced_ids.add(observation["observation_id"])
                        referenced_ids.update(observation.get("locator_ids", []))
        undisclosed = sorted(referenced_ids - bound_ids)
        if undisclosed:
            raise ValueError(
                "planning payload references entities absent from evidence bindings: "
                + ", ".join(undisclosed)
            )
        return self


class PlanningResearchQuestionPromotion(BaseModel):
    """Explicitly promote one selected RQ candidate into a PI decision."""

    model_config = ConfigDict(extra="forbid")
    expected_branch_revision: int = Field(ge=1)
    artifact_id: str = Field(min_length=1, max_length=128)
    expected_artifact_version: int = Field(ge=1)
    candidate_key: str = Field(min_length=1, max_length=500)
    phase: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=10_000)
    confirmed_by: Literal["pi"] = "pi"

    @model_validator(mode="after")
    def normalize(self):
        self.artifact_id = _strip(self.artifact_id)
        self.candidate_key = _strip(self.candidate_key)
        self.phase = _strip(self.phase)
        self.reason = _strip(self.reason)
        return self


class PlanningContributionProposalPrepare(BaseModel):
    """Prepare, but never apply, one selected contribution candidate."""

    model_config = ConfigDict(extra="forbid")
    expected_branch_revision: int = Field(ge=1)
    artifact_id: str = Field(min_length=1, max_length=128)
    expected_artifact_version: int = Field(ge=1)
    candidate_key: str = Field(min_length=1, max_length=500)
    manuscript_id: str = Field(min_length=1, max_length=128)
    expected_manuscript_revision: int = Field(ge=1)
    claim_local_key: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=1, max_length=10_000)
    actor: Literal["pi", "brain", "executor", "web_ui"] = "web_ui"

    @model_validator(mode="after")
    def normalize(self):
        self.artifact_id = _strip(self.artifact_id)
        self.candidate_key = _strip(self.candidate_key)
        self.manuscript_id = _strip(self.manuscript_id)
        self.claim_local_key = _strip(self.claim_local_key) if self.claim_local_key else None
        self.reason = _strip(self.reason)
        return self


class PlanningContributionRatification(BaseModel):
    """Bind an applied candidate wording to one exact active PI decision."""

    model_config = ConfigDict(extra="forbid")
    expected_branch_revision: int = Field(ge=1)
    artifact_id: str = Field(min_length=1, max_length=128)
    expected_artifact_version: int = Field(ge=1)
    candidate_key: str = Field(min_length=1, max_length=500)
    manuscript_id: str = Field(min_length=1, max_length=128)
    claim_ref: str = Field(min_length=1, max_length=500)
    expected_manuscript_revision: int = Field(ge=1)
    proposal_id: str = Field(min_length=1, max_length=128)
    decision_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=10_000)
    confirmed_by: Literal["pi"] = "pi"

    @model_validator(mode="after")
    def normalize(self):
        self.artifact_id = _strip(self.artifact_id)
        self.candidate_key = _strip(self.candidate_key)
        self.manuscript_id = _strip(self.manuscript_id)
        self.claim_ref = _strip(self.claim_ref)
        self.proposal_id = _strip(self.proposal_id)
        self.decision_id = _strip(self.decision_id)
        self.reason = _strip(self.reason)
        return self


class PlanningEvaluationMissionCreate(BaseModel):
    """Create one canonical missing-evidence mission from an exact contract version."""

    model_config = ConfigDict(extra="forbid")
    expected_branch_revision: int = Field(ge=1)
    artifact_id: str = Field(min_length=1, max_length=128)
    expected_artifact_version: int = Field(ge=1)
    commitment_key: str = Field(min_length=1, max_length=500)
    requirement_key: str = Field(min_length=1, max_length=500)
    phase: str = Field(default="evaluation", min_length=1, max_length=500)
    motivated_by_decision: str | None = Field(default=None, max_length=128)
    reason: str = Field(min_length=1, max_length=10_000)
    actor: Literal["pi", "brain", "executor", "web_ui"] = "web_ui"

    @model_validator(mode="after")
    def normalize(self):
        for field_name in (
            "artifact_id", "commitment_key", "requirement_key", "phase", "reason"
        ):
            setattr(self, field_name, _strip(getattr(self, field_name)))
        self.motivated_by_decision = (
            _strip(self.motivated_by_decision) if self.motivated_by_decision else None
        )
        return self


class PlanningEvaluationResultProposalPrepare(BaseModel):
    """Prepare, but never apply, one native result-unit proposal."""

    model_config = ConfigDict(extra="forbid")
    expected_branch_revision: int = Field(ge=1)
    artifact_id: str = Field(min_length=1, max_length=128)
    expected_artifact_version: int = Field(ge=1)
    commitment_key: str = Field(min_length=1, max_length=500)
    manuscript_id: str = Field(min_length=1, max_length=128)
    expected_manuscript_revision: int = Field(ge=1)
    result_unit_local_key: str = Field(min_length=1, max_length=500)
    location: str = Field(min_length=1, max_length=4000)
    title: str = Field(min_length=1, max_length=1000)
    artifact_ref: str = Field(pattern=r"^(art|fig)_.+", max_length=128)
    reason: str = Field(min_length=1, max_length=10_000)
    actor: Literal["pi", "brain", "executor", "web_ui"] = "web_ui"

    @model_validator(mode="after")
    def normalize(self):
        for field_name in (
            "artifact_id",
            "commitment_key",
            "manuscript_id",
            "result_unit_local_key",
            "location",
            "title",
            "artifact_ref",
            "reason",
        ):
            setattr(self, field_name, _strip(getattr(self, field_name)))
        return self


def parse_json_field(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        return json.loads(value)
    return value
