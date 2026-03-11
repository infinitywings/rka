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


async def _persist_llm_kv(config) -> None:
    """Persist LLM settings to kv_store in the database."""
    db = get_db()
    pairs = {
        "llm.enabled": str(config.llm_enabled).lower(),
        "llm.model": config.llm_model,
        "llm.api_base": config.llm_api_base or "",
        "llm.api_key": config.llm_api_key or "",
        "llm.think": str(config.llm_think).lower(),
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
    )


class LLMModel(BaseModel):
    id: str
    owned_by: str | None = None


@router.get("/llm/models")
async def list_models() -> list[LLMModel]:
    """Fetch available models from the configured LLM backend (LM Studio / Ollama)."""
    config = get_config()
    api_base = config.llm_api_base
    if not api_base:
        return []

    # Normalize: strip trailing /v1 if present, then append /v1/models
    base = api_base.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    url = f"{base}/v1/models"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data", [])
            return [
                LLMModel(id=m["id"], owned_by=m.get("owned_by"))
                for m in models
            ]
    except Exception as exc:
        logger.debug("Failed to fetch models from %s: %s", url, exc)
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
    )
