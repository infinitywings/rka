# Using RKA from ChatGPT (Custom MCP Connector)

This guide sets up your **local** RKA MCP server as a custom connector in
ChatGPT, so ChatGPT can call RKA tools (and load the role skills) remotely —
without disturbing your existing local access from Claude Code, Claude
Desktop, or Codex.

> **Scope.** Only the MCP server is exposed. The RKA web UI stays private and
> is never tunneled. Your API keys and OAuth passphrase stay on your machine.

## How it fits together

ChatGPT custom connectors talk to an HTTPS "Server URL" and authenticate with
OAuth. RKA's MCP server is local and stdio/HTTP only, so we put a small
OAuth-protected reverse proxy in front of it and expose that over HTTPS with a
tunnel:

```
ChatGPT  ──HTTPS──▶  ngrok  ──▶  OAuth proxy (127.0.0.1:9720)  ──▶  RKA HTTP MCP (127.0.0.1:9713)  ──▶  RKA API (127.0.0.1:9712)
          OAuth              scripts/rka_mcp_oauth_proxy.py         rka mcp --transport http           docker compose
```

- **RKA API** — the Docker backend (`docker compose up -d`), health at
  `http://127.0.0.1:9712/api/health`.
- **RKA HTTP MCP** — the same MCP server you use locally, started in HTTP mode
  on port `9713`, pointed at the API. Run with `RKA_SKILL_TOOLS=1` (see below).
- **OAuth proxy** — [`scripts/rka_mcp_oauth_proxy.py`](../scripts/rka_mcp_oauth_proxy.py);
  adds OAuth metadata, dynamic client registration, and a passphrase login in
  front of `/mcp`.
- **ngrok** — provides the public HTTPS URL ChatGPT connects to.

## Tool surface ChatGPT sees

ChatGPT connectors are tool-oriented: they cannot use Claude Code plugins or
MCP prompts, and they do not call `rka_load_tools` on their own, so
`tier=deferred` tools are invisible to them. To give ChatGPT the
plugin-with-skills experience, start the HTTP MCP with **`RKA_SKILL_TOOLS=1`**,
which promotes three skill tools to always-on. ChatGPT then sees **8 tools**:

| Tool | Purpose |
| --- | --- |
| `rka_query` | 56 read operations (`args={"operation": "...", ...}`) |
| `rka_execute` | 69 write/lifecycle operations |
| `rka_describe` | Operation schema lookup (`""` → 125-operation index) |
| `rka_load_tools` | Load a deferred legacy tool by name |
| `rka_help` | Deprecated alias for `rka_describe` |
| `rka_start_session` | Load a role skill (`pi`/`brain`/`executor`/`writer`) + a session checklist |
| `rka_list_skills` | List the packaged role skill guides |
| `rka_read_skill` | Read a skill guide or one of its referenced files |

Without the flag the surface is the standard 5 dispatch tools — that is what
local stdio clients keep, so local access is unaffected either way.

## Prerequisites

- RKA installed and the Docker backend running (see [INSTALL.md](../INSTALL.md)).
- The `rka` CLI on your PATH (`uv tool install --force .` from the repo root).
- [ngrok](https://ngrok.com/download) installed and authenticated
  (`ngrok config add-authtoken <token>`).
- A ChatGPT plan that supports custom connectors / developer mode.

## Setup

### 1. Confirm the RKA API is up

```bash
curl -sS http://127.0.0.1:9712/api/health   # expect {"status":"ok",...}
```

### 2. Start the HTTP MCP on port 9713 (with skill tools on)

```bash
RKA_API_URL=http://127.0.0.1:9712 RKA_SKILL_TOOLS=1 \
  rka mcp --transport http --host 127.0.0.1 --port 9713
```

Leave it running (or run it under your process manager of choice). A `406`
from `curl http://127.0.0.1:9713/mcp` is expected — the MCP endpoint requires
the streamable-HTTP handshake, not a plain GET.

### 3. Choose an OAuth passphrase and start the proxy

Pick a strong passphrase and keep it local — do **not** commit it. Store it in
your credential vault or a shell profile, not in the repo.

```bash
export RKA_MCP_OAUTH_PASSPHRASE='<choose-a-strong-passphrase>'
RKA_MCP_UPSTREAM='http://127.0.0.1:9713/mcp' \
RKA_MCP_OAUTH_PORT=9720 \
  python3 scripts/rka_mcp_oauth_proxy.py
```

Health check:

```bash
curl -sS http://127.0.0.1:9720/healthz   # expect {"status":"ok"}
```

### 4. Expose it with ngrok

```bash
ngrok http 9720
```

Note the public host it prints (e.g. `https://<something>.ngrok.app`). Your
ChatGPT connector URL is that host with `/mcp` appended:
`https://<ngrok-host>/mcp`.

> The free ngrok host changes each restart. If you restart ngrok, update the
> connector URL in ChatGPT. Optionally set
> `RKA_MCP_PUBLIC_BASE_URL=https://<ngrok-host>` before starting the proxy so
> the OAuth metadata advertises the correct external URL.

### 5. Add the connector in ChatGPT

In ChatGPT connector settings:

- **Connection type**: Server URL
- **Server URL**: `https://<ngrok-host>/mcp`
- **Authentication**: OAuth
- Complete the OAuth flow and enter the passphrase from step 3 when prompted.

### 6. Validate from ChatGPT

```text
rka_start_session(role="pi")
rka_query(args={"operation": "list_projects"})
```

`rka_start_session` returns the role skill plus a session checklist; if you
know your project id, pass it: `rka_start_session(role="pi", project_id="prj_...")`.

## Using it

- **Start every session** with `rka_start_session(role=...)` and follow the
  returned guide. Roles: `pi` (supervision/cockpit), `brain` (strategy),
  `executor` (implementation), `writer` (manuscripts).
- **Read** with `rka_query(args={"operation": "...", "project_id": "prj_...", ...})`
  — e.g. `status`, `context`, `research_map`, `search`.
- **Write** with `rka_execute(args={"operation": "...", ...})`
  — e.g. `record_note`, `record_decision`, `create_mission`.
- **Discover operations** with `rka_describe("")` (index) or
  `rka_describe("record_decision")` (one operation's schema).
- **Read a skill's reference files** with
  `rka_read_skill(name="writer", reference="references/workflows.md")`.
  Absolute paths and `..` traversal are rejected — only files inside the
  selected skill directory are readable.

Provenance rules are the same as everywhere in RKA: decisions need
`related_journal`, missions need `motivated_by_decision`, PI notes use
`source="pi"` with `verbatim_input`, and every project-scoped call carries
`project_id`.

## Security notes

- The web UI is not exposed — keep it that way unless you deliberately change it.
- The OAuth passphrase and any API keys live only on your machine (env vars or
  the credential vault, see [CRED_VAULT.md](CRED_VAULT.md)). Never commit them.
- If a passphrase or token was ever pasted into a chat transcript, treat it as
  exposed and rotate it.
- ngrok makes the proxy reachable from the public internet while it runs; stop
  the tunnel when you are not using it.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| ChatGPT shows only 5 tools (no `rka_start_session`) | HTTP MCP started without `RKA_SKILL_TOOLS=1`, or ChatGPT cached the old tool list | Restart step 2 with the flag; then reconnect/refresh the connector so it re-fetches tools |
| Connector can't authenticate | Wrong passphrase, or proxy not running | Re-check `RKA_MCP_OAUTH_PASSPHRASE`; confirm `curl http://127.0.0.1:9720/healthz` |
| Tools call but every op errors | HTTP MCP can't reach the API | Confirm `curl http://127.0.0.1:9712/api/health`; check `RKA_API_URL` on the MCP process |
| Connector URL stopped working | ngrok restarted with a new host | Update the Server URL in ChatGPT to the new `https://<ngrok-host>/mcp` |
| Skill tools appear but the content looks outdated | The installed `rka` wheel predates recent skill edits | Reinstall (`uv tool install --force --no-cache .`) and restart the :9713 process |
