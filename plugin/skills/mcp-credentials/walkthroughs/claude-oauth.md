# Claude OAuth — `CLAUDE_CODE_OAUTH_TOKEN`

> **Unsupported historical reference.** Agentic was shelved on 2026-08-27.
> Do not provision or persist this token for RKA Core or RKA Writer.

The RKA orchestrator daemon spawns a `claude-agent-sdk` subprocess (the Brain + Executor LLM). That subprocess needs Claude Max credentials. Inside the Docker container, the host's `~/.claude/.credentials.json` and macOS Keychain are NOT accessible — the only working auth path is a long-lived OAuth token in the env, exposed via `orchestrator/.env`.

This walkthrough is unique: the credential goes in **`orchestrator/.env`** (not a Claude Desktop MCP config), and the user mints it via the `claude` CLI on the host (NOT via the web).

## What you need

A long-lived OAuth token of the form `sk-ant-oat01-<80–200 chars>`.

## Where to get it

The user runs **on the host** (NOT inside Docker):

```bash
claude setup-token
```

This opens a browser to claude.com, prompts the user to log in (Claude Max account), and prints a long token. Long-lived (default ~1 year, refreshable). The user copies the token from the terminal.

If the user doesn't have the `claude` CLI installed:

```bash
npm install -g @anthropic-ai/claude-code
```

(Or via Homebrew: `brew install claude-code`.)

## Validation

Format: starts with `sk-ant-oat01-`, then 80–200 chars of `[A-Za-z0-9_-]`.

Regex: `^sk-ant-oat01-[A-Za-z0-9_-]{80,200}$`

If the user pastes a string that fails this regex:

- Starts with `sk-ant-api03-` instead of `sk-ant-oat01-` → they pasted an API key, not an OAuth token. API key won't trigger Claude Max billing (would charge per-token). Tell them to run `claude setup-token` instead.
- Wrong length → they may have truncated when copying. Have them re-run `claude setup-token` to display it fresh.

## Sanity check (optional)

Run a one-shot Claude API ping using the token. The token is used like an API key but the billing path is Max-subscription instead of per-token. The call also confirms the token is currently valid (not expired/revoked).

```bash
# Use a heredoc so the token doesn't appear on the command line / in shell history
KEY="$( pbpaste )"  # or have the user paste into a tmp file
curl -sS -X POST https://api.anthropic.com/v1/messages \
  -H "x-api-key: $KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-haiku-4-5","max_tokens":4,"messages":[{"role":"user","content":"hi"}]}' \
  | head -c 200
unset KEY
```

Expected: JSON with `"content"` field. 401 means the token is expired or revoked.

## Target env vars + file

Target: **`<rka-repo>/orchestrator/.env`** (line-oriented `KEY=VALUE`, NOT JSON).

```
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-<token>
```

The file is gitignored. Verify via `git check-ignore -v orchestrator/.env` — must return a `.gitignore` line.

## Refresh discipline

OAuth tokens minted via `claude setup-token` are long-lived but **do expire** (default ~1 year). If the user reports the orchestrator daemon failing auth, run them through this walkthrough again to mint a fresh token.

The daemon doesn't automatically refresh; the user has to re-mint and update `orchestrator/.env`, then `docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d --force-recreate rka-orchestrator` to pick up the new value.

## Restart instruction

```
✓ CLAUDE_CODE_OAUTH_TOKEN persisted to orchestrator/.env.

To activate, restart the orchestrator container:

  docker compose -f docker-compose.yml \
                 -f orchestrator/docker-compose.yml \
                 up -d --force-recreate rka-orchestrator

Verify via:
  curl -sf http://localhost:9713/health

Then try starting an orchestrator workflow — if auth was the
issue, it should now reach the Claude API successfully.
```

## Common pitfalls

- **Token in `claude_desktop_config.json` instead of `orchestrator/.env`** — wrong file. The Claude Desktop app reads `claude_desktop_config.json` for its own MCP servers; the orchestrator daemon (a separate process inside Docker) reads `orchestrator/.env`. Setting it in the wrong place silently fails.
- **`ANTHROPIC_API_KEY` set instead of `CLAUDE_CODE_OAUTH_TOKEN`** — API key routes to per-token billing; OAuth token routes to Max subscription. The `_RealSDKClient` in `orchestrator/orchestrator/llm_client.py` scrubs `ANTHROPIC_API_KEY` from the subprocess env specifically to prevent this misroute.
- **Token wrapped in quotes** — `.env` should have the value bare, no `""` around it. The line `CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-…"` would persist the quotes as part of the value and fail auth.
