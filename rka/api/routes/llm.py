"""LLM configuration routes — runtime config + health for the web UI."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from rka.api.deps import get_llm, get_config, get_db, set_llm
from rka.infra.llm import LLMClient

logger = logging.getLogger(__name__)
router = APIRouter()


class LLMStatus(BaseModel):
    enabled: bool
    available: bool
    model: str
    api_base: str | None
    api_key_set: bool
    think: bool
    context_window: int


class LLMConfigUpdate(BaseModel):
    enabled: bool | None = None
    model: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    think: bool | None = None


# ---- KV helpers ----

_KV_PREFIX = "llm."

async def _load_llm_overrides(config) -> None:
    """Apply any DB-persisted LLM settings over the .env defaults."""
    db = get_db()
    rows = await db.fetchall(
        "SELECT key, value FROM kv_store WHERE key LIKE 'llm.%'",
    )
    for row in rows:
        k = row["key"].removeprefix(_KV_PREFIX)
        v = row["value"]
        if k == "enabled":
            config.llm_enabled = v.lower() == "true"
        elif k == "model":
            config.llm_model = v
        elif k == "api_base":
            config.llm_api_base = v or None
        elif k == "api_key":
            config.llm_api_key = v or None
        elif k == "think":
            config.llm_think = v.lower() == "true"
        elif k == "context_window":
            try:
                config.llm_context_window = int(v)
            except ValueError:
                pass


async def _persist_llm_kv(config) -> None:
    """Persist LLM settings to kv_store in the database."""
    db = get_db()
    pairs = {
        "llm.enabled": str(config.llm_enabled).lower(),
        "llm.model": config.llm_model,
        "llm.api_base": config.llm_api_base or "",
        "llm.api_key": config.llm_api_key or "",
        "llm.think": str(config.llm_think).lower(),
        "llm.context_window": str(config.llm_context_window),
    }
    for key, value in pairs.items():
        await db.execute(
            "INSERT INTO kv_store (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [key, value],
        )
    await db.commit()


# ---- Routes ----

@router.get("/llm/status")
async def get_llm_status() -> LLMStatus:
    """Get current LLM configuration and availability."""
    config = get_config()
    llm = get_llm()
    return LLMStatus(
        enabled=config.llm_enabled,
        available=bool(llm and llm._available),
        model=config.llm_model,
        api_base=config.llm_api_base,
        api_key_set=bool(config.llm_api_key),
        think=config.llm_think,
        context_window=config.llm_context_window,
    )


@router.put("/llm/config")
async def update_llm_config(data: LLMConfigUpdate) -> LLMStatus:
    """Update LLM configuration at runtime, re-check availability, and persist to DB."""
    config = get_config()

    if data.enabled is not None:
        config.llm_enabled = data.enabled
    if data.model is not None:
        config.llm_model = data.model
    if data.api_base is not None:
        config.llm_api_base = data.api_base
    if data.api_key is not None:
        config.llm_api_key = data.api_key or None
    if data.think is not None:
        config.llm_think = data.think

    # Re-create LLM client with updated config
    llm: LLMClient | None = None
    if config.llm_enabled:
        llm = LLMClient(config)
        await llm.is_available()

        # Auto-detect context window from backend
        if config.llm_api_base and llm._available:
            ctx = await _detect_context_window(config.llm_api_base, config.llm_model)
            if ctx:
                config.llm_context_window = ctx
    set_llm(llm)

    # Persist to database so changes survive server restarts
    await _persist_llm_kv(config)

    return LLMStatus(
        enabled=config.llm_enabled,
        available=bool(llm and llm._available),
        model=config.llm_model,
        api_base=config.llm_api_base,
        api_key_set=bool(config.llm_api_key),
        think=config.llm_think,
        context_window=config.llm_context_window,
    )


class LLMModel(BaseModel):
    id: str
    owned_by: str | None = None
    context_length: int | None = None


def _normalize_base(api_base: str) -> str:
    """Strip trailing /v1 from base URL."""
    base = api_base.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base


async def _detect_context_window(api_base: str, model_id: str) -> int | None:
    """Auto-detect model context window from LM Studio native API or Ollama API.

    LM Studio: GET /api/v0/models → data[].max_context_length / loaded_context_length
    Ollama:    POST /api/show {name} → model_info.context_length
    Falls back to None if unavailable.
    """
    base = _normalize_base(api_base)
    # Strip the openai/ prefix used by LiteLLM routing
    bare_model = model_id.removeprefix("openai/").removeprefix("ollama/")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Try LM Studio native API first
            try:
                resp = await client.get(f"{base}/api/v0/models")
                if resp.is_success:
                    data = resp.json()
                    models = data if isinstance(data, list) else data.get("data", [])
                    for m in models:
                        if m.get("id") == bare_model or bare_model in str(m.get("id", "")):
                            ctx = m.get("loaded_context_length") or m.get("max_context_length")
                            if ctx:
                                logger.info("Detected context window %d for %s via LM Studio", ctx, bare_model)
                                return int(ctx)
            except Exception:
                pass

            # Try Ollama API
            try:
                resp = await client.post(f"{base}/api/show", json={"name": bare_model})
                if resp.is_success:
                    info = resp.json()
                    ctx = (info.get("model_info") or {}).get("context_length")
                    if ctx:
                        logger.info("Detected context window %d for %s via Ollama", ctx, bare_model)
                        return int(ctx)
            except Exception:
                pass

    except Exception as exc:
        logger.debug("Context window detection failed: %s", exc)

    return None


@router.get("/llm/models")
async def list_models() -> list[LLMModel]:
    """Fetch available models from the configured LLM backend (LM Studio / Ollama)."""
    config = get_config()
    api_base = config.llm_api_base
    if not api_base:
        return []

    base = _normalize_base(api_base)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Try LM Studio native API first (has context_length info)
            try:
                resp = await client.get(f"{base}/api/v0/models")
                if resp.is_success:
                    data = resp.json()
                    models = data if isinstance(data, list) else data.get("data", [])
                    return [
                        LLMModel(
                            id=m["id"],
                            owned_by=m.get("publisher") or m.get("owned_by"),
                            context_length=m.get("loaded_context_length") or m.get("max_context_length"),
                        )
                        for m in models
                    ]
            except Exception:
                pass

            # Fallback to standard OpenAI /v1/models
            resp = await client.get(f"{base}/v1/models")
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data", [])
            return [
                LLMModel(id=m["id"], owned_by=m.get("owned_by"))
                for m in models
            ]
    except Exception as exc:
        logger.debug("Failed to fetch models: %s", exc)
        return []


@router.post("/llm/check")
async def check_llm() -> LLMStatus:
    """Re-check LLM availability without changing config."""
    config = get_config()
    llm = get_llm()
    if llm:
        await llm.is_available()
    return LLMStatus(
        enabled=config.llm_enabled,
        available=bool(llm and llm._available),
        model=config.llm_model,
        api_base=config.llm_api_base,
        api_key_set=bool(config.llm_api_key),
        think=config.llm_think,
        context_window=config.llm_context_window,
    )
