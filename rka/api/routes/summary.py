"""Summary and QA API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from rka.api.deps import get_scoped_summary_service, get_scoped_qa_service
from rka.services.summary import SummaryService, QAService

router = APIRouter()


# ---------- Request models ----------

class GenerateSummaryRequest(BaseModel):
    scope_type: str = Field(..., description="Scope: phase, mission, tag, project")
    scope_id: str | None = Field(None, description="Scope ID (e.g. phase name, mission ID)")
    granularity: str = Field("paragraph", description="one_line, paragraph, or narrative")
    produced_by: str = Field("llm", description="Who produced this summary")


class AskRequest(BaseModel):
    question: str = Field(..., description="Research question to answer")
    session_id: str | None = Field(None, description="Existing QA session ID (for follow-ups)")
    scope_type: str | None = Field(None, description="Optional scope filter")
    scope_id: str | None = Field(None, description="Optional scope ID")
    actor: str = Field("pi", description="Who is asking")


class BlessRequest(BaseModel):
    actor: str = Field("pi")


# ---------- Summary routes ----------

@router.post("/summaries/generate")
async def generate_summary(
    req: GenerateSummaryRequest,
    svc: SummaryService = Depends(get_scoped_summary_service),
):
    """Generate a multi-granularity summary for a scope."""
    result = await svc.generate(
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        granularity=req.granularity,
        produced_by=req.produced_by,
    )
    if result is None:
        return {"error": "LLM unavailable or no evidence found"}
    return result


@router.get("/summaries")
async def list_summaries(
    scope_type: str | None = None,
    scope_id: str | None = None,
    blessed_only: bool = False,
    limit: int = Query(20, le=100),
    svc: SummaryService = Depends(get_scoped_summary_service),
):
    """List exploration summaries."""
    return await svc.list_summaries(
        scope_type=scope_type, scope_id=scope_id,
        blessed_only=blessed_only, limit=limit,
    )


@router.get("/summaries/{summary_id}")
async def get_summary(
    summary_id: str,
    svc: SummaryService = Depends(get_scoped_summary_service),
):
    """Get a single summary."""
    result = await svc.get(summary_id)
    if result is None:
        return {"error": "Summary not found"}
    return result


@router.post("/summaries/{summary_id}/bless")
async def bless_summary(
    summary_id: str,
    req: BlessRequest,
    svc: SummaryService = Depends(get_scoped_summary_service),
):
    """Mark a summary as blessed (human-approved)."""
    result = await svc.bless(summary_id, actor=req.actor)
    if result is None:
        return {"error": "Summary not found"}
    return result


# ---------- QA routes ----------

@router.post("/qa/ask")
async def ask_question(
    req: AskRequest,
    svc: QAService = Depends(get_scoped_qa_service),
):
    """Ask a research question grounded in knowledge base evidence."""
    result = await svc.ask(
        question=req.question,
        session_id=req.session_id,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        actor=req.actor,
    )
    if result is None:
        return {"error": "LLM unavailable"}
    return result


@router.get("/qa/sessions")
async def list_qa_sessions(
    limit: int = Query(20, le=100),
    svc: QAService = Depends(get_scoped_qa_service),
):
    """List QA sessions."""
    return await svc.list_sessions(limit=limit)


@router.get("/qa/sessions/{session_id}")
async def get_qa_session(
    session_id: str,
    svc: QAService = Depends(get_scoped_qa_service),
):
    """Get a QA session with all its logs."""
    result = await svc.get_session(session_id)
    if result is None:
        return {"error": "Session not found"}
    return result


@router.post("/qa/verify/{qa_log_id}/{source_index}")
async def verify_qa_source(
    qa_log_id: str,
    source_index: int,
    svc: QAService = Depends(get_scoped_qa_service),
):
    """Verify a cited source in a QA answer."""
    return await svc.verify_source(qa_log_id, source_index)
