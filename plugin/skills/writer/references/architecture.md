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

## Graph semantics Writer uses

Writer records cross-entity provenance only through the schema-valid
`entity_links` vocabulary (see `../brain/architecture.md` section "Entity-link
and claim-edge vocabularies"). Most edges are materialized automatically from
typed `related_*` fields by core services:

| Edge | From | To | Meaning |
|---|---|---|---|
| `cites` | manuscript jrn_ | lit_ | manuscript cites this literature item |
| `references` | manuscript jrn_ | dec_ | manifest records its checkpoint decisions |
| `justified_by` | checkpoint dec_ | jrn_ | checkpoint decision rests on this evidence |
| `informed_by` | lit_ | checkpoint dec_ | literature informed this decision |
| `motivated` | checkpoint dec_ | revision mission mis_ | checkpoint triggered the rework |
| `supersedes` | new dec_ | old dec_ | revisited checkpoint replaces prior |
| `produced` | mission mis_ | manuscript jrn_ | revision mission updated this manuscript |

Scientific support, contradiction, and qualification are represented only as
`claim_edges` among `clm_` records. The claim spine references those records and
checks their status; it does not invent cross-type `supports` or `contradicts`
links. The Writer never invents new edge types or creates orphan entities.

## Bookkeeper invariant (Phase 1)

The original Phase 1 bookkeeper invariant was a delivery boundary, not a permanent architecture rule. Phase 0 reliability now deliberately adds narrow core semantics: `claims.verified` means source grounding only; `claims.evidence_status` separately records scientific support; reference validations are immutable manuscript/project-scoped attestations; and the core CLI owns atomic workspace initialization. Writer still owns prose, files, venue structure, rendering, and derived projections. These core changes must remain typed, migrated, and backward-compatible rather than being re-encoded as Writer tags or YAML conventions.

## Workspace template structure

The package ships a workspace template at `rka/skills/writer/workspace-template/`. Never copy it by hand. `rka writer init` preflights the target, registers or verifies a `jrn_` manuscript, substitutes every core token in a sibling staging directory, writes `.rka/manuscript.json`, and atomically publishes the complete directory:

```
manuscripts/<project-id>/<venue>/
  .rka/manuscript.json        # explicit project/manuscript binding from init
  .mcp.json                   # portable commands; no credentials/project default
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

## Current reliability boundary

- RKA core owns project/manuscript identity, claim grounding, scientific-support status, PI decisions, currency, and reference-validation attestations.
- Writer owns the editable derived spine, generated Markdown views, prose, citation formatting, venue templates, rendering, and layout checks.
- `rka writer assist` is read-only and produces candidates; it cannot ratify or write records.
- `rka writer readiness` requires a fresh project-scoped entity packet and live-valid claim spine before drafting.
- Missing provenance, missing render artifacts, unsupported claim types, unscoped ratifications, and unavailable resolution evidence fail closed.
- `rka-writer-tools`, Stages A through G, extended venue specs, and the R1-R4 revision loop are implemented; historical phase labels elsewhere do not override this current boundary.
