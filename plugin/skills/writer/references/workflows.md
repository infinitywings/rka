# Writer Workflows

Operational depth for the Writer skill. The SKILL.md narrates the contract; this file documents how the contract executes.

> **v2.7.0 dispatch translation.** Legacy tool names in this file (`rka_get_changelog`, `rka_get_research_map`, `rka_record_pi_selection`, `rka_get_literature`, `rka_search`, `rka_add_literature`, `rka_update_literature`, `rka_get_mission`, `rka_submit_report`, `rka_submit_checkpoint`, `rka_add_note`, etc.) are synonyms for `rka_query(args={"operation": ...})` (reads) / `rka_execute(args={"operation": ...})` (writes) under the v2.7.0+ typed-arg surface. Pass `project_id` explicitly on every call — there is no active-project session state at the MCP layer. See the role SKILL.md files for the full mapping and `rka_describe(operation="<name>")` for per-operation signatures.

## Session Start (full walkthrough)

The PI launches `claude` in a manuscript working directory `manuscripts/<project-id>/<venue>/`. Claude Code loads the Writer skill on session start. The following steps run before the first PI exchange:

### Step 1: project confirmation

The working directory encodes the project: `manuscripts/<project-id>/<venue>/`. Take the `prj_...` id from the directory name (e.g. `manuscripts/prj_01KS.../CHI/`) and confirm it exists:

```python
rka_query(args={"operation": "list_projects"})  # confirm the prj_... id from the directory name exists
```

There is no active-project session state at the MCP layer — thread the workspace `project_id="prj_01KS..."` explicitly on every `rka_query` / `rka_execute` call. Confirming the id against `list_projects` on every session start prevents writes landing in the wrong project.

### Step 2: changelog

```python
rka_query(args={
    "operation": "changelog",
    "project_id": "prj_01KS...",
    "filters": {"since": "<last writing session date from .planning/ACTIVE_WORKFLOW.md>"},
})
```

Surface any new `lit_`, `jrn_`, `dec_`, or `mis_` entries since the last writing session. New `lit_` items may belong in the current draft's reference set; new `jrn_` may carry PI direction that updates the working outline.

### Step 3: research map

```python
rka_query(args={"operation": "research_map", "project_id": "prj_01KS..."})
```

Structural overview of clusters and claims. Filter to clusters relevant to the manuscript's topic before quoting. The map is the source of truth for what evidence is available to cite.

### Step 4: state resume

Read `.planning/ACTIVE_WORKFLOW.md`. Expected structure:

```markdown
# Active Workflow

current_phase: drafting
last_checkpoint: outline (resolved 2026-04-12)
next_action: draft §3 Method
last_session: 2026-04-11
```

If `ACTIVE_WORKFLOW.md` is absent, infer from the working directory:

- `.planning/PRECIS.md` absent: phase = venue selection.
- `PRECIS.md` present, `OUTLINE.md` absent: phase = outline.
- `OUTLINE.md` present, `sections/` empty: phase = table and figure planning.
- `sections/` populated: phase = drafting; next section is the first one with status `outlined` rather than `drafted`.
- All sections drafted, no `audit.json`: phase = render and audit.
- `audit.json` shows BLOCK verdicts: phase = revision.
- `audit.json` all PASS or WARN: phase = final layout checkpoint.

### Step 5: MCP verification

Verify `.mcp.json` lists the `rka` server:

```bash
cat .mcp.json | jq '.mcpServers | keys'
```

Phase 1 does not require `rka-writer-tools`. If absent, `scripts/validate_references.py` Stage A pass-through is used. If `rka` is absent, the workspace is misconfigured; surface to the PI before proceeding.

### Step 6: greet PI

Greet the PI with the inferred state and the next action. Example:

> Picked up the CHI manuscript at the start of drafting. Outline ratified 2026-04-12 (six sections). Last session ended after §2 Related Work was drafted. Next action: draft §3 Method, anchoring to clusters `ecl_01KQ...` and `ecl_01KQ...`. Ready when you are.

## The Seven Sub-Procedures

The seven sub-procedures map to the six PI checkpoints plus the Revision Loop.

### 1. Venue handler

Trigger: PI says they want to target venue X, or no `venue/X.md` exists for the chosen venue.

Procedure:

1. Confirm the CFP and submission window via the venue's official site (use `WebFetch`).
2. If `references/venue/<venue>.md` exists, load it and present the schema summary to the PI.
3. If absent, scaffold: fetch three to five recent papers from the venue via OpenAlex; extract the seven-field schema (section names, page-limit class, tone, forbidden constructions, citation style, required sections, sample corpus). Single-paper imitation is brittle (anti-pattern 12).
4. Generate three candidate venue framings if multiple venues are in play (e.g., HCI paper could target CHI, CSCW, UIST). Present via strip-then-re-inject.
5. PI selects via `rka_record_pi_selection`. Decision recorded with three options, opposing-critique ranking.

Output: ratified Venue Decision (`dec_`), `.planning/PRECIS.md` PI-authored, `references/venue/<venue>.md` populated if newly scaffolded.

### 2. Outline co-author

Trigger: Venue ratified, no `OUTLINE.md` yet.

Procedure:

1. Read research map for the project; identify clusters and claims relevant to the manuscript topic.
2. Generate three outline framings with PI preference stripped from context:
   - Results-led: section ordering driven by the most novel finding.
   - Method-led: section ordering driven by the methodological contribution.
   - Motivation-led: section ordering driven by the problem framing.
3. For each framing, draft a 5-to-8-section outline with one-sentence section purposes.
4. Prune any framing dominated on scope-coverage, novelty-positioning, and venue-fit.
5. Re-inject PI preference as opposing-critique; rank surviving framings.
6. Present three (or fewer if pruned) options to the PI; one carries `is_recommended`.
7. PI selects; record via `rka_record_pi_selection`.

Output: Outline Decision (`dec_`), `.planning/OUTLINE.md`, `.planning/sketches/<section-id>.md` per section.

Iron Law: **no prose before outline ratification.** The `main.tex` stays skeleton-only.

### 3. Table, figure, and chart planner

Trigger: Outline ratified, no `tables/` or `figures/` populated.

Procedure:

1. For each result-bearing section, generate three presentation framings:
   - Figure-heavy: visual emphasis, supporting tables.
   - Table-heavy: quantitative emphasis, illustrative figures.
   - Balanced.
2. For each framing, propose specific tables (booktabs LaTeX), figures (Paper Banana prompt for diagrams; matplotlib + seaborn code for charts), and chart styling via venue presets (tueplots, SciencePlots).
3. Paper Banana prompts are stored as `jrn_` entries tagged `figure-prompt` per `dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D` Q6, with the manuscript manifest in `related_journal`.
4. Present three options. PI selects.

Output: Table-Figure-Chart Plan Decision (`dec_`), `.planning/PLAN.md`, draft table .tex files, Paper Banana prompts as `jrn_`, chart skeleton .py files referencing `scripts/chart_render.py`.

### 4. Reference validator

Trigger: PI provides a candidate reference list, OR drafting surfaces a citation gap.

Phase 1 procedure (manual; Stage A only):

1. For each candidate reference, look up in RKA via `rka_get_literature` or `rka_search`. If present and tagged `validation:VERIFIED`, accept.
2. For references not in RKA, prompt PI to either add via `rka_add_literature` (tagged `validation:UNVERIFIED` initially) or cite from external metadata.
3. `scripts/validate_references.py` Stage A converts `rka_get_literature` output (CSL-JSON) to BibTeX via manubot if installed.
4. Stages B through G are stubbed; manual verification by PI in Phase 1.

Phase 2 procedure (when `rka-writer-tools` MCP is live): see `reference_pipeline.md`.

Output: `refs.bib` populated, per-reference validation verdict stored as a `validation:<status>` tag on `lit_` entries via `rka_update_literature` (there is no `validation_status` field; use `tags` or `notes`).

### 5. Section drafter

Trigger: Outline ratified, Table-Figure-Chart Plan ratified, References set ratified. Next section's status is `outlined` (not yet `drafted`).

Procedure (OpenScholar evidence-first per `jrn_01KS0AVZRDA0KPXK61MN9PV5DE`):

1. Dispatch a fresh subagent for the section (clean context window per `dispatching-parallel-agents` discipline).
2. Subagent reads: section sketch, ratified outline, relevant clusters from research map, references in scope.
3. Subagent drafts the section evidence-first: quote evidence first; build prose around the quote; place hidden provenance comments before each evidence-citation prose unit.
4. Subagent self-audits before commit: runs `scripts/ai_tic_lint.py` on the section; iterates until style score reaches 0.85 or three iterations elapse.
5. If three iterations fail, ESCALATE via the Revision Loop Class R2.
6. Otherwise commit section to `sections/<section-id>.tex`, mark `drafted` in manifest, and surface to PI for the Draft section checkpoint.

PI ratifies via the Draft section checkpoint (one of the six PI checkpoints). Three options: accept, revise (with PI comments), escalate.

### 6. Local renderer plus layout auditor

Trigger: At least one section drafted; periodically during drafting; mandatorily before the Final Layout checkpoint.

Procedure:

1. `scripts/render.sh` runs latexmk with the venue's engine (default pdflatex).
2. If compile fails, parse `.log` for the first BLOCK error (Undefined control sequence, Reference undefined, etc.); surface to PI with the offending line; PI directs the fix.
3. If compile succeeds, `scripts/layout_audit.py` runs against the rendered PDF plus log files.
4. `audit.json` reports the twelve fields per `latex_audit.md`. Any BLOCK verdict halts progress; WARN verdicts noted for the Final Layout checkpoint.

Output: `main.pdf`, `audit.json`. The manuscript manifest's `related_journal` gains a pointer to the latest `audit.json` snapshot stored as a `jrn_` if the PI requests durable record.

### 7. Revision-loop handler (Phase 3 implementation)

Trigger paths:

- **Direct PI invocation** (CLI): `python scripts/revision_handler.py --dispatch --comment "..." --section sections/03.tex --manuscript-id jrn_... --review-state .planning/REVIEW_STATE.md`.
- **Brain-spawned mission**: a `writer-revision` mission lands with `tags=["writer-revision", "comment-class:<r1|r2|r3|r4>", "manuscript:<jrn_id>"]` plus the structured review comment in `context`. The Writer's Claude Code session reads the mission via `rka_get_mission(id)`, extracts the comment-class tag and the comment, then dispatches to the matching handler. Lifecycle: Brain creates -> Writer picks up -> dispatches -> `rka_submit_report` (success) or `rka_submit_checkpoint` (R4 escalation or REVIEW_STATE three-iteration cap).

Procedure:

1. Classify each comment via `classify_comment(comment_text)` (heuristic-only; regex/keyword/structural patterns).
2. If `ambiguous=True`, escalate to PI via `rka_submit_checkpoint(type="clarification", ...)` before invoking any handler.
3. Otherwise dispatch:

- **R1 Factual** (sentence-level): `handle_factual_r1(comment, section_path, citation_ids, validate_references_script=...)` invokes `validate_references.py` Stage B-G on cited references; produces a factual-correction proposal on VERIFIED; surfaces alternative candidates on HALLUCINATED / RETRACTED.
- **R2 Style or AI-tic**: `handle_style_r2(comment, section_path, strict=True, ai_tic_lint_script=...)` re-runs `ai_tic_lint.py` at strict mode; reports verdict PASS / WARN / BLOCK; PI reviews residual violations.
- **R3 Inconsistency** (cross-section): `handle_inconsistency_r3(comment, section_paths, bridge_check_script=...)` uses `bridge_repetition_check.py` at ratio >= 0.7 to surface near-duplicate sentence pairs across sections; the Writer reasons over each pair to decide if it is an intentional restatement or a contradiction.
- **R4 Logical gap or unsupported claim**: `handle_logical_r4(comment, section_path, manuscript_id, rka_client=...)` ESCALATES by preparing a `writer_evidence_gap` mission payload addressed to Brain; Writer waits for Brain's evidence-gap response.

Classifier discipline (per `dec_01KS2WPKMRVSJ2R0PP74722PEH` Brain ratification 2026-05-20): `classify_comment` is heuristic-only because the Writer is itself a Claude Code session. The Writer's runtime IS the LLM-assisted reasoning layer that reviews comment + heuristic result before invoking any handler. No server-side LLM call.

REVIEW_STATE.md iteration tracking:

- `read_review_state(path)` parses `.planning/REVIEW_STATE.md` per the workspace template schema.
- `advance_review_state(state, success, note)` increments iteration and computes the verdict:
  - `success=True` -> `COMPLETE`.
  - `success=False` AND `iteration+1 < max` -> `CONTINUE`.
  - `success=False` AND `iteration+1 >= max` -> `ESCALATE`.
- Max iterations 3 per comment. The third failed iteration auto-escalates to a PI Style or Logical checkpoint with three resolution options.

Venue-aware overrides: `load_venue_overrides(venue_md_path)` reads per-venue `references/venue/<venue>.md` Forbidden-constructions field for stricter rules. The R2 style handler optionally consults these on top of universal `ai_tic_lint` rules.

Phase 3 ships the implementation. Phase 4+ (manuscript search UI, versioning, multi-author, OpenAlex/arXiv submission, manuscript export) is deferred indefinitely per `mis_01KS2WW6MRN6AXP11EMCSCDFAR` scope_boundaries.

## Checkpoint UX patterns

All six PI checkpoints use the strip-then-re-inject decision UX inherited from Brain (`../brain/decision_ux.md` is the canonical reference). Three ratified options per checkpoint; opposing-critique ranking; PI selection via `rka_record_pi_selection`.

Per-checkpoint specifics:

| Checkpoint | Three option framings | Pareto axes |
|---|---|---|
| Venue | venue A / venue B / venue C | venue fit, deadline, audience reach |
| Outline | results-led / method-led / motivation-led | novelty positioning, scope coverage, venue fit |
| Table-Figure-Chart Plan | figure-heavy / table-heavy / balanced | space efficiency, readability, evidence density |
| Reference set | broad / focused / minimum | coverage, page-budget, citation novelty |
| Draft section | accept / revise / escalate | quality, scope, time |
| Final layout | submit / iterate / hold | publication risk, polish, deadline |

PI selection produces a `dec_`. The decision is immutable once selected or rejected. Revisions create a new `dec_` that `supersedes` the prior.

## Session digest

At the end of each writing session, record a session digest as a `jrn_`:

```python
rka_execute(args={
    "operation": "record_note",
    "project_id": "prj_01KS...",
    "type": "note",
    "source": "executor",
    "content": """
# Writing session digest <ISO date>

- Sections advanced: §3 Method (outlined -> drafted)
- Checkpoints resolved: Draft §3 (PI: accept)
- Lit added: lit_01KS... (Smith 2024) via record_literature
- Style score current: 0.91 (target 0.85)
- Next action: draft §4 Evaluation

## Open items
- One UNVERIFIED reference flagged (Jones 2023): PI to confirm next session.
""",
    # record_note links live inside the nested provenance object
    # (add "related_mission": "mis_..." here for a revision mission)
    "provenance": {"related_decisions": ["dec_outline_ratified", "dec_draft_section_3"]},
    "tags": ["writing-session-digest", "manuscript-CHI"],
})
```

The digest helps the next session's State Resume step find the right next action.
