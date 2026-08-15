"""Typed experiment, run, observation, and evidence-locator models."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ExperimentActor = Literal["pi", "brain", "executor", "web_ui", "llm", "import"]
ExperimentReviewActor = Literal["pi", "brain", "executor", "web_ui"]
ExperimentStatus = Literal["planned", "active", "completed", "abandoned"]
WorkingTreeState = Literal["clean", "dirty", "unknown"]
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
RunAction = Literal["start", "succeed", "fail", "cancel"]
RunKind = Literal["local", "docker", "cluster", "manual", "import"]
ObservationKind = Literal[
    "metric", "comparison", "test", "qualitative", "failure", "artifact"
]
ObservationDirection = Literal[
    "positive", "negative", "inconclusive", "neutral", "error"
]
EvidenceSourceKind = Literal["artifact", "repository"]
EvidenceLocatorKind = Literal[
    "whole_artifact",
    "page",
    "line_range",
    "table",
    "table_cell",
    "json_pointer",
    "notebook_cell",
    "record",
]
ClaimEvidenceRole = Literal["support", "qualifier", "counterevidence", "context"]

_HEX_RE = re.compile(r"[0-9a-fA-F]{7,64}\Z")
_HASH_RE = re.compile(r"[0-9a-fA-F]{64}\Z")


def _strip_optional(value: str | None) -> str | None:
    return value.strip() or None if isinstance(value, str) else value


def _normalize_string_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


class RepositorySnapshotMixin(BaseModel):
    """Shared all-or-none immutable repository snapshot."""

    repository_url: str | None = Field(default=None, max_length=2048)
    commit_sha: str | None = Field(default=None, max_length=64)
    working_tree_state: WorkingTreeState | None = None

    @model_validator(mode="after")
    def validate_repository_snapshot(self):
        self.repository_url = _strip_optional(self.repository_url)
        self.commit_sha = _strip_optional(self.commit_sha)
        values = (self.repository_url, self.commit_sha, self.working_tree_state)
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError(
                "repository_url, commit_sha, and working_tree_state are all-or-none"
            )
        if self.repository_url:
            parsed = urlparse(self.repository_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("repository_url must be an absolute HTTPS URL")
        if self.commit_sha and not _HEX_RE.fullmatch(self.commit_sha):
            raise ValueError("commit_sha must be 7 to 64 hexadecimal characters")
        return self


class ExperimentPlanFields(RepositorySnapshotMixin):
    """Exact, immutable experiment-plan content."""

    objective: str = Field(min_length=1, max_length=20_000)
    hypothesis: str | None = Field(default=None, max_length=20_000)
    protocol: str = Field(min_length=1, max_length=100_000)
    conditions: list[str] = Field(default_factory=list, max_length=500)
    variables: list[str] = Field(default_factory=list, max_length=500)
    metrics: list[str] = Field(default_factory=list, max_length=500)
    baselines: list[str] = Field(default_factory=list, max_length=500)
    success_criteria: list[str] = Field(default_factory=list, max_length=500)
    failure_criteria: list[str] = Field(default_factory=list, max_length=500)

    @field_validator(
        "conditions",
        "variables",
        "metrics",
        "baselines",
        "success_criteria",
        "failure_criteria",
        mode="after",
    )
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return _normalize_string_list(values)

    @model_validator(mode="after")
    def normalize_plan_text(self):
        self.objective = self.objective.strip()
        self.protocol = self.protocol.strip()
        self.hypothesis = _strip_optional(self.hypothesis)
        return self


class ExperimentCreate(ExperimentPlanFields):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=1000)
    created_by: ExperimentActor
    reason: str = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def normalize_create(self):
        self.title = self.title.strip()
        self.reason = self.reason.strip()
        return self


class ExperimentPlanAppend(ExperimentPlanFields):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    created_by: ExperimentActor
    reason: str = Field(min_length=1, max_length=10_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return value.strip()


class ExperimentTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    target_status: ExperimentStatus
    actor: ExperimentActor
    reason: str = Field(min_length=1, max_length=10_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return value.strip()


class ExperimentPlanVersion(BaseModel):
    id: str
    experiment_id: str
    project_id: str
    version: int
    objective: str
    hypothesis: str | None = None
    protocol: str
    conditions: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    baselines: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    failure_criteria: list[str] = Field(default_factory=list)
    repository_url: str | None = None
    commit_sha: str | None = None
    working_tree_state: str | None = None
    created_by: str
    reason: str
    supersedes_plan_id: str | None = None
    created_at: str


class Experiment(BaseModel):
    id: str
    project_id: str
    title: str
    status: ExperimentStatus
    current_plan_version: int
    revision: int
    created_by: str
    created_at: str
    updated_at: str


class ExperimentDetail(Experiment):
    current_plan: ExperimentPlanVersion
    plan_versions: list[ExperimentPlanVersion] = Field(default_factory=list)
    runs: list["ExperimentRun"] = Field(default_factory=list)


class ExperimentRunCreate(RepositorySnapshotMixin):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(min_length=1, max_length=128)
    plan_version: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=1000)
    runner: RunKind
    command: str | None = Field(default=None, max_length=100_000)
    config: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)
    created_by: ExperimentActor
    reason: str = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def normalize_run(self):
        self.experiment_id = self.experiment_id.strip()
        self.label = self.label.strip()
        self.command = _strip_optional(self.command)
        self.reason = self.reason.strip()
        return self


class ExperimentRunTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    action: RunAction
    actor: ExperimentActor
    reason: str = Field(min_length=1, max_length=10_000)
    started_at: str | None = None
    completed_at: str | None = None
    exit_code: int | None = None
    failure_summary: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def validate_transition_fields(self):
        self.reason = self.reason.strip()
        self.failure_summary = _strip_optional(self.failure_summary)
        if self.action == "fail" and not self.failure_summary:
            raise ValueError("fail requires failure_summary")
        if self.action == "start" and any(
            value is not None
            for value in (self.completed_at, self.exit_code, self.failure_summary)
        ):
            raise ValueError(
                "start cannot set completed_at, exit_code, or failure_summary"
            )
        return self


class ExperimentRun(BaseModel):
    id: str
    experiment_id: str
    project_id: str
    plan_version: int
    label: str
    runner: str
    command: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)
    repository_url: str | None = None
    commit_sha: str | None = None
    working_tree_state: str | None = None
    status: RunStatus
    started_at: str | None = None
    completed_at: str | None = None
    exit_code: int | None = None
    failure_summary: str | None = None
    revision: int
    created_by: str
    created_at: str
    updated_at: str


class ExperimentRunEvent(BaseModel):
    id: str
    run_id: str
    project_id: str
    action: str
    from_status: str | None = None
    to_status: str
    run_revision: int
    actor: str
    reason: str
    exit_code: int | None = None
    created_at: str


class ExperimentRunDetail(ExperimentRun):
    events: list[ExperimentRunEvent] = Field(default_factory=list)
    observations: list["ExperimentObservation"] = Field(default_factory=list)


class ExperimentObservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=1000)
    kind: ObservationKind
    direction: ObservationDirection
    summary: str = Field(min_length=1, max_length=50_000)
    value_real: float | None = None
    value_text: str | None = Field(default=None, max_length=100_000)
    unit: str | None = Field(default=None, max_length=256)
    sample_size: int | None = Field(default=None, ge=0)
    uncertainty_note: str | None = Field(default=None, max_length=20_000)
    observed_at: str
    recorded_by: ExperimentActor

    @model_validator(mode="after")
    def validate_value(self):
        self.run_id = self.run_id.strip()
        self.name = self.name.strip()
        self.summary = self.summary.strip()
        self.value_text = _strip_optional(self.value_text)
        self.unit = _strip_optional(self.unit)
        self.uncertainty_note = _strip_optional(self.uncertainty_note)
        self.observed_at = self.observed_at.strip()
        if self.value_real is not None and self.value_text is not None:
            raise ValueError("provide at most one of value_real and value_text")
        if self.kind in {"metric", "comparison", "test"} and (
            self.value_real is None and self.value_text is None
        ):
            raise ValueError(f"{self.kind} requires value_real or value_text")
        if self.kind in {"qualitative", "failure"} and self.value_text is None:
            raise ValueError(f"{self.kind} requires value_text")
        return self


class ExperimentObservation(BaseModel):
    id: str
    run_id: str
    project_id: str
    name: str
    kind: ObservationKind
    direction: ObservationDirection
    summary: str
    value_real: float | None = None
    value_text: str | None = None
    unit: str | None = None
    sample_size: int | None = None
    uncertainty_note: str | None = None
    observed_at: str
    recorded_by: str
    created_at: str


class EvidenceLocatorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=1, max_length=128)
    source_kind: EvidenceSourceKind
    artifact_id: str | None = Field(default=None, max_length=128)
    repository_url: str | None = Field(default=None, max_length=2048)
    commit_sha: str | None = Field(default=None, max_length=64)
    relative_path: str | None = Field(default=None, max_length=4096)
    locator_kind: EvidenceLocatorKind
    locator_start: int | None = Field(default=None, ge=0)
    locator_end: int | None = Field(default=None, ge=0)
    locator_value: str | None = Field(default=None, max_length=10_000)
    content_hash: str | None = Field(default=None, max_length=64)
    label: str | None = Field(default=None, max_length=1000)
    created_by: ExperimentActor

    @model_validator(mode="after")
    def validate_locator(self):
        for field_name in (
            "observation_id",
            "artifact_id",
            "repository_url",
            "commit_sha",
            "relative_path",
            "locator_value",
            "content_hash",
            "label",
        ):
            value = getattr(self, field_name)
            if isinstance(value, str):
                setattr(self, field_name, value.strip() or None)

        if self.source_kind == "artifact":
            if not self.artifact_id:
                raise ValueError("artifact source requires artifact_id")
            if any(
                value is not None
                for value in (self.repository_url, self.commit_sha, self.relative_path)
            ):
                raise ValueError("artifact source cannot include repository fields")
        else:
            if self.artifact_id is not None:
                raise ValueError("repository source cannot include artifact_id")
            if not self.repository_url or not self.commit_sha or not self.relative_path:
                raise ValueError(
                    "repository source requires repository_url, commit_sha, and relative_path"
                )
            parsed = urlparse(self.repository_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("repository_url must be an absolute HTTPS URL")
            if not _HEX_RE.fullmatch(self.commit_sha):
                raise ValueError("commit_sha must be 7 to 64 hexadecimal characters")
            path = PurePosixPath(self.relative_path)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("relative_path must be a safe repository-relative path")
            if not self.content_hash or not _HASH_RE.fullmatch(self.content_hash):
                raise ValueError("repository source requires a 64-character content_hash")

        if self.content_hash and not _HASH_RE.fullmatch(self.content_hash):
            raise ValueError("content_hash must be 64 hexadecimal characters")

        if self.locator_kind in {"page", "line_range"}:
            if self.locator_start is None:
                raise ValueError(f"{self.locator_kind} requires locator_start")
            if self.locator_end is not None and self.locator_end < self.locator_start:
                raise ValueError("locator_end must be >= locator_start")
        elif not self.locator_value:
            raise ValueError(f"{self.locator_kind} requires locator_value")
        return self


class EvidenceLocator(BaseModel):
    id: str
    observation_id: str
    project_id: str
    source_kind: EvidenceSourceKind
    artifact_id: str | None = None
    repository_url: str | None = None
    commit_sha: str | None = None
    relative_path: str | None = None
    locator_kind: EvidenceLocatorKind
    locator_start: int | None = None
    locator_end: int | None = None
    locator_value: str | None = None
    content_hash: str
    label: str | None = None
    created_by: str
    created_at: str


class ClaimEvidenceRelation(BaseModel):
    id: str
    project_id: str
    claim_id: str
    observation_id: str
    candidate_id: str
    role: ClaimEvidenceRole
    status: Literal["active", "revoked"]
    reviewed_by: str
    review_reason: str
    created_at: str
    revoked_by: str | None = None
    revocation_reason: str | None = None
    revoked_at: str | None = None


class ExperimentObservationDetail(ExperimentObservation):
    locators: list[EvidenceLocator] = Field(default_factory=list)
    interpretation_candidates: list[dict[str, Any]] = Field(default_factory=list)
    claim_relations: list[ClaimEvidenceRelation] = Field(default_factory=list)
