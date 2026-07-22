# RKA Writer Skill

Version 2.6.1. The Writer co-authors manuscripts grounded in the RKA
research graph and is distributed for Claude Code and Codex. It drafts
but does not assert: manuscript claims must remain traceable to current
RKA evidence and PI-ratified decisions.

Mission of record: `mis_01KS0C3RP04XANCZAB3HTNAG0P`.
Decisions: `dec_01KS0AWYDV752AWQRF40CQBRFZ` (deployment),
`dec_01KS0AXXASJ5GXV7M0SS39Y066` (SerpAPI tertiary),
`dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D` (Q1-Q8 bundle),
`dec_01KS12H9KT1T03DHX2Q6FKTXHH` (anti-AI-tic primary-source disposition).

## Quickstart

### 1. Copy the workspace template to your manuscript directory

```
cp -R rka/skills/writer/workspace-template manuscripts/<project-id>/<venue>/
cd manuscripts/<project-id>/<venue>/
```

Then customize:

- Edit `.mcp.json`: replace `<your-username>` and `prj_REPLACE_WITH_PROJECT_ID`.
- Edit `.planning/PRECIS.md`: PI authors the title and abstract.
- Edit `main.tex` after the Venue checkpoint resolves: replace
  `\documentclass{article}` with the venue class.

### 2. Launch Claude Code in the manuscript directory

```
claude
```

The Writer skill loads on session start (rka-writer skill). The Session
Start procedure runs:

1. `rka_query(args={"operation": "status", "project_id": "prj_..."})`
   confirms the project (project_id comes from `list_projects`, not
   session state).
2. `rka_query(args={"operation": "changelog", "project_id": "prj_...",
   "filters": {"since": "<ISO-date>"}})` surfaces RKA changes since last
   session.
3. `rka_query(args={"operation": "research_map", "project_id": "prj_..."})`
   provides the structural overview.
4. `.planning/ACTIVE_WORKFLOW.md` carries resume state.
5. The Writer greets the PI with the inferred next action.

### 3. Run scripts via Bash

The Writer invokes scripts via the `Bash` tool inside Claude Code. PI
can also invoke them directly from a terminal:

```
# Lint a section for AI-tics
python3 rka/skills/writer/scripts/ai_tic_lint.py sections/03-method.tex \
        --config ai_tic_config.yaml \
        --output ai_tic_report.json

# Detect bridge repetition across sections
python3 rka/skills/writer/scripts/bridge_repetition_check.py sections/*.tex

# Build the PDF
./rka/skills/writer/scripts/render.sh main.tex

# Audit the layout after a successful render
python3 rka/skills/writer/scripts/layout_audit.py --venue CHI --output audit.json
```

## Current v2.6.1 surface

| Component | Status |
|---|---|
| `SKILL.md` | v2.6.1 role contract, checkpoints, provenance, and review workflow |
| `references/` | architecture, evidence and citation rules, review guidance, and venue registry |
| `scripts/` | deterministic provenance, citation, venue, reference, layout, and claim-spine checks |
| `mcp_tools/` | reference-metadata and discovery backends for Writer workflows |
| `workspace-template/` | manuscript scaffold with resumable planning state |
| `tests/skills/writer/` | unit, integration, contract, and source-to-plugin parity coverage |

The Writer does not replace PI judgment, treat a structural check as
semantic proof, or produce accept/reject predictions. Evidence gaps and
contradictions return to RKA for resolution. See
[`docs/phase-1-mvp.md`](docs/phase-1-mvp.md) for the historical Phase 1
narrative.

## Per-project AI-tic configuration

`ai_tic_config.yaml` in the manuscript directory overrides default
behavior on a per-term basis. The defaults block HIGH-tier terms (PI
verbatim list plus Kobak 2025 plus Matsui 2025). Disable a term:

```yaml
facilitate:
  verdict: disable
  rationale: "Used in the medical sense (catheter facilitates drainage); domain-legitimate."
```

CRITICAL hits and absolute bans (em-dash U+2014, en-dash U+2013, bullet
density) cannot be overridden. See [`references/ai_tics.md`](references/ai_tics.md)
for the full tier table and replacement guidance.

## Architecture overview

The Writer is a role skill, not a separate process or service. It reads
from and writes to RKA through the existing `rka` MCP server. Canonical
Writer behavior lives under `rka/skills/writer/` and is mirrored
byte-for-byte under `plugin/skills/writer/`; its tests live under
`tests/skills/writer/`. The bookkeeper-not-thinker boundary keeps Writer
changes out of `rka/services/`, `rka/api/`, `rka/mcp/`, and `web/`.

The manuscript is represented as a `jrn_` manifest in RKA (Option 2 per
`dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D` Q1), with the working directory tree
on disk holding the actual `.tex` files. The `jrn_` manifest carries
`related_decisions` (the six PI checkpoints), `related_literature` (all
cited `lit_`), and `related_journal` (all quoted `jrn_`).

See [`references/architecture.md`](references/architecture.md) for the
full architecture, [`references/workflows.md`](references/workflows.md)
for the session-start procedure and seven sub-procedures, and the
[`SKILL.md`](SKILL.md) frontmatter for the contract.

## Pointers

- Mission of record: `mis_01KS0C3RP04XANCZAB3HTNAG0P`
- Comprehensive design (RKA-resident): `jrn_01KS0B8EDZ4FYFF11Q8CQ97ZDT`
- Deep research synthesis: `jrn_01KS0AVZRDA0KPXK61MN9PV5DE`
- Brain counterpart skill: [`../brain/SKILL.md`](../brain/SKILL.md)
- Executor counterpart skill: [`../executor/SKILL.md`](../executor/SKILL.md)
- PI counterpart skill: [`../pi/SKILL.md`](../pi/SKILL.md)
- Top-level skills index: [`../SKILL.md`](../SKILL.md)
