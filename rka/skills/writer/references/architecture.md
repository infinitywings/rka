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
            +--> .planning/
                 +--> RKA_CLAIM_SPINE.yaml (editable Writer projection)
                 +--> CONTRIBUTION_CONTRACT.md (generated, read-only)
                 +--> ARGUMENT_SPINE.md (generated, read-only)
                 +--> RESULTS_TRACE.md (generated, read-only)
                 +--> other working state
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

> **v2.7.0 dispatch translation.** Legacy tool names below (`rka_add_decision`, `rka_record_pi_selection`, `rka_get_research_map`, `rka_add_note`, etc.) are synonyms for `rka_execute(args={"operation": ...})` / `rka_query(args={"operation": ...})` under the v2.7.0+ typed-arg surface. The discipline (`source="pi"` + `verbatim_input`, `related_journal=[...]` on decisions, `project_id` on every call, etc.) carries over verbatim — only the call shape changes. See the role SKILL.md files for the full mapping and `rka_describe(operation="<name>")` for per-operation signatures.

| Tool | When | Purpose |
|---|---|---|
| `rka_get_status` | session start | confirm phase/focus for the explicitly passed project_id |
| `rka_get_changelog` | session start, before every writing gate | refresh dependencies and identify records changed since the saved claim-spine cursor |
| `rka_get_research_map` | session start, before outline | structural overview of clusters and claims |
| entity reads | claim planning, session start, before every writing gate | resolve claim-spine dependencies and identify affected claims and manuscript units |
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

## Claim-spine representation

The claim spine adds a structured argument projection without changing the RKA
data model. Its full contract is in [`claim_spine.md`](claim_spine.md).

```text
live RKA entities and links
        |
        | resolve, check project, status, and terminal sources
        v
.planning/RKA_CLAIM_SPINE.yaml
        |
        | deterministic rendering only
        +--> CONTRIBUTION_CONTRACT.md
        +--> ARGUMENT_SPINE.md
        +--> RESULTS_TRACE.md
        |
        | claim/unit dependencies
        v
sections/*.tex + hidden provenance comments
```

Canonicality is layered rather than duplicated:

- RKA is canonical for research observations, literature, claim extraction,
  decision history, entity status, and provenance.
- `RKA_CLAIM_SPINE.yaml` is the editable Writer-side map from those records to
  this manuscript. It is regenerable and cannot make a record true by naming
  it.
- The three Markdown files are generated views. They are never authoritative
  inputs and are never edited to repair the YAML.
- The manuscript `jrn_` remains the canonical RKA record for the paper itself.

The Outline checkpoint owns contribution ratification. The PI chooses exact,
bounded wording; the active `dec_` records that wording and is referenced by
the spine's `ratified_by` field. A decision licenses the manuscript framing but
does not serve as empirical support. Positive evidence, qualifiers, and
counterevidence resolve through verified `clm_` records to current source
records. An `ecl_` is useful for discovery but is not terminal evidence.

The dependency snapshot records all RKA entities used by the spine, including
sources reached through claim records and their live freshness metadata. On
session resume, currency comparison maps changed or currently invalid entities
back to affected claim IDs and manuscript unit IDs. A changed record never
rewrites PI-ratified wording automatically. Yellow staleness remains a surfaced
warning; missing, wrong-project, red-stale, temporally invalid, inactive,
reprocessing-required, retracted, or unresolvable dependencies block the
relevant writing gate. Unknown freshness metadata or an unavailable resolver
or snapshot is `ERROR`, never `PASS`.

Snapshot creation is itself gated by live validation and accepts only `PASS`.
Currency checking does not trust the saved snapshot as proof: it revalidates
the active spine and recursively expands both claim-level and unit-only source
dependencies before reporting affected units.

The claim spine emits no new entity or edge types and requires no service, API,
MCP, or web change. It uses the existing research-map, changelog, entity,
decision, and manuscript surfaces. Reviewer-facing output remains advisory and
contains no aggregate paper score or accept/reject prediction.

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
    provenance={                      # record_note nests linkage under provenance (not top-level)
        "related_decisions": [
            "dec_venue_checkpoint",
            "dec_outline_checkpoint",
            "dec_table_figure_plan",
            "dec_reference_set",
            "dec_draft_approvals",
            "dec_final_layout",
        ],
        "related_literature": ["lit_..."],  # all cited
    },
    tags=["manuscript", "venue:CHI", "phase:draft", "writer-session:3"],
    importance="high",
    confidence="tested",
)
```

The manifest is updated as the manuscript progresses through phases; the `tags` field carries the current phase via `phase:<draft|review|final>`. The `related_decisions` field grows as each of the six PI checkpoints ratifies a `dec_`.

The Outline checkpoint produces the framing decision plus one child
claim-scope `dec_` per selected contribution. Each child stores one exact claim
sentence in `chosen`, so `ratified_by` remains unambiguous when a paper has
multiple contributions. These records implement the PI's explicit Outline
selection; they do not add a seventh checkpoint. If evidence later supports a
materially different contribution, a new claim-scope decision supersedes the
old one; the manifest keeps both in its decision lineage while the spine points
only to the current decision.

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

Phase 2 may introduce the `rka-writer-tools` MCP server as a separate sibling MCP (not a modification of the existing `rka` server). The manuscript capabilities themselves already shipped on the existing `rka` server (available at v2.5.7+) as live dispatch operations — `manuscript` (via `rka_query`), and `validate_reference` / `register_manuscript` (via `rka_execute`); the legacy bare names `rka_get_manuscript` / `rka_validate_reference` / `rka_register_manuscript` remain in the deferred tier, loadable via `rka_load_tools`. Phase 1 stays out of `rka/mcp/`.

## Workspace template structure

Phase 1 ships a workspace template at `rka/skills/writer/workspace-template/`. The PI copies it to `manuscripts/<project-id>/<venue>/` to bootstrap a new manuscript:

```
manuscripts/<project-id>/<venue>/
  .mcp.json                   # rka required; rka-writer-tools commented (Phase 2)
  .latexmkrc                  # TEXINPUTS=./styles//: ; @default_files = ('main.tex')
  .planning/
    ACTIVE_WORKFLOW.md        # current_phase, last_checkpoint, next_action
    PRECIS.md                 # PI-authored title + abstract + venue
    RKA_CLAIM_SPINE.yaml      # editable mapping from RKA records to claims/units
    CONTRIBUTION_CONTRACT.md  # generated read-only contribution view
    ARGUMENT_SPINE.md         # generated read-only unit/claim view
    RESULTS_TRACE.md          # generated read-only result/claim view
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
- RKA-backed claim-spine planning files, resolver-injected validation, and
  deterministic rendering remain within the Writer tree and use the existing
  RKA surface.
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
- Manuscript operations `manuscript` (`rka_query`), `validate_reference` and `register_manuscript` (`rka_execute`) — already shipped on the `rka` server at v2.5.7+; legacy names `rka_get_manuscript` / `rka_validate_reference` / `rka_register_manuscript` loadable via `rka_load_tools`.

The phasing rationale: Phase 1 ships a usable Writer for PI's solo drafting workflow (manual reference assembly is acceptable). Phase 2 makes reference validation automated. Phase 3 closes the loop with Brain-spawned revisions.
