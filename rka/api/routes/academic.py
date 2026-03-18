"""Academic import routes — BibTeX, DOI enrichment, Mermaid export, batch import."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from rka.services.academic import AcademicImportService
from rka.api.deps import get_scoped_academic_service

router = APIRouter()


# ---- BibTeX Import ----

class BibtexImportRequest(BaseModel):
    bibtex: str
    default_status: str = "to_read"
    added_by: str = "import"
    skip_duplicates: bool = True


@router.post("/import/bibtex")
async def import_bibtex(
    data: BibtexImportRequest,
    svc: AcademicImportService = Depends(get_scoped_academic_service),
):
    """Import literature entries from BibTeX content."""
    return await svc.import_bibtex(
        bibtex_content=data.bibtex,
        default_status=data.default_status,
        added_by=data.added_by,
        skip_duplicates=data.skip_duplicates,
    )


@router.post("/import/bibtex-file")
async def import_bibtex_file(
    file: UploadFile = File(...),
    default_status: str = "to_read",
    added_by: str = "import",
    skip_duplicates: bool = True,
    svc: AcademicImportService = Depends(get_scoped_academic_service),
):
    """Import literature entries from an uploaded .bib file."""
    content = await file.read()
    return await svc.import_bibtex(
        bibtex_content=content.decode("utf-8"),
        default_status=default_status,
        added_by=added_by,
        skip_duplicates=skip_duplicates,
    )


# ---- DOI Enrichment ----

@router.post("/literature/{lit_id}/enrich-doi")
async def enrich_from_doi(
    lit_id: str,
    svc: AcademicImportService = Depends(get_scoped_academic_service),
):
    """Enrich a literature entry by looking up its DOI via CrossRef."""
    result = await svc.enrich_from_doi(lit_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ---- Mermaid Decision Tree Export ----

@router.get("/decisions/mermaid")
async def export_mermaid(
    phase: str | None = None,
    active_only: bool = False,
    svc: AcademicImportService = Depends(get_scoped_academic_service),
):
    """Export the decision tree as a Mermaid flowchart diagram."""
    mermaid = await svc.export_decisions_mermaid(phase=phase, active_only=active_only)
    return {"mermaid": mermaid}


# ---- Document Ingestion ----

class IngestDocumentRequest(BaseModel):
    content: str
    source: str = "brain"
    default_type: str = "finding"
    phase: str | None = None
    tags: list[str] | None = None
    related_literature: list[str] | None = None
    related_decisions: list[str] | None = None
    related_mission: str | None = None
    split_by_headings: bool = True
    # v2.1
    provenance_type: str | None = None
    role_id: str | None = None


@router.post("/ingest/document")
async def ingest_document(
    data: IngestDocumentRequest,
    svc: AcademicImportService = Depends(get_scoped_academic_service),
):
    """Ingest a markdown document by splitting into journal entries."""
    return await svc.ingest_document(
        content=data.content,
        source=data.source,
        default_type=data.default_type,
        phase=data.phase,
        tags=data.tags,
        related_literature=data.related_literature,
        related_decisions=data.related_decisions,
        related_mission=data.related_mission,
        split_by_headings=data.split_by_headings,
        provenance_type=data.provenance_type,
        role_id=data.role_id,
    )


# ---- Batch Import ----

class BatchImportEntry(BaseModel):
    """A single entry in a batch import."""
    entity_type: str  # "note" | "literature" | "decision"
    data: dict


class BatchImportRequest(BaseModel):
    entries: list[BatchImportEntry]
    actor: str = "import"


@router.post("/import/batch")
async def batch_import(
    req: BatchImportRequest,
    svc: AcademicImportService = Depends(get_scoped_academic_service),
):
    """Batch import multiple entries of different types.

    Supports: note, literature, decision.
    """
    from rka.models.literature import LiteratureCreate
    from rka.models.journal import JournalEntryCreate
    from rka.models.decision import DecisionCreate
    from rka.services.decisions import DecisionService
    from rka.services.notes import NoteService

    results = {"imported": [], "errors": []}
    note_svc = NoteService(
        svc.lit.db,
        llm=svc.lit.llm,
        embeddings=svc.lit.embeddings,
        project_id=svc.lit.project_id,
    )
    dec_svc = DecisionService(
        svc.lit.db,
        llm=svc.lit.llm,
        embeddings=svc.lit.embeddings,
        project_id=svc.lit.project_id,
    )

    for i, entry in enumerate(req.entries):
        try:
            if entry.entity_type == "literature":
                data = LiteratureCreate(**entry.data)
                lit = await svc.lit.create(data, actor=req.actor)
                results["imported"].append({"index": i, "id": lit.id, "type": "literature"})

            elif entry.entity_type == "note":
                data = JournalEntryCreate(**entry.data)
                note = await note_svc.create(data, actor=req.actor)
                results["imported"].append({"index": i, "id": note.id, "type": "note"})

            elif entry.entity_type == "decision":
                data = DecisionCreate(**entry.data)
                dec = await dec_svc.create(data, actor=req.actor)
                results["imported"].append({"index": i, "id": dec.id, "type": "decision"})

            else:
                results["errors"].append({
                    "index": i, "error": f"Unknown entity type: {entry.entity_type}"
                })

        except Exception as exc:
            results["errors"].append({"index": i, "error": str(exc)})

    return results
