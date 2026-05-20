# Writer Workflows

Operational depth for the Writer skill. The SKILL.md narrates the contract; this file documents how the contract executes.

## Session Start (full walkthrough)

The PI launches `claude` in a manuscript working directory `manuscripts/<project-id>/<venue>/`. Claude Code loads the Writer skill on session start. The following steps run before the first PI exchange:

### Step 1: project confirmation

```python
rka_get_status()
```

Look at the returned project ID. Compare to the directory name. If the directory is `manuscripts/prj_01KS.../CHI/` and `rka_get_status` returns a different project, switch:

```python
rka_list_projects()  # show all
rka_set_project(project_id="prj_01KS...")  # the one matching the workspace
```

The MCP `_session.project_id` is per-process and ephemeral; verifying on every session start prevents writes landing in the wrong project. If `.mcp.json` env carries `RKA_PROJECT`, this step is automatic.

### Step 2: changelog

```python
rka_get_changelog(since="<last writing session date from .planning/ACTIVE_WORKFLOW.md>")
```

Surface any new `lit_`, `jrn_`, `dec_`, or `mis_` entries since the last writing session. New `lit_` items may belong in the current draft's reference set; new `jrn_` may carry PI direction that updates the working outline.

### Step 3: research map

```python
rka_get_research_map()
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

1. For each candidate reference, look up in RKA via `rka_get_literature` or `rka_search`. If present and `validation_status=VERIFIED`, accept.
2. For references not in RKA, prompt PI to either add via `rka_add_literature` (with `validation_status=UNVERIFIED` initially) or cite from external metadata.
3. `scripts/validate_references.py` Stage A converts `rka_get_literature` output (CSL-JSON) to BibTeX via manubot if installed.
4. Stages B through G are stubbed; manual verification by PI in Phase 1.

Phase 2 procedure (when `rka-writer-tools` MCP is live): see `reference_pipeline.md`.

Output: `refs.bib` populated, per-reference `validation_status` updated on `lit_` entries via `rka_update_literature`.

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

### 7. Revision-loop handler

Trigger: PI returns review comments on a draft (post Draft section checkpoint with `revise` option).

Procedure: classify each comment into R1, R2, R3, or R4 per the SKILL.md `Revision Loop` section:

- **R1 Factual** (sentence-level): auto-fix inline; re-render; bump `REVIEW_STATE.md` iteration.
- **R2 Style or AI-tic**: re-run `ai_tic_lint.py` at higher severity; auto-revise.
- **R3 Inconsistency** (cross-section): structural rewrite of all affected sections; re-render full document.
- **R4 Logical gap or unsupported claim**: ESCALATE via `rka_create_mission` so the Brain or Executor can gather evidence.

`.planning/REVIEW_STATE.md` tracks iteration with `iteration: N / max: 3 / verdict: CONTINUE | ESCALATE | COMPLETE`. Three failed iterations auto-escalate to a PI Style or Logical checkpoint with three resolution options.

Phase 1 documents the Revision Loop; Phase 3 wires the Brain-mission-driven implementation.

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
rka_add_note(
    type="note",
    source="executor",
    content="""
# Writing session digest <ISO date>

- Sections advanced: §3 Method (outlined -> drafted)
- Checkpoints resolved: Draft §3 (PI: accept)
- Lit added: lit_01KS... (Smith 2024) via rka_add_literature
- Style score current: 0.91 (target 0.85)
- Next action: draft §4 Evaluation

## Open items
- One UNVERIFIED reference flagged (Jones 2023): PI to confirm next session.
""",
    related_mission=None,  # or revision mission if applicable
    related_decisions=["dec_outline_ratified", "dec_draft_section_3"],
    tags=["writing-session-digest", "manuscript-CHI"],
)
```

The digest helps the next session's State Resume step find the right next action.
