"""Typed models for safe external-source registration and admission."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SourceKind = Literal["file", "pasted_text", "url", "repository", "zotero"]
SourceContentMode = Literal["bytes", "locator_manifest"]
OwnershipKind = Literal[
    "researcher", "institution", "third_party", "public_domain", "unknown"
]
SourceRegistrationActor = Literal[
    "pi", "brain", "executor", "web_ui", "llm", "import", "system"
]
SourceAdmissionActor = Literal["pi", "brain", "executor", "web_ui"]
SourceAdmissionTarget = Literal["journal", "claim", "decision"]

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class RegisterSourceRequest(BaseModel):
    """One local source-registration request; no remote locator is fetched."""

    model_config = ConfigDict(extra="forbid")

    source_kind: SourceKind
    title: str | None = Field(default=None, max_length=1000)
    filepath: str | None = Field(default=None, max_length=8192)
    pasted_text: str | None = Field(default=None, max_length=10_000_000)
    content_base64: str | None = None
    filename: str | None = Field(default=None, max_length=1024)
    stable_locator: str | None = Field(default=None, max_length=8192)
    mime: str | None = Field(default=None, max_length=256)
    expected_content_hash: str | None = Field(default=None, max_length=64)
    ownership_kind: OwnershipKind = "unknown"
    ownership_note: str | None = Field(default=None, max_length=10_000)
    provenance: dict[str, Any] = Field(default_factory=dict)
    registered_by: SourceRegistrationActor

    @model_validator(mode="after")
    def validate_input_mode(self) -> "RegisterSourceRequest":
        self.title = self.title.strip() if self.title else None
        self.filepath = self.filepath.strip() if self.filepath else None
        self.pasted_text = self.pasted_text if self.pasted_text is not None else None
        self.filename = self.filename.strip() if self.filename else None
        self.stable_locator = self.stable_locator.strip() if self.stable_locator else None
        self.mime = self.mime.strip() if self.mime else None
        self.ownership_note = self.ownership_note.strip() if self.ownership_note else None

        supplied_bytes = sum(
            value is not None
            for value in (self.filepath, self.pasted_text, self.content_base64)
        )
        if supplied_bytes > 1:
            raise ValueError(
                "provide at most one of filepath, pasted_text, and content_base64"
            )
        if self.source_kind == "pasted_text" and self.pasted_text is None:
            raise ValueError("pasted_text sources require pasted_text")
        if self.source_kind == "file" and not (
            self.filepath is not None or self.content_base64 is not None
        ):
            raise ValueError("file sources require filepath or content_base64")
        if self.source_kind in {"url", "repository", "zotero"} and not self.stable_locator:
            raise ValueError(f"{self.source_kind} sources require stable_locator")
        if supplied_bytes == 0 and not self.stable_locator:
            raise ValueError("a source requires bytes or a stable_locator")
        if self.pasted_text is not None and self.source_kind != "pasted_text":
            raise ValueError("pasted_text bytes are only valid for source_kind='pasted_text'")
        if self.content_base64 is not None and self.source_kind == "pasted_text":
            raise ValueError("pasted_text sources must use pasted_text, not content_base64")
        if self.filename is not None and self.content_base64 is None:
            raise ValueError("filename is only valid with content_base64")
        if self.expected_content_hash is not None:
            self.expected_content_hash = self.expected_content_hash.strip().lower()
            if not _SHA256_RE.fullmatch(self.expected_content_hash):
                raise ValueError("expected_content_hash must be a lowercase SHA-256 hex digest")
        return self


class RegisteredSource(BaseModel):
    id: str
    project_id: str
    artifact_id: str
    source_kind: SourceKind
    content_mode: SourceContentMode
    title: str
    stable_locator: str | None = None
    content_hash: str
    manifest_hash: str
    ownership_kind: OwnershipKind
    ownership_note: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    registered_by: SourceRegistrationActor
    created_at: str | None = None


class RegisterSourceResult(BaseModel):
    source: RegisteredSource
    duplicate: bool


class SourceAdmissionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=1)
    target_type: SourceAdmissionTarget
    target_id: str = Field(min_length=1, max_length=128)
    actor: SourceAdmissionActor
    reason: str = Field(min_length=1, max_length=10_000)
    grounding_verified: Literal[True]

    @model_validator(mode="after")
    def normalize(self) -> "SourceAdmissionCreate":
        self.candidate_id = self.candidate_id.strip()
        self.target_id = self.target_id.strip()
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("reason must not be blank")
        return self


class SourceAdmission(BaseModel):
    id: str
    project_id: str
    source_id: str
    candidate_id: str
    candidate_revision: int
    target_type: SourceAdmissionTarget
    target_id: str
    source_manifest_hash: str
    actor: SourceAdmissionActor
    reason: str
    grounding_verified: bool
    created_at: str | None = None


class RegisteredSourceDetail(RegisteredSource):
    artifact: dict[str, Any]
    admissions: list[SourceAdmission] = Field(default_factory=list)
    interpretation_candidate_count: int = 0
