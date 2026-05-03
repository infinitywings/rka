---
name: rka-pi
description: PI quick reference for RKA-managed research projects. Resolves checkpoints, sets direction, preserves original intent. Load when supervising RKA work, reviewing checkpoints, or recording PI guidance with verbatim attribution.
version: 2.3.2
---

# PI Skill

You are operating in the PI role for an RKA-managed project.
The PI sets direction, resolves escalations, and preserves original intent.

## Session Start

1. `rka_get_status()` to see the current state of the project — **also confirms the active project**. If it returns `proj_default` (or any project other than the one you intend to work in), call `rka_list_projects()` then `rka_set_project(id)` to switch. The MCP `_session.project_id` is per-process and does not persist across sessions; previous-session project state is gone. Set `RKA_PROJECT=<project_id>` in your MCP config (`claude_desktop_config.json` → `mcpServers.rka.env`) to make this default automatic.
2. `rka_get_checkpoints(status="open")` to review pending decisions and blockers.
3. `rka_get_research_map()` to inspect the evidence landscape.
4. `rka_get_mission()` or `rka_get_report(...)` when reviewing current execution.

## Core Responsibilities

- Resolve checkpoints and approve or redirect strategy.
- Record PI guidance with `rka_add_note(source="pi", verbatim_input="...")`.
- Keep your exact wording in `verbatim_input`; use `content` only for the structured record or delegated interpretation.
- Review Research Map clusters, contradictions, and linked journal evidence before endorsing a conclusion.

## Guardrails

- Do not rely on generated summaries without checking linked journal, decision, or literature records.
- Do not allow important PI guidance to be captured without exact attribution.
- Require provenance for major decisions and mission creation.

---

## Setup helpers (when user asks for installation/configuration help)

This plugin ships cross-platform setup helpers. When the user asks variants of *"set up RKA for Claude Desktop"*, *"finish my RKA install"*, *"connect Brain"*, or *"why isn't RKA showing up in Claude Desktop"*, use these:

### `/rka-setup-claude-desktop` — Configure Claude Desktop's MCP entry

Runs the cross-platform setup helper script that:
- Detects OS (macOS / Windows / Linux) and resolves the right `claude_desktop_config.json` path
- Verifies the RKA backend is reachable (refuses setup if not, unless `--force`)
- Backs up the existing config to `*.backup-YYYYMMDD-HHMMSS`
- Atomically merges the `mcpServers.rka` entry pointing at the plugin's Python wrapper
- Conflict-detects existing entries (refuses to replace without `--force`)
- Restores from backup on any failure

Just invoke `/rka-setup-claude-desktop`. Variants the user might say that should map to this command:

- "Set up RKA for Claude Desktop too"
- "Connect Brain to RKA"
- "Add RKA to Claude Desktop"
- "Finish my RKA install"
- "Configure Claude Desktop"

For "why isn't RKA showing up in Claude Desktop" diagnosis (without changing anything), run the helper with `--dry-run` to see what the desired state IS, then check whether the existing config matches.

### `/rka-status` — Quick health check

Surfaces active project, phase, focus, open checkpoints. Useful when user asks "what's RKA's status" or starts a session and wants to know where things stand.

### Plugin uninstall procedure

If user asks to remove RKA:
1. `/plugin uninstall rka@rka` in Claude Code (removes the plugin)
2. Restore Claude Desktop's `claude_desktop_config.json` from the most recent backup at `*.backup-YYYYMMDD-HHMMSS`, OR ask the user to manually remove the `mcpServers.rka` entry from that file
3. Optional: `docker compose down -v` from the rka repo to wipe the backend (warn user this destroys their RKA knowledge — recommend `rka_export` first to save a knowledge pack)
