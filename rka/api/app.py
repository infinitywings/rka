"""FastAPI application factory with Phase 2 lifecycle."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from rka import __version__
from rka.api.routes import (
    academic as academic_routes,
    artifacts as artifact_routes,
    audit as audit_routes,
    checkpoints as checkpoints_routes,
    context as context_routes,
    decisions as decisions_routes,
    enrich as enrich_routes,
    events as events_routes,
    graph as graph_routes,
    literature as literature_routes,
    llm as llm_routes,
    missions as missions_routes,
    notes as notes_routes,
    project as project_routes,
    search as search_routes,
    summary as summary_routes,
    tags as tags_routes,
    workspace as workspace_routes,
    claims as claims_routes,
    clusters as clusters_routes,
    topics as topics_routes,
    research_map as research_map_routes,
    review_queue as review_queue_routes,
    onboarding as onboarding_routes,
)
from rka.config import RKAConfig
from rka.infra.database import Database
from rka.infra.embeddings import EmbeddingService
from rka.infra.llm import LLMClient
from rka.services.context import ContextEngine
from rka.services.search import SearchService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down database + Phase 2 services on startup/shutdown."""
    config: RKAConfig = app.state.config
    background_tasks: list[asyncio.Task] = []

    db = Database(config.database_url)
    await db.connect()
    await db.initialize_schema()
    await db.initialize_phase2_schema()
    app.state.db = db

    from rka.api.routes.llm import _load_llm_overrides

    await _load_llm_overrides(config, db)

    llm: LLMClient | None = None
    if config.llm_enabled:
        llm = LLMClient(config)
        logger.info("LLM enabled (model=%s, base=%s)", config.llm_model, config.llm_api_base or "default")

        async def _probe_llm() -> None:
            max_attempts = 6
            for attempt in range(1, max_attempts + 1):
                try:
                    if await llm.is_available():
                        logger.info("LLM health check passed on attempt %d/%d", attempt, max_attempts)
                        if config.llm_api_base and config.llm_context_window <= 4096:
                            from rka.api.routes.llm import _detect_context_window

                            ctx = await _detect_context_window(config.llm_api_base, config.llm_model)
                            if ctx:
                                config.llm_context_window = ctx
                                logger.info("Auto-detected context window: %d tokens", ctx)
                        return
                except Exception:
                    logger.exception(
                        "Background LLM startup probe failed on attempt %d/%d",
                        attempt,
                        max_attempts,
                    )

                if attempt < max_attempts:
                    delay_seconds = min(5 * attempt, 20)
                    logger.warning(
                        "LLM health check attempt %d/%d failed; retrying in %ds",
                        attempt,
                        max_attempts,
                        delay_seconds,
                    )
                    await asyncio.sleep(delay_seconds)

            logger.warning(
                "LLM health check FAILED after %d attempts — Q&A, summaries, and classification "
                "will error until the LLM backend is reachable. Ensure your configured LLM "
                "backend is running.",
                max_attempts,
            )

        background_tasks.append(asyncio.create_task(_probe_llm()))
    else:
        logger.warning(
            "LLM is DISABLED (RKA_LLM_ENABLED=false). Q&A, summaries, "
            "and classification features will not work. Set RKA_LLM_ENABLED=true "
            "and configure model/backend settings from the Settings page or environment."
        )
    app.state.llm = llm

    embeddings: EmbeddingService | None = None
    if config.embeddings_enabled:
        embeddings = EmbeddingService(model_name=config.embedding_model, db=db)
        logger.info("Embedding service enabled (model=%s)", config.embedding_model)
    app.state.embeddings = embeddings

    search = SearchService(db=db, embeddings=embeddings)
    app.state.search = search

    context = ContextEngine(
        db=db,
        search=search,
        llm=llm,
        hot_days=config.context_hot_days,
        warm_days=config.context_warm_days,
    )
    app.state.context = context

    logger.info(
        "RKA started — vec=%s, llm=%s, embeddings=%s",
        db.vec_available,
        config.llm_enabled,
        config.embeddings_enabled,
    )

    yield

    for task in background_tasks:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    await db.close()


def create_app(config: RKAConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    effective_config = config or RKAConfig()

    app = FastAPI(
        title="Research Knowledge Agent",
        description="REST API for AI-assisted research orchestration",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.config = effective_config
    app.state.db = None
    app.state.llm = None
    app.state.embeddings = None
    app.state.search = None
    app.state.context = None

    from rka.infra.llm import LLMUnavailableError

    @app.exception_handler(LLMUnavailableError)
    async def llm_unavailable_handler(request: Request, exc: LLMUnavailableError):
        return JSONResponse(
            status_code=503,
            content={
                "detail": str(exc),
                "error": "llm_unavailable",
                "hint": "Ensure LLM is enabled and model/backend settings are configured correctly.",
            },
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:9713",
            "http://127.0.0.1:9713",
            "http://localhost:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(project_routes.router, prefix="/api", tags=["project"])
    app.include_router(notes_routes.router, prefix="/api", tags=["notes"])
    app.include_router(decisions_routes.router, prefix="/api", tags=["decisions"])
    app.include_router(literature_routes.router, prefix="/api", tags=["literature"])
    app.include_router(missions_routes.router, prefix="/api", tags=["missions"])
    app.include_router(checkpoints_routes.router, prefix="/api", tags=["checkpoints"])
    app.include_router(events_routes.router, prefix="/api", tags=["events"])
    app.include_router(search_routes.router, prefix="/api", tags=["search"])
    app.include_router(tags_routes.router, prefix="/api", tags=["tags"])
    app.include_router(context_routes.router, prefix="/api", tags=["context"])
    app.include_router(audit_routes.router, prefix="/api", tags=["audit"])
    app.include_router(academic_routes.router, prefix="/api", tags=["academic"])
    app.include_router(workspace_routes.router, prefix="/api", tags=["workspace"])
    app.include_router(enrich_routes.router, prefix="/api", tags=["enrich"])
    app.include_router(graph_routes.router, prefix="/api", tags=["graph"])
    app.include_router(summary_routes.router, prefix="/api", tags=["summary"])
    app.include_router(artifact_routes.router, prefix="/api", tags=["artifacts"])
    app.include_router(llm_routes.router, prefix="/api", tags=["llm"])
    app.include_router(claims_routes.router, prefix="/api", tags=["claims"])
    app.include_router(clusters_routes.router, prefix="/api", tags=["clusters"])
    app.include_router(topics_routes.router, prefix="/api", tags=["topics"])
    app.include_router(research_map_routes.router, prefix="/api", tags=["research-map"])
    app.include_router(review_queue_routes.router, prefix="/api", tags=["review-queue"])
    app.include_router(onboarding_routes.router, prefix="/api", tags=["onboarding"])

    @app.get("/api/health")
    async def health(request: Request):
        db = request.app.state.db
        llm = request.app.state.llm
        config = request.app.state.config

        llm_status = "disabled"
        if llm:
            llm_status = "available" if llm.available else "unavailable"

        return {
            "status": "ok",
            "version": __version__,
            "vec_available": db.vec_available,
            "llm_status": llm_status,
            "llm_model": config.llm_model if llm else None,
        }

    _candidates = [
        Path.cwd() / "web" / "dist",
        Path(__file__).resolve().parent.parent.parent / "web" / "dist",
    ]
    _web_dist = next((p for p in _candidates if p.is_dir()), None)
    if _web_dist and _web_dist.is_dir():
        _index_html = _web_dist / "index.html"
        _assets_dir = _web_dist / "assets"
        if _assets_dir.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=str(_assets_dir)),
                name="static-assets",
            )

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            file_path = _web_dist / full_path
            if full_path and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(_index_html))

        logger.info("Web UI served from %s", _web_dist)
    else:
        logger.info("No web UI build found (run 'cd web && npm run build'). Searched: %s", [str(p) for p in _candidates])

    return app


app = create_app()
