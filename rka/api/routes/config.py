"""Embedding configuration REST endpoints (Mission D T3).

Four routes:

  - GET  /api/config/embedding              — current config (api_key redacted)
  - PUT  /api/config/embedding              — validate + test + persist;
                                              202 if backfill kicked off,
                                              200 if only api_key changed
  - POST /api/config/embedding/test         — probe without persisting
  - GET  /api/config/embedding/backfill/status[?job_id=…]
                                            — polling endpoint for the UI

Error mapping (Affordance G):
  EmbeddingConfigError → 422 {"error": "embedding_config_invalid",
                              "detail": ..., "hint": ...}
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from rka.api.deps import get_db, get_embeddings
from rka.config import RKAConfig
from rka.infra.embedding_backends import EmbeddingConfigError
from rka.infra.embeddings import EmbeddingService
from rka.services.embedding_backfill import (
    BackfillService,
    JobStatus,
    get_status,
    latest_status,
    register_job,
)
from rka.services.embedding_config import (
    EmbeddingConfig,
    EmbeddingConfigService,
)
from rka.services.embedding_reshape import reshape_all_vec_tables_if_needed

logger = logging.getLogger(__name__)

router = APIRouter()

REDACTED_API_KEY = "***"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_service(request: Request) -> EmbeddingConfigService:
    """Per-request service instance pointed at the app's configured /data dir.

    `RKAConfig` has a `data_dir` attribute set during app startup. Tests
    point this at `tmp_path` via the config fixture.
    """
    cfg: RKAConfig = request.app.state.config
    data_dir = getattr(cfg, "data_dir", None) or Path("/data")
    return EmbeddingConfigService(config_dir=data_dir)


def _redact(config: EmbeddingConfig) -> dict[str, Any]:
    """Return a dict copy of `config` with `config.api_key` redacted."""
    payload = config.model_dump()
    sub = payload.get("config") or {}
    if "api_key" in sub and sub["api_key"]:
        sub["api_key"] = REDACTED_API_KEY
        payload["config"] = sub
    return payload


def _422(error: str, detail: str, hint: str = "") -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": error, "detail": detail, "hint": hint},
    )


def _backend_signature(config: EmbeddingConfig) -> tuple[str, str, int]:
    """Identity tuple used to decide whether backfill needs to fire on PUT.

    Two configs that produce the same `(backend, model_or_name, dim)`
    tuple are interchangeable from the vec_claims table's perspective —
    only the api_key may have changed, no re-embed needed.
    """
    backend = config.backend
    sub = config.config or {}
    model = sub.get("model") or sub.get("model_name") or ""
    dim = int(sub.get("dim") or 0)
    return (backend, model, dim)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/config/embedding")
async def get_embedding_config(request: Request) -> Any:
    try:
        cfg = _config_service(request).load_config()
    except EmbeddingConfigError as exc:
        return _422("embedding_config_invalid", exc.detail, exc.hint)
    return _redact(cfg)


@router.put("/api/config/embedding")
async def put_embedding_config(
    request: Request,
    body: EmbeddingConfig,
    background_tasks: BackgroundTasks,
    actor: str = Query(default="pi"),
) -> Any:
    svc = _config_service(request)

    # Step 1: probe the requested config before persisting.
    test_result = await svc.test_config(body)
    if not test_result.ok:
        return _422(
            "embedding_config_invalid",
            f"connection test failed: {test_result.detail}",
            "verify base_url + model + api_key in Settings → Embeddings",
        )

    # Step 2: load prior config to determine if backfill is needed.
    try:
        prior = svc.load_config()
    except EmbeddingConfigError:
        # Treat a corrupt prior as "different" so backfill fires.
        prior = None

    needs_backfill = (
        prior is None or _backend_signature(prior) != _backend_signature(body)
    )

    # Step 3: persist.
    try:
        saved = svc.save_config(body, actor=actor)
    except EmbeddingConfigError as exc:
        return _422("embedding_config_invalid", exc.detail, exc.hint)

    if not needs_backfill:
        # api_key (or only-provenance) change — no re-embed.
        return JSONResponse(status_code=200, content=_redact(saved))

    # Step 4: kick off backfill in the background and return 202 + job ref.
    db = request.app.state.db
    new_embeddings = EmbeddingService.from_config(saved.model_dump(), db=db)
    # Swap the app-level embeddings handle so subsequent requests use it.
    request.app.state.embeddings = new_embeddings

    # v2.5.5 (mis_01KS1RFNM2T1HTB077G507T1FR): reshape EVERY vec_* table
    # before backfill starts. The v2.4 path reshaped vec_claims only;
    # this version covers vec_journal/decisions/literature/missions/
    # artifacts too, plus invalidates their stale metadata so backfill
    # picks them up.
    target_dim = int(
        (saved.config or {}).get("dim")
        or test_result.detected_dim
        or new_embeddings.dim
        or 768
    )
    reshape_results = await reshape_all_vec_tables_if_needed(db, dim=target_dim)

    status_obj = register_job()
    backfill_svc = BackfillService(db=db, embeddings=new_embeddings)
    background_tasks.add_task(_run_backfill_safely, backfill_svc, status_obj)

    return JSONResponse(
        status_code=202,
        content={
            **_redact(saved),
            "job_id": status_obj.job_id,
            "status_url": f"/api/config/embedding/backfill/status?job_id={status_obj.job_id}",
            "reshape": {
                table: {"did_reshape": did, "pending": pending}
                for table, (did, pending) in reshape_results.items()
            },
        },
    )


@router.post("/api/config/embedding/test")
async def test_embedding_config(request: Request, body: EmbeddingConfig) -> Any:
    svc = _config_service(request)
    try:
        result = await svc.test_config(body)
    except EmbeddingConfigError as exc:
        return _422("embedding_config_invalid", exc.detail, exc.hint)
    return {
        "ok": result.ok,
        "detail": result.detail,
        "detected_dim": result.detected_dim,
        "latency_ms": result.latency_ms,
    }


@router.get("/api/config/embedding/backfill/status")
async def get_backfill_status(job_id: str | None = Query(default=None)) -> Any:
    """Polling endpoint for the Settings UI progress bar.

    With `job_id`: return that specific job's snapshot. Without: return
    the most recent job (handy for the UI to pick up an in-progress
    backfill after a page refresh).
    """
    if job_id:
        status = get_status(job_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"unknown job_id: {job_id}")
        return status.snapshot()
    latest = latest_status()
    if latest is None:
        return {"state": "idle", "job_id": None}
    return latest.snapshot()


# ---------------------------------------------------------------------------
# Background-task helper
# ---------------------------------------------------------------------------


async def _run_backfill_safely(svc: BackfillService, status: JobStatus) -> None:
    """Wraps BackfillService.run_backfill so unhandled exceptions land in
    the status snapshot rather than the background-task logger."""
    try:
        await svc.run_backfill(status)
    except Exception as exc:  # noqa: BLE001
        status.state = "failed"
        status.error = str(exc)
        logger.exception("backfill job %s failed", status.job_id)
