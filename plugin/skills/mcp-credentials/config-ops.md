# Config operations — read / parse / merge / backup / write

The load-bearing technical pattern for this skill. Every credential persistence runs this exact procedure. A botched write can prevent Claude Desktop from starting, so the discipline here is strict.

## File targets

| Target | Format | Parser |
|---|---|---|
| `claude_desktop_config.json` | JSON | Python `json` |
| `~/.claude.json` | JSON | Python `json` |
| `<repo>/.claude/mcp.json` | JSON | Python `json` |
| `orchestrator/.env` | `KEY=VALUE` per line | Plain text, line-oriented |

## The procedure (JSON targets)

### Step 1 — Resolve the path

Cross-platform per [`catalog.md`](catalog.md). Verify the path is absolute and the parent directory exists. If it doesn't, the user hasn't installed Claude Desktop yet — surface that.

### Step 2 — Read the current file

If the file doesn't exist, that's fine — start from `{"mcpServers": {}}`. If it exists but doesn't parse as JSON, **abort**. Show the user the parse error and ask them to fix the file manually first. Do NOT overwrite a file you can't parse — Claude Desktop won't be able to either, but at least the user can recover.

### Step 3 — Deep-merge the new env entries

```python
import copy
config = current_config_dict
config.setdefault("mcpServers", {})
server_block = config["mcpServers"].setdefault(server_name, {})
# Preserve any existing command/args; only modify env.
server_block.setdefault("env", {})
for key, value in new_env_entries.items():
    server_block["env"][key] = value
```

Critical: **don't replace `mcpServers.<server>`** — only set/update `mcpServers.<server>.env.<KEY>`. Existing `command`, `args`, and any other env keys must survive.

### Step 4 — Validate the merged JSON

Before writing, dump and re-parse to confirm the JSON is well-formed:

```python
import json
serialized = json.dumps(config, indent=2) + "\n"
json.loads(serialized)  # raises if malformed; abort if so
```

### Step 5 — Backup

```python
from datetime import datetime, timezone
backup_path = f"{target_path}.bak.{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%SZ')}"
shutil.copy2(target_path, backup_path)  # preserves mtime + permissions
```

Tell the user the backup path before writing the new file.

### Step 6 — Atomic write

Write to a sibling temp file, then `os.replace()` (which is atomic on POSIX and almost-atomic on Windows):

```python
import os, tempfile
fd, tmp = tempfile.mkstemp(
    prefix=os.path.basename(target_path) + ".",
    suffix=".tmp",
    dir=os.path.dirname(target_path),
)
with os.fdopen(fd, "w") as f:
    f.write(serialized)
os.replace(tmp, target_path)
```

Why the temp file: if the process dies mid-write, the original file is intact. `os.replace` swaps in the new content atomically.

### Step 7 — Show the diff

After writing, run `diff <backup_path> <target_path>` (or compute it in Python) and show the user exactly what changed. Surface the env keys you added but **mask the values** — print `KEY=<set>` not `KEY=<actual-secret>`. This prevents the credential from appearing in conversation logs you can't delete later.

```
✓ Persisted credentials. Diff (values masked):

  mcpServers.zotero.env:
    + ZOTERO_API_KEY = <set>
    + ZOTERO_LIBRARY_ID = 12345678
    + ZOTERO_LIBRARY_TYPE = user

Backup at /Users/you/Library/Application Support/Claude/claude_desktop_config.json.bak.2026-05-30T17-32-15Z
```

Note: numeric IDs (Zotero library ID) and other non-secret config values are fine to show.

## The procedure (`.env` targets)

### Step 1 — Resolve the path

For `orchestrator/.env`, the path is `<rka-repo-root>/orchestrator/.env`. The user must be in or pass the absolute path. Verify the file is gitignored before writing (check `.gitignore` for `.env` or `orchestrator/.env`).

### Step 2 — Read the current file

If absent, start from empty. If present, parse as line-oriented `KEY=VALUE` (skip comments and blank lines, preserve them on rewrite).

```python
existing = {}
preserved_lines = []
for line in current_lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        preserved_lines.append(line)
        continue
    if "=" not in stripped:
        preserved_lines.append(line)
        continue
    key, _, value = stripped.partition("=")
    existing[key.strip()] = value.strip()
```

### Step 3 — Merge

```python
for key, value in new_env_entries.items():
    existing[key] = value
```

### Step 4 — Write (line-oriented format)

```python
output = "\n".join(preserved_lines + [
    f"{k}={v}" for k, v in sorted(existing.items())
]) + "\n"
```

Critical detail learned from a prior session bug: **every line MUST end with a newline.** A file that ends with `KEY1=value1KEY2=value2` (no newline between) gets parsed as `KEY1=value1KEY2=value2` and the second key is lost. The `\n` join + trailing `+ "\n"` is the discipline.

### Step 5 — Backup + atomic write + diff (same as JSON)

Same backup naming, same temp-file-then-replace pattern, same masked diff at the end.

## Edge cases worth handling

- **The user has a partially-set config** (e.g., `mcpServers.rka` exists with `command` and `args` but no `env`). Preserve `command` + `args`; just add `env`.
- **The user has the same env var set via two paths** (e.g., they put `SEMANTIC_SCHOLAR_API_KEY` in both `mcpServers.rka.env` and `mcpServers.zotero.env`). Don't clean up duplicates without asking. Surface them and offer to consolidate.
- **The user pastes an env var with surrounding quotes** (e.g., `"sk-ant-…"`). Strip outer quotes before persisting — JSON would otherwise nest them as part of the value.
- **The user is on Windows and the file path contains spaces.** Ensure the path is quoted properly in any shell command you run, and don't rely on shell glob expansion.
- **The user's `.env` ends without a final newline AND has the concatenation bug already.** Detect by parsing — if a value contains `=` followed by a key-like uppercase identifier, warn and offer to repair before adding new keys.

## What to do when something goes wrong

| Symptom | Likely cause | Recovery |
|---|---|---|
| `json.JSONDecodeError` reading the existing file | User hand-edited the file and broke it | Show the parse error with line+col; ask them to fix manually. Do not auto-repair. |
| `PermissionError` writing the file | Wrong owner / read-only mount / sandboxed app | Print the path; explain the user needs write access. On macOS, this can mean the app is sandboxed. |
| `OSError: [Errno 28] No space left` | Disk full | Surface clearly. Don't leave the temp file behind — `try/finally` to clean up. |
| The merged JSON parses but doesn't include the new env entry | Path resolution mismatch (e.g., user wrote to a Claude Code config but Claude Desktop is the one running) | Confirm with the user which app they're using; re-read [`catalog.md`](catalog.md) target table. |

## Restore-from-backup escape hatch

If the user calls you back saying "Claude Desktop won't start after the change" or "the new MCP server isn't showing up":

1. Locate the most recent backup: `ls -t <config-path>.bak.*` — they're ISO-timestamped so sort lexically = sort chronologically.
2. `cp <backup-path> <config-path>` — restore.
3. Tell the user to fully quit + reopen.

Always leave the backup in place after a successful write; don't auto-delete. Disk space is cheap; user trust is not.
