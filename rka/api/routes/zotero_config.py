"""Zotero configuration REST endpoints (v2.7.0.2 Bug 1 fix).

Three routes that mirror the embedding-config shape:

  - GET  /api/config/zotero        — current config (api_key redacted)
  - PUT  /api/config/zotero        — validate + test + persist
  - POST /api/config/zotero/test   — probe without persisting

Error mapping (Affordance G pattern):
  ZoteroConfigError → 422 {"error": "zotero_config_invalid",
                            "detail": ..., "hint": ...}

Pre-v2.7.0.2 the linker read creds only from ``os.environ``. The
rka-server + rka-worker Docker images don't ship Zotero env, so the
linker permanently reported ``zotero_not_configured`` unless the
operator ``source .env``'d before every ``docker compose up
--force-recreate``. This route persists creds to
``/data/zotero_config.json`` (the rka-data volume) so they survive
container recreate. The env vars still win when set — operator
override path stays intact for one-off testing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from rka.config import RKAConfig
from rka.services.zotero_config import (
    ZoteroConfig,
    ZoteroConfigError,
    ZoteroConfigService,
)

logger = logging.getLogger(__name__)

router = APIRouter()

REDACTED_API_KEY = "***"


def _config_service(request: Request) -> ZoteroConfigService:
    """Per-request service instance pointed at the app's /data dir."""
    cfg: RKAConfig = request.app.state.config
    data_dir = getattr(cfg, "data_dir", None) or Path("/data")
    return ZoteroConfigService(config_dir=data_dir)


def _redact(config: ZoteroConfig) -> dict[str, Any]:
    """Return a dict copy of `config` with `api_key` redacted."""
    payload = config.model_dump()
    if payload.get("api_key"):
        payload["api_key"] = REDACTED_API_KEY
    return payload


def _422(error: str, detail: str, hint: str = "") -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": error, "detail": detail, "hint": hint},
    )


@router.get("/api/config/zotero")
async def get_zotero_config(request: Request) -> Any:
    """Return the persisted Zotero config with `api_key` redacted.

    When the file doesn't exist, returns the empty default
    (``api_key=""``, ``library_id=""``) so the UI can render a fresh
    form. ``is_configured()`` on the client side: both fields non-empty.
    """
    try:
        cfg = _config_service(request).load_config()
    except ZoteroConfigError as exc:
        return _422("zotero_config_invalid", str(exc), exc.hint or "")
    return _redact(cfg)


@router.put("/api/config/zotero")
async def put_zotero_config(
    request: Request,
    body: ZoteroConfig,
    actor: str = Query(default="pi"),
) -> Any:
    """Validate + test + persist a new Zotero config.

    Probes the key against Zotero's ``/keys/<key>`` endpoint before
    saving so we don't persist creds that don't actually work. On
    success, returns the redacted persisted config + the probe detail.
    """
    svc = _config_service(request)

    # Step 1: probe the requested config before persisting.
    test_result = await svc.test_config(body)
    if not test_result.get("ok"):
        return _422(
            "zotero_config_invalid",
            f"connection test failed: {test_result.get('detail')}",
            "verify api_key + library_id + library_type at https://www.zotero.org/settings/keys",
        )

    # Step 2: persist.
    try:
        saved = svc.save_config(body, actor=actor)
    except ZoteroConfigError as exc:
        return _422("zotero_config_invalid", str(exc), exc.hint or "")

    return JSONResponse(
        status_code=200,
        content={**_redact(saved), "test": test_result},
    )


@router.post("/api/config/zotero/test")
async def test_zotero_config(request: Request, body: ZoteroConfig) -> Any:
    """Probe the supplied creds against Zotero's `/keys/<key>` endpoint.

    Does NOT persist. Used by the Web UI's "Test connection" button
    before the user commits.
    """
    svc = _config_service(request)
    result = await svc.test_config(body)
    return result
