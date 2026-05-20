"""arXiv backend via the arxiv package (pinned >=3.0,<4.0).

Stage B resolution final fallback for preprints. No API key; library
self-rate-limits at one request per three seconds.

Pin: arxiv 4.0 shipped 2026-05-17 (3 days before Phase 2 mission filing);
two majors in 5 weeks indicates unstable change velocity. Phase 2 pins to
the 3.x line; Phase 3+ will audit 4.x release notes and re-evaluate per
dec_01KS2S22VV5P5SWWXNBXQDHMGX Brain ratification 2026-05-20.
"""

from __future__ import annotations

from typing import Any

try:
    import arxiv as _arxiv  # type: ignore
    _AVAILABLE = True
except ImportError:
    _arxiv = None  # type: ignore
    _AVAILABLE = False


def is_available() -> bool:
    return _AVAILABLE


def get_paper(arxiv_id: str) -> dict[str, Any] | None:
    """Fetch a specific arXiv preprint by ID and return CSL-JSON-ish."""
    if not _AVAILABLE:
        return None
    try:
        search = _arxiv.Search(id_list=[arxiv_id])
        client = _arxiv.Client()
        result = next(client.results(search), None)
        return _to_csl_json(result) if result else None
    except Exception:
        return None


def search_papers(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Free-text search against arXiv listings."""
    if not _AVAILABLE:
        return []
    try:
        search = _arxiv.Search(query=query, max_results=max_results)
        client = _arxiv.Client()
        return [_to_csl_json(r) for r in client.results(search)]
    except Exception:
        return []


def _to_csl_json(result) -> dict[str, Any]:
    """Convert an arxiv.Result object to CSL-JSON-ish."""
    csl: dict[str, Any] = {
        "title": result.title,
        "URL": result.entry_id,
    }
    doi = getattr(result, "doi", None)
    if doi:
        csl["DOI"] = doi
    if result.published:
        csl["issued"] = {"date-parts": [[result.published.year]]}
    authors_raw = getattr(result, "authors", None) or []
    if authors_raw:
        authors: list[dict[str, str]] = []
        for a in authors_raw:
            name = getattr(a, "name", "") or ""
            if not name:
                continue
            parts = name.split()
            authors.append(
                {"family": parts[-1], "given": " ".join(parts[:-1])} if len(parts) > 1
                else {"family": parts[0]}
            )
        if authors:
            csl["author"] = authors
    return csl
