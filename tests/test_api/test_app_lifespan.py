"""Application lifespan tests."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

import rka.api.app as app_module
from rka.api.deps import get_llm
from rka.api.app import create_app
from rka.api.routes import llm as llm_routes
from rka.config import RKAConfig
from rka.infra.database import Database
from rka.infra.llm import LLMClient


@pytest.mark.asyncio
async def test_lifespan_does_not_block_on_llm_startup_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    async def fake_is_available(self: LLMClient) -> bool:
        await asyncio.sleep(0.2)
        self._available = False
        return False

    async def fake_load_sqlite_vec(self: Database) -> None:
        self._vec_loaded = False

    monkeypatch.setattr(LLMClient, "is_available", fake_is_available)
    monkeypatch.setattr(Database, "_load_sqlite_vec", fake_load_sqlite_vec)

    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("test.db"),
        llm_enabled=True,
        llm_model="openai/test-model",
        llm_api_base="http://127.0.0.1:1/v1",
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)

    start = time.perf_counter()
    await lifespan.__aenter__()
    elapsed = time.perf_counter() - start

    try:
        assert elapsed < 0.15
    finally:
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_lifespan_retries_llm_startup_probe_until_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    attempts = 0
    original_sleep = asyncio.sleep

    async def fake_is_available(self: LLMClient) -> bool:
        nonlocal attempts
        attempts += 1
        self._available = attempts >= 3
        return self._available

    async def fake_load_sqlite_vec(self: Database) -> None:
        self._vec_loaded = False

    async def fake_detect_context_window(api_base: str, model_id: str) -> int:
        assert api_base == "http://127.0.0.1:1/v1"
        assert model_id == "openai/test-model"
        return 262144

    async def fake_sleep(_: float) -> None:
        await original_sleep(0)

    monkeypatch.setattr(LLMClient, "is_available", fake_is_available)
    monkeypatch.setattr(Database, "_load_sqlite_vec", fake_load_sqlite_vec)
    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(llm_routes, "_detect_context_window", fake_detect_context_window)

    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("retry.db"),
        llm_enabled=True,
        llm_model="openai/test-model",
        llm_api_base="http://127.0.0.1:1/v1",
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)

    await lifespan.__aenter__()

    try:
        for _ in range(10):
            if attempts >= 3:
                break
            await original_sleep(0)

        assert attempts >= 3
        assert get_llm().available is True
        assert config.llm_context_window == 262144
    finally:
        await lifespan.__aexit__(None, None, None)
