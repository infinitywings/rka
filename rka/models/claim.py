"""Claim and evidence cluster models (v2.0)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── Claims ──────────────────────────────────────────────────

ClaimType = Literal[
    "hypothesis", "evidence", "method", "result", "observation", "assumption"
]


class ClaimCreate(BaseModel):
    """Create a new claim (typically by the distillation pipeline)."""

    source_entry_id: str
    claim_type: ClaimType
    content: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    verified: bool = False
    source_offset_start: int | None = None
    source_offset_end: int | None = None


class ClaimUpdate(BaseModel):
    """Partial update for a claim."""

    content: str | None = None
    claim_type: ClaimType | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verified: bool | None = None
    stale: bool | None = None


class Claim(BaseModel):
    """Full claim record from database."""

    id: str
    source_entry_id: str
    claim_type: str
    content: str
    confidence: float = 0.5
    verified: bool = False
    stale: bool = False
    source_offset_start: int | None = None
    source_offset_end: int | None = None
    project_id: str = "proj_default"
    created_at: str | None = None
    updated_at: str | None = None


# ── Evidence Clusters ───────────────────────────────────────

ClusterConfidence = Literal["strong", "moderate", "emerging", "contested", "refuted"]


class EvidenceClusterCreate(BaseModel):
    """Create a new evidence cluster."""

    research_question_id: str | None = None
    label: str
    synthesis: str | None = None
    confidence: ClusterConfidence = "emerging"


class EvidenceClusterUpdate(BaseModel):
    """Partial update for an evidence cluster."""

    label: str | None = None
    synthesis: str | None = None
    confidence: ClusterConfidence | None = None
    needs_reprocessing: bool | None = None
    synthesized_by: Literal["llm", "brain"] | None = None


class EvidenceCluster(BaseModel):
    """Full evidence cluster record from database."""

    id: str
    research_question_id: str | None = None
    label: str
    synthesis: str | None = None
    confidence: str = "emerging"
    claim_count: int = 0
    gap_count: int = 0
    needs_reprocessing: bool = False
    synthesized_by: str = "llm"
    project_id: str = "proj_default"
    created_at: str | None = None
    updated_at: str | None = None


# ── Claim Edges ─────────────────────────────────────────────

ClaimRelationType = Literal[
    "member_of", "supports", "contradicts", "qualifies", "supersedes"
]


class ClaimEdgeCreate(BaseModel):
    """Create a claim edge (relationship between claims or claim-to-cluster)."""

    source_claim_id: str
    target_claim_id: str | None = None
    cluster_id: str | None = None
    relation: ClaimRelationType
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ClaimEdge(BaseModel):
    """Full claim edge record from database."""

    id: str
    source_claim_id: str
    target_claim_id: str | None = None
    cluster_id: str | None = None
    relation: str
    confidence: float = 0.5
    project_id: str = "proj_default"
    created_at: str | None = None
