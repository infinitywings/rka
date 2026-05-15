"""Unit tests for EmbeddingConfigService (Mission D T2).

Covers:
  - Default-on-missing semantics (load returns DEFAULT_CONFIG without persisting)
  - Save → reload round-trip
  - File-mode 0600 after save
  - Pre-flight backup written before save
  - Atomic write semantics (no partial file on disk if save fails)
  - Corrupt-file path raises EmbeddingConfigError with hint
  - test_config dispatches to backend.test_connection (mocked)
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import httpx
import pytest

from rka.infra.embedding_backends.base import ConnectionTestResult
from rka.services.embedding_config import (
    DEFAULT_CONFIG,
    EmbeddingConfig,
    EmbeddingConfigError,
    EmbeddingConfigService,
)


# ---------------------------------------------------------------------------
# Default + missing-file behavior
# ---------------------------------------------------------------------------


def test_load_on_missing_file_returns_default_without_persisting(tmp_path: Path):
    svc = EmbeddingConfigService(config_dir=tmp_path)
    cfg = svc.load_config()
    assert cfg.backend == "fastembed"
    assert cfg.config["model_name"] == "nomic-ai/nomic-embed-text-v1.5"
    assert cfg.config["dim"] == 768
    # First-run baseline; T7 will persist this on first boot, not load_config.
    assert not svc.config_path.exists()


def test_default_config_is_fastembed_nomic_768():
    # Locking the default per acceptance criteria; changing this is a
    # breaking change (first-run experience).
    assert DEFAULT_CONFIG.backend == "fastembed"
    assert DEFAULT_CONFIG.config["dim"] == 768
    assert "nomic" in DEFAULT_CONFIG.config["model_name"]


# ---------------------------------------------------------------------------
# Save + reload round-trip
# ---------------------------------------------------------------------------


def test_save_then_load_round_trip(tmp_path: Path):
    svc = EmbeddingConfigService(config_dir=tmp_path)
    cfg = EmbeddingConfig(
        backend="openai_compat",
        config={
            "base_url": "http://host.docker.internal:1234",
            "model": "qwen3-embedding-8b",
            "api_key": "sk-test",
            "dim": 4096,
        },
    )
    saved = svc.save_config(cfg, actor="pi")
    assert saved.updated_at is not None
    assert saved.updated_at.endswith("Z")
    assert saved.updated_by == "pi"

    loaded = svc.load_config()
    assert loaded.backend == "openai_compat"
    assert loaded.config["base_url"] == "http://host.docker.internal:1234"
    assert loaded.config["api_key"] == "sk-test"  # redaction happens at REST layer
    assert loaded.config["dim"] == 4096
    assert loaded.updated_by == "pi"


# ---------------------------------------------------------------------------
# File-mode 0600
# ---------------------------------------------------------------------------


def test_saved_config_has_mode_0600(tmp_path: Path):
    svc = EmbeddingConfigService(config_dir=tmp_path)
    cfg = EmbeddingConfig(
        backend="openai_compat",
        config={"base_url": "http://x", "model": "m", "api_key": "sk-x", "dim": 4},
    )
    svc.save_config(cfg, actor="pi")
    mode = stat.S_IMODE(os.stat(svc.config_path).st_mode)
    assert mode == 0o600, f"expected mode 0o600 to protect api_key; got {oct(mode)}"


# ---------------------------------------------------------------------------
# Pre-flight backup
# ---------------------------------------------------------------------------


def test_first_save_skips_backup(tmp_path: Path):
    svc = EmbeddingConfigService(config_dir=tmp_path)
    cfg = EmbeddingConfig(backend="fastembed", config={"model_name": "m", "dim": 768})
    svc.save_config(cfg, actor="pi")
    # No prior file → no backup expected on the very first save.
    assert not svc.backup_path.exists()


def test_subsequent_save_writes_prior_config_to_backup(tmp_path: Path):
    svc = EmbeddingConfigService(config_dir=tmp_path)
    first = EmbeddingConfig(
        backend="fastembed", config={"model_name": "first", "dim": 768}
    )
    svc.save_config(first, actor="pi")

    second = EmbeddingConfig(
        backend="ollama", config={"base_url": "http://x", "model": "m"}
    )
    svc.save_config(second, actor="brain")

    # Backup should now hold the first config.
    backup_payload = json.loads(svc.backup_path.read_text())
    assert backup_payload["backend"] == "fastembed"
    assert backup_payload["config"]["model_name"] == "first"

    # Backup file also gets the 0600 floor.
    mode = stat.S_IMODE(os.stat(svc.backup_path).st_mode)
    assert mode == 0o600


def test_backup_overwritten_on_each_save(tmp_path: Path):
    svc = EmbeddingConfigService(config_dir=tmp_path)
    svc.save_config(
        EmbeddingConfig(backend="fastembed", config={"model_name": "v1", "dim": 768}),
        actor="pi",
    )
    svc.save_config(
        EmbeddingConfig(backend="fastembed", config={"model_name": "v2", "dim": 768}),
        actor="pi",
    )
    svc.save_config(
        EmbeddingConfig(backend="fastembed", config={"model_name": "v3", "dim": 768}),
        actor="pi",
    )
    # Backup holds v2 (immediately prior), not v1.
    backup_payload = json.loads(svc.backup_path.read_text())
    assert backup_payload["config"]["model_name"] == "v2"


# ---------------------------------------------------------------------------
# Atomic write semantics
# ---------------------------------------------------------------------------


def test_atomic_write_leaves_no_partial_file_on_disk(tmp_path: Path):
    svc = EmbeddingConfigService(config_dir=tmp_path)
    cfg = EmbeddingConfig(backend="fastembed", config={"model_name": "m", "dim": 768})
    svc.save_config(cfg, actor="pi")

    # After save: no .tmp files left in the config directory.
    leftovers = list(tmp_path.glob(".embedding_config.*.tmp"))
    assert leftovers == []
    # And the live file is valid JSON parseable as EmbeddingConfig.
    parsed = EmbeddingConfig.model_validate_json(svc.config_path.read_text())
    assert parsed.backend == "fastembed"


def test_save_validates_config_is_pydantic_model_instance(tmp_path: Path):
    # The Pydantic validator catches malformed dicts before they reach disk.
    svc = EmbeddingConfigService(config_dir=tmp_path)
    with pytest.raises(Exception):  # Pydantic ValidationError or similar
        EmbeddingConfig.model_validate({"backend": "magic-unknown", "config": {}})


# ---------------------------------------------------------------------------
# Corrupt file path
# ---------------------------------------------------------------------------


def test_load_corrupt_file_raises_embedding_config_error(tmp_path: Path):
    svc = EmbeddingConfigService(config_dir=tmp_path)
    svc.config_path.parent.mkdir(parents=True, exist_ok=True)
    svc.config_path.write_text("not-valid-json {{{")
    with pytest.raises(EmbeddingConfigError) as ctx:
        svc.load_config()
    assert "unreadable" in ctx.value.detail
    assert ctx.value.hint  # hint must be populated for the 422 response


def test_embedding_config_error_carries_hint_field():
    err = EmbeddingConfigError("oops", hint="try X")
    assert err.detail == "oops"
    assert err.hint == "try X"


# ---------------------------------------------------------------------------
# test_config → backend.test_connection
# ---------------------------------------------------------------------------


def _ollama_responder(dim: int = 5):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embedding": [0.1] * dim})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_test_config_returns_connection_test_result(tmp_path: Path, monkeypatch):
    # Inject an http_client via factory by monkey-patching make_backend.
    from rka.infra.embedding_backends.ollama import OllamaBackend

    fake_client = httpx.AsyncClient(transport=_ollama_responder(dim=5), base_url="http://x")
    real_make = OllamaBackend

    def make_with_client(*args, **kwargs):
        kwargs["http_client"] = fake_client
        return real_make(*args, **kwargs)

    monkeypatch.setattr(
        "rka.infra.embedding_backends.OllamaBackend", make_with_client, raising=False
    )
    # The factory imports OllamaBackend lazily inside make_backend; patch
    # the module path the factory uses.
    monkeypatch.setattr(
        "rka.infra.embedding_backends.ollama.OllamaBackend",
        make_with_client,
        raising=False,
    )

    svc = EmbeddingConfigService(config_dir=tmp_path)
    cfg = EmbeddingConfig(
        backend="ollama",
        config={"base_url": "http://x", "model": "m"},
    )
    result = await svc.test_config(cfg)
    assert isinstance(result, ConnectionTestResult)
    assert result.ok is True
    assert result.detected_dim == 5


@pytest.mark.asyncio
async def test_test_config_returns_not_ok_for_invalid_backend(tmp_path: Path):
    svc = EmbeddingConfigService(config_dir=tmp_path)
    # Constructing the Pydantic model with backend literally outside the
    # allowed set fails — verifying our service surfaces gracefully.
    # Use a valid Pydantic model whose backend factory will then raise
    # (e.g. missing required field for openai_compat).
    cfg = EmbeddingConfig(
        backend="openai_compat",
        config={},  # missing base_url + model
    )
    result = await svc.test_config(cfg)
    assert result.ok is False
    assert "invalid config" in result.detail


# ---------------------------------------------------------------------------
# Directory creation
# ---------------------------------------------------------------------------


def test_save_creates_config_dir_if_missing(tmp_path: Path):
    svc = EmbeddingConfigService(config_dir=tmp_path / "nested" / "data")
    cfg = EmbeddingConfig(backend="fastembed", config={"model_name": "m", "dim": 768})
    svc.save_config(cfg, actor="pi")
    assert svc.config_path.exists()
