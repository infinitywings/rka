---
description: "Bootstrap a new manuscript workspace from the Writer skill's workspace-template. Creates a per-manuscript working directory with main.tex, refs.bib, .mcp.json, .planning/ and substitutes placeholders (your username, project ID)."
argument-hint: "[project_id] [venue] [path]"
---

Run the cross-platform bootstrap helper script that ships with this plugin:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/start-manuscript.py
```

If the user passed arguments to the slash command, forward them positionally. The helper accepts:

- `--project-id <prj_…>` — RKA project ID (the workspace's `.mcp.json` `RKA_PROJECT` value)
- `--venue <CHI|EMNLP|NeurIPS|USENIX|IEEE-SP|OSDI|Nature>` — venue name (must match a `references/venue/<VENUE>.md` file shipped with the Writer skill)
- `--path <dir>` — manuscript working directory to create (default: `./manuscripts/<project-slug>/<venue>/`)
- `--force` — overwrite existing files in the target directory (otherwise refuses if non-empty)

If the user invoked `/rka-start-manuscript` with no arguments, the script prints a list of supported venues and exits 2 so you (Claude) can prompt the user in the chat thread for project_id + venue + path, then re-invoke with the appropriate `--project-id` / `--venue` / `--path` flags.

If the user invoked `/rka-start-manuscript prj_01ABC CHI manuscripts/my-paper/`, forward those as `--project-id prj_01ABC --venue CHI --path manuscripts/my-paper/`.

Capture the script's stdout AND stderr in your response. The script handles all the cross-platform logic — OS detection, $USER substitution in `.mcp.json`, project-ID substitution, workspace-template file copy preserving hidden files (`.latexmkrc`, `.mcp.json`, `.planning/`), non-destructive overwrite refusal, and clear next-step messaging.

After the script completes, summarize the result for the user in plain language:

- **Exit code 0 + "manuscript workspace bootstrapped"**: tell the user the workspace is ready. Show them the path. Remind them to:
  1. Fill in their SerpAPI key + emails in `.mcp.json` `env` (the placeholders are visible)
  2. Confirm `rka-writer-tools` binary is installed: `which rka-writer-tools` should return a path; if not, run `UV_CACHE_DIR=/tmp/uv-cache uv tool install --force --reinstall '.[writer-tools]'` from the rka repo root
  3. `cd <path> && claude` to start the Writer-skill drafting session
- **Exit code 2 + "no arguments provided"**: prompt the user for project_id + venue + path; re-invoke
- **Exit code 1 + "target directory exists and is non-empty"**: ask the user whether to re-run with `--force` to overwrite
- **Exit code 1 + "venue not recognized"**: list the supported venues from the script's stderr; ask the user to pick one
- **Exit code 1 + "rka-writer-tools binary not on PATH"**: warn the user but still complete the bootstrap (the `.mcp.json` is created); tell them to install the binary before `cd <path> && claude`

Do NOT call additional tools beyond the bash invocation. Keep the response under 25 lines.
