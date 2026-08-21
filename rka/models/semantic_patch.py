"""Typed proposal envelopes for workbench semantic edits."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rka.models.planning import PlanningArtifactVersionAppend


ProposalActor = Literal["pi", "brain", "executor", "web_ui"]
ProposalReviewer = Literal["pi", "web_ui"]
ProposalOrigin = Literal["human", "host_agent", "lm_studio"]
ProviderBoundary = Literal["none", "host_conversation", "local_loopback"]
ProposalStatus = Literal[
    "proposed", "applied", "rejected", "conflicted", "superseded", "expired"
]
ContextRole = Literal[
    "support", "qualifier", "counterevidence", "context", "inspiration", "unresolved"
]


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextSelection(_ClosedModel):
    entity_id: str = Field(min_length=1, max_length=128)
    role: ContextRole = "context"
    locator: str | None = Field(default=None, max_length=20_000)

    @field_validator("entity_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("entity_id must not be blank")
        return value


class ContextTarget(_ClosedModel):
    target_type: Literal["manuscript", "planning_branch"]
    target_id: str = Field(min_length=1, max_length=128)

    @field_validator("target_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("target_id must not be blank")
        return value


class PlanningArtifactUpsertOperation(_ClosedModel):
    operation: Literal["planning_artifact_upsert"] = "planning_artifact_upsert"
    branch_id: str = Field(min_length=1, max_length=128)
    append: PlanningArtifactVersionAppend

    @field_validator("branch_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("branch_id must not be blank")
        return value


class ManuscriptMetadataUpdateOperation(_ClosedModel):
    operation: Literal["manuscript_metadata_update"] = "manuscript_metadata_update"
    manuscript_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=20_000)
    abstract: str | None = Field(default=None, max_length=100_000)
    venue: str | None = Field(default=None, max_length=2_000)
    workspace_ref: str | None = Field(default=None, max_length=20_000)

    @field_validator("manuscript_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("manuscript_id must not be blank")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if not (
            self.model_fields_set
            & {"title", "abstract", "venue", "workspace_ref"}
        ):
            raise ValueError("manuscript metadata operation requires at least one field")
        return self


class ArgumentSpineReplaceOperation(_ClosedModel):
    operation: Literal["argument_spine_replace"] = "argument_spine_replace"
    manuscript_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=1)
    spine: dict[str, Any]

    @field_validator("manuscript_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("manuscript_id must not be blank")
        return value


SemanticPatchOperation = Annotated[
    PlanningArtifactUpsertOperation
    | ManuscriptMetadataUpdateOperation
    | ArgumentSpineReplaceOperation,
    Field(discriminator="operation"),
]


class SemanticPatchProposalCreate(_ClosedModel):
    origin: ProposalOrigin
    intent: str = Field(min_length=1, max_length=20_000)
    reason: str = Field(min_length=1, max_length=10_000)
    created_by: ProposalActor
    operations: list[SemanticPatchOperation] = Field(min_length=1, max_length=20)
    provider: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=500)
    boundary: ProviderBoundary = "none"
    context_manifest_id: str | None = Field(default=None, max_length=128)
    supersedes_proposal_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_origin(self):
        self.intent = self.intent.strip()
        self.reason = self.reason.strip()
        self.provider = self.provider.strip() if self.provider else None
        self.model = self.model.strip() if self.model else None
        self.context_manifest_id = (
            self.context_manifest_id.strip() if self.context_manifest_id else None
        )
        self.supersedes_proposal_id = (
            self.supersedes_proposal_id.strip() if self.supersedes_proposal_id else None
        )
        if not self.intent or not self.reason:
            raise ValueError("intent and reason must not be blank")
        if self.origin == "human":
            if self.provider or self.model or self.boundary != "none" or self.context_manifest_id:
                raise ValueError("human proposals cannot declare an AI provider boundary")
        else:
            if not self.provider or not self.model or not self.context_manifest_id:
                raise ValueError("AI proposals require provider, model, and context_manifest_id")
            expected = "host_conversation" if self.origin == "host_agent" else "local_loopback"
            if self.boundary != expected:
                raise ValueError(f"{self.origin} proposals require boundary={expected!r}")

        aggregates: set[tuple[str, str]] = set()
        for operation in self.operations:
            if isinstance(operation, PlanningArtifactUpsertOperation):
                key = ("planning_branch", operation.branch_id)
            else:
                key = ("manuscript", operation.manuscript_id)
            if key in aggregates:
                raise ValueError(
                    "a proposal may contain at most one operation per mutable aggregate"
                )
            aggregates.add(key)
        return self


class ContextManifestCreate(_ClosedModel):
    origin: Literal["host_agent", "lm_studio"]
    provider: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=500)
    boundary: Literal["host_conversation", "local_loopback"]
    selected_context: list[ContextSelection] = Field(default_factory=list, max_length=500)
    include_source_closure: bool = True
    targets: list[ContextTarget] = Field(default_factory=list, max_length=50)
    constraints: list[str] = Field(default_factory=list, max_length=500)
    omissions: list[str] = Field(default_factory=list, max_length=500)
    truncation_notes: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_boundary(self):
        self.provider = self.provider.strip()
        self.model = self.model.strip()
        if not self.provider or not self.model:
            raise ValueError("provider and model must not be blank")
        expected = "host_conversation" if self.origin == "host_agent" else "local_loopback"
        if self.boundary != expected:
            raise ValueError(f"{self.origin} manifests require boundary={expected!r}")
        return self


class SemanticPatchProposalTransition(_ClosedModel):
    expected_revision: int = Field(ge=1)
    actor: ProposalReviewer
    reason: str = Field(min_length=1, max_length=10_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value


class LMStudioProposalRequest(_ClosedModel):
    instruction: str = Field(min_length=1, max_length=40_000)
    created_by: ProposalActor
    selected_context: list[ContextSelection] = Field(default_factory=list, max_length=500)
    targets: list[ContextTarget] = Field(default_factory=list, max_length=50)
    include_source_closure: bool = True
    constraints: list[str] = Field(default_factory=list, max_length=500)
    omissions: list[str] = Field(default_factory=list, max_length=500)
    truncation_notes: list[str] = Field(default_factory=list, max_length=500)
    model: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def normalize_request(self):
        self.instruction = self.instruction.strip()
        self.model = self.model.strip() if self.model else None
        if not self.instruction:
            raise ValueError("instruction must not be blank")
        return self


class GeneratedProposalDraft(_ClosedModel):
    intent: str = Field(min_length=1, max_length=20_000)
    reason: str = Field(min_length=1, max_length=10_000)
    operations: list[SemanticPatchOperation] = Field(min_length=1, max_length=20)
