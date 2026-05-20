"""Tests for EnrichmentWorker.boot() embedding config loading (v2.5.8 Bug 2 fix).

Per dec_01KS3E1FGSK530N8HM04BNMCEW: the worker startup must load the
persisted embedding config from `<data_dir>/embedding_config.json` so
PI changes via the webui take effect across restarts. Pre-fix worker
boot used env vars only, which left the worker serving stale embeddings
after PI swapped the embedding backend via PUT /api/config/embedding.

Tests exercise `EnrichmentWorker._resolve_embeddings()` directly so we
do not depend on a real EmbeddingService construction (which requires
optional fastembed dependencies).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Lazy import inside the test so we surface the import error if worker.py
# refactor breaks the module.
def _import_worker():
    from rka.services.worker import EnrichmentWorker
    return EnrichmentWorker


def _write_config(data_dir: Path, *, backend: str, model_name: str, dim: int) -> Path:
    """Write a minimal embedding_config.json that EmbeddingConfigService.load_config can parse."""
    config_path = data_dir / "embedding_config.json"
    payload = {
        "backend": backend,
        "config": {"model_name": model_name, "dim": dim},
        "updated_at": None,
        "updated_by": "test-fixture",
    }
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


class TestWorkerStartupReadsPersistedConfig:
    """When /data/embedding_config.json exists, _resolve_embeddings loads it."""

    def test_resolve_embeddings_uses_persisted_config(self, tmp_path: Path) -> None:
        EnrichmentWorker = _import_worker()

        # Write a fastembed config the loader will accept.
        _write_config(
            tmp_path,
            backend="fastembed",
            model_name="nomic-ai/nomic-embed-text-v1.5",
            dim=768,
        )

        # Mock EmbeddingService.from_config so we do not need a real
        # fastembed install to run the test. Capture the kwargs the loader
        # passes through.
        fake_embedding_service = MagicMock()
        fake_embedding_service.dim = 768

        with patch(
            "rka.infra.embeddings.EmbeddingService.from_config",
            return_value=fake_embedding_service,
        ) as patched:
            mock_db = MagicMock()
            result = EnrichmentWorker._resolve_embeddings(
                db=mock_db,
                data_dir=tmp_path,
                embeddings_enabled=True,
                env_fallback_model="some-other-model",
            )

        assert result is fake_embedding_service
        # The from_config call should have used the persisted backend / model_name,
        # not the env_fallback_model.
        assert patched.called
        call_kwargs = patched.call_args.kwargs
        call_args_payload = patched.call_args.args[0] if patched.call_args.args else None
        # Confirm the persisted config (not env) was passed in.
        payload = call_args_payload if call_args_payload is not None else call_kwargs.get("config")
        assert payload is not None
        assert payload.get("backend") == "fastembed"
        assert payload["config"]["model_name"] == "nomic-ai/nomic-embed-text-v1.5"

    def test_boot_classmethod_threads_data_dir_through(self, tmp_path: Path) -> None:
        """Smoke test of boot(): the classmethod returns an EnrichmentWorker with embeddings set."""
        EnrichmentWorker = _import_worker()

        _write_config(
            tmp_path,
            backend="fastembed",
            model_name="nomic-ai/nomic-embed-text-v1.5",
            dim=768,
        )

        fake_embedding_service = MagicMock()
        fake_embedding_service.dim = 768

        with patch(
            "rka.infra.embeddings.EmbeddingService.from_config",
            return_value=fake_embedding_service,
        ):
            mock_db = MagicMock()
            worker = EnrichmentWorker.boot(
                db=mock_db,
                data_dir=tmp_path,
                embeddings_enabled=True,
            )

        assert worker.embeddings is fake_embedding_service
        assert worker.db is mock_db


class TestWorkerStartupFallsBackToEnvWhenConfigAbsent:
    """When /data/embedding_config.json is missing, _resolve_embeddings falls back to env."""

    def test_resolve_embeddings_falls_back_to_env_when_config_missing(
        self, tmp_path: Path, caplog
    ) -> None:
        EnrichmentWorker = _import_worker()

        # Intentionally do NOT write embedding_config.json; tmp_path is empty.
        assert not (tmp_path / "embedding_config.json").exists()

        # Mock the env-fallback EmbeddingService constructor so we do not
        # need real fastembed.
        fake_embedding_service = MagicMock()
        fake_embedding_service.dim = 768

        with patch(
            "rka.infra.embeddings.EmbeddingService",
            return_value=fake_embedding_service,
        ) as patched:
            mock_db = MagicMock()
            with caplog.at_level(logging.INFO):
                result = EnrichmentWorker._resolve_embeddings(
                    db=mock_db,
                    data_dir=tmp_path,
                    embeddings_enabled=True,
                    env_fallback_model="env-fallback-model",
                )

        assert result is fake_embedding_service
        # Verify the env_fallback_model was used (not whatever from_config
        # would have produced).
        call_kwargs = patched.call_args.kwargs
        assert call_kwargs.get("model_name") == "env-fallback-model"
        # Verify the log message confirms the fallback path was taken.
        assert any(
            "falling back to env defaults" in record.message
            and "persisted config" in record.message
            for record in caplog.records
        )

    def test_resolve_embeddings_disabled_returns_none(self, tmp_path: Path) -> None:
        """embeddings_enabled=False short-circuits to None without loading config."""
        EnrichmentWorker = _import_worker()
        mock_db = MagicMock()
        result = EnrichmentWorker._resolve_embeddings(
            db=mock_db,
            data_dir=tmp_path,
            embeddings_enabled=False,
            env_fallback_model="any",
        )
        assert result is None
