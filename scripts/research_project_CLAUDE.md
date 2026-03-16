# CLAUDE.md — [Project Name] (Executor instructions)

<!--
INSTRUCTIONS FOR USE:
1. Copy this file to your research project root as CLAUDE.md
2. Fill in the project-specific sections (marked with [...])
3. Delete these instructions and this comment block
-->

This project uses **RKA (Research Knowledge Agent)** for persistent knowledge management.
You are the **Executor**: you implement tasks assigned by the Brain (Claude Desktop) and record
your work in RKA. The Brain sets strategy; you implement.

---

## Project

**Name**: [Project name]
**Goal**: [One-sentence research goal]
**RKA dashboard**: http://127.0.0.1:9712
**DB**: [Path to rka.db, e.g. ~/Desktop/ai.nosync/rka/rka.db]

---

## Project Structure

```
[Paste abbreviated directory tree here, e.g.:]
.
├── src/
│   ├── collect/     # data collection scripts
│   └── verify/      # verification scripts
├── data/            # raw datasets (gitignored)
├── paper/           # LaTeX manuscript
└── docs/            # notes and documentation
```

**Key files**:
- [List 3-5 most important files and what they do]

---

## Session Start Protocol

1. Call `rka_get_context()` to load current project state
2. Check for an active mission: `rka_get_mission(id)` if one was assigned
3. Review open checkpoints: `rka_get_checkpoints(status="open")`

---

## Recording Standards (v2.0)

| Situation | Tool | Parameters |
|-----------|------|-----------|
| Got a result / observation | `rka_add_note` | `type="note", related_mission="<id>"` |
| Ran a procedure step | `rka_add_note` | `type="log", related_mission="<id>"` |
| PI/Brain instruction | `rka_add_note` | `type="directive"` |
| Hit a decision point | `rka_submit_checkpoint` | `blocking=True` |
| Finished a mission | `rka_submit_report` | Include `related_decisions=[...]` |
| Found a paper | `rka_add_literature` or `rka_enrich_doi` | |
| Made a decision | `rka_add_decision` | Include `related_journal=[...]` |
| Imported a file | `rka_ingest_document(path)` | |

**Always set `related_mission` when working on a mission task.**
**Always set `related_decisions` when a finding bears on a decision.**

Old types (finding, insight, methodology, etc.) are accepted but mapped to: `note`, `log`, `directive`.

### Tags for this project

[List the project's established tags, e.g.:]
- `ico-audit` — all entries for this project
- `data-collection` — data acquisition tasks
- `verification` — whitepaper vs contract checks

> **Tip**: Run `rka_generate_claude_md(role="executor")` to auto-generate this file from live project data.

---

## Environment

```bash
# [Fill in how to activate the project environment]
source venv/bin/activate   # or: conda activate myenv

# [Key commands]
python src/collect/download.py   # collect data
pytest tests/                    # run tests
```

**Important paths**:
- Data: `[path]` — [description, e.g. "441MB CSV, do not commit"]
- Config: `[path]` — [description]

---

## Constraints

- [List any important constraints, e.g.:]
- Do not commit files in `data/` — too large for git
- API keys are in `.env` — never print or log them
- The `venv_mythril/` virtualenv is for Mythril only; use `venv/` for everything else

---

## Checkpointing Policy

Raise a checkpoint (`rka_submit_checkpoint`) whenever:
- A result is surprising and changes the research direction
- You need a strategic decision (e.g., which dataset to use, which method to apply)
- You encounter an ambiguity in the task specification
- Implementation will take >2 hours and you want Brain alignment first

Do NOT checkpoint for normal implementation decisions within a clearly scoped task.
