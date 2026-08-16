# Writer Workflows

Operational depth for the Writer skill. The SKILL.md narrates the contract; this file documents how the contract executes.

> **v2.7.0 dispatch translation.** Legacy tool names in this file (`rka_get_changelog`, `rka_get_research_map`, `rka_record_pi_selection`, `rka_get_literature`, `rka_search`, `rka_add_literature`, `rka_update_literature`, `rka_get_mission`, `rka_submit_report`, `rka_submit_checkpoint`, `rka_add_note`, etc.) are synonyms for `rka_query(args={"operation": ...})` (reads) / `rka_execute(args={"operation": ...})` (writes) under the v2.7.0+ typed-arg surface. Pass `project_id` explicitly on every call — there is no active-project session state at the MCP layer. See the role SKILL.md files for the full mapping and `rka_describe(operation="<name>")` for per-operation signatures.

## Session Start (full walkthrough)

The PI launches `claude` in a manuscript working directory `manuscripts/<project-id>/<venue>/`. Claude Code loads the Writer skill on session start. The following steps run before the first PI exchange:

### Step 1: project confirmation

Read `.rka/manuscript.json`, which `rka writer init` writes only after registering or verifying the manuscript and atomically publishing the workspace. Treat its `project_id` and `manuscript_id` as the binding, then confirm the project exists:

```python
rka_query(args={"operation": "list_projects"})  # confirm the bound prj_... id exists
```

There is no active-project session state at the MCP layer and the workspace `.mcp.json` intentionally carries no default project. Thread `project_id="prj_01KS..."` explicitly on every call. A missing/malformed metadata file is a setup blocker; do not infer a write target from the directory name.

### Step 2: evidence-to-writing impact

If `.planning/RKA_CLAIM_SPINE.yaml` has a synchronized integer cursor, run:

```bash
rka writer impact \
  --project-id prj_01KS... \
  --manuscript-id man_01KS... \
  --claim-spine .planning/RKA_CLAIM_SPINE.yaml
```

Inspect the affected claims, units, file locations, artifacts, and changed
sources. A partial page is not a clean result; continue pagination or perform a
full synchronization. The legacy date-based changelog may help general
orientation, but it is not the manuscript invalidation authority.

### Step 3: synchronize and inspect the research map

Refresh the local projection before treating it as current:

```bash
rka writer sync \
  --project-id prj_01KS... \
  --manuscript-id man_01KS... \
  --output .planning/RKA_CLAIM_SPINE.yaml \
  --render-dir .planning
```

```python
rka_query(args={
    "operation": "changelog",
    "project_id": "prj_01KS...",
    "filters": {"since": "<last writing session date from .planning/ACTIVE_WORKFLOW.md>"},
})  # orientation only; the integer manuscript cursor remains authoritative
rka_query(args={"operation": "research_map", "project_id": "prj_01KS..."})
```

The research map is a retrieval overview. The synchronized native manuscript
aggregate is the source of truth for which claims and units this paper uses.

### Step 3a: authoritative readiness

Before substantive work, ask RKA for the target-phase gate:

```bash
rka writer readiness \
  --project-id prj_01KS... \
  --manuscript-id man_01KS... \
  --target-phase drafting
```

Server readiness checks current exact PI ratifications, evidence roles,
scientific support, terminal source currency, contradiction state, result
coverage, and phase checkpoints. `BLOCK` or `ERROR` stops the affected gate;
surface every `WARN` with its claim or unit.

Do not repair a claim from generated YAML or Markdown. Dry-run candidate
material with `rka writer import-spine`, create a server-side semantic patch,
review its diff and warnings, then apply it separately with proposal and target
revision guards. Record the PI decision separately, bind the exact version,
and synchronize again. Direct CLI `--apply` is a PI-authorized local
compatibility path, not the normal workbench or host-agent route.
An empty bootstrap spine is expected before contribution planning but cannot
authorize drafting. Packet/snapshot validation is a compatibility path for a
legacy v1 workspace only.

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
- Venue ratified and `FRAMING_SESSION.yaml` absent or incomplete: phase =
  framing elicitation.
- Framing session complete, claim spine not ratified: phase = contribution and
  outline.
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

Both servers should be listed. If `rka` is absent, the workspace is misconfigured. Missing optional metadata providers in `rka-writer-tools` must appear as explicit degraded audit state; they do not become confirmations. Credentials come from the process environment or credential vault, never from the manuscript workspace.

### Step 6: greet PI

Greet the PI with the inferred state and the next action. Example:

> Picked up the CHI manuscript at the start of drafting. The Outline and claims
> were ratified 2026-04-12; C1 and C2 remain current at the saved RKA cursor.
> Last session ended after §2 Related Work. Next action: draft §3 Method from
> units U-METHOD-1 through U-METHOD-3. Ready when you are.

## The Seven Sub-Procedures

The seven sub-procedures map to the six PI checkpoints plus the Revision Loop.
Most PI exchanges inside them use the choice-first interaction contract in
[`framing_elicitation.md`](framing_elicitation.md): one decision per turn, two
to four bounded options, concrete pros and cons, explicit single-select or
multi-select mode, and a recommendation when justified. Use free text only for
a custom alternative, missing evidence, unresolved disagreement, or exact
wording correction.

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

1. Run server-attested `rka writer assist`. It queries the project research
   map, groups duplicate support, preserves excluded-claim reason codes, and
   admits only current Brain-reviewed clusters bound to active research
   questions. Select which research questions are in manuscript scope.
2. Resolve every cluster blocker through Brain. Do not promote journal prose,
   an LLM-only synthesis, stale claims, or unresolved counterevidence.
3. Start or resume `.planning/FRAMING_SESSION.yaml` using
   [`framing_elicitation.md`](framing_elicitation.md). Identify whether each
   participant is supplying author voice, researcher judgment, PI authority,
   or more than one role. Ask one choice at a time and update the artifact
   after each selection.
4. Run the needed elicitation rounds for reader outcome, problem or gap,
   contribution portfolio, novelty axis, evidence anchors, claim calibration,
   narrative architecture, and reviewer-sensitive boundaries. Use
   single-select for mutually exclusive choices and multi-select for compatible
   contribution, result, or defense choices. Every option shows pros, cons,
   evidence, missing evidence, and its effect on the paper.
5. If author and researcher selections conflict, propose two to four
   reconciliation paths. Do not silently average their positions. Escalate an
   unresolved authority conflict to the PI.
6. Read the selected cluster lineage and assemble evidence from several short
   retrieval angles. For each contribution candidate, resolve positive
   evidence, qualifiers, counterevidence, terminal source records, current
   design decisions, and relevant superseded choices that explain the design's
   evolution. Superseded choices may inform lineage but are not current
   support. An `ecl_` guides synthesis but does not count as terminal empirical
   support; a `dec_` ratifies wording but does not prove it.
7. Build a contribution contract and candidate proposal with exact claim text,
   source-backed evidence, missing evidence, novelty/significance risks,
   allowed wording, prohibited wording, and planned manuscript units. The
   assist result seeds this work but cannot write or ratify it. Treat risks,
   counterevidence, and prohibited wording as a complete internal planning
   record, not as text that must all appear in the public manuscript. Classify
   their public treatment through
   [`persuasive_framing.md`](persuasive_framing.md).
8. Generate two to four bounded claim-and-outline framings with PI preference
   stripped from context. Use these defaults when they are genuinely distinct:
   - Results-led: section ordering driven by the most novel finding.
   - Method-led: section ordering driven by the methodological contribution.
   - Motivation-led: section ordering driven by the problem framing.
   Add a hybrid only when it has a coherent reading path that the defaults do
   not represent.
9. For each framing, show the exact contribution wording, its evidence path,
   conditions, known counterevidence, missing evidence, and a 5-to-8-section
   outline with one-sentence section purposes. Include concrete pros, cons,
   reviewer advantage, reviewer risk, and venue fit.
10. Prune any framing dominated on evidence coverage, scope accuracy,
   novelty-positioning, venue fit, quick-reader comprehension, strongest-
   evidence visibility, and narrative momentum. Do not compute an aggregate
   paper score or acceptance prediction.
11. Re-inject PI preference as opposing-critique; rank surviving framings.
12. Present the surviving options as the final F9 single-select choice; one
   carries `is_recommended` when justified. The PI may select one, combine
   named parts, request revised options, or defer and commission an evidence
   mission. Show the complete proposed contribution contract and outline, then
   obtain explicit final confirmation.
13. Dry-run `rka writer import-spine`. Review the evidence roles, result
   coverage, and proposed revision; apply only with an explicit expected
   revision. Import never creates ratifications.
14. Query `manuscript_outline` and progressively elaborate the active `mun_`
   hierarchy from L2 communicative sections toward L5 claim-sized units. Every
   major unit states its communicative job, intended takeaway, intended claim,
   and evidence plan. Treat citation, figure, table, transition, and location
   fields as plans until their sources or artifacts exist.
15. For each direct or AI-assisted change, call
   `prepare_manuscript_outline_proposal` with `edit`, `expand`, `condense`, or
   `reorder`. Inspect the semantic diff, findings, claim/evidence binding
   changes, and downstream ordering impact. Apply the `spp_` separately with
   `apply_semantic_patch_proposal`; re-query the outline after apply. Expansion
   retains its parent, condensation preserves the union of descendant
   bindings on the retained parent, and reorder names the complete active
   unit-key set.
16. Record the PI's selected framing and one child claim-scope `dec_` per
   selected contribution. Set `chosen` to the exact claim text,
   `decided_by: pi`, and connect the decision to its evidence and Outline
   lineage. Bind each exact native claim version through
   `ratify_manuscript_claim`. A later material edit requires a new version and
   a superseding PI decision.
17. When the outline projection has no rationale blockers, create the native
    Outline checkpoint and show the exact hierarchy and bindings to the PI.
    Resolve it only through `resolve_manuscript_checkpoint` with a same-project
    PI decision. Then run `rka writer sync` and require server readiness. The
    generated `CONTRIBUTION_CONTRACT.md`,
   `ARGUMENT_SPINE.md`, and `RESULTS_TRACE.md` are read-only views.

Output: Outline Decision (`dec_`), one exact-wording claim-scope `dec_` per
contribution with evidence provenance,
`.planning/FRAMING_SESSION.yaml`,
`.planning/RKA_CLAIM_SPINE.yaml`, its three generated views,
`.planning/OUTLINE.md`, and `.planning/sketches/<section-id>.md` per section.

Iron Law: **no prose before claim and outline ratification.** The `main.tex`
stays skeleton-only. Fluent planning text, a decision by itself, or a populated
table does not satisfy the evidence requirement.

Use
[`evidence_to_spine_pipeline.md`](evidence_to_spine_pipeline.md) for the
admission rules, failure states, and change-handling policy.

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
6. Apply unit and artifact changes through a revision-guarded native spine
   update. Synchronize, require bidirectional claim/result coverage, and
   regenerate `RESULTS_TRACE.md`.

Output: Table-Figure-Chart Plan Decision (`dec_`), `.planning/PLAN.md`, updated
claim-spine units and generated Results Trace, draft table .tex files, Paper
Banana prompts as `jrn_`, and chart skeleton .py files referencing
`scripts/chart_render.py`.

### 4. Reference validator

Trigger: PI provides a candidate reference list, OR drafting surfaces a citation gap.

Procedure:

1. Resolve each candidate against same-project `lit_` records. Add a missing
   candidate as unverified literature; existence in RKA is not validation.
2. Choose its exact case-sensitive citation key and replace the complete
   revision-guarded active set with
   `replace_manuscript_reference_manifest`. Omission retires an old membership;
   it does not delete history. Cross-project records, duplicate keys, and
   duplicate active literature bindings fail closed.
3. Submit Stage A-G validation through the core manuscript operation using
   both the canonical manuscript ID and the member's exact `literature_id`.
   The supplied DOI/title must match that literature identity. The
   request returns a durable pending job because identifier, retraction,
   author, and rescue-provider checks are slow external work.
4. Poll the job status. `pending` or `running` never counts as verified.
   `failed` is a blocking validation failure with preserved error details.
5. The worker runs the complete native stage trace, including Stage D
   retraction checks, and appends an immutable project/manuscript-scoped
   attestation.
6. Refresh `manuscript_reference_manifest`. Only keys in its
   `approved_citation_keys` may be cited or enter the drafting bibliography.
   The latest exact attempt wins: a newer failure, identity mismatch,
   retraction, exclusion, or later literature update blocks an older pass.
7. Run `verify_citations.py` with the fresh claim-spine projection plus the
   expected project and canonical manuscript IDs. A bibliography entry alone
   never authorizes a citation. Every other terminal status blocks the
   reference gate or requires an explicit PI disposition that does not rewrite
   the attestation.

Output: authoritative reference membership, `refs.bib`, durable validation
job/result metadata, and immutable reference-validation attestations. See
`reference_pipeline.md`.

### 5. Section drafter

Trigger: Claim and Outline wording ratified, claim-spine validation and currency
checks do not block, Table-Figure-Chart Plan ratified, and References set
ratified. Next section's status is `outlined` (not yet `drafted`).

Procedure (OpenScholar evidence-grounded per `jrn_01KS0AVZRDA0KPXK61MN9PV5DE`):

1. Dispatch a fresh subagent for the section (clean context window per `dispatching-parallel-agents` discipline).
2. Subagent reads: section sketch, ratified outline, the relevant claim-spine
   units, freshly resolved positive evidence, qualifiers, counterevidence,
   publication-boundary classifications, references in scope, and the claim's
   prohibited wording. Generated views are explanatory; resolution is against
   RKA.
3. Subagent first extracts evidence facts, conditions, and boundaries into its
   private working notes. It then drafts claim-centered, strength-first prose
   around the section's communicative job. Quote a source only when its exact
   wording matters; do not build the prose by patching quotations together.
   Place hidden provenance comments before each evidence-citation prose unit.
4. Apply the publication boundary from
   [`persuasive_framing.md`](persuasive_framing.md): M1 and M2 issues receive
   visible public treatment; M3 details go to the method, appendix, artifact,
   or reproducibility material; M4 and S items remain in the private risk
   record unless venue policy requires them. Never omit an issue whose absence
   would materially mislead a reasonable reader. Map every M1/M2 item to its
   public paragraph, figure, table, caption, or claim. If a mapping is missing,
   escalate and do not advance the affected unit to `drafted`.
5. Run the four quick-reader checks in `persuasive_framing.md`. If a scan
   fails, revise the framing or escalate the unresolved evidence/wording
   decision; never delete a material limitation merely to make the scan pass.
6. Subagent checks that no new contribution appeared in prose and that each
   empirical statement has role-appropriate terminal support. A decision or
   evidence cluster alone is not support.
7. Subagent self-audits before commit: runs `scripts/ai_tic_lint.py` on the
   section; iterates until style score reaches 0.85 or three iterations elapse.
8. If three iterations fail, ESCALATE via the Revision Loop Class R2.
9. Otherwise commit the section to `sections/<section-id>.tex`, update the
   corresponding native unit status through a revision-guarded spine update,
   synchronize, and surface it to the PI for the Draft section checkpoint.

PI ratifies via the Draft section checkpoint (one of the six PI checkpoints). Three options: accept, revise (with PI comments), escalate.

### 6. Local renderer plus layout auditor

Trigger: At least one section drafted; periodically during drafting; mandatorily before the Final Layout checkpoint.

Procedure:

1. `scripts/render.sh` runs latexmk with the venue's engine (default pdflatex).
2. If compile fails, parse `.log` for the first BLOCK error (Undefined control sequence, Reference undefined, etc.); surface to PI with the offending line; PI directs the fix.
3. If compile succeeds, `scripts/layout_audit.py` runs against the rendered PDF plus log files.
4. Before the Final Layout checkpoint, run impact, synchronize, request server
   readiness for the final phase, and run provenance/citation checks. Any
   `BLOCK` or `ERROR` prevents the final gate. Surface each `WARN`.
5. `audit.json` reports the twelve fields per `latex_audit.md`. Any BLOCK verdict halts progress; WARN verdicts noted for the Final Layout checkpoint.

Output: `main.pdf`, `audit.json`. If the PI requests a durable audit record,
store it as a provenance-linked `jrn_` and reference it from the relevant
native unit or checkpoint workflow.

### 7. Revision-loop handler (Phase 3 implementation)

Trigger paths:

- **Direct PI invocation** (CLI): `python scripts/revision_handler.py --dispatch --comment "..." --section sections/03.tex --manuscript-id man_... --review-state .planning/REVIEW_STATE.md`.
- **Brain-spawned mission**: a `writer-revision` mission lands with
  `tags=["writer-revision", "comment-class:<r1|r2|r3|r4>",
  "manuscript:<man_id>"]` plus the structured review comment in `context`.
  Writer reads the mission, verifies the canonical manuscript binding, and
  dispatches to the matching handler.

Procedure:

1. Classify each comment via `classify_comment(comment_text)` (heuristic-only; regex/keyword/structural patterns).
2. If `ambiguous=True`, escalate to PI via `rka_submit_checkpoint(type="clarification", ...)` before invoking any handler.
3. Otherwise dispatch:

- **R1 Factual** (sentence-level): `handle_factual_r1(comment, section_path, citation_ids, validate_references_script=...)` invokes `validate_references.py` Stage B-G on cited references; produces a factual-correction proposal on VERIFIED; surfaces alternative candidates on HALLUCINATED / RETRACTED.
- **R2 Style or AI-tic**: `handle_style_r2(comment, section_path, strict=True, ai_tic_lint_script=...)` re-runs `ai_tic_lint.py` at strict mode; reports verdict PASS / WARN / BLOCK; PI reviews residual violations.
- **R3 Inconsistency** (cross-section): `handle_inconsistency_r3(comment, section_paths, bridge_check_script=...)` uses `bridge_repetition_check.py` at ratio >= 0.7 to surface near-duplicate sentence pairs across sections; the Writer reasons over each pair to decide if it is an intentional restatement or a contradiction.
- **R4 Logical gap or unsupported claim**: `handle_logical_r4(comment, section_path, manuscript_id, rka_client=...)` ESCALATES by preparing a `writer_evidence_gap` mission payload addressed to Brain; Writer waits for Brain's evidence-gap response.

An R4 response that adds or changes evidence emits change events affecting the
dependent claims and units. Inspect impact and synchronize. Do not strengthen
the contribution automatically; if exact wording changes materially, append a
version and seek a PI decision that supersedes the prior ratification.

Classifier discipline (per `dec_01KS2WPKMRVSJ2R0PP74722PEH` Brain ratification 2026-05-20): `classify_comment` is heuristic-only because the Writer is itself a Claude Code session. The Writer's runtime IS the LLM-assisted reasoning layer that reviews comment + heuristic result before invoking any handler. No server-side LLM call.

REVIEW_STATE.md iteration tracking:

- `read_review_state(path)` parses `.planning/REVIEW_STATE.md` per the workspace template schema.
- `advance_review_state(state, success, note)` increments iteration and computes the verdict:
  - `success=True` -> `COMPLETE`.
  - `success=False` AND `iteration+1 < max` -> `CONTINUE`.
  - `success=False` AND `iteration+1 >= max` -> `ESCALATE`.
- Max iterations 3 per comment. The third failed iteration auto-escalates to a PI Style or Logical checkpoint with three resolution options.

Venue-aware overrides: `load_venue_overrides(venue_md_path)` reads per-venue `references/venue/<venue>.md` Forbidden-constructions field for stricter rules. The R2 style handler optionally consults these on top of universal `ai_tic_lint` rules.

Manuscript search UI, multi-author coordination, and submission automation
remain outside this workflow.

## Checkpoint UX patterns

All six PI checkpoints use the strip-then-re-inject decision UX inherited from
Brain (`../brain/decision_ux.md` is the canonical reference). Present two to
four credible options, use opposing-critique ranking, and identify one
recommendation when justified. Every option includes concrete pros, cons,
evidence status, material risk, and manuscript consequence. Formal checkpoint
resolution is single-select via `rka_record_pi_selection`.

Preparatory decisions default to the choice-first contract in
[`framing_elicitation.md`](framing_elicitation.md). Use multi-select only when
the options can coexist, such as contribution inclusion, primary/supporting
results, or independent reviewer defenses. Record those micro-selections in
the framing session, not as RKA decisions. Use the host's structured selector
when available; otherwise ask for option IDs.

Per-checkpoint specifics:

| Checkpoint | Typical option framings | Pareto axes |
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
- Claim spine: synchronized at cursor 1284; C1 and C2 current
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
