# Reference Validation Pipeline

Seven stages (A through G) are implemented in `scripts/validate_references.py`. Optional providers degrade explicitly; an unavailable provider never counts as a confirmation. The core manuscript operation enables retraction checking and persists an immutable project/manuscript-scoped attestation.

## Architectural rationale

Citation fabrication is the most common LLM failure in manuscript drafting. Cross-study average is 51 percent across six published studies covering 732 LLM-generated citations (`jrn_01KS0AVZRDA0KPXK61MN9PV5DE` captures the empirical anchors). Multi-source cross-check is the only working defense; a single-source check is insufficient.

The pipeline is structured as seven stages with explicit verdict statuses. A reference advances through stages; any stage may set a terminal status. Only `VERIFIED` references are eligible for bibliography compilation; every other status blocks the CLI gate unless a separate, explicit PI-governed workflow handles the exception.

## Stage A: Extraction

Inputs:
- `rka_query(args={"operation": "literature", "project_id": "prj_..."})` to pull `lit_` entities for the project.
- Anystyle parse of free-text references (if PI provides plain-text references rather than RKA-resident `lit_`).
- Direct identifiers (DOI, arXiv, PubMed) extracted from text via regex.

Outputs:
- A working set of candidate references in CSL-JSON form.
- Each candidate carries `source_origin` (RKA-resident `lit_`, free-text parse, or direct identifier).

Current status: **implemented** for CSL-JSON/direct identifiers and manubot conversion. Free-text anystyle parsing remains an optional external preprocessing path.

## Stage B: Identifier resolution

Current provider calls:

1. **DOI input:** Crossref, OpenAlex, and Semantic Scholar are queried so Stage C can count independent provider hits.
2. **Title-only input:** Crossref, OpenAlex, Semantic Scholar, and arXiv are searched.
3. **manubot:** used by Stage A's standalone identifier-to-BibTeX path and by Stage F compilation; it is not counted as a Stage C provider hit.

Never query Google Scholar directly. Direct scraping is forbidden per `dec_01KS0AXXASJ5GXV7M0SS39Y066` and anti-pattern 8 in SKILL.md.

Current status: **implemented** through the installed `rka-writer-tools` backends. Each attempted and confirming source is recorded.

## Stage C: Cross-source existence validation

A reference is `VERIFIED` at Stage C only when at least two independent providers return a hit. The current deterministic gate counts provider hits; it does not reconcile title, author, year, or venue fields. Detailed cross-provider field reconciliation remains a PI-visible follow-up and must not be inferred from `VERIFIED` alone.

Statuses set by Stage C:

- `VERIFIED`: at least two independent providers return a hit.
- `LOW_CONFIDENCE`: exactly one provider returns a hit; this is blocking.
- `UNVERIFIED`: no provider returns a hit; advance to Stage G niche-citation rescue.

`FIELD_ERROR` is not a metadata-disagreement verdict in the current implementation. It records malformed input or a provider/stage failure that prevents a trustworthy conclusion.

Current status: **implemented** for source-count confirmation.

## Stage D: Retraction check

Retraction Watch was acquired by Crossref in September 2023. The Retraction Watch Database (RWDB) feeds the main Crossref REST API. Primary check:

```
GET /v1/works/{DOI} -> updated-by array -> filter source="retraction-watch"
```

The implemented core check inspects Crossref update metadata. A local Retraction Watch CSV mirror is a possible secondary source, not a claim made by the current attestation.

OpenAlex `is_retracted` is a tertiary check; the field had pipeline issues from December 2023 through March 2024 (Hauschke and Nazarovets 2024, arXiv:2403.13339) and is not authoritative on its own.

R retractcheck was archived in 2022; do not use.

Statuses set or preserved by Stage D:

- `VERIFIED`: the enabled DOI retraction check completed and found no retraction.
- `RETRACTED`: Crossref `updated-by` includes a retraction record. Compile blocks unless PI overrides with retraction-discussion citation rationale stored as `dec_`.
- `FIELD_ERROR`: the enabled retraction backend was unavailable or failed; the gate fails closed.

Current status: **implemented** for DOI-bearing references via Crossref update metadata. Core manuscript validation does not disable this stage.

## Stage E: Author disambiguation

The current implementation searches OpenAlex author candidates and uses optional affiliation hints. An unmatched author conditionally triggers the budgeted SerpAPI author fallback; no ORCID lookup is currently implemented. A mismatch triggers `AUTHOR_MISMATCH`; partial or unavailable coverage triggers `LOW_CONFIDENCE`.

Current status: **implemented when authors are supplied and author checking is requested**. The audit records whether this optional stage ran.

## Stage F: Bibliography compilation

Once all references are `VERIFIED`, compile `refs.bib`:

1. manubot generates BibTeX entries from CSL-JSON.
2. bibtex-tidy (Node CLI, MIT) applies hygiene: `--curly --numeric --sort=key --duplicates=key,doi --escape --tidy-comments --remove-empty-fields --enclosing-braces=title`.
3. Optional: betterbib (GPL-3.0) cross-source field sync via subprocess. betterbib is **never vendored** due to its GPL license; only subprocess invocation is permitted.

Current status: **implemented** for entries whose preceding validation verdict permits compilation.

## Stage G: Niche-citation rescue

When Stages B through C return empty across all primary sources (Crossref, OpenAlex, Semantic Scholar, arXiv), one final SerpAPI `google_scholar` lookup runs before assigning `HALLUCINATED`. A hit produces `UNVERIFIED` with `note=scholar-only-source`, which triggers a PI checkpoint to either ratify the citation with a `dec_` override or remove it.

SerpAPI budget: 200 searches per manuscript (counted across Stages E and G), tracked in `refs.audit.json`. `SERPAPI_KEY` is an env var, never committed; if unset, Stage G silently skips and the reference proceeds to `HALLUCINATED`.

Current status: **implemented when a SerpAPI budget/provider is available**. Absence is recorded and never converted to confirmation.

## Status reference

| Status | Set by | Compile block? | Resolution path |
|---|---|---|---|
| `VERIFIED` | Stage C (two sources concur) | no | proceed |
| `FIELD_ERROR` | malformed input or provider/stage failure | yes | repair input or restore the failed stage; do not infer a metadata conflict |
| `UNVERIFIED` | Stage C (insufficient sources) or Stage G hit | yes | proceed to Stage G; on Stage G hit, PI checkpoint |
| `RETRACTED` | Stage D | yes | PI override with retraction-discussion rationale |
| `HALLUCINATED` | Stage G empty | yes | remove citation or PI ratifies as non-existent claim |
| `AUTHOR_MISMATCH` | Stage E | yes | Stage E rerun with SerpAPI; PI reconciles |
| `LOW_CONFIDENCE` | Stage E | yes | Stage E rerun with SerpAPI; PI ratifies |

## Runtime and audit boundary

The `rka-writer-tools` MCP exposes `validate_reference`, `disambiguate_author`, `find_citation`, and `check_retraction`. Provider packages and credentials are runtime concerns and are never stored in a manuscript workspace. SerpAPI is optional and budgeted; its absence is explicit in the audit. The core `validate_reference` operation stores the input identity, manuscript/project scope, stages run, sources attempted and confirmed, categorical status, notes, and complete returned payload. Re-running creates another immutable attestation rather than overwriting history.

## Library version reference

Re-verify installed versions when reproducing an audit; the following are design-time references, not live-policy pins:

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

Installed versions may diverge. Record the actual environment for reproducibility rather than treating this table as authoritative current package guidance.

## References

- Deep research synthesis (citation hallucination empirical floor): `jrn_01KS0AVZRDA0KPXK61MN9PV5DE`.
- SerpAPI policy: `dec_01KS0AXXASJ5GXV7M0SS39Y066`.
- Q1-Q8 bundle (Phase scoping): `dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D`.
- OpenAlex retraction data issue: Hauschke and Nazarovets 2024, arXiv:2403.13339.
