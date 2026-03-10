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

## Recording Work in RKA

### What to record

| Situation | Tool | Notes |
|---|---|---|
| Completed a script / pipeline step | `rka_add_note` | `type="methodology"` |
| Got a result or measurement | `rka_add_note` | `type="finding"`, `confidence="hypothesis"` |
| Noticed unexpected behavior | `rka_add_note` | `type="observation"` |
| Hit a decision that needs Brain/PI | `rka_submit_checkpoint` | Set `blocking=True` |
| Found a relevant paper | `rka_add_literature` or `rka_enrich_doi` | |
| Imported a new file | `rka_ingest_document(path)` | |

Always set `related_mission=<id>` when working on a mission task.

### Tags for this project

[List the project's established tags, e.g.:]
- `ico-audit` — all entries for this project
- `data-collection` — data acquisition tasks
- `verification` — whitepaper vs contract checks
- `methodology` — pipeline and process notes

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
