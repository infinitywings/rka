"""Typed requests for proposal-first progressive outline editing."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _clean_strings(values: list[str]) -> list[str]:
    cleaned = [value.strip() for value in values]
    if any(not value for value in cleaned):
        raise ValueError("outline intention lists cannot contain blank values")
    return list(dict.fromkeys(cleaned))


class OutlineUnitPatch(_ClosedModel):
    title: str | None = Field(default=None, max_length=20_000)
    location: str | None = Field(default=None, min_length=1, max_length=20_000)
    outline_level: int | None = Field(default=None, ge=2, le=5)
    parent_unit_key: str | None = Field(default=None, max_length=200)
    communicative_job: str | None = Field(default=None, max_length=20_000)
    intended_takeaway: str | None = Field(default=None, max_length=20_000)
    transition_from_previous: str | None = Field(default=None, max_length=20_000)
    quick_reader_role: str | None = Field(default=None, max_length=20_000)
    evidence_plan: list[str] | None = Field(default=None, max_length=500)
    figure_intentions: list[str] | None = Field(default=None, max_length=500)
    table_intentions: list[str] | None = Field(default=None, max_length=500)
    citation_intentions: list[str] | None = Field(default=None, max_length=1000)
    blocker: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("outline unit edit requires at least one field")
        for field in (
            "evidence_plan", "figure_intentions", "table_intentions", "citation_intentions"
        ):
            value = getattr(self, field)
            if value is not None:
                setattr(self, field, _clean_strings(value))
        return self

class OutlineChildDraft(_ClosedModel):
    local_key: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=20_000)
    location: str = Field(min_length=1, max_length=20_000)
    communicative_job: str = Field(min_length=1, max_length=20_000)
    intended_takeaway: str = Field(min_length=1, max_length=20_000)
    transition_from_previous: str | None = Field(default=None, max_length=20_000)
    quick_reader_role: str | None = Field(default=None, max_length=20_000)
    evidence_plan: list[str] = Field(min_length=1, max_length=500)
    figure_intentions: list[str] = Field(default_factory=list, max_length=500)
    table_intentions: list[str] = Field(default_factory=list, max_length=500)
    citation_intentions: list[str] = Field(default_factory=list, max_length=1000)
    blocker: str | None = Field(default=None, max_length=20_000)
    claim_keys: list[str] | None = Field(default=None, min_length=1, max_length=500)
    support_ids: list[str] | None = Field(default=None, max_length=500)
    qualifier_ids: list[str] | None = Field(default=None, max_length=500)
    counterevidence_ids: list[str] | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def normalize_lists(self):
        self.local_key = self.local_key.strip()
        self.title = self.title.strip()
        self.location = self.location.strip()
        self.communicative_job = self.communicative_job.strip()
        self.intended_takeaway = self.intended_takeaway.strip()
        for field in (
            "evidence_plan", "figure_intentions", "table_intentions", "citation_intentions"
        ):
            setattr(self, field, _clean_strings(getattr(self, field)))
        if self.claim_keys is not None:
            self.claim_keys = _clean_strings(self.claim_keys)
        for field in ("support_ids", "qualifier_ids", "counterevidence_ids"):
            value = getattr(self, field)
            if value is not None:
                setattr(self, field, _clean_strings(value))
        return self


class OutlineProposalRequest(_ClosedModel):
    expected_revision: int = Field(ge=1)
    action: Literal["edit", "expand", "condense", "reorder"]
    reason: str = Field(min_length=1, max_length=10_000)
    unit_key: str | None = Field(default=None, max_length=200)
    patch: OutlineUnitPatch | None = None
    children: list[OutlineChildDraft] = Field(default_factory=list, max_length=100)
    descendant_keys: list[str] = Field(default_factory=list, max_length=1000)
    ordered_unit_keys: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_action_shape(self):
        self.unit_key = self.unit_key.strip() if self.unit_key else None
        self.descendant_keys = _clean_strings(self.descendant_keys)
        self.ordered_unit_keys = _clean_strings(self.ordered_unit_keys)
        if self.action == "edit" and (not self.unit_key or self.patch is None):
            raise ValueError("edit requires unit_key and patch")
        if self.action == "expand" and (not self.unit_key or not self.children):
            raise ValueError("expand requires unit_key and children")
        if self.action == "condense" and (not self.unit_key or not self.descendant_keys):
            raise ValueError("condense requires unit_key and descendant_keys")
        if self.action == "reorder" and not self.ordered_unit_keys:
            raise ValueError("reorder requires ordered_unit_keys")
        return self
