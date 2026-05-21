"""Semantic Scholar backend via semanticscholar.

Stage B resolution fallback after OpenAlex. CS / AI coverage strength.
API key optional but recommended for higher rate limits per
dec_01KS2S22VV5P5SWWXNBXQDHMGX assumption #6.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from semanticscholar import SemanticScholar  # type: ignore
    _AVAILABLE = True
except ImportError:
    SemanticScholar = None  # type: ignore
    _AVAILABLE = False


def is_available() -> bool:
    return _AVAILABLE


def _client():
    if not _AVAILABLE:
        raise ImportError("semanticscholar not installed.")
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    return SemanticScholar(api_key=api_key) if api_key else SemanticScholar()


def resolve_doi(doi: str) -> dict[str, Any] | None:
    """Resolve a DOI to CSL-JSON via Semantic Scholar."""
    if not _AVAILABLE:
        return None
    try:
        paper = _client().get_paper(f"DOI:{doi}")
        if paper is None:
            return None
        raw = getattr(paper, "raw_data", None) or {}
        return _to_csl_json(raw) if raw else None
    except Exception:
        return None


def paper_by_id(identifier: str) -> dict[str, Any] | None:
    """Resolve any S2-recognized identifier (DOI:, ARXIV:, CorpusId:, etc.)."""
    if not _AVAILABLE:
        return None
    try:
        paper = _client().get_paper(identifier)
        if paper is None:
            return None
        raw = getattr(paper, "raw_data", None) or {}
        return _to_csl_json(raw) if raw else None
    except Exception:
        return None


def search_papers(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Free-text title/abstract search."""
    if not _AVAILABLE:
        return []
    try:
        results = _client().search_paper(query, limit=limit)
        return [_to_csl_json(getattr(r, "raw_data", None) or {}) for r in results]
    except Exception:
        return []


def _to_csl_json(record: dict[str, Any]) -> dict[str, Any]:
    """Convert a Semantic Scholar paper record to CSL-JSON-ish."""
    external = record.get("externalIds") or {}
    csl: dict[str, Any] = {
        "DOI": external.get("DOI"),
        "title": record.get("title"),
    }
    year = record.get("year")
    if year:
        csl["issued"] = {"date-parts": [[year]]}
    authors_raw = record.get("authors") or []
    if authors_raw:
        authors: list[dict[str, str]] = []
        for a in authors_raw:
            name = a.get("name") or ""
            if name:
                parts = name.split()
                authors.append(
                    {"family": parts[-1], "given": " ".join(parts[:-1])} if len(parts) > 1
                    else {"family": parts[0]}
                )
        if authors:
            csl["author"] = authors
    return {k: v for k, v in csl.items() if v is not None}
