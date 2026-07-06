# Reference Validation Pipeline

Seven stages (A through G). Phase 1 implements only Stage A; Stages B through G are documented architecture here and stubbed in `scripts/validate_references.py` (raise `NotImplementedError` with this file referenced).

## Architectural rationale

Citation fabrication is the most common LLM failure in manuscript drafting. Cross-study average is 51 percent across six published studies covering 732 LLM-generated citations (`jrn_01KS0AVZRDA0KPXK61MN9PV5DE` captures the empirical anchors). Multi-source cross-check is the only working defense; a single-source check is insufficient.

The pipeline is structured as seven stages with explicit verdict statuses. A reference advances through stages; any stage may set a terminal status. Compile-time enforcement at the Writer layer blocks `UNVERIFIED` and `HALLUCINATED` citations unless overridden via `dec_`.

## Stage A: Extraction

Inputs:
- `rka_query(args={"operation": "literature", "project_id": "prj_..."})` to pull `lit_` entities for the project.
- Anystyle parse of free-text references (if PI provides plain-text references rather than RKA-resident `lit_`).
- Direct identifiers (DOI, arXiv, PubMed) extracted from text via regex.

Outputs:
- A working set of candidate references in CSL-JSON form.
- Each candidate carries `source_origin` (RKA-resident `lit_`, free-text parse, or direct identifier).

Phase 1 status: **implemented**. `scripts/validate_references.py` Stage A converts CSL-JSON from `rka_query` `literature` output to BibTeX via the `manubot` Python package if installed. Free-text anystyle parsing requires the anystyle Ruby gem and is a Phase 2 deliverable.

## Stage B: Identifier resolution

Resolution waterfall (preferred to fallback):

1. **Crossref via habanero** (`habanero.Crossref.works(ids=[doi])`). Canonical for DOI to BibTeX.
2. **manubot** (`manubot cite doi:...`). Multi-source identifier resolver; fallback for non-DOI identifiers (PubMed, PMC, arXiv, ISBN, Wikidata).
3. **OpenAlex via pyalex**. Title-to-DOI resolution if only a title is available.
4. **Semantic Scholar via semanticscholar Python package**. Coverage strength: CS and AI. Multi-format IDs: `DOI:`, `ARXIV:`, `CorpusId:`.
5. **arXiv via the arxiv Python package**. Preprint resolution. Built-in rate limit one request per three seconds.

Never query Google Scholar directly. Direct scraping is forbidden per `dec_01KS0AXXASJ5GXV7M0SS39Y066` and anti-pattern 8 in SKILL.md.

Phase 1 status: **stubbed**. Stage B requires `rka-writer-tools` MCP server (Phase 2 deliverable) or local Python packages installed in the workspace. The stub in `scripts/validate_references.py` raises `NotImplementedError` and points the PI to this file.

## Stage C: Cross-source existence validation

A reference is `VERIFIED` only when at least two independent sources confirm its existence with consistent metadata (title, authors, year, venue). Conflicting metadata produces `FIELD_ERROR` with the conflict surfaced.

Statuses set by Stage C:

- `VERIFIED`: at least two sources concur on title plus first author plus year.
- `FIELD_ERROR`: one or more sources found but metadata diverges.
- `UNVERIFIED`: zero or one sources found; advance to Stage G niche-citation rescue.

Phase 1 status: **stubbed**.

## Stage D: Retraction check

Retraction Watch was acquired by Crossref in September 2023. The Retraction Watch Database (RWDB) feeds the main Crossref REST API. Primary check:

```
GET /v1/works/{DOI} -> updated-by array -> filter source="retraction-watch"
```

Secondary check: CSV mirror at `api.labs.crossref.org/data/retractionwatch` or `git clone gitlab.com/crossref/retraction-watch-data`.

OpenAlex `is_retracted` is a tertiary check; the field had pipeline issues from December 2023 through March 2024 (Hauschke and Nazarovets 2024, arXiv:2403.13339) and is not authoritative on its own.

R retractcheck was archived in 2022; do not use.

Statuses set by Stage D:

- `VERIFIED`: passes retraction check.
- `RETRACTED`: Crossref `updated-by` includes a retraction record. Compile blocks unless PI overrides with retraction-discussion citation rationale stored as `dec_`.

Phase 1 status: **stubbed**.

## Stage E: Author disambiguation

Two-step:

1. OpenAlex Author IDs (W ID system).
2. ORCID via `python-orcid` package.

Sources concur on the same author entity. Mismatch triggers `AUTHOR_MISMATCH`. Low coverage triggers `LOW_CONFIDENCE`.

Third source on `AUTHOR_MISMATCH` or `LOW_CONFIDENCE`: SerpAPI `google_scholar_author` endpoint, per `dec_01KS0AXXASJ5GXV7M0SS39Y066`. Used only conditionally; not on every disambiguation.

Phase 1 status: **stubbed**.

## Stage F: Bibliography compilation

Once all references are `VERIFIED`, compile `refs.bib`:

1. manubot generates BibTeX entries from CSL-JSON.
2. bibtex-tidy (Node CLI, MIT) applies hygiene: `--curly --numeric --sort=key --duplicates=key,doi --escape --tidy-comments --remove-empty-fields --enclosing-braces=title`.
3. Optional: betterbib (GPL-3.0) cross-source field sync via subprocess. betterbib is **never vendored** due to its GPL license; only subprocess invocation is permitted.

Phase 1 status: Stage A output feeds Stage F directly without B-E validation. Phase 2 wires the full chain.

## Stage G: Niche-citation rescue

When Stages B through C return empty across all primary sources (Crossref, OpenAlex, Semantic Scholar, arXiv), one final SerpAPI `google_scholar` lookup runs before assigning `HALLUCINATED`. A hit produces `UNVERIFIED` with `note=scholar-only-source`, which triggers a PI checkpoint to either ratify the citation with a `dec_` override or remove it.

SerpAPI budget: 200 searches per manuscript (counted across Stages E and G), tracked in `refs.audit.json`. `SERPAPI_KEY` is an env var, never committed; if unset, Stage G silently skips and the reference proceeds to `HALLUCINATED`.

Phase 1 status: **stubbed**; SerpAPI integration is a Phase 2 deliverable.

## Status reference

| Status | Set by | Compile block? | Resolution path |
|---|---|---|---|
| `VERIFIED` | Stage C (two sources concur) | no | proceed |
| `FIELD_ERROR` | Stage C (metadata conflict) | yes | PI reviews; reconcile metadata or override |
| `UNVERIFIED` | Stage C (insufficient sources) or Stage G hit | yes | proceed to Stage G; on Stage G hit, PI checkpoint |
| `RETRACTED` | Stage D | yes | PI override with retraction-discussion rationale |
| `HALLUCINATED` | Stage G empty | yes | remove citation or PI ratifies as non-existent claim |
| `AUTHOR_MISMATCH` | Stage E | yes | Stage E rerun with SerpAPI; PI reconciles |
| `LOW_CONFIDENCE` | Stage E | yes | Stage E rerun with SerpAPI; PI ratifies |

## Phase 2 implementation notes

The Phase 2 mission will:

1. Install `habanero`, `pyalex`, `semanticscholar`, `arxiv`, `manubot`, `python-orcid`, `bibtex-tidy` (Node), `anystyle` (Ruby gem) at the workspace level.
2. Build the `rka-writer-tools` MCP server exposing high-level operations `validate_reference`, `disambiguate_author`, `find_citation`, `check_retraction`. Each operation orchestrates the stages above.
3. Wire `scripts/validate_references.py` from stub to full implementation.
4. Add `SERPAPI_KEY` env var support; default None silently skips Stages E (third source) and G.
5. Add nightly RWDB CSV refresh as a cron-managed sidecar.
6. Extend `ai_tic_config.yaml` with per-project SerpAPI budget overrides.

Estimated Phase 2 scope: 3 engineer-weeks plus ~5 PI hours (per design doc Section 16).

## Library version pins (Phase 2 reference)

These will be re-verified at Phase 2 Backbrief per the version-drift discipline:

| Package | Version at design-time | License |
|---|---|---|
| habanero | 2.3.0 | MIT |
| pyalex | (latest, requires API key from 2026-02-13) | MIT |
| semanticscholar | 0.12.0 | MIT |
| arxiv | 2.1.0 | MIT |
| manubot | (latest) | BSD-2 + CC0 |
| python-orcid / PyOrcid | (latest) | BSD-3 / MIT |
| bibtex-tidy | (latest, Node) | MIT |
| anystyle (Ruby gem) | (latest) | BSD-2 |
| betterbib | (subprocess only) | GPL-3.0 (never vendored) |

The actual installed versions at Phase 2 may diverge; the Backbrief at that mission's start will re-verify each pin against the current PyPI / RubyGems / npm registry and flag any line silent over six months.

## References

- Deep research synthesis (citation hallucination empirical floor): `jrn_01KS0AVZRDA0KPXK61MN9PV5DE`.
- SerpAPI policy: `dec_01KS0AXXASJ5GXV7M0SS39Y066`.
- Q1-Q8 bundle (Phase scoping): `dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D`.
- OpenAlex retraction data issue: Hauschke and Nazarovets 2024, arXiv:2403.13339.
