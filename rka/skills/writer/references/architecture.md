# Writer Architecture

The Writer is a Claude Code skill (Markdown SKILL.md + Python scripts + workspace template) operating in VSCode per `dec_01KS0AWYDV752AWQRF40CQBRFZ`. It reads from and writes to RKA via the existing `rka` MCP server. It does not introduce new RKA orchestration; it operates on a manuscript working directory and emits provenance edges back into the research graph.

## Deployment model

```
VSCode (PI workspace)
  +--> Claude Code session (entry point)
       +--> SKILL.md (this skill) ----> Native tools: Read/Edit/Write/Bash/Grep/Glob/WebSearch/WebFetch
       |                          +--> MCP servers via .mcp.json:
       |                                  rka (required)
       |                                  rka-writer-tools (Phase 2, optional)
       |
       +--> Workspace = manuscripts/<project-id>/<venue>/
            +--> sections/*.tex
            +--> figures/, tables/, charts/
            +--> refs.bib
            +--> main.tex
            +--> .planning/ (working state)
            +--> .latexmkrc, .mcp.json
            +--> ai_tic_config.yaml (per-project overrides)
            +--> styles/ (vendored venue templates)
```

Two invocation paths land in this skill:

1. **Direct PI invocation.** PI launches `claude` in the manuscript directory; the skill loads on session start when Claude Code detects the workspace.
2. **Brain-spawned subagent.** Brain creates a revision mission (`rka_create_mission`); a fresh Claude Code subagent picks it up and operates on the manuscript directory.

Same skill content in both paths; the entry point differs.

## RKA integration

The Writer reads broadly from RKA at session start and during drafting:

| Tool | When | Purpose |
|---|---|---|
| `rka_get_status` | session start | confirm active project, phase |
| `rka_get_changelog` | session start | what changed since last writing session |
| `rka_get_research_map` | session start, before outline | structural overview of clusters and claims |
| `rka_get_journal` | during drafting | quote PI directives, prior findings |
| `rka_get_literature` | during drafting | citation source for `lit_` entities |
| `rka_get_decision_tree` | during outline | ratified decisions to cite |
| `rka_search` | during drafting | targeted retrieval (queries kept to 2 to 4 words) |
| `rka_get_context` | during drafting | importance-ranked context bundle for a topic |

The Writer writes back to RKA when an artifact is generated or a checkpoint resolves:

| Tool | When | What is recorded |
|---|---|---|
| `rka_add_note` | manuscript manifest creation, checkpoint ratification, session digest | `jrn_` entries with full provenance |
| `rka_add_decision` | each of 6 PI checkpoints | `dec_` with options, rationale, PI selection |
| `rka_record_pi_selection` | each checkpoint after PI picks | links PI's choice to a `dec_` |
| `rka_update_literature` | after reference validation | `validation_status` field on `lit_` |
| `rka_create_mission` | only for follow-ups Brain or Executor handle | revision missions during the Revision Loop |

The Writer does **not** call `rka_create_project`, `rka_create_gate`, or any orchestration tool that grows new RKA structure. The bookkeeper invariant for Phase 1 is preserved.

## Option 2 manuscript representation (`dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D` Q1)

A manuscript is represented by two artifacts: the working-directory tree on disk and a `jrn_` manifest in RKA. There is no new entity type; the `jrn_` manifest serves as the canonical manuscript record.

Manifest fields:

```python
rka_add_note(
    type="note",
    source="executor",  # or "pi" if PI directly authored the launch
    content="""
# Manuscript: <Title>

## Section index
- §1 Introduction: drafted | revised | submitted
- §2 Related Work: drafted
- §3 Method: drafted
- §4 Evaluation: drafted
- §5 Discussion: outlined
- §6 Conclusion: outlined

## Working directory
manuscripts/<project-id>/<venue>/

## Current phase
draft  # draft | review | final | submitted
""",
    verbatim_input="<full PI-authored title + abstract>",
    related_decisions=[
        "dec_venue_checkpoint",
        "dec_outline_checkpoint",
        "dec_table_figure_plan",
        "dec_reference_set",
        "dec_draft_approvals",
        "dec_final_layout",
    ],
    related_literature=["lit_..."],  # all cited
    related_journal=["jrn_..."],     # all quoted
    tags=["manuscript", "venue:CHI", "phase:draft", "writer-session:3"],
    importance="high",
    confidence="tested",
)
```

The manifest is updated as the manuscript progresses through phases; the `tags` field carries the current phase via `phase:<draft|review|final>`. The `related_decisions` field grows as each of the six PI checkpoints ratifies a `dec_`.

Option 3 (a new `man_` entity type with schema migration) was rejected per Q1 ratification because it would require migration scaffolding in `rka/db/schema.sql` and `rka/services/` (violating the bookkeeper invariant for Phase 1).

## Provenance edges Writer emits

Across the 12-type `entity_links` vocabulary (see `../brain/architecture.md` section "The 12-Type Provenance Vocabulary" for the full taxonomy), the Writer emits:

| Edge | From | To | Meaning |
|---|---|---|---|
| `cites` | manuscript jrn_ | lit_ | manuscript cites this literature item |
| `references` | manuscript jrn_ | jrn_ | manuscript quotes or paraphrases this journal entry |
| `justified_by` | checkpoint dec_ | jrn_ | checkpoint decision rests on this evidence |
| `supports` | jrn_ (claim) | lit_ | claim is supported by this paper |
| `contradicts` | jrn_ (claim) | lit_ | claim contradicts this paper |
| `derived_from` | revision mission mis_ | dec_ (checkpoint) | mission spawned from this checkpoint |
| `supersedes` | new dec_ | old dec_ | revisited checkpoint replaces prior |
| `produced` | mission mis_ | manuscript jrn_ | revision mission updated this manuscript |
| `informed_by` | manuscript jrn_ | research_map cluster | manuscript draws on this evidence cluster |

The Writer never invents new edge types and never creates orphan entities. Every manifest entry has the required upstream links per the table above.

## Bookkeeper invariant (Phase 1)

The Writer's Phase 1 scope adds files only under `rka/skills/writer/` and `tests/skills/writer/` (plus optional minimal touch of `rka/skills/SKILL.md` for the top-level skills index). It modifies zero files under `rka/services/`, `rka/api/`, `rka/mcp/`, or `web/`.

Verification at every commit boundary:

```bash
git diff main -- rka/services/ rka/api/ rka/mcp/ web/  # must be empty
```

If this command produces any output, the commit violates the bookkeeper invariant and must be reworked before push.

Phase 2 may introduce the `rka-writer-tools` MCP server as a separate sibling MCP (not a modification of the existing `rka` server). Phase 3 may add the optional MCP tools `rka_get_manuscript`, `rka_validate_reference`, `rka_register_manuscript` to the existing `rka` server; that introduction will land in a Phase 3 mission with its own bookkeeper exemption rationale ratified by Brain and PI. Phase 1 stays out of `rka/mcp/`.

## Workspace template structure

Phase 1 ships a workspace template at `rka/skills/writer/workspace-template/`. The PI copies it to `manuscripts/<project-id>/<venue>/` to bootstrap a new manuscript:

```
manuscripts/<project-id>/<venue>/
  .mcp.json                   # rka required; rka-writer-tools commented (Phase 2)
  .latexmkrc                  # TEXINPUTS=./styles//: ; @default_files = ('main.tex')
  .planning/
    ACTIVE_WORKFLOW.md        # current_phase, last_checkpoint, next_action
    PRECIS.md                 # PI-authored title + abstract + venue
    OUTLINE.md                # ratified outline (post-Outline checkpoint)
    REVIEW_STATE.md           # iteration counter for Revision Loop
    sketches/                 # per-section sketches before drafting
  styles/                     # vendored venue templates (populated by fetch_template)
  sections/                   # section .tex files
  figures/, tables/, charts/  # generated artifacts
  refs.bib                    # validated bibliography
  main.tex                    # skeleton, then \input{sections/*}
  ai_tic_config.yaml          # per-project overrides
```

## Phase boundaries

Phase 1 (this mission):

- SKILL.md, references/, scripts/ (with stubs for Phase 2 items), workspace-template/, tests/skills/writer/, docs.
- Two seed venues: CHI, EMNLP.
- Anti-AI-tic enforcement live and tested.
- Local LaTeX render plus layout audit live and tested.
- Reference validation Stage A (CSL-JSON pass-through) live; Stages B through G stubbed.
- Manual reference handling acceptable in Phase 1.

Phase 2 (separate future mission):

- `rka-writer-tools` MCP server (habanero plus pyalex plus semanticscholar plus arxiv plus serpapi).
- Reference validation Stages B through G live.
- SerpAPI integration with credit budget.
- Five additional venue files (USENIX, IEEE-SP, NeurIPS, OSDI, Nature).
- Author disambiguation with ORCID + SerpAPI.

Phase 3 (separate future mission):

- Revision Loop with four `comment_class` mission shapes (R1, R2, R3, R4).
- Brain mission integration for Writer revisions (Brain spawns a Writer subagent on a Revision Mission).
- Optional MCP tools `rka_get_manuscript`, `rka_validate_reference`, `rka_register_manuscript`.

The phasing rationale: Phase 1 ships a usable Writer for PI's solo drafting workflow (manual reference assembly is acceptable). Phase 2 makes reference validation automated. Phase 3 closes the loop with Brain-spawned revisions.
