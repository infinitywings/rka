"""FastAPI dependency injection — DB and service instances with Phase 2 support."""

from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import Depends, Header, HTTPException, Query

from rka.config import RKAConfig
from rka.infra.database import Database
from rka.infra.llm import LLMClient
from rka.infra.embeddings import EmbeddingService
from rka.services.project import ProjectService
from rka.services.notes import NoteService
from rka.services.decisions import DecisionService
from rka.services.literature import LiteratureService
from rka.services.missions import MissionService
from rka.services.checkpoints import CheckpointService
from rka.services.events import EventService
from rka.services.search import SearchService
from rka.services.context import ContextEngine
from rka.services.audit import AuditService
from rka.services.academic import AcademicImportService
from rka.services.workspace import WorkspaceService
from rka.services.graph import GraphService
from rka.services.summary import SummaryService, QAService
from rka.services.artifacts import ArtifactService
from rka.services.knowledge_pack import KnowledgePackService

logger = logging.getLogger(__name__)


@lru_cache()
def get_config() -> RKAConfig:
    if _config is not None:
        return _config
    return RKAConfig()


# Singleton instances (initialized in app lifespan)
_db: Database | None = None
_config: RKAConfig | None = None
_llm: LLMClient | None = None
_embeddings: EmbeddingService | None = None
_search: SearchService | None = None
_context: ContextEngine | None = None

DEFAULT_PROJECT_ID = "proj_default"


def set_config(config: RKAConfig) -> None:
    global _config
    _config = config


def get_project_id(
    x_rka_project: str | None = Header(default=None, alias="X-RKA-Project"),
    project_id: str | None = Query(default=None),
) -> str:
    """Resolve project id from header/query with legacy-compatible default."""
    return (x_rka_project or project_id or DEFAULT_PROJECT_ID).strip()


async def require_project(project_id: str = Depends(get_project_id)) -> str:
    """Validate project exists before executing project-scoped operations."""
    db = get_db()
    row = await db.fetchone("SELECT id FROM projects WHERE id = ?", [project_id])
    if not row:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return project_id


def get_db() -> Database:
    if _db is None:
        raise RuntimeError("Database not initialized")
    return _db


def set_db(db: Database) -> None:
    global _db
    _db = db


def get_llm() -> LLMClient | None:
    return _llm


def set_llm(llm: LLMClient | None) -> None:
    global _llm
    _llm = llm


def get_embeddings() -> EmbeddingService | None:
    return _embeddings


def set_embeddings(emb: EmbeddingService | None) -> None:
    global _embeddings
    _embeddings = emb


def get_search_service(project_id: str = DEFAULT_PROJECT_ID) -> SearchService:
    if _search is not None:
        return _search.with_project(project_id)
    return SearchService(get_db(), embeddings=_embeddings, project_id=project_id)


def set_search_service(svc: SearchService | None) -> None:
    global _search
    _search = svc


def get_context_engine() -> ContextEngine | None:
    return _context


def set_context_engine(ctx: ContextEngine | None) -> None:
    global _context
    _context = ctx


# Service factories — inject LLM + embeddings when available
def get_project_service() -> ProjectService:
    return ProjectService(get_db())


def get_note_service(project_id: str = DEFAULT_PROJECT_ID) -> NoteService:
    return NoteService(get_db(), llm=_llm, embeddings=_embeddings, project_id=project_id)


def get_scoped_note_service(project_id: str = Depends(require_project)) -> NoteService:
    return get_note_service(project_id=project_id)


def get_decision_service(project_id: str = DEFAULT_PROJECT_ID) -> DecisionService:
    return DecisionService(get_db(), llm=_llm, embeddings=_embeddings, project_id=project_id)


def get_scoped_decision_service(project_id: str = Depends(require_project)) -> DecisionService:
    return get_decision_service(project_id=project_id)


def get_literature_service(project_id: str = DEFAULT_PROJECT_ID) -> LiteratureService:
    return LiteratureService(get_db(), llm=_llm, embeddings=_embeddings, project_id=project_id)


def get_scoped_literature_service(project_id: str = Depends(require_project)) -> LiteratureService:
    return get_literature_service(project_id=project_id)


def get_mission_service(project_id: str = DEFAULT_PROJECT_ID) -> MissionService:
    return MissionService(get_db(), llm=_llm, embeddings=_embeddings, project_id=project_id)


def get_scoped_mission_service(project_id: str = Depends(require_project)) -> MissionService:
    return get_mission_service(project_id=project_id)


def get_checkpoint_service(project_id: str = DEFAULT_PROJECT_ID) -> CheckpointService:
    return CheckpointService(get_db(), project_id=project_id)


def get_scoped_checkpoint_service(project_id: str = Depends(require_project)) -> CheckpointService:
    return get_checkpoint_service(project_id=project_id)


def get_event_service(project_id: str = DEFAULT_PROJECT_ID) -> EventService:
    return EventService(get_db(), project_id=project_id)


def get_scoped_event_service(project_id: str = Depends(require_project)) -> EventService:
    return get_event_service(project_id=project_id)


def get_audit_service(project_id: str = DEFAULT_PROJECT_ID) -> AuditService:
    return AuditService(get_db(), project_id=project_id)


def get_scoped_audit_service(project_id: str = Depends(require_project)) -> AuditService:
    return get_audit_service(project_id=project_id)


def get_academic_service(project_id: str = DEFAULT_PROJECT_ID) -> AcademicImportService:
    return AcademicImportService(
        get_literature_service(project_id=project_id),
        note_service=get_note_service(project_id=project_id),
    )


def get_scoped_academic_service(project_id: str = Depends(require_project)) -> AcademicImportService:
    return get_academic_service(project_id=project_id)


def get_workspace_service(project_id: str = DEFAULT_PROJECT_ID) -> WorkspaceService:
    return WorkspaceService(
        db=get_db(),
        academic_service=get_academic_service(project_id=project_id),
        note_service=get_note_service(project_id=project_id),
        literature_service=get_literature_service(project_id=project_id),
        llm=_llm,
    )


def get_scoped_workspace_service(project_id: str = Depends(require_project)) -> WorkspaceService:
    return get_workspace_service(project_id=project_id)


def get_graph_service() -> GraphService:
    return GraphService(get_db())


def get_summary_service(project_id: str = DEFAULT_PROJECT_ID) -> SummaryService:
    return SummaryService(get_db(), llm=_llm, embeddings=_embeddings, project_id=project_id)


def get_scoped_summary_service(project_id: str = Depends(require_project)) -> SummaryService:
    return get_summary_service(project_id=project_id)


def get_qa_service(project_id: str = DEFAULT_PROJECT_ID) -> QAService:
    return QAService(get_db(), llm=_llm, embeddings=_embeddings, project_id=project_id)


def get_scoped_qa_service(project_id: str = Depends(require_project)) -> QAService:
    return get_qa_service(project_id=project_id)


def get_artifact_service(project_id: str = DEFAULT_PROJECT_ID) -> ArtifactService:
    return ArtifactService(get_db(), llm=_llm, embeddings=_embeddings, project_id=project_id)


def get_scoped_artifact_service(project_id: str = Depends(require_project)) -> ArtifactService:
    return get_artifact_service(project_id=project_id)


def get_knowledge_pack_service(project_id: str = DEFAULT_PROJECT_ID) -> KnowledgePackService:
    return KnowledgePackService(get_db(), llm=_llm, embeddings=_embeddings, project_id=project_id)


def get_scoped_knowledge_pack_service(project_id: str = Depends(require_project)) -> KnowledgePackService:
    return get_knowledge_pack_service(project_id=project_id)
