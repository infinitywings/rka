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
    changes as changes_routes,
    config as config_routes,
    context as context_routes,
    decisions as decisions_routes,
    enrich as enrich_routes,
    entities as entities_routes,
    events as events_routes,
    graph as graph_routes,
    literature as literature_routes,
    llm as llm_routes,
    manuscripts as manuscripts_routes,
    manuscript_sources as manuscript_source_routes,
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
    maintenance as maintenance_routes,
    verification as verification_routes,
    researcher_tools as researcher_tools_routes,
    hooks as hooks_routes,
    interpretations as interpretations_routes,
    experiments as experiments_routes,
    planning as planning_routes,
    semantic_patches as semantic_patch_routes,
    zotero_config as zotero_config_routes,
)
from rka.config import RKAConfig
from rka.contracts import is_writer_compatibility_path as _is_writer_compatibility_path
from rka.infra.database import Database
from rka.infra.embeddings import EmbeddingService
from rka.infra.llm import LLMClient
from rka.services.context import ContextEngine
from rka.services.search import SearchService

logger = logging.getLogger(__name__)

_WRITER_MIGRATION_TARGET = "https://github.com/rka-project/rka-writer"


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
        logger.info(
            "LLM enabled (model=%s, base=%s)", config.llm_model, config.llm_api_base or "default"
        )

        async def _probe_llm() -> None:
            max_attempts = 6
            for attempt in range(1, max_attempts + 1):
                try:
                    if await llm.is_available():
                        logger.info(
                            "LLM health check passed on attempt %d/%d", attempt, max_attempts
                        )
                        if config.llm_api_base and config.llm_context_window <= 4096:
                            from rka.api.routes.llm import _detect_context_window

                            ctx = await _detect_context_window(
                                config.llm_api_base, config.llm_model
                            )
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
        # Mission D first-run hook: persist DEFAULT_CONFIG to
        # /data/embedding_config.json on first boot if it doesn't exist,
        # then load whatever's on disk through the pluggable factory.
        # Falls back to legacy FastEmbed if the config file is corrupt or
        # the data_dir isn't writable (e.g. test fixtures with default
        # `/data`, read-only volume mounts).
        from rka.services.embedding_config import (
            DEFAULT_CONFIG,
            EmbeddingConfigError,
            EmbeddingConfigService,
        )
        from rka.services.embedding_reshape import reshape_all_vec_tables_if_needed

        cfg_svc = EmbeddingConfigService(config_dir=config.data_dir)
        try:
            if not cfg_svc.config_path.exists():
                try:
                    cfg_svc.save_config(DEFAULT_CONFIG.model_copy(), actor="system-default")
                    logger.info(
                        "first-run: persisted DEFAULT embedding config to %s",
                        cfg_svc.config_path,
                    )
                except (OSError, EmbeddingConfigError) as exc:
                    # data_dir not writable (e.g. read-only test fixture).
                    # Silent fall-through to legacy FastEmbed below.
                    logger.warning(
                        "could not persist DEFAULT embedding config to %s: %s; "
                        "continuing with in-memory default",
                        cfg_svc.config_path,
                        exc,
                    )
                    raise EmbeddingConfigError(
                        "data_dir not writable; using legacy fastembed", hint=""
                    )
            embedding_cfg = cfg_svc.load_config()
            embeddings = EmbeddingService.from_config(embedding_cfg.model_dump(), db=db)
            logger.info(
                "Embedding service enabled (backend=%s, dim=%d)",
                embedding_cfg.backend,
                embeddings.dim,
            )

            # v2.5.5 startup-hook (mis_01KS1RFNM2T1HTB077G507T1FR): reshape
            # every vec_* table whose dim no longer matches the configured
            # embedding dim. The v2.4 path covered vec_claims only; the
            # other five hardcoded float[768] tables were stuck at the old
            # dim and their embedding_metadata kept the stale model_name.
            target_dim = int(embedding_cfg.config.get("dim") or embeddings.dim or 768)
            reshape_results = await reshape_all_vec_tables_if_needed(db, dim=target_dim)
            reshaped = [(t, p) for t, (did, p) in reshape_results.items() if did]
            if reshaped:
                logger.info(
                    "vec tables reshaped at startup (dim=%d): %s",
                    target_dim,
                    ", ".join(f"{t} pending={p}" for t, p in reshaped),
                )
        except EmbeddingConfigError as exc:
            # Corrupt config OR unwritable data_dir: fall back to legacy
            # FastEmbed so the API still starts. The Settings page renders
            # the 422 hint on next GET.
            logger.warning(
                "embedding config error at startup: %s; falling back to legacy FastEmbed",
                exc.detail,
            )
            embeddings = EmbeddingService(model_name=config.embedding_model, db=db)
    app.state.embeddings = embeddings

    search = SearchService(db=db, embeddings=embeddings)
    app.state.search = search

    context = ContextEngine(
        db=db,
        search=search,
        llm=llm,
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
        description="REST API for provenance-aware research records and retrieval",
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

    # Affordance G (Mission B / mis_01KR209WY4M6WQFEXRH79KC2ZF):
    # Replace the generic 500 the import route would otherwise surface
    # for KnowledgePackIntegrityError with a structured 422 carrying
    # the per-issue findings (category, severity, count, ids,
    # description, fix_action). Severity field is populated by Affordance
    # E so consumers can distinguish critical vs warning without knowing
    # the category list.
    from rka.services.base import EntityLinkValidationError
    from rka.services.knowledge_pack import KnowledgePackIntegrityError

    @app.exception_handler(EntityLinkValidationError)
    async def entity_link_validation_handler(
        request: Request,
        exc: EntityLinkValidationError,
    ):
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_entity_link",
                "detail": str(exc),
            },
        )

    @app.exception_handler(KnowledgePackIntegrityError)
    async def knowledge_pack_integrity_handler(
        request: Request,
        exc: KnowledgePackIntegrityError,
    ):
        return JSONResponse(
            status_code=422,
            content={
                "error": "knowledge_pack_integrity_failed",
                "detail": str(exc),
                "issues": exc.issues,
                "hint": "Resolve the listed integrity issues at the pack source, then retry the import.",
            },
        )

    @app.middleware("http")
    async def writer_compatibility_notice(request: Request, call_next):
        """Add an out-of-band notice without changing legacy response bodies."""

        response = await call_next(request)
        if _is_writer_compatibility_path(request.url.path):
            response.headers["X-RKA-Compatibility-Status"] = "deprecated"
            response.headers["X-RKA-Removal-Milestone"] = "E5"
            response.headers["Link"] = f'<{_WRITER_MIGRATION_TARGET}>; rel="successor-version"'
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:9713",
            "http://127.0.0.1:9713",
            "http://localhost:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-RKA-Compatibility-Status",
            "X-RKA-Removal-Milestone",
            "Link",
        ],
    )

    app.include_router(project_routes.router, prefix="/api", tags=["project"])
    app.include_router(notes_routes.router, prefix="/api", tags=["notes"])
    app.include_router(manuscripts_routes.router, prefix="/api", tags=["manuscripts"])
    app.include_router(
        manuscript_source_routes.router,
        prefix="/api",
        tags=["manuscript-sources"],
    )
    app.include_router(decisions_routes.router, prefix="/api", tags=["decisions"])
    app.include_router(literature_routes.router, prefix="/api", tags=["literature"])
    app.include_router(missions_routes.router, prefix="/api", tags=["missions"])
    app.include_router(checkpoints_routes.router, prefix="/api", tags=["checkpoints"])
    app.include_router(changes_routes.router, prefix="/api", tags=["changes"])
    app.include_router(events_routes.router, prefix="/api", tags=["events"])
    app.include_router(search_routes.router, prefix="/api", tags=["search"])
    app.include_router(tags_routes.router, prefix="/api", tags=["tags"])
    app.include_router(context_routes.router, prefix="/api", tags=["context"])
    app.include_router(audit_routes.router, prefix="/api", tags=["audit"])
    app.include_router(academic_routes.router, prefix="/api", tags=["academic"])
    app.include_router(workspace_routes.router, prefix="/api", tags=["workspace"])
    app.include_router(enrich_routes.router, prefix="/api", tags=["enrich"])
    app.include_router(entities_routes.router, prefix="/api", tags=["entities"])
    app.include_router(graph_routes.router, prefix="/api", tags=["graph"])
    app.include_router(summary_routes.router, prefix="/api", tags=["summary"])
    app.include_router(artifact_routes.router, prefix="/api", tags=["artifacts"])
    app.include_router(llm_routes.router, prefix="/api", tags=["llm"])
    app.include_router(claims_routes.router, prefix="/api", tags=["claims"])
    app.include_router(
        interpretations_routes.router,
        prefix="/api",
        tags=["interpretation-staging"],
    )
    app.include_router(
        experiments_routes.router,
        prefix="/api",
        tags=["experiments"],
    )
    app.include_router(
        planning_routes.router,
        prefix="/api",
        tags=["manuscript-planning"],
    )
    app.include_router(
        semantic_patch_routes.router,
        prefix="/api",
        tags=["semantic-patches"],
    )
    app.include_router(clusters_routes.router, prefix="/api", tags=["clusters"])
    app.include_router(topics_routes.router, prefix="/api", tags=["topics"])
    app.include_router(research_map_routes.router, prefix="/api", tags=["research-map"])
    app.include_router(review_queue_routes.router, prefix="/api", tags=["review-queue"])
    app.include_router(onboarding_routes.router, prefix="/api", tags=["onboarding"])
    app.include_router(maintenance_routes.router, prefix="/api", tags=["maintenance"])
    app.include_router(verification_routes.router, prefix="/api", tags=["verification"])
    app.include_router(researcher_tools_routes.router, prefix="/api", tags=["researcher-tools"])
    app.include_router(hooks_routes.router, prefix="/api", tags=["hooks"])
    # Mission D T3: pluggable embedding backend configuration.
    # Routes carry their own /api/config/... prefix internally; mount with
    # an empty prefix so the documented paths don't end up doubled.
    app.include_router(config_routes.router, tags=["config"])
    # v2.7.0.2 Bug 1 fix: persistent Zotero config at /data/zotero_config.json
    # so the linker survives `docker compose up -d --build` without re-sourcing
    # env. Routes carry their own /api/config/zotero prefix.
    app.include_router(zotero_config_routes.router, tags=["zotero-config"])

    @app.get("/api/health")
    async def health(request: Request):
        # Mission D (v2.4.0): /api/health no longer returns LLM fields per
        # the LLM-capability-removal directive jrn_01KRNZBS50K250HHHHEC58E4GC.
        # LLM availability is covered by the orchestrator's Claude Code SDK
        # path in a follow-up release.
        db = request.app.state.db
        return {
            "status": "ok",
            "version": __version__,
            "vec_available": db.vec_available,
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
        logger.info(
            "No web UI build found (run 'cd web && npm run build'). Searched: %s",
            [str(p) for p in _candidates],
        )

    return app


app = create_app()
