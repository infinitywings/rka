"""Persistent Zotero linker configuration.

The config lives at `/data/zotero_config.json` (the rka-data Docker
volume; survives `docker compose up -d --build`). File-mode 0600 so the
`api_key` field is owner-readable only. Every save first writes the
previous config to `/data/zotero_config.backup.json` for one-step
rollback.

The schema mirrors the env-var triple that `zotero_linker._env_config`
historically read (`ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`,
`ZOTERO_LIBRARY_TYPE`), plus two provenance fields (`updated_at`,
`updated_by`). The REST API at `/api/config/zotero` redacts `api_key`
before returning the config to clients.

v2.7.0.2 (Bug 1 fix): pre-v2.7.0.2, `zotero_linker._env_config()` read
only `os.environ`. The `rka-server` and `rka-worker` containers don't
have Zotero env wired by default, so every link call returned
`zotero_not_configured`. Operators had to `source .env` before
`docker compose up` and re-source on every recreate. This service
makes the cred path persistent: drop the api_key once via the REST PUT
(or hand-edit the file with mode 0600 preserved), and it survives
container recreate. The env vars still win when set — operator
override path stays intact for one-off testing.

First-run behavior:
  - If the file doesn't exist, `load_config()` returns the empty
    config (`api_key=""`, `library_id=""`) WITHOUT writing it.
    `zotero_linker._env_config()` then returns `None` and the linker
    reports `zotero_not_configured` — same behavior as pre-v2.7.0.2
    when env was also empty.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "DEFAULT_CONFIG",
    "ZoteroConfig",
    "ZoteroConfigError",
    "ZoteroConfigService",
]

logger = logging.getLogger(__name__)


LibraryType = Literal["user", "group"]


class ZoteroConfigError(Exception):
    """Raised when the persisted Zotero config can't be read/written."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class ZoteroConfig(BaseModel):
    """Schema for `/data/zotero_config.json`.

    All fields default to empty strings so first-run / missing-file
    paths return a well-formed object that callers can check with
    `is_configured()` rather than handling None.
    """

    api_key: str = Field(default="", description="Zotero API key")
    library_id: str = Field(default="", description="Numeric library ID (e.g. '9646912')")
    library_type: LibraryType = Field(default="user")
    updated_at: str | None = None
    updated_by: str | None = None

    model_config = {"extra": "forbid"}

    def is_configured(self) -> bool:
        """True iff both api_key + library_id are non-empty."""
        return bool(self.api_key.strip() and self.library_id.strip())


DEFAULT_CONFIG = ZoteroConfig(
    api_key="",
    library_id="",
    library_type="user",
    updated_at=None,
    updated_by="system-default",
)
"""First-run baseline. Used when `/data/zotero_config.json` doesn't
exist yet. Not auto-persisted — operators populate via REST PUT or by
hand-editing the file (mode 0600)."""


def _now_iso_z() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ZoteroConfigService:
    """Read/write the persistent Zotero config.

    Construction takes a `config_dir` so tests can point at `tmp_path`.
    Production binding defaults to `/data` (the rka-data Docker volume).
    """

    CONFIG_FILENAME = "zotero_config.json"
    BACKUP_FILENAME = "zotero_config.backup.json"

    def __init__(self, config_dir: Path | str = Path("/data")) -> None:
        self.config_dir = Path(config_dir)
        self.config_path = self.config_dir / self.CONFIG_FILENAME
        self.backup_path = self.config_dir / self.BACKUP_FILENAME

    # ------------------------------------------------------------------
    # Read / load
    # ------------------------------------------------------------------

    def load_config(self) -> ZoteroConfig:
        """Return the persisted config; on missing-file, return the default
        WITHOUT persisting."""
        if not self.config_path.exists():
            logger.debug(
                "zotero config file missing at %s; returning DEFAULT_CONFIG (empty)",
                self.config_path,
            )
            return DEFAULT_CONFIG.model_copy()
        try:
            raw = self.config_path.read_text()
            payload = json.loads(raw)
            return ZoteroConfig.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            raise ZoteroConfigError(
                f"zotero config at {self.config_path} is unreadable: {exc!s}",
                hint="restore from /data/zotero_config.backup.json or remove the file",
            )

    # ------------------------------------------------------------------
    # Write / save
    # ------------------------------------------------------------------

    def save_config(self, config: ZoteroConfig, actor: str) -> ZoteroConfig:
        """Persist `config`, after first writing the prior file (if any) to
        `zotero_config.backup.json`. Atomic via tmp+rename. File-mode 0600.

        Returns the persisted config with updated_at + updated_by populated.
        """
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: pre-flight backup. Copy current → backup. No-op on first save.
        if self.config_path.exists():
            try:
                shutil.copy2(self.config_path, self.backup_path)
                os.chmod(self.backup_path, 0o600)
            except OSError as exc:
                raise ZoteroConfigError(
                    f"failed to write pre-flight backup to {self.backup_path}: {exc!s}",
                    hint="verify the /data volume is writable + owner-only",
                )

        # Step 2: stamp provenance.
        stamped = config.model_copy(
            update={
                "updated_at": _now_iso_z(),
                "updated_by": actor or "unknown",
            }
        )

        # Step 3: atomic write via tmp+rename in the same directory.
        body = stamped.model_dump_json(indent=2)
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".zotero_config.", suffix=".tmp", dir=str(self.config_dir)
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                f.write(body)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.config_path)
        except OSError as exc:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise ZoteroConfigError(
                f"failed to write zotero config to {self.config_path}: {exc!s}",
                hint="verify the /data volume is writable",
            )

        logger.info(
            "zotero config saved (library_id=%s, library_type=%s; actor=%s)",
            stamped.library_id,
            stamped.library_type,
            stamped.updated_by,
        )
        return stamped

    # ------------------------------------------------------------------
    # Reachability test (no-persist probe via httpx)
    # ------------------------------------------------------------------

    async def test_config(self, config: ZoteroConfig) -> dict:
        """Probe Zotero's `/keys/<api_key>` endpoint to verify the creds work.

        Does NOT persist. Used by REST endpoint `POST /api/config/zotero/test`
        and by the PUT handler before committing.

        Returns: {"ok": bool, "detail": str, "library_access": dict | None}
        """
        if not config.is_configured():
            return {
                "ok": False,
                "detail": "api_key and library_id are required",
                "library_access": None,
            }
        try:
            import httpx
        except ImportError:
            return {
                "ok": False,
                "detail": "httpx not installed (server-side dependency missing)",
                "library_access": None,
            }
        url = f"https://api.zotero.org/keys/{config.api_key.strip()}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url, headers={"Zotero-API-Version": "3", "User-Agent": "rka/2.7"}
                )
            if resp.status_code == 200:
                body = resp.json()
                # Don't surface the api_key itself in the detail; just confirm.
                return {
                    "ok": True,
                    "detail": f"key valid (userID={body.get('userID')})",
                    "library_access": body.get("access") or None,
                }
            if resp.status_code in (401, 403):
                return {
                    "ok": False,
                    "detail": "api_key rejected by Zotero (401/403)",
                    "library_access": None,
                }
            return {
                "ok": False,
                "detail": f"Zotero API returned HTTP {resp.status_code}",
                "library_access": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "detail": f"probe failed: {type(exc).__name__}: {exc!s}",
                "library_access": None,
            }
