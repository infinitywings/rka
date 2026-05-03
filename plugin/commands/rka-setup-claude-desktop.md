---
description: "Configure Claude Desktop's MCP server entry to use the RKA wrapper. Cross-platform (macOS / Windows / Linux). Atomic with backup; conflict-detects existing entries."
argument-hint: "[--force]"
---

Run the cross-platform setup helper script that ships with this plugin:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup-claude-desktop.py
```

If the user passed `--force` as an argument to the slash command, append it:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup-claude-desktop.py --force
```

Capture the script's stdout AND stderr in your response. The script handles all the cross-platform logic — OS detection, config file location, atomic merge, backup with timestamp, conflict detection, restore-on-failure.

After the script completes, summarize the result for the user in plain language:

- **Exit code 0 + "already configured"**: tell the user Claude Desktop is already set up correctly; no action needed.
- **Exit code 0 + "config updated"**: tell the user the setup succeeded, mention the backup path, and explicitly remind them to fully quit + reopen Claude Desktop (the script's NEXT STEP message has the OS-specific quit instructions; relay them).
- **Exit code 1 + "Backend NOT reachable"**: tell the user RKA's Docker backend isn't running. Suggest running `docker compose up -d` from the rka repo, then re-running this slash command.
- **Exit code 1 + "CONFLICT"**: tell the user that an existing `mcpServers.rka` entry differs from the proposed one. Show them the diff (already in script output). Ask whether to re-run with `--force` to replace it.
- **Exit code 2 + "malformed JSON"**: surface the error; do NOT auto-fix the user's config. Suggest they back it up and fix the JSON manually first.
- **Exit code 2 + "wrapper script not found"**: tell the user to reinstall the rka plugin via `/plugin uninstall rka@rka` then `/plugin install rka@rka`.

Do NOT call additional tools beyond the bash invocation. Keep the response under 20 lines.

If the user wants to preview without making changes, suggest they re-run with `--dry-run` (e.g., the user types `/rka-setup-claude-desktop --dry-run` and you append `--dry-run` to the python invocation).
