"""Native manuscript and evidence-to-writing spine models.

The models in this module mirror migration 033.  They intentionally do not
interpret legacy ``jrn_`` manuscript manifests or infer PI ratification.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

ManuscriptState = Literal[
    "active",
    "on_hold",
    "submitted",
    "accepted",
    "rejected",
    "withdrawn",
    "archived",
]
ManuscriptClaimKind = Literal[
    "empirical",
    "methodological",
    "theoretical",
    "survey",
    "position",
]
ManuscriptClaimState = Literal["candidate", "active", "retired"]
ManuscriptUnitKind = Literal[
    "abstract",
    "introduction",
    "related_work",
    "background",
    "method",
    "result",
    "discussion",
    "limitation",
    "conclusion",
    "caption",
    "appendix",
    "other",
]
ManuscriptUnitStatus = Literal["planned", "drafted", "reviewed", "final", "removed"]
ManuscriptEvidenceRole = Literal["support", "qualifier", "counterevidence"]
ManuscriptClaimUnitRelationship = Literal["advances", "tests", "bounds", "mentions"]
ManuscriptCheckpointKind = Literal[
    "venue",
    "outline",
    "table_figure_plan",
    "reference_set",
    "draft_section",
    "final_layout",
]
ManuscriptCheckpointStatus = Literal["pending", "resolved", "rejected", "superseded"]
ManuscriptReferenceState = Literal["active", "retired"]
VerificationVerdict = Literal["pass", "warn", "block", "error"]
VerificationDimensionVerdict = Literal[
    "pass", "warn", "block", "error", "not_checked"
]


def _json_value(value: Any) -> Any:
    """Deserialize JSON text returned by SQLite while accepting native values."""
    if isinstance(value, str):
        return json.loads(value)
    return value


class ManuscriptCreate(BaseModel):
    """Create a native manuscript without importing or mutating legacy records."""

    model_config = ConfigDict(extra="forbid")

    title: NonEmptyStr
    abstract: str | None = None
    venue: str | None = None
    phase: Literal["planning"] = "planning"
    state: Literal["active"] = "active"
    workspace_ref: str | None = None
    legacy_journal_id: str | None = None


class ManuscriptUpdate(BaseModel):
    """Optimistic-concurrency update for a native manuscript.

    Services must match ``expected_revision`` and increment ``revision`` in the
    same transaction.  Callers never set the new revision directly.
    """

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    title: NonEmptyStr | None = None
    abstract: str | None = None
    venue: str | None = None
    phase: NonEmptyStr | None = None
    state: ManuscriptState | None = None
    workspace_ref: str | None = None

    @model_validator(mode="after")
    def require_change(self) -> ManuscriptUpdate:
        if not (self.model_fields_set - {"expected_revision"}):
            raise ValueError("at least one manuscript field must be updated")
        return self


class Manuscript(BaseModel):
    """Full native manuscript row."""

    id: str
    project_id: str
    title: str
    abstract: str | None = None
    venue: str | None = None
    phase: str
    state: ManuscriptState
    workspace_ref: str | None = None
    revision: int
    legacy_journal_id: str | None = None
    created_at: str
    updated_at: str


class ManuscriptClaimCreate(BaseModel):
    """Create stable manuscript-claim identity; wording lives in versions."""

    model_config = ConfigDict(extra="forbid")

    manuscript_id: str
    local_key: NonEmptyStr
    kind: ManuscriptClaimKind
    state: ManuscriptClaimState = "candidate"


class ManuscriptClaimUpdate(BaseModel):
    """Update claim lifecycle without rewriting any wording version."""

    model_config = ConfigDict(extra="forbid")

    state: ManuscriptClaimState


class ManuscriptClaim(BaseModel):
    """Stable manuscript claim identity."""

    id: str
    manuscript_id: str
    project_id: str
    local_key: str
    kind: ManuscriptClaimKind
    state: ManuscriptClaimState
    created_at: str
    updated_at: str


class ManuscriptClaimVersionCreate(BaseModel):
    """Append an immutable wording version.

    ``expected_previous_version=0`` creates the first version.  Higher values
    let a service reject racing appends instead of silently forking wording.
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    expected_previous_version: int = Field(default=0, ge=0)
    exact_wording: NonEmptyStr
    allowed_wording: NonEmptyStr
    prohibited_wording: list[NonEmptyStr] = Field(min_length=1)


class ManuscriptClaimVersion(BaseModel):
    """Immutable claim wording version."""

    claim_id: str
    version: int
    manuscript_id: str
    project_id: str
    exact_wording: str
    allowed_wording: str
    prohibited_wording: list[str]
    created_at: str

    _parse_prohibited_wording = field_validator(
        "prohibited_wording", mode="before"
    )(_json_value)


class ManuscriptClaimRatificationCreate(BaseModel):
    """Bind one exact claim version to one explicit PI decision."""

    model_config = ConfigDict(extra="forbid")

    manuscript_id: str
    claim_id: str
    claim_version: int = Field(ge=1)
    decision_id: str
    ratified_at: str


class ManuscriptClaimRatification(BaseModel):
    """Immutable claim-ratification row."""

    id: str
    manuscript_id: str
    project_id: str
    claim_id: str
    claim_version: int
    decision_id: str
    ratified_at: str
    created_at: str


class ManuscriptUnitCreate(BaseModel):
    """Create one claim-sized manuscript unit."""

    model_config = ConfigDict(extra="forbid")

    manuscript_id: str
    local_key: NonEmptyStr
    kind: ManuscriptUnitKind
    location: NonEmptyStr
    title: str | None = None
    artifact_ref: str | None = None
    allowed_interpretation: str | None = None
    prohibited_interpretation: str | None = None
    sequence: int = Field(default=0, ge=0)
    status: ManuscriptUnitStatus = "planned"

    @model_validator(mode="after")
    def require_result_boundaries(self) -> ManuscriptUnitCreate:
        if self.kind == "result":
            for field_name in (
                "artifact_ref",
                "allowed_interpretation",
                "prohibited_interpretation",
            ):
                value = getattr(self, field_name)
                if value is None or not value.strip():
                    raise ValueError(f"result units require {field_name}")
        return self


class ManuscriptUnitUpdate(BaseModel):
    """Partial unit update; services retain the unit's manuscript binding."""

    model_config = ConfigDict(extra="forbid")

    kind: ManuscriptUnitKind | None = None
    location: NonEmptyStr | None = None
    title: str | None = None
    artifact_ref: str | None = None
    allowed_interpretation: str | None = None
    prohibited_interpretation: str | None = None
    sequence: int | None = Field(default=None, ge=0)
    status: ManuscriptUnitStatus | None = None


class ManuscriptUnit(BaseModel):
    """Full native manuscript unit row."""

    id: str
    manuscript_id: str
    project_id: str
    local_key: str
    kind: ManuscriptUnitKind
    location: str
    title: str | None = None
    artifact_ref: str | None = None
    allowed_interpretation: str | None = None
    prohibited_interpretation: str | None = None
    sequence: int
    status: ManuscriptUnitStatus
    created_at: str
    updated_at: str


class ManuscriptClaimEvidenceCreate(BaseModel):
    """Attach a typed core RKA claim to one manuscript claim version."""

    model_config = ConfigDict(extra="forbid")

    manuscript_id: str
    manuscript_claim_id: str
    claim_version: int = Field(ge=1)
    evidence_claim_id: str
    role: ManuscriptEvidenceRole
    ordinal: int = Field(default=0, ge=0)


class ManuscriptClaimEvidence(ManuscriptClaimEvidenceCreate):
    """Typed claim-evidence join row."""

    project_id: str
    created_at: str


class ManuscriptUnitEvidenceCreate(BaseModel):
    """Attach a typed core RKA claim to one manuscript unit."""

    model_config = ConfigDict(extra="forbid")

    manuscript_id: str
    unit_id: str
    evidence_claim_id: str
    role: ManuscriptEvidenceRole
    ordinal: int = Field(default=0, ge=0)


class ManuscriptUnitEvidence(ManuscriptUnitEvidenceCreate):
    """Typed unit-evidence join row."""

    project_id: str
    created_at: str


class ManuscriptClaimUnitCreate(BaseModel):
    """Relate a manuscript claim version to a unit with explicit semantics."""

    model_config = ConfigDict(extra="forbid")

    manuscript_id: str
    manuscript_claim_id: str
    claim_version: int = Field(ge=1)
    unit_id: str
    relationship: ManuscriptClaimUnitRelationship


class ManuscriptClaimUnit(ManuscriptClaimUnitCreate):
    """Typed claim-unit join row."""

    project_id: str
    created_at: str


class ManuscriptReferenceMemberInput(BaseModel):
    """One active citation-key binding in the authoritative reference set."""

    model_config = ConfigDict(extra="forbid")

    citation_key: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=256,
            pattern=r"^[^,\s{}]+$",
        ),
    ]
    literature_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, pattern=r"^lit_.+"),
    ]


class ManuscriptReferenceManifestReplace(BaseModel):
    """Revision-guarded full replacement of active citation membership."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    members: list[ManuscriptReferenceMemberInput] = Field(max_length=2_000)

    @model_validator(mode="after")
    def require_unique_bindings(self) -> ManuscriptReferenceManifestReplace:
        citation_keys: set[str] = set()
        literature_ids: set[str] = set()
        for member in self.members:
            folded_key = member.citation_key.casefold()
            if folded_key in citation_keys:
                raise ValueError(
                    "reference manifest citation keys must be unique "
                    "case-insensitively"
                )
            if member.literature_id in literature_ids:
                raise ValueError(
                    "reference manifest may bind one literature record only once"
                )
            citation_keys.add(folded_key)
            literature_ids.add(member.literature_id)
        return self


class ManuscriptReferenceMember(BaseModel):
    """Stored, project-scoped citation membership row."""

    id: str
    manuscript_id: str
    project_id: str
    citation_key: str
    literature_id: str
    state: ManuscriptReferenceState
    created_at: str
    updated_at: str
    retired_at: str | None = None


class ManuscriptCheckpointCreate(BaseModel):
    """Create a pending checkpoint; resolution is a separate explicit action."""

    model_config = ConfigDict(extra="forbid")

    manuscript_id: str
    kind: ManuscriptCheckpointKind
    unit_id: str | None = None
    supersedes_id: str | None = None

    @model_validator(mode="after")
    def validate_unit_scope(self) -> ManuscriptCheckpointCreate:
        if self.kind == "draft_section" and self.unit_id is None:
            raise ValueError("draft_section checkpoints require unit_id")
        if self.kind != "draft_section" and self.unit_id is not None:
            raise ValueError("only draft_section checkpoints may set unit_id")
        return self


class ManuscriptCheckpointResolve(BaseModel):
    """Resolve a pending checkpoint through an explicit decision."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    status: Literal["resolved", "rejected"]
    resolved_at: str


class ManuscriptCheckpoint(BaseModel):
    """Full manuscript checkpoint row."""

    id: str
    manuscript_id: str
    project_id: str
    kind: ManuscriptCheckpointKind
    unit_id: str | None = None
    decision_id: str | None = None
    approved_choice: str | None = None
    dependency_snapshot: dict[str, Any] = Field(default_factory=dict)
    status: ManuscriptCheckpointStatus
    supersedes_id: str | None = None
    created_at: str
    resolved_at: str | None = None

    _parse_dependency_snapshot = field_validator(
        "dependency_snapshot", mode="before"
    )(_json_value)


class ManuscriptClaimVerificationAttestationCreate(BaseModel):
    """Append a multidimensional, immutable claim-verification result."""

    model_config = ConfigDict(extra="forbid")

    manuscript_id: str
    claim_id: str
    claim_version: int = Field(ge=1)
    overall_verdict: VerificationVerdict
    grounding_verdict: VerificationDimensionVerdict
    evidence_verdict: VerificationDimensionVerdict
    contradiction_verdict: VerificationDimensionVerdict
    currency_verdict: VerificationDimensionVerdict
    ratification_verdict: VerificationDimensionVerdict
    unit_coverage_verdict: VerificationDimensionVerdict
    changelog_cursor: str | None = None
    dependency_snapshot: dict[str, Any] = Field(default_factory=dict)
    full_json_payload: dict[str, Any]
    validator_version: str | None = None
    started_at: str
    completed_at: str


class ManuscriptClaimVerificationAttestation(
    ManuscriptClaimVerificationAttestationCreate
):
    """Full immutable verification-attestation row."""

    id: str
    project_id: str
    created_at: str

    _parse_dependency_snapshot = field_validator(
        "dependency_snapshot", mode="before"
    )(_json_value)
    _parse_full_json_payload = field_validator(
        "full_json_payload", mode="before"
    )(_json_value)
