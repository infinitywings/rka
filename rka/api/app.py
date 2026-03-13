"""FastAPI application factory with Phase 2 lifecycle."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from rka.config import RKAConfig
from rka.infra.database import Database
from rka.infra.llm import LLMClient
from rka.infra.embeddings import EmbeddingService
from rka.services.search import SearchService
from rka.services.context import ContextEngine
from rka.api.deps import (
    set_db, set_llm, set_embeddings, set_search_service, set_context_engine,
    get_config, set_config,
)
from rka.api.routes import (
    project as project_routes,
    notes as notes_routes,
    decisions as decisions_routes,
    literature as literature_routes,
    missions as missions_routes,
    checkpoints as checkpoints_routes,
    events as events_routes,
    search as search_routes,
    tags as tags_routes,
    context as context_routes,
    audit as audit_routes,
    academic as academic_routes,
    workspace as workspace_routes,
    enrich as enrich_routes,
    graph as graph_routes,
    summary as summary_routes,
    artifacts as artifact_routes,
    llm as llm_routes,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down database + Phase 2 services on startup/shutdown."""
    config = getattr(app.state, "config", None) or get_config()
    background_tasks: list[asyncio.Task] = []

    # Phase 1: Database
    db = Database(config.database_url)
    await db.connect()
    await db.initialize_schema()
    set_db(db)

    # Phase 2: Schema extensions (FTS5 + optionally sqlite-vec)
    await db.initialize_phase2_schema()

    # Apply any DB-persisted LLM config overrides (from web UI settings)
    from rka.api.routes.llm import _load_llm_overrides
    await _load_llm_overrides(config)

    # LLM client — required for Q&A, summaries, and classification
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
                        # Auto-detect context window if not already set from DB
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
    set_llm(llm)

    # Phase 2: Embedding service
    embeddings: EmbeddingService | None = None
    if config.embeddings_enabled:
        embeddings = EmbeddingService(model_name=config.embedding_model, db=db)
        logger.info("Embedding service enabled (model=%s)", config.embedding_model)
    set_embeddings(embeddings)

    # Phase 2: Search service (hybrid FTS5 + vector)
    search = SearchService(db=db, embeddings=embeddings)
    set_search_service(search)

    # Phase 2: Context engine
    context = ContextEngine(
        db=db,
        search=search,
        llm=llm,
        hot_days=config.context_hot_days,
        warm_days=config.context_warm_days,
    )
    set_context_engine(context)

    logger.info(
        "RKA started — vec=%s, llm=%s, embeddings=%s",
        db.vec_available, config.llm_enabled, config.embeddings_enabled,
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
    effective_config = config or get_config()
    set_config(effective_config)

    app = FastAPI(
        title="Research Knowledge Agent",
        description="REST API for AI-assisted research orchestration",
        version="1.2.0",
        lifespan=lifespan,
    )
    app.state.config = effective_config

    # Global error handler for LLM unavailability
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

    # CORS for local web UI development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:9713",
            "http://127.0.0.1:9713",
            "http://localhost:5173",  # Vite dev server
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register route modules
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

    @app.get("/api/health")
    async def health():
        from rka.api.deps import get_db, get_llm
        db = get_db()
        llm = get_llm()
        llm_status = "disabled"
        if llm:
            llm_status = "available" if llm.available else "unavailable"
        return {
            "status": "ok",
            "version": "1.2.0",
            "vec_available": db.vec_available,
            "llm_status": llm_status,
            "llm_model": get_config().llm_model if llm else None,
        }

    # Phase 3: Static file serving for web UI
    # Search multiple locations: CWD, project root (dev), package dir (Docker)
    _candidates = [
        Path.cwd() / "web" / "dist",                            # CWD (Docker: /app)
        Path(__file__).resolve().parent.parent.parent / "web" / "dist",  # dev: repo root
    ]
    _web_dist = next((p for p in _candidates if p.is_dir()), None)
    if _web_dist and _web_dist.is_dir():
        _index_html = _web_dist / "index.html"

        # Mount static assets (JS, CSS, fonts) at /assets
        _assets_dir = _web_dist / "assets"
        if _assets_dir.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=str(_assets_dir)),
                name="static-assets",
            )

        # SPA catch-all: any non-API route returns index.html for client-side routing
        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            # Serve actual files from dist if they exist (e.g. favicon, robots.txt)
            file_path = _web_dist / full_path
            if full_path and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(_index_html))

        logger.info("Web UI served from %s", _web_dist)
    else:
        logger.info("No web UI build found (run 'cd web && npm run build'). Searched: %s", [str(p) for p in _candidates])

    return app


# Module-level instance for uvicorn (e.g. `uvicorn rka.api.app:app`)
app = create_app()
