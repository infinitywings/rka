"""Crossref backend via habanero.

Stage B resolution chain primary source. Stage D retraction check via the
Crossref update-to field. No API key required; OPTIONAL polite-pool email
via CROSSREF_EMAIL env var.

Per dec_01KS2S22VV5P5SWWXNBXQDHMGX assumption #5: habanero polite-pool email
configured via CROSSREF_EMAIL.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from habanero import Crossref  # type: ignore
    _AVAILABLE = True
except ImportError:
    Crossref = None  # type: ignore
    _AVAILABLE = False


def is_available() -> bool:
    """Return True if habanero is importable."""
    return _AVAILABLE


def _client():
    """Return a habanero.Crossref client with polite-pool email if set."""
    if not _AVAILABLE:
        raise ImportError(
            "habanero not installed. Install with: pip install 'rka[writer-tools]'"
        )
    email = os.environ.get("CROSSREF_EMAIL")
    return Crossref(mailto=email) if email else Crossref()


def resolve_doi(doi: str) -> dict[str, Any] | None:
    """Resolve a DOI to CSL-JSON via Crossref REST.

    Returns None on 404, network error, or when habanero is not installed.
    The returned dict is Crossref's CSL-JSON-shaped record (the "message"
    field of a /works/{doi} response).
    """
    if not _AVAILABLE:
        return None
    try:
        result = _client().works(ids=[doi])
        if isinstance(result, list):
            result = result[0] if result else {}
        return result.get("message")
    except Exception:
        return None


def search_works(query: str, rows: int = 10) -> list[dict[str, Any]]:
    """Title-based search via Crossref REST."""
    if not _AVAILABLE:
        return []
    try:
        result = _client().works(query=query, limit=rows)
        return result.get("message", {}).get("items", [])
    except Exception:
        return []


def get_update_to(doi: str) -> list[dict[str, Any]]:
    """Return the Crossref update-to records for a DOI (Stage D retraction).

    The update-to field lists records that update or retract this work.
    Filter by source='retraction-watch' (or 'crossref') to identify
    retractions specifically.
    """
    if not _AVAILABLE:
        return []
    record = resolve_doi(doi)
    if record is None:
        return []
    return record.get("update-to", []) or []
