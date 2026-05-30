"""Gap 5 — Docker-secret OAuth token loading.

When the operator opts into the Docker-secret overlay, the OAuth token
lands at /run/secrets/claude_oauth_token (read-only tmpfs). The daemon
reads it at startup and exports to env so the SDK subprocess picks it
up. When the secret file is absent, env_file fallback is preserved.

Tests use monkeypatch to redirect the secret path to a tmp file and
verify the env-var behavior + redaction.
"""

from __future__ import annotations

import logging
import os

import pytest

from orchestrator import server


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Each test gets a clean CLAUDE_CODE_OAUTH_TOKEN slate."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    yield


def test_missing_secret_file_falls_through(monkeypatch, tmp_path):
    """No file → no env change. Pre-Gap-5 behavior preserved."""
    monkeypatch.setenv(
        "ORCHESTRATOR_OAUTH_SECRET_PATH", str(tmp_path / "does_not_exist")
    )
    server._maybe_load_oauth_secret()
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in os.environ


def test_empty_secret_file_falls_through(monkeypatch, tmp_path):
    """An empty file is treated as absent — no env change."""
    secret = tmp_path / "secret"
    secret.write_text("")
    monkeypatch.setenv("ORCHESTRATOR_OAUTH_SECRET_PATH", str(secret))
    server._maybe_load_oauth_secret()
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in os.environ


def test_secret_file_with_value_exports_to_env(monkeypatch, tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("sk-real-oauth-token-from-secret\n")  # trailing newline OK
    monkeypatch.setenv("ORCHESTRATOR_OAUTH_SECRET_PATH", str(secret))

    server._maybe_load_oauth_secret()

    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-real-oauth-token-from-secret"


def test_secret_overrides_env_file_value(monkeypatch, tmp_path):
    """When both env_file (orchestrator/.env) and the secret are set,
    the secret wins — secrets are the operationally preferred path."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "old-from-env-file")
    secret = tmp_path / "secret"
    secret.write_text("new-from-secret")
    monkeypatch.setenv("ORCHESTRATOR_OAUTH_SECRET_PATH", str(secret))

    server._maybe_load_oauth_secret()

    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "new-from-secret"


def test_secret_value_never_appears_in_logs(monkeypatch, tmp_path, caplog):
    """Critical: the OAuth token value MUST NEVER land in logs."""
    secret = tmp_path / "secret"
    secret.write_text("VERY_SECRET_TOKEN_VALUE_12345")
    monkeypatch.setenv("ORCHESTRATOR_OAUTH_SECRET_PATH", str(secret))

    with caplog.at_level(logging.DEBUG, logger="orchestrator.server"):
        server._maybe_load_oauth_secret()

    log_text = " ".join(r.getMessage() for r in caplog.records)
    assert "VERY_SECRET_TOKEN_VALUE_12345" not in log_text
    # But the load itself IS logged so audit trail exists.
    assert any("oauth secret loaded" in r.getMessage() for r in caplog.records)


def test_default_path_is_docker_secret_location(monkeypatch):
    """When ORCHESTRATOR_OAUTH_SECRET_PATH is unset, the helper looks at
    the canonical Docker secret mount path."""
    monkeypatch.delenv("ORCHESTRATOR_OAUTH_SECRET_PATH", raising=False)
    # Should be safe — no such file in CI/dev environments. Just confirms
    # the default doesn't crash.
    server._maybe_load_oauth_secret()
    # No assertion on env — just no exception.


def test_secret_matching_env_file_does_not_log_override(monkeypatch, tmp_path, caplog):
    """When env and secret carry the SAME value, don't emit the override
    notice — it's just noise."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "same-value")
    secret = tmp_path / "secret"
    secret.write_text("same-value")
    monkeypatch.setenv("ORCHESTRATOR_OAUTH_SECRET_PATH", str(secret))

    with caplog.at_level(logging.DEBUG, logger="orchestrator.server"):
        server._maybe_load_oauth_secret()

    log_text = " ".join(r.getMessage() for r in caplog.records)
    assert "overrides" not in log_text
