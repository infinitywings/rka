"""OpenAlex backend via pyalex.

Stage B resolution fallback after Crossref; Stage E primary author
disambiguation source. No API key required; polite-pool via OPENALEX_EMAIL
env var (free tier acceptable per dec_01KS2S22VV5P5SWWXNBXQDHMGX assumption #4).
"""

from __future__ import annotations

import os
from typing import Any

try:
    import pyalex  # type: ignore
    from pyalex import Works, Authors  # type: ignore
    _AVAILABLE = True
except ImportError:
    pyalex = None  # type: ignore
    Works = None  # type: ignore
    Authors = None  # type: ignore
    _AVAILABLE = False


def is_available() -> bool:
    return _AVAILABLE


def _configure_polite_pool() -> None:
    """Set pyalex.config.email from OPENALEX_EMAIL if available."""
    if not _AVAILABLE:
        return
    email = os.environ.get("OPENALEX_EMAIL")
    if email:
        pyalex.config.email = email


def _normalize_doi(doi: str) -> str:
    """Strip protocol prefix so the OpenAlex lookup key is consistent."""
    return doi.replace("https://doi.org/", "").replace("http://doi.org/", "").strip()


def resolve_doi(doi: str) -> dict[str, Any] | None:
    """Resolve a DOI to a CSL-JSON-ish shape via OpenAlex Works."""
    if not _AVAILABLE:
        return None
    _configure_polite_pool()
    try:
        normalized = _normalize_doi(doi)
        lookup_key = f"https://doi.org/{normalized}"
        record = Works()[lookup_key]
        return _to_csl_json(record) if record else None
    except Exception:
        return None


def search_works(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Free-text search across OpenAlex Works."""
    if not _AVAILABLE:
        return []
    _configure_polite_pool()
    try:
        results = Works().search(query).get(per_page=max_results)
        return [_to_csl_json(w) for w in results]
    except Exception:
        return []


def disambiguate_author(
    name: str,
    affiliation_hints: list[str] | None = None,
) -> dict[str, Any] | None:
    """Author disambiguation via OpenAlex Authors search.

    If affiliation_hints provided, pick the first candidate whose affiliation
    text contains any hint. Otherwise return the highest-ranked candidate.
    """
    if not _AVAILABLE:
        return None
    _configure_polite_pool()
    try:
        candidates = Authors().search(name).get(per_page=5)
        if not candidates:
            return None
        if affiliation_hints:
            hints_lower = [h.lower() for h in affiliation_hints]
            for cand in candidates:
                affs = " ".join(
                    (a.get("institution") or {}).get("display_name") or ""
                    for a in (cand.get("affiliations") or [])
                ).lower()
                if any(h in affs for h in hints_lower):
                    return cand
        return candidates[0]
    except Exception:
        return None


def _to_csl_json(record: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenAlex Works record to a CSL-JSON-ish dict.

    Keeps only the fields the validation pipeline cares about. Removes None
    values so downstream comparison logic does not stumble on absence.
    """
    doi_field = record.get("doi") or ""
    csl: dict[str, Any] = {
        "DOI": doi_field.replace("https://doi.org/", "") if doi_field else None,
        "title": record.get("title"),
        "type": (
            "article-journal"
            if record.get("type") == "journal-article"
            else record.get("type")
        ),
    }
    year = record.get("publication_year")
    if year:
        csl["issued"] = {"date-parts": [[year]]}
    authors_raw = record.get("authorships") or []
    if authors_raw:
        authors: list[dict[str, str]] = []
        for a in authors_raw:
            name = (a.get("author") or {}).get("display_name") or ""
            if name:
                parts = name.split()
                authors.append(
                    {"family": parts[-1], "given": " ".join(parts[:-1])} if len(parts) > 1
                    else {"family": parts[0]}
                )
        if authors:
            csl["author"] = authors
    return {k: v for k, v in csl.items() if v is not None}
