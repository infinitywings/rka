"""Zotero Web API client — find-or-create a per-project collection.

The orchestrator creates one Zotero collection per RKA project during
onboarding. All literature captured for the project (by the PI via the
Zotero Connector browser extension) gets organized under this collection,
so Brain + Executor can query the project's lit set via zotero-mcp
filtered by collection key.

This module is a thin wrapper around the Zotero REST API at
https://api.zotero.org. Reads ZOTERO_API_KEY + ZOTERO_LIBRARY_ID +
ZOTERO_LIBRARY_TYPE from the environment. Returns None on any error
(non-fatal — onboarding proceeds; PI can create the collection
manually later).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

ZOTERO_API_BASE = "https://api.zotero.org"
DEFAULT_TIMEOUT = 10.0


def _env_config() -> Optional[tuple[str, str, str]]:
    """Return (api_key, library_id, library_type) or None if unconfigured."""
    api_key = os.environ.get("ZOTERO_API_KEY", "").strip()
    library_id = os.environ.get("ZOTERO_LIBRARY_ID", "").strip()
    library_type = (os.environ.get("ZOTERO_LIBRARY_TYPE") or "user").strip().lower()
    if not api_key or not library_id:
        return None
    if library_type not in ("user", "users", "group", "groups"):
        library_type = "user"
    # Normalize to plural for URL path
    library_type = library_type.rstrip("s") + "s"
    return api_key, library_id, library_type


def find_or_create_collection(
    name: str,
    *,
    parent_collection_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[tuple[str, str]]:
    """Find a collection by exact name; create it if missing.

    Returns (collection_key, collection_name) on success, None on error
    or if Zotero is not configured.

    Idempotent — re-running with the same name returns the existing
    collection rather than creating a duplicate.
    """
    cfg = _env_config()
    if cfg is None:
        logger.info("Zotero not configured (ZOTERO_API_KEY/LIBRARY_ID missing)")
        return None

    api_key, library_id, library_type = cfg

    try:
        import httpx
    except ImportError:
        logger.warning("httpx not available; cannot reach Zotero API")
        return None

    headers = {
        "Zotero-API-Key": api_key,
        "Zotero-API-Version": "3",
        "User-Agent": "rka-orchestrator/0.1",
    }
    base = f"{ZOTERO_API_BASE}/{library_type}/{library_id}"

    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            # 1. Search existing collections for an exact name match
            r = client.get(f"{base}/collections", params={"limit": 100})
            if r.status_code == 200:
                for col in r.json():
                    data = col.get("data", {})
                    if data.get("name") == name:
                        key = data.get("key")
                        if key:
                            return key, name

            # 2. Not found — create it
            payload = [{"name": name}]
            if parent_collection_key:
                payload[0]["parentCollection"] = parent_collection_key
            r = client.post(f"{base}/collections", json=payload)
            if r.status_code not in (200, 201):
                logger.warning(
                    "Zotero collection create failed: HTTP %d %s",
                    r.status_code, r.text[:200],
                )
                return None
            body = r.json()
            successful = body.get("successful", {})
            if not successful:
                logger.warning("Zotero collection create returned no successful key")
                return None
            created = successful.get("0", {})
            key = created.get("key") or created.get("data", {}).get("key")
            if not key:
                return None
            return key, name
    except Exception as exc:  # noqa: BLE001
        logger.warning("Zotero collection upsert failed: %s", exc)
        return None


def is_configured() -> bool:
    """Quick check whether Zotero API credentials are present."""
    return _env_config() is not None
