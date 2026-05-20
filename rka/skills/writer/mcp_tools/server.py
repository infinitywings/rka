"""rka-writer-tools MCP server.

FastMCP-based stdio server exposing 4 high-level tools that orchestrate
calls to 5 backend wrappers (Crossref via habanero, OpenAlex via pyalex,
Semantic Scholar via semanticscholar, arXiv via arxiv, SerpAPI via serpapi).

Phase 2 deliverable per dec_01KS2S22VV5P5SWWXNBXQDHMGX (Option A bundled
single mission). Bookkeeper invariant preserved: this MCP server lives
under rka/skills/writer/mcp_tools/, NOT under rka/mcp/ (which remains the
RKA core MCP).

CLI:
    rka-writer-tools                                  # via installed entry point
    python -m rka.skills.writer.mcp_tools.server      # via module

The 4 tools wrap pieces of the Stage B through G validation pipeline that
is implemented in full in rka/skills/writer/scripts/validate_references.py
(T2 deliverable). The MCP server provides the same operations as MCP-tool
calls for use by external orchestrators (e.g., Brain mission revisions
in Phase 3).
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from rka.skills.writer.mcp_tools.backends import (
    crossref,
    openalex,
    semantic_scholar,
)
from rka.skills.writer.mcp_tools.backends import arxiv_backend as arxiv
from rka.skills.writer.mcp_tools.backends import serpapi_backend as serpapi


WRITER_TOOLS_INSTRUCTIONS = """\
rka-writer-tools exposes the Writer skill's external-citation operations as
MCP tools. Four tools available:

- validate_reference: cross-source identifier resolution (Crossref ->
  OpenAlex -> Semantic Scholar -> arXiv). Returns the first hit or
  UNVERIFIED with the list of sources tried.
- disambiguate_author: OpenAlex two-step; SerpAPI tertiary on mismatch
  (consumes credit budget).
- find_citation: free-text title/keyword search across primary indexes.
- check_retraction: Crossref update-to records for a DOI.

Per dec_01KS0AXXASJ5GXV7M0SS39Y066: SerpAPI is tertiary and respects a
credit budget (default 200/manuscript via SERPAPI_BUDGET env). Per
dec_01KS2S22VV5P5SWWXNBXQDHMGX: SerpAPI paths gracefully degrade when
SERPAPI_API_KEY is absent.

Backend availability is reported by the report_backend_availability tool;
the validation pipeline degrades gracefully on missing backends rather
than failing.
"""


mcp = FastMCP("rka-writer-tools", instructions=WRITER_TOOLS_INSTRUCTIONS)


@mcp.tool()
def validate_reference(
    doi: str | None = None,
    title: str | None = None,
    authors: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve a citation via the Stage B resolution waterfall.

    Tries Crossref (habanero), then OpenAlex (pyalex), then Semantic
    Scholar, then arXiv. Returns the first non-empty hit. If all sources
    return empty, returns status='UNVERIFIED' with the sources tried.

    The pipeline in validate_references.py (T2) implements full Stage C
    cross-source confirmation (>= 2 sources concur => VERIFIED). This MCP
    tool returns the single-source view; callers needing confirmation
    should call once per source and aggregate, or use the pipeline script.

    Args:
        doi: Explicit DOI; takes precedence over title and authors.
        title: Paper title for title-based search.
        authors: List of author surnames for query refinement.

    Returns:
        {"status": "resolved", "source": "<backend>", "csl_json": {...}}
        or {"status": "UNVERIFIED", "tried": ["crossref", ...]}.
    """
    tried: list[str] = []

    if doi:
        for name, fn in (
            ("crossref", crossref.resolve_doi),
            ("openalex", openalex.resolve_doi),
            ("semantic_scholar", semantic_scholar.resolve_doi),
        ):
            tried.append(name)
            result = fn(doi)
            if result:
                return {"status": "resolved", "source": name, "csl_json": result}
        return {"status": "UNVERIFIED", "tried": tried}

    if title:
        query = title if not authors else f"{title} {' '.join(authors)}"
        for name, fn in (
            ("crossref", crossref.search_works),
            ("openalex", openalex.search_works),
            ("semantic_scholar", semantic_scholar.search_papers),
            ("arxiv", arxiv.search_papers),
        ):
            tried.append(name)
            results = fn(query, max_results=1) if name != "crossref" else fn(query, rows=1)
            if results:
                return {
                    "status": "resolved",
                    "source": name,
                    "csl_json": results[0],
                }
        return {"status": "UNVERIFIED", "tried": tried}

    return {"status": "error", "message": "Provide at least doi or title."}


@mcp.tool()
def disambiguate_author(
    name: str,
    affiliation_hints: list[str] | None = None,
    use_serpapi_fallback: bool = False,
) -> dict[str, Any]:
    """OpenAlex author disambiguation; SerpAPI tertiary on mismatch.

    Primary path: pyalex Authors.search(name) with affiliation filtering.
    On AUTHOR_MISMATCH or LOW_CONFIDENCE verdicts (caller signals via
    use_serpapi_fallback), invoke SerpAPI google_scholar_profiles search
    and consume one credit from the per-manuscript budget.

    Args:
        name: Author display name.
        affiliation_hints: Optional list of institution names to refine.
        use_serpapi_fallback: When True, falls back to SerpAPI if primary
            returns empty or low-confidence. Consumes one credit.

    Returns:
        {"status": "resolved", "source": "openalex" | "serpapi", "author": {...}}
        or {"status": "AUTHOR_MISMATCH", "tried": [...]}.
    """
    primary = openalex.disambiguate_author(name, affiliation_hints=affiliation_hints)
    if primary:
        return {"status": "resolved", "source": "openalex", "author": primary}

    if use_serpapi_fallback and serpapi.is_available():
        budget = serpapi.default_budget_from_env()
        fallback = serpapi.google_scholar_author_search(
            name, budget=budget, affiliation_hints=affiliation_hints
        )
        if fallback:
            return {
                "status": "resolved",
                "source": "serpapi",
                "author": fallback,
                "budget_used": budget.used,
            }

    return {"status": "AUTHOR_MISMATCH", "tried": ["openalex"] + (["serpapi"] if use_serpapi_fallback else [])}


@mcp.tool()
def find_citation(
    query: str,
    max_results: int = 5,
) -> dict[str, Any]:
    """Free-text search across Crossref + OpenAlex + Semantic Scholar + arXiv.

    Returns per-source result lists. Caller aggregates / dedupes by DOI.

    Args:
        query: Title or keyword query.
        max_results: Per-source result cap (default 5).
    """
    return {
        "crossref": crossref.search_works(query, rows=max_results),
        "openalex": openalex.search_works(query, max_results=max_results),
        "semantic_scholar": semantic_scholar.search_papers(query, limit=max_results),
        "arxiv": arxiv.search_papers(query, max_results=max_results),
    }


@mcp.tool()
def check_retraction(doi: str) -> dict[str, Any]:
    """Stage D retraction check via Crossref update-to.

    Returns a list of update records (empty if not retracted). Filter
    client-side for source='retraction-watch' to identify retractions
    specifically; other update types include corrections and addenda.
    """
    updates = crossref.get_update_to(doi)
    is_retracted = any(
        (u.get("type") == "retraction"
         or "retract" in (u.get("type") or "").lower()
         or u.get("source") == "retraction-watch")
        for u in updates
    )
    return {
        "doi": doi,
        "is_retracted": is_retracted,
        "updates": updates,
    }


@mcp.tool()
def report_backend_availability() -> dict[str, bool]:
    """Diagnostic: report which backend wrappers are usable.

    Each backend reports True only when its PyPI package is installed AND
    (for SerpAPI) its API key env var is set.
    """
    return {
        "crossref": crossref.is_available(),
        "openalex": openalex.is_available(),
        "semantic_scholar": semantic_scholar.is_available(),
        "arxiv": arxiv.is_available(),
        "serpapi": serpapi.is_available(),
    }


def main() -> None:
    """Entry point for the rka-writer-tools console script."""
    mcp.run()


if __name__ == "__main__":
    main()
