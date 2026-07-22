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

### Step 3a: claim-spine currency

Read `.planning/RKA_CLAIM_SPINE.yaml` when it contains a manuscript id and at
least one claim. Follow [`claim_spine.md`](claim_spine.md): resolve every
dependency inside the explicit project, compare the stored `rka_snapshot` with
the current records, and map any changed entity back to affected claims and
manuscript units.

In a plugin session, retrieve those records through the authenticated RKA MCP
and create a fresh, temporary entity packet for `claim_spine.py
--entity-packet`. Follow every claim to its `source_entry_id`. Do not commit or
reuse the packet as evidence, and do not expose the local REST API merely to
run validation. Preserve the live freshness fields in that packet, including
`stale`, `staleness`, `valid_from`, `valid_until`, `staleness_verdict`, and a
cluster's `synthesis_valid_until` / `needs_reprocessing`; stripping them can
turn a real blocker into an unsafe apparent pass.

Do not repair a claim from a generated Markdown view. The YAML is the editable
Writer projection; RKA remains canonical for the records it names. A changed
entity marks dependent claims for revalidation but never rewrites PI-ratified
wording automatically.

Session-start outcomes:

- `PASS`: dependencies are current; resume the recorded action.
- `WARN`: show the affected claim/unit and the bounded issue before resuming.
- `BLOCK`: stop the affected Outline, Draft, or Final Layout gate.
- `ERROR`: resolver, parse, or snapshot state is unusable. Stop validation;
  `ERROR` is never treated as `PASS`.

Create or refresh `rka_snapshot` only after exact `PASS`. The snapshot command
runs the same validation and writes nothing for `WARN`, `BLOCK`, or `ERROR`.
`check-currency` also re-runs current validation, so an unchanged invalid
record cannot become valid merely because an earlier snapshot captured it.

An empty bootstrap spine is expected before contribution planning. It is not a
validated contribution and cannot authorize substantive drafting.

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
- `PRECIS.md` present, claim spine not ratified: phase = contribution and outline.
- Claim spine ratified, `OUTLINE.md` absent: phase = outline completion.
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

> Picked up the CHI manuscript at the start of drafting. The Outline and claims
> were ratified 2026-04-12; C1 and C2 remain current at the saved RKA cursor.
> Last session ended after §2 Related Work. Next action: draft §3 Method from
> units U-METHOD-1 through U-METHOD-3. Ready when you are.

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

1. Read the research map and assemble evidence from several short retrieval
   angles. For each contribution candidate, resolve positive evidence,
   qualifiers, counterevidence, terminal source records, current design
   decisions, and relevant superseded choices that explain the design's
   evolution. Superseded choices may inform lineage but are not current
   support. An `ecl_` may guide discovery but does not count as terminal
   empirical support; a `dec_` ratifies wording but does not prove it.
2. Populate `.planning/RKA_CLAIM_SPINE.yaml` with candidate claim text,
   source-backed evidence, allowed wording, prohibited wording, and planned
   manuscript units. Leave claim status as `candidate` until the PI acts.
3. Generate three bounded claim-and-outline framings with PI preference stripped from context:
   - Results-led: section ordering driven by the most novel finding.
   - Method-led: section ordering driven by the methodological contribution.
   - Motivation-led: section ordering driven by the problem framing.
4. For each framing, show the exact contribution wording, its evidence path,
   conditions, known counterevidence, missing evidence, and a 5-to-8-section
   outline with one-sentence section purposes.
5. Prune any framing dominated on evidence coverage, scope honesty,
   novelty-positioning, and venue fit. Do not compute an aggregate paper score
   or acceptance prediction.
6. Re-inject PI preference as opposing-critique; rank surviving framings.
7. Present three (or fewer if pruned) options to the PI; one carries
   `is_recommended`. The PI may retain, narrow, or defer a claim and commission
   an evidence-gap mission.
8. Record the PI's selected framing via `rka_record_pi_selection`. As part of
   the same Outline checkpoint, create one child claim-scope `dec_` per selected
   contribution: set `chosen` to that claim's exact text, `decided_by: pi`, and
   link it to the Outline decision and its evidence. Set the claim to
   `status: ratified` and `ratified_by` to that claim-scope decision. This is
   bookkeeping for the PI's explicit selection, not a seventh checkpoint. A
   later material edit requires a new claim-scope decision that supersedes the
   old one.
9. Validate the spine, build its dependency snapshot, and render the read-only
   `CONTRIBUTION_CONTRACT.md`, `ARGUMENT_SPINE.md`, and `RESULTS_TRACE.md` views.
   A rendered file does not substitute for live validation.

Output: Outline Decision (`dec_`), one exact-wording claim-scope `dec_` per
contribution with evidence provenance,
`.planning/RKA_CLAIM_SPINE.yaml`, its three generated views,
`.planning/OUTLINE.md`, and `.planning/sketches/<section-id>.md` per section.

Iron Law: **no prose before claim and outline ratification.** The `main.tex`
stays skeleton-only. Fluent planning text, a decision by itself, or a populated
table does not satisfy the evidence requirement.

### 3. Table, figure, and chart planner

Trigger: Outline ratified, no `tables/` or `figures/` populated.

Procedure:

1. For each empirical claim in the ratified claim spine, create at least one
   result unit with source-backed evidence, an artifact path, experimental or
   threat-model conditions, an allowed interpretation, and a prohibited
   interpretation. Every major result unit must name at least one contribution
   claim; otherwise it is orphaned or explicitly exploratory.
2. For each result-bearing section, generate three presentation framings:
   - Figure-heavy: visual emphasis, supporting tables.
   - Table-heavy: quantitative emphasis, illustrative figures.
   - Balanced.
3. For each framing, propose specific tables (booktabs LaTeX), figures (Paper Banana prompt for diagrams; matplotlib + seaborn code for charts), and chart styling via venue presets (tueplots, SciencePlots).
4. Paper Banana prompts are stored as `jrn_` entries tagged `figure-prompt` per `dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D` Q6, with the manuscript manifest in `related_journal`.
5. Present three options. PI selects.
6. Update claim-spine unit locations and artifacts, revalidate bidirectional
   claim/result coverage, refresh the snapshot, and regenerate
   `RESULTS_TRACE.md`.

Output: Table-Figure-Chart Plan Decision (`dec_`), `.planning/PLAN.md`, updated
claim-spine units and generated Results Trace, draft table .tex files, Paper
Banana prompts as `jrn_`, and chart skeleton .py files referencing
`scripts/chart_render.py`.

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

Trigger: Claim and Outline wording ratified, claim-spine validation and currency
checks do not block, Table-Figure-Chart Plan ratified, and References set
ratified. Next section's status is `outlined` (not yet `drafted`).

Procedure (OpenScholar evidence-first per `jrn_01KS0AVZRDA0KPXK61MN9PV5DE`):

1. Dispatch a fresh subagent for the section (clean context window per `dispatching-parallel-agents` discipline).
2. Subagent reads: section sketch, ratified outline, the relevant claim-spine
   units, freshly resolved positive evidence and qualifiers, references in
   scope, and the claim's prohibited wording. Generated views are explanatory;
   resolution is against RKA.
3. Subagent drafts the section evidence-first: quote evidence first; build prose around the quote; place hidden provenance comments before each evidence-citation prose unit. The draft must stay within each unit's allowed interpretation.
4. Subagent checks that no new contribution appeared in prose and that each
   empirical statement has role-appropriate terminal support. A decision or
   evidence cluster alone is not support.
5. Subagent self-audits before commit: runs `scripts/ai_tic_lint.py` on the section; iterates until style score reaches 0.85 or three iterations elapse.
6. If three iterations fail, ESCALATE via the Revision Loop Class R2.
7. Otherwise commit section to `sections/<section-id>.tex`, mark `drafted` in manifest, and surface to PI for the Draft section checkpoint.

PI ratifies via the Draft section checkpoint (one of the six PI checkpoints). Three options: accept, revise (with PI comments), escalate.

### 6. Local renderer plus layout auditor

Trigger: At least one section drafted; periodically during drafting; mandatorily before the Final Layout checkpoint.

Procedure:

1. `scripts/render.sh` runs latexmk with the venue's engine (default pdflatex).
2. If compile fails, parse `.log` for the first BLOCK error (Undefined control sequence, Reference undefined, etc.); surface to PI with the offending line; PI directs the fix.
3. If compile succeeds, `scripts/layout_audit.py` runs against the rendered PDF plus log files.
4. Before the Final Layout checkpoint, re-run claim-spine validation and
   currency comparison plus provenance and citation checks. Any `BLOCK` or
   `ERROR` prevents the final gate. A `WARN` is surfaced with its affected
   claim and unit.
5. `audit.json` reports the twelve fields per `latex_audit.md`. Any BLOCK verdict halts progress; WARN verdicts noted for the Final Layout checkpoint.

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

An R4 response that adds or changes evidence invalidates the dependent
claim-spine snapshot. Re-resolve the affected claim and units. Do not strengthen
the contribution automatically; if the exact wording changes materially, seek
a new PI decision that supersedes the previous ratification.

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
| Outline | results-led / method-led / motivation-led, each with bounded claim wording | evidence coverage, claim boundary, novelty positioning, venue fit |
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
- Claim spine: PASS at cursor evt_...; C1 and C2 current
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
