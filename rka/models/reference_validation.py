"""Bounded input models for manuscript-reference validation.

The validator may call network-backed providers, so its durable job boundary
must not accept arbitrary CSL/provider payloads.  These models intentionally
cover only the lookup keys the Writer pipeline consumes.
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

MAX_REFERENCE_PAYLOAD_BYTES = 64 * 1024
MAX_REFERENCE_DOI_CHARS = 255
MAX_REFERENCE_TITLE_CHARS = 2_000
MAX_REFERENCE_AUTHORS = 100
MAX_AUTHOR_NAME_CHARS = 256
MAX_AUTHOR_LITERAL_CHARS = 512
_SENSITIVE_INPUT_RE = re.compile(
    r"(?i)(?:"
    r"authorization\s*:|"
    r"bearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S+"
    r")"
)


def _reject_likely_credential(value: str) -> str:
    if _SENSITIVE_INPUT_RE.search(value):
        raise ValueError("reference input appears to contain a credential")
    return value


class ReferenceAuthor(BaseModel):
    """One bounded CSL-style person or institutional author."""

    model_config = ConfigDict(extra="forbid")

    family: Annotated[
        str | None,
        Field(default=None, min_length=1, max_length=MAX_AUTHOR_NAME_CHARS),
    ] = None
    given: Annotated[
        str | None,
        Field(default=None, min_length=1, max_length=MAX_AUTHOR_NAME_CHARS),
    ] = None
    literal: Annotated[
        str | None,
        Field(default=None, min_length=1, max_length=MAX_AUTHOR_LITERAL_CHARS),
    ] = None

    @field_validator("family", "given", "literal", mode="before")
    @classmethod
    def _strip_optional_name(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = " ".join(value.split())
            return _reject_likely_credential(stripped) if stripped else None
        return value

    @model_validator(mode="after")
    def _require_identity(self) -> "ReferenceAuthor":
        if self.family is None and self.literal is None:
            raise ValueError("author requires family or literal")
        return self


class ReferenceValidationInput(BaseModel):
    """Strict, normalized lookup input accepted by REST, MCP, and services."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )

    doi: Annotated[
        str | None,
        Field(
            default=None,
            min_length=1,
            max_length=MAX_REFERENCE_DOI_CHARS,
            validation_alias=AliasChoices("DOI", "doi"),
            serialization_alias="DOI",
        ),
    ] = None
    title: Annotated[
        str | None,
        Field(default=None, min_length=1, max_length=MAX_REFERENCE_TITLE_CHARS),
    ] = None
    author: Annotated[
        list[ReferenceAuthor] | None,
        Field(default=None, max_length=MAX_REFERENCE_AUTHORS),
    ] = None

    @field_validator("doi", mode="before")
    @classmethod
    def _normalize_doi(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            lowered = stripped.casefold()
            for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
                if lowered.startswith(prefix):
                    lowered = lowered[len(prefix) :].strip()
                    break
            return _reject_likely_credential(lowered) if lowered else None
        return value

    @field_validator("title", mode="before")
    @classmethod
    def _normalize_title(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = " ".join(value.split())
            return _reject_likely_credential(stripped) if stripped else None
        return value

    @model_validator(mode="after")
    def _require_lookup_key(self) -> "ReferenceValidationInput":
        if self.doi is None and self.title is None:
            raise ValueError("Reference must carry at least DOI or title.")
        return self

    def durable_dict(self) -> dict[str, Any]:
        """Return canonical JSON input and enforce an aggregate byte ceiling."""
        payload = self.model_dump(exclude_none=True, by_alias=True)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(encoded) > MAX_REFERENCE_PAYLOAD_BYTES:
            raise ValueError(
                "Reference validation input exceeds the 64 KiB durable limit."
            )
        return payload


def normalize_reference_input(reference: dict[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize an untrusted reference mapping."""
    return ReferenceValidationInput.model_validate(reference).durable_dict()


__all__ = [
    "MAX_AUTHOR_LITERAL_CHARS",
    "MAX_AUTHOR_NAME_CHARS",
    "MAX_REFERENCE_AUTHORS",
    "MAX_REFERENCE_DOI_CHARS",
    "MAX_REFERENCE_PAYLOAD_BYTES",
    "MAX_REFERENCE_TITLE_CHARS",
    "ReferenceAuthor",
    "ReferenceValidationInput",
    "normalize_reference_input",
]
