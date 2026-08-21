"""Typed contracts for conflict-safe Markdown/LaTeX source synchronization."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rka.models.semantic_patch import ProposalOrigin, ProviderBoundary


SourceFormat = Literal["markdown", "latex"]
SourceProposalStatus = Literal[
    "proposed", "applied", "rejected", "conflicted", "superseded", "expired"
]
SourceProposalActor = Literal["pi", "brain", "executor", "web_ui"]
SourceProposalReviewer = Literal["pi", "web_ui"]


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManuscriptSourcePath(_ClosedModel):
    relative_path: str = Field(min_length=1, max_length=4096)

    @field_validator("relative_path")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("relative_path must not be blank")
        return value


class ManuscriptSourceProposalCreate(ManuscriptSourcePath):
    origin: ProposalOrigin
    expected_content_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
        description="SHA-256 of the current file, or null only when it must be absent.",
    )
    content: str = Field(max_length=20 * 1024 * 1024)
    created_by: SourceProposalActor
    reason: str = Field(min_length=1, max_length=10_000)
    provider: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=500)
    boundary: ProviderBoundary = "none"
    context_manifest_id: str | None = Field(default=None, max_length=128)
    supersedes_proposal_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_origin(self):
        self.reason = self.reason.strip()
        self.provider = self.provider.strip() if self.provider else None
        self.model = self.model.strip() if self.model else None
        self.context_manifest_id = (
            self.context_manifest_id.strip() if self.context_manifest_id else None
        )
        self.supersedes_proposal_id = (
            self.supersedes_proposal_id.strip() if self.supersedes_proposal_id else None
        )
        if self.expected_content_hash:
            self.expected_content_hash = self.expected_content_hash.lower()
        if not self.reason:
            raise ValueError("reason must not be blank")
        if self.origin == "human":
            if self.provider or self.model or self.boundary != "none" or self.context_manifest_id:
                raise ValueError("human proposals cannot declare an AI provider boundary")
        else:
            if not self.provider or not self.model or not self.context_manifest_id:
                raise ValueError("AI proposals require provider, model, and context_manifest_id")
            expected = "host_conversation" if self.origin == "host_agent" else "local_loopback"
            if self.boundary != expected:
                raise ValueError(f"{self.origin} proposals require boundary={expected!r}")
        return self


class ManuscriptSourceProposalTransition(_ClosedModel):
    expected_revision: int = Field(ge=1)
    actor: SourceProposalReviewer
    reason: str = Field(min_length=1, max_length=10_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value
