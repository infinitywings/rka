"""Canonical manuscript and argument-spine REST endpoints.

The compatibility register/read routes accept legacy ``jrn_`` aliases while
native operations resolve to authoritative ``man_`` aggregates. Historical
reference-validation job status remains readable for migration and audit.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from rka.api.deps import (
    get_db,
    get_embeddings,
    get_llm,
    get_scoped_semantic_patch_service,
    get_transport_actor,
    require_project,
)
from rka.infra.database import Database
from rka.infra.embeddings import EmbeddingService
from rka.infra.llm import LLMClient
from rka.models.manuscript_native import (
    ManuscriptCheckpointCreate,
    ManuscriptCheckpointResolve,
    ManuscriptClaimVerificationAttestationCreate,
    ManuscriptCreate,
    ManuscriptReferenceManifestReplace,
    ManuscriptUpdate,
)
from rka.models.outline import OutlineProposalRequest
from rka.models.semantic_patch import (
    SemanticPatchProposalCreate,
    SemanticPatchProposalTransition,
)
from rka.services.manuscript import ManuscriptService
from rka.services.manuscript_native import (
    ManuscriptNotFoundError,
    ManuscriptRevisionConflict,
    NativeManuscriptService,
)
from rka.services.notes import NoteService
from rka.services.outline import ManuscriptOutlineService
from rka.services.reference_validation import ReferenceValidationService
from rka.services.semantic_patch import (
    SemanticPatchConflictError,
    SemanticPatchService,
)

router = APIRouter(deprecated=True)


# Small transport-only request wrappers stay next to the routes; native domain
# entities and invariant-bearing models live in rka/models/manuscript_native.py.


class ManuscriptRegisterRequest(BaseModel):
    """Inputs to POST /api/manuscripts."""

    model_config = ConfigDict(extra="forbid")

    venue: str = Field(..., description="Target venue (CHI, EMNLP, USENIX, etc.)")
    title: str = Field(..., description="Manuscript title (PI authored)")
    abstract: str | None = Field(default=None, description="Manuscript abstract (PI authored)")
    sections: list[str] | None = Field(default=None, description="Initial section ids; outlined status by default")


class ArgumentSpineUpsertRequest(BaseModel):
    """Explicit human bulk replacement, retained for CLI compatibility."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=1)
    spine: dict[str, Any]
    reason: str = Field(
        default="Explicitly apply the reviewed bulk argument-spine replacement.",
        min_length=1,
        max_length=10_000,
    )


class ManuscriptMetadataUpdateRequest(BaseModel):
    """Update descriptive metadata without bypassing lifecycle gates."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=1)
    title: str | None = Field(default=None, min_length=1)
    abstract: str | None = None
    venue: str | None = None
    workspace_ref: str | None = None

    def to_domain(self) -> ManuscriptUpdate:
        return ManuscriptUpdate.model_validate(
            self.model_dump(exclude_unset=True)
        )


class ClaimRatificationRequest(BaseModel):
    """Bind exact wording to an explicit PI decision."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=1)
    decision_id: str
    claim_version: int | None = Field(default=None, ge=1)
    ratified_at: str | None = None


class ManuscriptTransitionRequest(BaseModel):
    """Advance a native manuscript through a readiness-gated phase."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=1)
    target_phase: str
    target_state: str | None = None


class ManuscriptCheckpointRequest(BaseModel):
    """Create one pending manuscript checkpoint."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=1)
    kind: str
    unit_id: str | None = None
    supersedes_id: str | None = None


class ManuscriptCheckpointResolutionRequest(BaseModel):
    """Resolve a pending manuscript checkpoint through a PI decision."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=1)
    decision_id: str
    status: Literal["resolved", "rejected"]
    resolved_at: str


class VerificationAttestationRequest(BaseModel):
    """Append one immutable multidimensional claim-verification result."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=1)
    attestation: dict[str, Any]


def get_scoped_manuscript_service(
    project_id: str = Depends(require_project),
    db: Database = Depends(get_db),
    llm: LLMClient | None = Depends(get_llm),
    embeddings: EmbeddingService | None = Depends(get_embeddings),
) -> ManuscriptService:
    notes = NoteService(db=db, llm=llm, embeddings=embeddings, project_id=project_id)
    return ManuscriptService(db=db, notes=notes, project_id=project_id)


def get_scoped_native_manuscript_service(
    project_id: str = Depends(require_project),
    db: Database = Depends(get_db),
) -> NativeManuscriptService:
    return NativeManuscriptService(db=db, project_id=project_id)


def get_scoped_reference_validation_service(
    project_id: str = Depends(require_project),
    db: Database = Depends(get_db),
) -> ReferenceValidationService:
    return ReferenceValidationService(db=db, project_id=project_id)


def get_scoped_outline_service(
    project_id: str = Depends(require_project),
    db: Database = Depends(get_db),
) -> ManuscriptOutlineService:
    return ManuscriptOutlineService(db=db, project_id=project_id)


@router.post("/manuscripts", status_code=201)
async def register_manuscript(
    data: ManuscriptRegisterRequest,
    actor: str = Depends(get_transport_actor),
    svc: ManuscriptService = Depends(get_scoped_manuscript_service),
    native: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    """Compatibility register: create legacy jrn_ plus canonical man_."""
    entry = await svc.register(
        venue=data.venue,
        title=data.title,
        abstract=data.abstract,
        sections=data.sections,
        actor=actor,
    )
    canonical_id = await native.resolve_id(entry.id)
    return {
        "id": entry.id,
        "project_id": entry.project_id,
        "canonical_id": canonical_id,
        "legacy_journal_id": entry.id,
        "deprecated_id": True,
        "deprecation": (
            "The jrn_ manifest id is supported for one compatibility window; "
            "use canonical_id on native manuscript operations."
        ),
        "title": data.title,
        "venue": data.venue,
        "phase": "draft",
        "created_at": entry.created_at,
    }


@router.post("/manuscripts/native", status_code=201)
async def create_native_manuscript(
    data: ManuscriptCreate,
    actor: str = Depends(get_transport_actor),
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    """Create a canonical native manuscript without inferred ratification."""
    manuscript = await svc.create(data, actor=actor)
    return manuscript.model_dump()


@router.get("/manuscripts/{manuscript_id}")
async def get_manuscript(
    manuscript_id: str,
    svc: ManuscriptService = Depends(get_scoped_manuscript_service),
    native: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    """Read either a canonical man_ manuscript or a legacy jrn_ alias.

    Returns 404 if the journal entry does not exist OR if it is not
    tagged 'manuscript' (in which case it is a regular journal entry,
    not a Writer manuscript manifest).
    """
    native_record = await native.get(manuscript_id)
    if native_record is not None and manuscript_id.startswith("man_"):
        result = native_record.model_dump()
        result.update({
            "canonical_id": native_record.id,
            "requested_id": manuscript_id,
            "deprecated_id": False,
        })
        return result

    manuscript = await svc.get(manuscript_id)
    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail=f"Manuscript {manuscript_id} not found (or not tagged 'manuscript')",
        )
    canonical_id = await native.resolve_id(manuscript_id)
    manuscript.update({
        "canonical_id": canonical_id,
        "requested_id": manuscript_id,
        "deprecated_id": canonical_id is not None,
    })
    return manuscript


@router.patch("/manuscripts/{manuscript_id}")
async def update_native_manuscript(
    manuscript_id: str,
    data: ManuscriptMetadataUpdateRequest,
    actor: str = Depends(get_transport_actor),
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    try:
        return (
            await svc.update(
                manuscript_id,
                data.to_domain(),
                actor=actor,
            )
        ).model_dump()
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ManuscriptRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/manuscripts/{manuscript_id}/argument-spine")
async def upsert_argument_spine(
    manuscript_id: str,
    data: ArgumentSpineUpsertRequest,
    actor: str = Depends(get_transport_actor),
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
    patches: SemanticPatchService = Depends(get_scoped_semantic_patch_service),
) -> dict[str, Any]:
    """Apply an explicitly requested human bulk import through the proposal ledger.

    Agents and MCP callers must create an AI-attributed semantic proposal and
    leave its apply transition to a PI or web user. The native service method
    remains the internal primitive used by semantic-patch apply and pack import.
    """
    if actor != "web_ui":
        raise HTTPException(
            status_code=403,
            detail=(
                "direct argument-spine replacement is restricted to explicit "
                "human/web use; create an attributed semantic patch proposal instead"
            ),
        )
    try:
        # Preserve the route family's uniform 404 contract before proposal
        # preview converts a missing target into a generic validation error.
        await svc.get_context(manuscript_id)
        proposal = await patches.create_proposal(
            SemanticPatchProposalCreate(
                origin="human",
                intent="Replace the reviewed argument-spine projection.",
                reason=data.reason,
                created_by="web_ui",
                operations=[
                    {
                        "operation": "argument_spine_replace",
                        "manuscript_id": manuscript_id,
                        "expected_revision": data.expected_revision,
                        "spine": data.spine,
                    }
                ],
            )
        )
        await patches.apply_proposal(
            proposal["id"],
            SemanticPatchProposalTransition(
                expected_revision=1,
                actor="web_ui",
                reason=data.reason,
            ),
        )
        context = await svc.get_context(manuscript_id)
        context["semantic_patch_proposal_id"] = proposal["id"]
        return context
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ManuscriptRevisionConflict, SemanticPatchConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/manuscripts/{manuscript_id}/references")
async def get_manuscript_reference_manifest(
    manuscript_id: str,
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    """Read active citation membership and exact validation currency."""
    try:
        return await svc.get_reference_manifest(manuscript_id)
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/manuscripts/{manuscript_id}/references")
async def replace_manuscript_reference_manifest(
    manuscript_id: str,
    data: ManuscriptReferenceManifestReplace,
    actor: str = Depends(get_transport_actor),
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    """Atomically replace the authoritative active citation-key set."""
    try:
        return await svc.replace_reference_manifest(
            manuscript_id,
            data,
            actor=actor,
        )
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ManuscriptRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/manuscripts/{manuscript_id}/claims/{claim_ref}/ratifications")
async def ratify_manuscript_claim(
    manuscript_id: str,
    claim_ref: str,
    data: ClaimRatificationRequest,
    actor: str = Depends(get_transport_actor),
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    try:
        ratification = await svc.ratify_claim(
            manuscript_id,
            claim_id=claim_ref if claim_ref.startswith("mcl_") else None,
            local_key=None if claim_ref.startswith("mcl_") else claim_ref,
            claim_version=data.claim_version,
            decision_id=data.decision_id,
            expected_revision=data.expected_revision,
            ratified_at=data.ratified_at,
            actor=actor,
        )
        return ratification.model_dump()
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ManuscriptRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/manuscripts/{manuscript_id}/transition")
async def transition_manuscript(
    manuscript_id: str,
    data: ManuscriptTransitionRequest,
    actor: str = Depends(get_transport_actor),
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    try:
        manuscript = await svc.transition_phase(
            manuscript_id,
            expected_revision=data.expected_revision,
            target_phase=data.target_phase,
            target_state=data.target_state,
            actor=actor,
        )
        return manuscript.model_dump()
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ManuscriptRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/manuscripts/{manuscript_id}/context")
async def get_native_manuscript_context(
    manuscript_id: str,
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    try:
        return await svc.get_context(manuscript_id)
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/manuscripts/{manuscript_id}/readiness")
async def get_native_manuscript_readiness(
    manuscript_id: str,
    target_phase: str = Query(default="drafting"),
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    try:
        return await svc.get_readiness(
            manuscript_id,
            target_phase=target_phase,
        )
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/manuscripts/{manuscript_id}/spine")
async def export_native_argument_spine(
    manuscript_id: str,
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    try:
        return await svc.export_spine_projection(manuscript_id)
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/manuscripts/{manuscript_id}/outline")
async def get_progressive_manuscript_outline(
    manuscript_id: str,
    svc: ManuscriptOutlineService = Depends(get_scoped_outline_service),
) -> dict[str, Any]:
    """Project the L2-L5 outline, rationale completeness, and checkpoint state."""
    try:
        return await svc.get_outline(manuscript_id)
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/manuscripts/{manuscript_id}/outline/proposals", status_code=201)
async def prepare_progressive_outline_proposal(
    manuscript_id: str,
    data: OutlineProposalRequest,
    actor: str = Depends(get_transport_actor),
    svc: ManuscriptOutlineService = Depends(get_scoped_outline_service),
) -> dict[str, Any]:
    """Prepare a structural outline proposal without mutating the manuscript."""
    try:
        return await svc.prepare_proposal(manuscript_id, data, actor=actor)
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ManuscriptRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/manuscripts/{manuscript_id}/writing-candidates")
async def get_native_manuscript_writing_candidates(
    manuscript_id: str,
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    """Return cluster/RQ-smoothed, read-only candidate paper claims."""
    try:
        return await svc.get_writing_candidates(manuscript_id)
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/manuscripts/{manuscript_id}/checkpoints", status_code=201)
async def create_manuscript_checkpoint(
    manuscript_id: str,
    data: ManuscriptCheckpointRequest,
    actor: str = Depends(get_transport_actor),
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    try:
        checkpoint = await svc.create_checkpoint(
            ManuscriptCheckpointCreate(
                manuscript_id=manuscript_id,
                kind=data.kind,
                unit_id=data.unit_id,
                supersedes_id=data.supersedes_id,
            ),
            expected_revision=data.expected_revision,
            actor=actor,
        )
        return checkpoint.model_dump()
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ManuscriptRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/manuscripts/checkpoints/{checkpoint_id}/resolve")
async def resolve_manuscript_checkpoint(
    checkpoint_id: str,
    data: ManuscriptCheckpointResolutionRequest,
    actor: str = Depends(get_transport_actor),
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    try:
        checkpoint = await svc.resolve_checkpoint(
            checkpoint_id,
            ManuscriptCheckpointResolve(
                decision_id=data.decision_id,
                status=data.status,
                resolved_at=data.resolved_at,
            ),
            expected_revision=data.expected_revision,
            actor=actor,
        )
        return checkpoint.model_dump()
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ManuscriptRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/manuscripts/{manuscript_id}/verification-attestations",
    status_code=201,
)
async def record_manuscript_verification_attestation(
    manuscript_id: str,
    data: VerificationAttestationRequest,
    actor: str = Depends(get_transport_actor),
    svc: NativeManuscriptService = Depends(get_scoped_native_manuscript_service),
) -> dict[str, Any]:
    payload = dict(data.attestation)
    payload["manuscript_id"] = manuscript_id
    try:
        attestation = await svc.record_verification_attestation(
            ManuscriptClaimVerificationAttestationCreate.model_validate(payload),
            expected_revision=data.expected_revision,
            actor=actor,
        )
        return attestation.model_dump()
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ManuscriptRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/manuscripts/{manuscript_id}/reference-validations/{job_id}",
)
async def get_reference_validation_status(
    manuscript_id: str,
    job_id: str,
    svc: ReferenceValidationService = Depends(
        get_scoped_reference_validation_service
    ),
) -> dict[str, Any]:
    """Return project- and manuscript-scoped status for a historical job."""
    result = await svc.get_status(manuscript_id, job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Reference validation job not found")
    return result
