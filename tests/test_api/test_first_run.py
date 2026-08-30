"""Tests for the v2.4.0 first-run experience (Mission D T7).

Two behaviors:
  1. App startup persists `DEFAULT_CONFIG` to /data/embedding_config.json
     when the file doesn't exist. Subsequent starts use the persisted file.
  2. The docker-compose.yml no longer contains any RKA_LLM_* references
     (regression lock for the LLM-env-block removal).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig
from rka.services.embedding_config import EmbeddingConfigService


@pytest_asyncio.fixture
async def first_run_api_client(tmp_path: Path):
    """API client whose `data_dir` points at a fresh tmp_path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("first_run.db"),
        data_dir=data_dir,
        # Embeddings DEFAULT is True in v2.4.0; explicit keep so the test
        # doesn't depend on the env to choose the path.
        embeddings_enabled=True,
        llm_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, data_dir
    finally:
        await lifespan.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Default config persisted on first boot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_boot_persists_default_config(first_run_api_client):
    """On a tmp data_dir that has no embedding_config.json, the startup
    hook must write DEFAULT_CONFIG (fastembed + nomic-768) to disk."""
    _client, data_dir = first_run_api_client

    cfg_path = data_dir / "embedding_config.json"
    assert cfg_path.exists(), (
        "first-boot hook should have written /data/embedding_config.json"
    )

    payload = json.loads(cfg_path.read_text())
    assert payload["backend"] == "fastembed"
    assert payload["config"]["model_name"] == "nomic-ai/nomic-embed-text-v1.5"
    assert payload["config"]["dim"] == 768
    assert payload["updated_by"] == "system-default"


@pytest.mark.asyncio
async def test_first_boot_persisted_config_round_trips_via_GET(first_run_api_client):
    """The persisted DEFAULT shows up through the REST GET endpoint —
    with api_key redaction applied (no api_key on fastembed, so the
    field is simply absent)."""
    client, _data_dir = first_run_api_client
    r = await client.get("/api/config/embedding")
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "fastembed"
    assert body["config"]["dim"] == 768


# ---------------------------------------------------------------------------
# Second boot does not overwrite a user-supplied config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_boot_does_not_overwrite_user_config(tmp_path: Path):
    """If the user previously saved a non-default config, a fresh app
    startup must NOT clobber it with DEFAULT."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    # Pre-populate the config file with a user choice.
    svc = EmbeddingConfigService(config_dir=data_dir)
    user_choice = svc.save_config(
        config=svc.load_config().model_copy(
            update={
                "backend": "openai_compat",
                "config": {
                    "base_url": "http://host.docker.internal:1234",
                    "model": "qwen3-embedding-8b",
                    "dim": 4096,
                },
            }
        ),
        actor="pi",
    )
    assert user_choice.backend == "openai_compat"

    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("second_boot.db"),
        data_dir=data_dir,
        embeddings_enabled=True,
        llm_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        # Verify the on-disk file still reflects the user choice.
        reloaded = svc.load_config()
        assert reloaded.backend == "openai_compat"
        assert reloaded.config["base_url"] == "http://host.docker.internal:1234"
    finally:
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_corrupt_config_starts_lexical_without_overwriting_bytes(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = data_dir / "embedding_config.json"
    corrupt = b"not-json {{{"
    cfg_path.write_bytes(corrupt)
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("corrupt_start.db"),
        data_dir=data_dir,
        embeddings_enabled=True,
        llm_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        assert app.state.embeddings is None
        assert cfg_path.read_bytes() == corrupt
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            capability = (await client.get("/api/capabilities")).json()["embedding"]
        assert capability["available"] is False
        assert capability["search_mode"] == "lexical"
        assert "unreadable" in capability["reason_unavailable"]
    finally:
        await lifespan.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# docker-compose.yml LLM-env-block removal regression lock
# ---------------------------------------------------------------------------


def test_docker_compose_has_no_llm_env_references():
    """v2.4.0 BREAKING-IN-MINOR scope: docker-compose.yml MUST NOT carry
    any RKA_LLM_* env var references (commented or active).

    The corresponding LLM service code is preserved; only the env knob
    surface is removed. Re-introducing RKA_LLM_* here would re-expose
    the surface the LLM-capability-removal directive
    (jrn_01KRNZBS50K250HHHHEC58E4GC) explicitly removed.
    """
    compose_path = Path(__file__).resolve().parent.parent.parent / "docker-compose.yml"
    body = compose_path.read_text()
    # Catches both `RKA_LLM_ENABLED` style and lower-case mentions in
    # commented blocks.
    matches = re.findall(r"RKA_LLM_\w*", body)
    assert not matches, (
        f"docker-compose.yml must not contain RKA_LLM_* references "
        f"after Mission D; found: {matches}"
    )


def test_docker_compose_enables_embeddings_by_default():
    """The flipped default (Mission D A12 default-on) must surface in
    docker-compose.yml so a fresh `docker compose up -d` works without
    further env tweaks."""
    compose_path = Path(__file__).resolve().parent.parent.parent / "docker-compose.yml"
    body = compose_path.read_text()
    assert "RKA_EMBEDDINGS_ENABLED" in body
    assert '"true"' in body or "true" in body
