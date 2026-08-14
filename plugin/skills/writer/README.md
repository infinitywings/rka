# RKA Writer Skill

Version 2.7.0. The Writer co-authors manuscripts grounded in the RKA
research graph and is distributed for Claude Code and Codex. It drafts
but does not assert: manuscript claims must remain traceable to current
RKA evidence and PI-ratified decisions.

Mission of record: `mis_01KS0C3RP04XANCZAB3HTNAG0P`.
Decisions: `dec_01KS0AWYDV752AWQRF40CQBRFZ` (deployment),
`dec_01KS0AXXASJ5GXV7M0SS39Y066` (SerpAPI tertiary),
`dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D` (Q1-Q8 bundle),
`dec_01KS12H9KT1T03DHX2Q6FKTXHH` (anti-AI-tic primary-source disposition).

## Quickstart

### 1. Register the manuscript and atomically create its workspace

```
rka writer init --project-id <prj_...> --venue <venue> --title "<PI-authored title>"
cd manuscripts/<project-id>/<venue>/
```

The command writes a complete, portable workspace only after RKA returns a
canonical native `man_` manuscript. It stores the explicit binding in
`.rka/manuscript.json` and leaves no unresolved core placeholders. Then:

- Run the choice-first framing session. The Writer proposes evidence-bounded
  options with pros and cons; the PI selects or edits the final title,
  abstract, claims, and paper spine recorded in `.planning/PRECIS.md`.
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
2. `rka writer impact --claim-spine .planning/RKA_CLAIM_SPINE.yaml` maps
   post-cursor changes to affected claims, units, files, and artifacts.
3. `rka writer sync` refreshes the read-only v2 spine and generated views.
4. `rka_query(args={"operation": "research_map", ...})` provides retrieval
   orientation.
5. `.planning/FRAMING_SESSION.yaml` resumes the advisory author/researcher
   interview; `.planning/ACTIVE_WORKFLOW.md` carries disposable local state.
6. `rka writer readiness --target-phase ...` asks RKA for the authoritative
   mechanical gate.
7. The Writer greets the PI with the inferred next action.

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

## Current v2.7.0 surface

| Component | Status |
|---|---|
| `SKILL.md` | v2.7.2 server-authoritative role contract, choice-first framing, checkpoints, provenance, and review workflow |
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

Writer is a role skill, not a second orchestrator. It uses RKA through the
typed MCP surface or a trusted local REST connection. Canonical Writer content
lives under `rka/skills/writer/` and is mirrored byte-for-byte under
`plugin/skills/writer/`; tests live under `tests/skills/writer/`.

RKA core owns the native `man_` manuscript aggregate, stable claims and
immutable wording versions, evidence roles, exact PI ratifications, units,
checkpoints, verification attestations, revisions, readiness, and change
impact. Writer owns `.tex` and other authoring files, venue formatting,
rendering, and deterministic projections. Legacy tagged `jrn_` manifests are
compatibility aliases only.

See [`references/architecture.md`](references/architecture.md) for the full
architecture, [`references/workflows.md`](references/workflows.md) for the
session-start procedure and seven sub-procedures,
[`references/server_authoritative_workflow.md`](references/server_authoritative_workflow.md)
for the sync/impact/update loop,
[`references/evidence_to_spine_pipeline.md`](references/evidence_to_spine_pipeline.md)
for journal-to-claim-to-cluster noise smoothing, and [`SKILL.md`](SKILL.md)
for the role contract.

## Pointers

- Mission of record: `mis_01KS0C3RP04XANCZAB3HTNAG0P`
- Comprehensive design (RKA-resident): `jrn_01KS0B8EDZ4FYFF11Q8CQ97ZDT`
- Deep research synthesis: `jrn_01KS0AVZRDA0KPXK61MN9PV5DE`
- Brain counterpart skill: [`../brain/SKILL.md`](../brain/SKILL.md)
- Executor counterpart skill: [`../executor/SKILL.md`](../executor/SKILL.md)
- PI counterpart skill: [`../pi/SKILL.md`](../pi/SKILL.md)
- Top-level skills index: [`../SKILL.md`](../SKILL.md)
