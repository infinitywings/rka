---
name: mcp-credentials
description: Set up credentials for MCP servers (Zotero, Semantic Scholar, Claude OAuth, SerpAPI, OpenAlex) by walking the user through key issuance and editing their Claude Desktop / Claude Code MCP config file. Load when the user asks "set up Zotero" or "add Semantic Scholar credentials" or "configure my MCP servers" or any similar credential-provisioning request.
version: 1.0.0
---

# MCP Credentials Setup

You are configuring an MCP server's credentials for a Claude Desktop or Claude Code install. Most cross-project MCP servers (Zotero, Semantic Scholar, Claude OAuth for the orchestrator's SDK, SerpAPI, OpenAlex) need credentials that the user obtains once and then reuses across every project.

This skill walks you through:

1. **Identifying** which service(s) the user wants to set up.
2. **Issuing** the credential (you guide the user to the right URL with the right form fields).
3. **Validating** the credential format (and optionally testing it against the live API).
4. **Persisting** the credential to `claude_desktop_config.json` (and/or `~/.claude.json` for Claude Code, and/or `orchestrator/.env` for the RKA orchestrator daemon).
5. **Telling the user to restart** the Claude app so the new MCP server entries load.

## Operating principles

- **Plaintext credentials are the platform default.** macOS / Windows / Linux MCP configs store credentials as plaintext JSON. The user has accepted this trade-off (most existing MCP servers — GitHub, Slack, Zotero, etc. — work the same way). Do not engineer a Keychain wrapper unless the user explicitly asks.
- **Never overwrite without backup.** Before writing any config file, copy it to `<file>.bak.<ISO-timestamp>` so the user can recover.
- **Deep-merge, don't replace.** The user likely already has other MCP servers configured. Read → parse → merge new entries → write back. Never overwrite the whole `mcpServers` block.
- **Atomic writes.** Write to a temp file, validate the JSON parses, then move into place. A botched write would prevent Claude Desktop from starting.
- **One service at a time, even if the user asks for several.** Walk through each one fully (issue → validate → persist) before moving to the next, so a failure on service 3 doesn't lose progress on services 1 and 2.

## Available walkthroughs (load on demand)

- [`walkthroughs/claude-oauth.md`](walkthroughs/claude-oauth.md) — `CLAUDE_CODE_OAUTH_TOKEN` for the RKA orchestrator daemon's claude-agent-sdk subprocess. Long-lived (~1 year). Mint via `claude setup-token` on the host.
- [`walkthroughs/zotero.md`](walkthroughs/zotero.md) — `ZOTERO_API_KEY` + `ZOTERO_LIBRARY_ID` + `ZOTERO_LIBRARY_TYPE` for the zotero-mcp server. Per-user library, scope-restrictable.
- [`walkthroughs/semantic-scholar.md`](walkthroughs/semantic-scholar.md) — `SEMANTIC_SCHOLAR_API_KEY` for the rka MCP server's Semantic Scholar search backend (legacy tool `rka_search_semantic_scholar`, deferred on the v2.7.0+ surface — load via `rka_load_tools`; the `rka_record_literature` verb's `search_source='semantic_scholar'` mode delegates to the same code, so the key applies regardless of surface). Raises the rate limit from 100 req/5min to 1 req/sec.
- [`walkthroughs/serpapi.md`](walkthroughs/serpapi.md) — `SERPAPI_KEY` for the rka MCP server's deep-research augmentation. 250 free searches/month.
- [`walkthroughs/openalex.md`](walkthroughs/openalex.md) — `OPENALEX_MAILTO` (just an email, not a secret) for the OpenAlex polite-pool, granting a higher rate limit.

## Reference docs (load on demand)

- [`catalog.md`](catalog.md) — registry of every supported service with envvar names, target config blocks, and validation regex. Use when you need a quick lookup.
- [`config-ops.md`](config-ops.md) — the read/parse/merge/backup/write pattern for `claude_desktop_config.json`, including cross-platform paths and atomic-write discipline.

## Standard flow

When the user asks you to set up one or more credentials, do this:

### Step 1 — Identify

Ask which service(s) the user wants if not stated. Surface the available walkthroughs so they know what's supported.

> *"Which credentials would you like to set up? I can walk you through Zotero, Semantic Scholar, Claude OAuth (for the RKA orchestrator), SerpAPI, or OpenAlex. You can do one or several."*

### Step 2 — Walkthrough (per service)

Load the relevant walkthrough card from `walkthroughs/<service>.md`. Each card has the same shape:

- **What you need** — list of fields the service requires
- **Where to get it** — step-by-step URL navigation
- **Validation** — regex for the key format, expected length, etc.
- **Optional sanity check** — a one-shot API call to confirm the credential works
- **Target env vars** — exact env-var names and which MCP server block they belong in

Walk the user through the steps. Use `AskUserQuestion` for branching choices (e.g., "personal library vs group library"). When they paste the key in chat, validate it against the regex; if it fails, point at the likely typo (wrong length, wrong charset).

### Step 3 — Sanity check (optional but recommended)

If the walkthrough card has a `Sanity check` block, run the curl command via Bash to confirm the credential works. Non-200 response → tell the user, suggest the most likely cause (wrong scope, expired, wrong ID), don't proceed to persist.

### Step 4 — Persist

Use the procedure in [`config-ops.md`](config-ops.md):

1. Read `claude_desktop_config.json` (or `~/.claude.json` for Claude Code, or `orchestrator/.env` for the orchestrator — the walkthrough card tells you which).
2. Parse as JSON (skip for `.env` — it's KEY=VALUE).
3. Deep-merge the new env entries into the target MCP server block.
4. Backup the original to `<file>.bak.<ISO-timestamp>`.
5. Write the new content atomically (temp file → validate parse → move).
6. Show the user the diff so they see exactly what changed.

### Step 5 — Restart instruction

```
✓ Done. Credentials persisted to <path>.
Backup saved at <path>.bak.<timestamp>.

To activate, **fully quit and reopen Claude Desktop**:
  - macOS: Cmd+Q, then reopen from Applications
  - Windows: right-click tray icon → Quit, then reopen from Start Menu
  - Linux: close the app entirely, then reopen

Once Claude Desktop is back up, ask me to "list Zotero items" (or
"search Semantic Scholar for X") to confirm the new MCP server
is active.
```

For Claude Code: reload the VS Code window (Cmd+Shift+P → "Developer: Reload Window") instead of full quit.

## Guardrails

- **Never paste credentials back to chat after persisting.** When you confirm persistence, refer to the credential as "the key you provided" or "the token now in your config" — don't echo it. This avoids accidental exposure in conversation logs or screenshots.
- **Don't run sanity-check curl commands in the foreground if the key is long-lived.** The shell history may persist the key. Use a pipe (`echo "$KEY" | curl --data-binary @-`) or a heredoc to avoid putting the key on the command line.
- **Don't edit `claude_desktop_config.json` if it currently fails to parse.** Show the user the parse error, ask them to fix it manually first. A botched JSON would prevent Claude Desktop from starting.
- **Don't proceed if the user pastes a credential that looks like it might already be in use elsewhere.** If the key format suggests it's a SSH key, GPG passphrase, AWS secret, etc. — confirm with the user before persisting.

## When the user asks for something this skill doesn't cover

If the user asks for a service not in [`catalog.md`](catalog.md), say so clearly and offer two paths:

1. **They can register a new MCP server manually** — point them at the MCP docs and the config file path.
2. **You can add a walkthrough** if they tell you the service's API and which env vars its MCP server expects. Add a new `walkthroughs/<service>.md` following the existing template.

Don't fabricate URLs or env-var names for unfamiliar services — verify against the service's docs first.
