"""Unit tests for the persistent Zotero config service (v2.7.0.2 Bug 1).

Mirrors the EmbeddingConfigService test pattern: tmp_path-rooted service,
no real network calls (the `test_config` probe is exercised separately
via monkeypatching httpx).
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from rka.services.zotero_config import (
    DEFAULT_CONFIG,
    ZoteroConfig,
    ZoteroConfigError,
    ZoteroConfigService,
)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_default_config_is_empty_and_not_configured():
    assert DEFAULT_CONFIG.api_key == ""
    assert DEFAULT_CONFIG.library_id == ""
    assert DEFAULT_CONFIG.library_type == "user"
    assert DEFAULT_CONFIG.is_configured() is False


def test_is_configured_requires_both_fields():
    assert ZoteroConfig(api_key="k", library_id="").is_configured() is False
    assert ZoteroConfig(api_key="", library_id="123").is_configured() is False
    assert ZoteroConfig(api_key="k", library_id="123").is_configured() is True
    # Whitespace-only counts as empty
    assert ZoteroConfig(api_key="  ", library_id="  ").is_configured() is False


def test_library_type_enforced_to_user_or_group():
    ZoteroConfig(api_key="k", library_id="1", library_type="user")
    ZoteroConfig(api_key="k", library_id="1", library_type="group")
    with pytest.raises(ValueError):
        ZoteroConfig(api_key="k", library_id="1", library_type="bogus")  # type: ignore[arg-type]


def test_model_forbids_extra_fields():
    with pytest.raises(ValueError):
        ZoteroConfig(api_key="k", library_id="1", surprise="x")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_default_without_writing(tmp_path):
    svc = ZoteroConfigService(config_dir=tmp_path)
    cfg = svc.load_config()
    assert cfg.api_key == ""
    assert cfg.library_id == ""
    assert cfg.is_configured() is False
    # File must NOT have been auto-written.
    assert not (tmp_path / "zotero_config.json").exists()


def test_load_persisted_file_returns_saved_values(tmp_path):
    svc = ZoteroConfigService(config_dir=tmp_path)
    saved = svc.save_config(
        ZoteroConfig(api_key="abc123", library_id="9646912", library_type="user"),
        actor="pi",
    )
    assert saved.api_key == "abc123"
    assert saved.library_id == "9646912"
    assert saved.updated_by == "pi"
    assert saved.updated_at is not None

    cfg = ZoteroConfigService(config_dir=tmp_path).load_config()
    assert cfg.api_key == "abc123"
    assert cfg.library_id == "9646912"
    assert cfg.library_type == "user"


def test_load_corrupt_file_raises_zotero_config_error(tmp_path):
    p = tmp_path / "zotero_config.json"
    p.write_text("{not valid json}")
    svc = ZoteroConfigService(config_dir=tmp_path)
    with pytest.raises(ZoteroConfigError) as exc_info:
        svc.load_config()
    assert "unreadable" in str(exc_info.value)
    assert exc_info.value.hint  # non-empty hint


# ---------------------------------------------------------------------------
# Save — atomic, mode 0600, pre-flight backup
# ---------------------------------------------------------------------------


def test_save_writes_file_with_mode_0600(tmp_path):
    svc = ZoteroConfigService(config_dir=tmp_path)
    svc.save_config(
        ZoteroConfig(api_key="abc", library_id="1", library_type="user"), actor="pi"
    )
    p = tmp_path / "zotero_config.json"
    assert p.exists()
    mode = stat.S_IMODE(os.stat(p).st_mode)
    assert mode == 0o600


def test_save_creates_pre_flight_backup_on_second_save(tmp_path):
    svc = ZoteroConfigService(config_dir=tmp_path)
    svc.save_config(
        ZoteroConfig(api_key="first", library_id="1"), actor="pi"
    )
    svc.save_config(
        ZoteroConfig(api_key="second", library_id="1"), actor="pi"
    )
    backup_path = tmp_path / "zotero_config.backup.json"
    assert backup_path.exists()
    backup_body = json.loads(backup_path.read_text())
    assert backup_body["api_key"] == "first"
    # backup file mode is also 0o600 (protects the prior api_key)
    mode = stat.S_IMODE(os.stat(backup_path).st_mode)
    assert mode == 0o600


def test_save_no_backup_on_first_save(tmp_path):
    svc = ZoteroConfigService(config_dir=tmp_path)
    svc.save_config(
        ZoteroConfig(api_key="first", library_id="1"), actor="pi"
    )
    assert not (tmp_path / "zotero_config.backup.json").exists()


def test_save_stamps_provenance_fields(tmp_path):
    svc = ZoteroConfigService(config_dir=tmp_path)
    saved = svc.save_config(
        ZoteroConfig(api_key="k", library_id="1"), actor="pi"
    )
    assert saved.updated_by == "pi"
    assert saved.updated_at is not None
    # ISO8601 Zulu format
    assert saved.updated_at.endswith("Z")


def test_save_creates_config_dir_if_missing(tmp_path):
    nested = tmp_path / "nested" / "data"
    assert not nested.exists()
    svc = ZoteroConfigService(config_dir=nested)
    svc.save_config(ZoteroConfig(api_key="k", library_id="1"), actor="pi")
    assert nested.exists()
    assert (nested / "zotero_config.json").exists()


# ---------------------------------------------------------------------------
# Reachability probe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_config_rejects_empty_creds(tmp_path):
    svc = ZoteroConfigService(config_dir=tmp_path)
    result = await svc.test_config(ZoteroConfig(api_key="", library_id=""))
    assert result["ok"] is False
    assert "required" in result["detail"]
    assert result["library_access"] is None


@pytest.mark.asyncio
async def test_test_config_handles_401_403_response(tmp_path, monkeypatch):
    """When Zotero rejects the api_key, surface it as a clear error."""
    import httpx

    class _StubClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, headers=None):
            return httpx.Response(401)

    monkeypatch.setattr(httpx, "AsyncClient", _StubClient)
    svc = ZoteroConfigService(config_dir=tmp_path)
    result = await svc.test_config(
        ZoteroConfig(api_key="bad", library_id="1", library_type="user")
    )
    assert result["ok"] is False
    assert "401" in result["detail"] or "403" in result["detail"]


@pytest.mark.asyncio
async def test_test_config_handles_200_success(tmp_path, monkeypatch):
    """200 with a valid body marks the test as ok and reports the access set."""
    import httpx

    class _StubClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, headers=None):
            return httpx.Response(
                200,
                json={
                    "key": "abc",
                    "userID": 9646912,
                    "access": {"user": {"library": True, "notes": True}},
                },
            )

    monkeypatch.setattr(httpx, "AsyncClient", _StubClient)
    svc = ZoteroConfigService(config_dir=tmp_path)
    result = await svc.test_config(
        ZoteroConfig(api_key="abc", library_id="9646912", library_type="user")
    )
    assert result["ok"] is True
    assert "userID" in result["detail"]
    assert result["library_access"] == {"user": {"library": True, "notes": True}}


# ---------------------------------------------------------------------------
# Round-trip integration
# ---------------------------------------------------------------------------


def test_save_then_load_returns_identical_fields(tmp_path):
    svc = ZoteroConfigService(config_dir=tmp_path)
    src = ZoteroConfig(
        api_key="z86gm6dVKCy1KxnVIP2AppZJ",
        library_id="9646912",
        library_type="user",
    )
    saved = svc.save_config(src, actor="pi")
    loaded = svc.load_config()
    assert loaded.api_key == src.api_key
    assert loaded.library_id == src.library_id
    assert loaded.library_type == src.library_type
    assert loaded.updated_at == saved.updated_at
    assert loaded.updated_by == saved.updated_by


def test_default_config_round_trips_through_save(tmp_path):
    """Even an empty config can be saved (e.g. the user wants to clear creds)."""
    svc = ZoteroConfigService(config_dir=tmp_path)
    svc.save_config(DEFAULT_CONFIG.model_copy(), actor="pi")
    loaded = svc.load_config()
    assert loaded.is_configured() is False
