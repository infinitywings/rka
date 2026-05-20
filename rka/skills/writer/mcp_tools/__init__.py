"""rka-writer-tools combined MCP server (Phase 2).

Provides 4 high-level MCP tools wrapping 5 external-API backends:

  validate_reference     -> Stage B resolution waterfall
                            (Crossref -> manubot -> OpenAlex -> S2 -> arXiv)
  disambiguate_author    -> OpenAlex two-step + ORCID, with SerpAPI tertiary
  find_citation          -> free-text search across primary indexes
  check_retraction       -> Crossref update-to + RWDB CSV mirror

Backends in rka.skills.writer.mcp_tools.backends.* gracefully degrade when
their PyPI package or API key is absent.

Phase 2 mission: mis_01KS2S871YPQ3D5RVY5K3PSQY6
Phase 2 scope decision: dec_01KS2S22VV5P5SWWXNBXQDHMGX
"""

__all__ = ["server"]
