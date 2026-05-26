"""Backend wrappers for the rka-writer-tools MCP server.

Each module wraps a single external-API client and exposes a small, stable
function surface used by the higher-level tools in
rka.skills.writer.mcp_tools.server. All backends gracefully degrade when
their PyPI package is not installed (functions return None or [] rather
than raising on the absence of the optional dependency).

Backends:
  crossref         (habanero)         Stage B, Stage D (update-to retraction)
  openalex         (pyalex)           Stage B, Stage E author disambiguation
  semantic_scholar (semanticscholar)  Stage B
  arxiv_backend    (arxiv)            Stage B
  serpapi_backend  (serpapi)          Stage E tertiary, Stage G niche rescue
"""
