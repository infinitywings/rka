# Phase 1 MVP: what shipped, what is deferred, how to use Phase 1 deliverables manually

Phase 1 of the RKA Writer skill ships a usable manuscript-drafting
substrate that operates against the existing `rka` MCP server. Reference
validation Stages B through G, the `rka-writer-tools` MCP server, the
Revision Loop, and the Brain mission integration are explicitly Phase 2
and Phase 3 deliverables. This document is the orientation read for the
PI to use Phase 1 effectively while Phase 2 and Phase 3 land.

Mission: `mis_01KS0C3RP04XANCZAB3HTNAG0P`. Decisions:
`dec_01KS0AWYDV752AWQRF40CQBRFZ` (deployment),
`dec_01KS0AXXASJ5GXV7M0SS39Y066` (SerpAPI tertiary),
`dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D` (Q1-Q8 bundle),
`dec_01KS12H9KT1T03DHX2Q6FKTXHH` (anti-AI-tic primary-source disposition,
PATCH 2).

> **v2.7.0 dispatch translation.** Legacy tool names in this document
> (`rka_add_decision`, `rka_record_pi_selection`, `rka_add_literature`,
> `rka_update_literature`, `rka_get_literature`, `rka_create_mission`, and the
> Phase 3 `rka_get_manuscript` / `rka_register_manuscript` /
> `rka_validate_reference`) are synonyms for `rka_execute(args={"operation":
> ...})` (writes) and `rka_query(args={"operation": ...})` (reads) under the
> v2.7.0+ typed-arg surface — e.g. `rka_add_decision` →
> `rka_execute(args={"operation": "record_decision", ...})` and
> `rka_get_literature` → `rka_query(args={"operation": "literature", ...})`.
> The legacy names are deferred tools loadable via `rka_load_tools`; the
> provenance discipline (`related_journal=[...]` and `phase` on decisions,
> `motivated_by_decision` on missions, `project_id` on every call) carries
> over unchanged. See `rka_describe(operation="<name>")` for per-operation
> signatures.

## What shipped in Phase 1

### SKILL.md and references

- `SKILL.md` (291 lines, v2.3.2 frontmatter, 16 sections in stable order).
- `references/workflows.md`: full session-start walkthrough and the seven
  sub-procedures (Venue handler, Outline co-author, Table/figure/chart
  planner, Reference validator, Section drafter, Local renderer plus
  layout auditor, Revision-loop handler).
- `references/architecture.md`: RKA integration, Option 2 manuscript
  representation, 9 provenance edges Writer emits, the bookkeeper
  invariant.
- `references/reference_pipeline.md`: 7-stage validation pipeline with
  Phase 1 implementation status per stage.
- `references/ai_tics.md`: anti-AI-tic enforcement with primary-source
  citations (PI verbatim list, Kobak 2025, Matsui 2025).
- `references/venue/CHI.md` and `references/venue/EMNLP.md`: seed venues
  with seven-field schema.
- `references/template_registry.md`: YAML registry with SHA-256
  placeholders for `acmart` and `acl-style-files`.
- `references/latex_audit.md`: 12-field layout audit checklist with
  regex patterns.
- `references/examples.md`: worked outline ratification and AI-tic
  catch examples.

### Scripts

- `scripts/ai_tic_lint.py` (full): lexical tiers, em-dash absolute ban,
  bullet-density cap, 3 structural detectors, style score, per-project
  override via `ai_tic_config.yaml`. Emits `ai_tic_report.json`.
- `scripts/bridge_repetition_check.py` (full, clean-room): cross-file
  sentence pairs at `difflib.SequenceMatcher` ratio 0.7 threshold.
- `scripts/render.sh` (full): bash wrapper for latexmk with
  `LATEX_ENGINE` env var (pdflatex / lualatex / xelatex).
- `scripts/layout_audit.py` (full): 12 fields with PASS/WARN/BLOCK
  verdicts. Emits `audit.json`.
- `scripts/chart_render.py` (skeleton): matplotlib + seaborn import
  verification, venue presets for CHI and EMNLP. PI fills in
  per-manuscript chart logic; standardized in Phase 2.
- `scripts/validate_references.py` (Stage A only): CSL-JSON to BibTeX
  via manubot subprocess. Stages B through G raise NotImplementedError.
- `scripts/fetch_template.py` (lookup-only): parses the YAML block in
  `references/template_registry.md`; actual archive fetch + SHA-256
  verify in Phase 2.

### Workspace template

`workspace-template/` ships as the bootstrap skeleton the PI copies to
`manuscripts/<project-id>/<venue>/`:

- `.mcp.json`, `.latexmkrc`, `ai_tic_config.yaml`, `main.tex`, `refs.bib`.
- `.planning/`: `ACTIVE_WORKFLOW.md`, `PRECIS.md`, `OUTLINE.md`,
  `REVIEW_STATE.md`.
- Directory placeholders: `sections/`, `figures/`, `tables/`, `charts/`,
  `styles/`.

The template's `.latexmkrc` was smoke-tested end-to-end at mission
close (TeX Live 2025, latexmk 4.86a): empty `\documentclass{article}`
manuscript compiled to a 15.9 KB single-page PDF via `render.sh`.

### Tests

`tests/skills/writer/` ships 43 tests across 5 files: `test_skill_loads.py`
(5), `test_ai_tic_lint.py` (16), `test_layout_audit.py` (11),
`test_bridge_repetition.py` (5), `test_venue_files.py` (6). All passing
on Python 3.13.8 with pytest 9.0.2.

## What is deferred

### Phase 2 (estimated 3 engineer-weeks plus 5 PI hours per design Section 16)

- `rka-writer-tools` MCP server bundling habanero, pyalex,
  semanticscholar, arxiv, manubot, python-orcid, bibtex-tidy.
- Reference validation Stages B through G live:
  - Stage B: identifier resolution waterfall.
  - Stage C: cross-source existence validation.
  - Stage D: Crossref `update-to` + RWDB CSV retraction check.
  - Stage E: OpenAlex + ORCID author disambiguation, SerpAPI third source.
  - Stage F: bibliography compilation chain.
  - Stage G: SerpAPI niche-citation rescue.
- SerpAPI integration with credit budget (200 searches per manuscript)
  per `dec_01KS0AXXASJ5GXV7M0SS39Y066`. `SERPAPI_KEY` env var.
- Author disambiguation with ORCID plus SerpAPI fallback.
- Five additional venue files: USENIX, IEEE-SP, NeurIPS, OSDI, Nature.
- `fetch_template.py` full lifecycle: archive download, SHA-256 verify,
  refusal on mismatch, install to `manuscripts/<project>/<venue>/styles/`.
- `chart_render.py` standardized chart specs per venue.
- `validate_references.py` standardized return statuses (VERIFIED,
  FIELD_ERROR, UNVERIFIED, RETRACTED, HALLUCINATED, AUTHOR_MISMATCH,
  LOW_CONFIDENCE) wired into the manuscript manifest.

### Phase 3 (estimated 2-3 engineer-weeks plus 4 PI hours per design Section 16)

- Revision Loop with four `comment_class` mission shapes (R1 Factual,
  R2 Style, R3 Inconsistency, R4 Logical-escalate) wired to the Brain
  via `rka_create_mission`.
- Brain mission integration: Brain spawns a Writer subagent on a
  Revision Mission.
- Optional MCP tools for manuscripts, added to the existing `rka` server.
  (Now shipped, 2026-05-20. On the v2.7.0+ surface these are
  `rka_query(args={"operation": "manuscript", "project_id": "prj_...", "id":
  "msc_..."})`, `rka_execute(args={"operation": "register_manuscript",
  "project_id": "prj_...", "venue": "...", "title": "..."})`, and
  `rka_execute(args={"operation": "validate_reference", "project_id":
  "prj_...", "manuscript_id": "msc_...", "doi": "..."})` — `validate_reference`
  requires at least one of `doi`/`title`. The legacy names
  `rka_get_manuscript` / `rka_register_manuscript` / `rka_validate_reference`
  remain loadable via `rka_load_tools`.)

## How to use Phase 1 deliverables manually

The validation pipeline is not automated in Phase 1. The PI uses Phase 1
deliverables as follows.

### Venue and outline

These flow through the standard PI checkpoint UX. No manual workaround
needed; the Writer drives the strip-then-re-inject pattern via
`rka_add_decision` and `rka_record_pi_selection`. The ratified outline
lands in `.planning/OUTLINE.md` plus a `dec_`.

### Reference assembly

Phase 1 supports manual assembly. Workflow:

1. PI compiles the candidate reference list (typically from prior reading
   captured as `lit_` entries via `rka_add_literature`).
2. `python3 scripts/validate_references.py --check` confirms manubot is
   on PATH (install via `pip install manubot` if not).
3. For each `lit_` in scope, PI either confirms the validation verdict is
   already recorded as `VERIFIED` from prior work (there is no
   `validation_status` field on a `lit_` entry — record the verdict in the
   entry's `tags` or `notes`), OR manually verifies the citation against
   Crossref / OpenAlex / Semantic Scholar / arXiv and updates via
   `rka_execute(args={"operation": "update_literature", "project_id":
   "prj_...", "id": "lit_...", "tags": ["validation:VERIFIED"]})`.
4. PI exports the verified set via `rka_query(args={"operation":
   "literature", "project_id": "prj_..."})`, saves as CSL-JSON, and runs
   Stage A:
   ```
   python3 scripts/validate_references.py --csl-json verified.json --out refs.bib
   ```
5. `refs.bib` populated; PI verifies with `bibtex-tidy` if installed.

Phase 2 will automate steps 3 to 5.

### Section drafting

Standard flow via the Section Drafter sub-procedure. After each section
draft:

```
python3 scripts/ai_tic_lint.py sections/03-method.tex \
        --config ai_tic_config.yaml --output ai_tic_report.json
```

The linter is auto-invoked by the Writer post-draft, but PI can run it
manually for additional checks (e.g., after a manual edit).

Bridge-repetition check across drafted sections:

```
python3 scripts/bridge_repetition_check.py sections/*.tex --output bridges.json
```

### Render and layout audit

Once at least one section is drafted:

```
./scripts/render.sh main.tex
python3 scripts/layout_audit.py --venue CHI --output audit.json
```

The audit report's `summary.overall_verdict` carries the gate signal for
the Final Layout PI checkpoint. `BLOCK` halts; `WARN` is acceptable per
PI judgment; `PASS` is clear.

### Template installation (Phase 1 manual)

Per `references/template_registry.md`, the PI manually fetches venue
templates using each entry's `install_command`. For `acmart`:

```
tlmgr install acmart
```

For `acl-style-files`:

```
git clone --branch 2025 https://github.com/acl-org/acl-style-files
cp -R acl-style-files manuscripts/<project>/<venue>/styles/
```

Then compute SHA-256 and update `references/template_registry.md` from
`TBD` to the actual value (commit the registry update separately).

Phase 2 will automate fetch + verify via `scripts/fetch_template.py`.

### Revision Loop (Phase 1 manual)

When the PI returns review comments on a section, manually classify each
into R1, R2, R3, or R4 per the Revision Loop section of `SKILL.md`.
Track iteration in `.planning/REVIEW_STATE.md`:

- R1 (Factual): inline fix; re-render; bump iteration.
- R2 (Style or AI-tic): re-run `ai_tic_lint.py` at stricter threshold.
- R3 (Inconsistency): structural rewrite; re-render full document.
- R4 (Logical gap): manually file `rka_create_mission` for Brain or
  Executor to gather evidence.

Cap at three iterations; on the third failure, surface as a PI Style or
Logical checkpoint with three resolution options.

Phase 3 will automate the Revision Loop with Brain mission integration.

## Empirical anchors

- Cross-study citation fabrication average is 51 percent across six
  studies covering 732 LLM-generated citations
  (`jrn_01KS0AVZRDA0KPXK61MN9PV5DE`). Multi-source validation is the
  only working defense.
- Kobak et al. 2025 (`Science Advances` 11(27):eadt3813,
  `doi:10.1126/sciadv.adt3813`): 13.5 percent of 2024 PubMed abstracts
  show LLM fingerprints; up to 40 percent in some subcorpora.
- Matsui 2025 (`Perspectives on Medical Education` 14(1):882-890):
  pure lexical blacklists over-flag legitimate academic prose;
  per-project overrides plus structural detectors are the recommended
  posture.

## Open questions for Phase 2 Backbrief

The Phase 2 mission Backbrief should re-verify:

1. PyPI versions of habanero, pyalex, semanticscholar, arxiv, manubot,
   python-orcid, bibtex-tidy. Each pinned at design-time per
   `references/reference_pipeline.md`; re-verify against current PyPI at
   Phase 2 Backbrief per the executor skill's version-drift discipline.
2. SerpAPI subscription tier appropriate for 200 searches per manuscript.
3. Crossref RWDB CSV mirror current location (may have moved since
   September 2023 acquisition).
4. OpenAlex API key requirement status (required from 2026-02-13).
5. ACL style files branch for the target submission year.

## Phase 2 readiness

HIGH confidence. All Phase 1 substrate is in place to support Phase 2
implementation:

- SKILL.md and references are stable and document the Phase 2 architecture.
- Scripts are organized with clear FULL vs STUB markers; Phase 2 fills
  the stubs.
- Workspace template is functional; Phase 2 adds the venue files and
  the live template fetch.
- Tests provide a regression floor; Phase 2 extends with reference
  validation tests.
- The bookkeeper invariant is preserved; Phase 2 will introduce
  `rka-writer-tools` as a sibling MCP server, not a modification of
  the existing `rka` server.
