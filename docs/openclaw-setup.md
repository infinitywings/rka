# OpenClaw Setup for RKA v2.1

How to configure [OpenClaw](https://openclaw.ai) agents to use RKA as their
shared knowledge base and coordination layer.

## Prerequisites

| Component | Version | Notes |
|-----------|---------|-------|
| RKA | v2.1+ | Running via `docker compose up -d` on the host |
| OpenClaw | Latest | Installed on the same host |
| RKA MCP binary | Latest | `pipx install . --force` from the RKA repo root |
| An RKA project | — | Created via `rka_create_project` or the Web UI |

RKA must be reachable at `http://localhost:9712` (the default `RKA_API_URL`).
All OpenClaw agents share this single RKA instance.

---

## 1. Register Roles in RKA

Before configuring OpenClaw, register each agent role in the RKA knowledge base.
This creates the subscription routing that connects agents to events.

From Claude Desktop (or any MCP client):

```
rka_register_role(
  name="researcher",
  description="Researcher Brain — exploration, synthesis, hypothesis generation",
  subscriptions=["report.*", "checkpoint.created.*", "literature.*", "decision.*"],
  model="claude-opus-4-20250514",
  model_tier="opus",
  autonomy_profile={"level": "supervised", "escalation_rules": {"inspection": "always_escalate"}}
)

rka_register_role(
  name="reviewer",
  description="Reviewer Brain — independent review, contradiction detection, quality gates",
  subscriptions=["decision.*", "report.*", "claim.*"],
  model="claude-sonnet-4-20250514",
  model_tier="sonnet",
  autonomy_profile={"level": "supervised", "escalation_rules": {"inspection": "always_escalate"}}
)

rka_register_role(
  name="executor",
  description="Executor — implementation, experiments, data processing, mission execution",
  subscriptions=["mission.*", "directive.*"],
  model="claude-sonnet-4-20250514",
  model_tier="sonnet",
  autonomy_profile={"level": "supervised", "escalation_rules": {"decision": "always_escalate"}}
)
```

Confirm with `rka_list_roles()`. Note the returned `role_id` values — you will
reference them in SOUL.md templates.

---

## 2. Install RKA as an OpenClaw Skill

Package the RKA MCP server so every OpenClaw agent can access it:

```bash
openclaw skills install rka-mcp
```

Or configure manually in the skill's connection file:

```json
{
  "mcpServers": {
    "rka": {
      "command": "/path/to/rka",
      "args": ["mcp"],
      "env": {
        "RKA_API_URL": "http://localhost:9712"
      }
    }
  }
}
```

Replace `/path/to/rka` with the output of `which rka` (typically
`~/.local/bin/rka` after `pipx install`).

---

## 3. Configure OpenClaw Agents

Create or edit `~/.openclaw/openclaw.json`:

```json
{
  "agents": {
    "list": [
      {
        "id": "researcher",
        "name": "Researcher Brain",
        "workspace": "~/.openclaw/workspace-researcher",
        "model": { "primary": "anthropic/claude-opus-4-20250514" },
        "identity": { "name": "RKA Researcher" },
        "tools": {
          "allow": ["exec", "read", "write", "browser", "sessions_send"],
          "deny": []
        }
      },
      {
        "id": "reviewer",
        "name": "Reviewer Brain",
        "workspace": "~/.openclaw/workspace-reviewer",
        "model": { "primary": "anthropic/claude-sonnet-4-20250514" },
        "identity": { "name": "RKA Reviewer" },
        "tools": {
          "allow": ["read", "sessions_send"],
          "deny": ["exec", "write", "browser"]
        }
      },
      {
        "id": "executor",
        "name": "RKA Executor",
        "workspace": "~/.openclaw/workspace-executor",
        "model": { "primary": "anthropic/claude-sonnet-4-20250514" },
        "identity": { "name": "RKA Executor" },
        "tools": {
          "allow": ["exec", "read", "write", "browser", "sessions_send"],
          "deny": []
        }
      }
    ]
  }
}
```

Each agent gets an **isolated workspace** directory. This is deliberate —
agents should not share filesystem state. RKA is the shared state layer.

---

## 4. Deploy SOUL.md and HEARTBEAT.md

Copy the templates from `docs/templates/` into each agent's workspace:

```bash
# Researcher Brain
cp docs/templates/researcher-brain-SOUL.md  ~/.openclaw/workspace-researcher/SOUL.md
cp docs/templates/HEARTBEAT.md              ~/.openclaw/workspace-researcher/HEARTBEAT.md

# Reviewer Brain
cp docs/templates/reviewer-brain-SOUL.md    ~/.openclaw/workspace-reviewer/SOUL.md
cp docs/templates/HEARTBEAT.md              ~/.openclaw/workspace-reviewer/HEARTBEAT.md

# Executor
cp docs/templates/executor-SOUL.md          ~/.openclaw/workspace-executor/SOUL.md
cp docs/templates/HEARTBEAT.md              ~/.openclaw/workspace-executor/HEARTBEAT.md
```

**Edit each SOUL.md** to replace the placeholder `ROLE_ID` with the actual
role ID returned by `rka_register_role` (e.g., `agent_role_abc123`).

---

## 5. Verify the Setup

### 5a. Check RKA connectivity

From each agent's workspace, verify the MCP binary can reach RKA:

```bash
rka mcp  # Should start without errors; Ctrl-C to exit
```

### 5b. Test role binding

In any OpenClaw agent session:

```
rka_bind_role(role_id="<your_role_id>")
rka_get_events(role_id="<your_role_id>")
```

Expect: successful binding, empty event list (no events yet).

### 5c. Test event fan-out

From Claude Desktop or the Web UI, create a test mission:

```
rka_create_mission(
  title="Test mission",
  objective="Verify event routing",
  tasks=["Step 1"]
)
```

Then check the Executor's event inbox:

```
rka_get_events(role_id="<executor_role_id>")
```

If the Executor is subscribed to `mission.*`, a `mission.created` event should
appear.

---

## 6. Event Polling (HEARTBEAT.md)

OpenClaw agents use cron-based polling to check for new events. The
`HEARTBEAT.md` template (in `docs/templates/`) configures a 30-second polling
interval.

The polling cycle is:

1. `rka_get_events(role_id, status="pending")` — check for new work
2. Process each event (load context, reason, write back to RKA)
3. `rka_ack_event(event_id)` — mark each event as consumed
4. `rka_save_role_state(role_id, role_state)` — persist any new learnings

Events left unacknowledged for 72 hours are automatically expired.

---

## 7. Topology

```
┌─────────────────────────────────────────────────────┐
│  Host machine                                       │
│                                                     │
│  ┌─────────────────┐    ┌────────────────────────┐  │
│  │ Docker           │    │ OpenClaw Gateway       │  │
│  │  ├─ RKA API     │◄───│  ├─ Researcher Brain   │  │
│  │  │  :9712       │    │  ├─ Reviewer Brain     │  │
│  │  ├─ Web UI      │    │  └─ Executor           │  │
│  │  └─ Worker      │    │                        │  │
│  └─────────────────┘    └────────────────────────┘  │
│                                                     │
│  ┌─────────────────┐                                │
│  │ Claude Desktop   │──── MCP stdio ──► rka binary  │
│  │  (PI interface) │         (proxies to :9712)     │
│  └─────────────────┘                                │
└─────────────────────────────────────────────────────┘
```

- **RKA** runs in Docker. All data in the `rka-data` volume.
- **OpenClaw** agents run outside Docker on the host.
- **MCP binary** (`~/.local/bin/rka`) is a thin proxy: stdio ↔ HTTP to `:9712`.
- **Claude Desktop** connects to RKA via the same MCP binary (PI's primary interface).

---

## Cautions for Real-World Setup

1. **OpenClaw configuration format may differ.** The `openclaw.json` structure
   shown here is based on the design document. Verify against the actual
   OpenClaw documentation — field names, nesting, and skill installation
   commands may have changed.

2. **HEARTBEAT.md cron syntax is OpenClaw-specific.** The polling interval and
   cron format depend on OpenClaw's implementation. Confirm the syntax in
   OpenClaw's docs.

3. **Model IDs will change.** The `claude-opus-4-20250514` and
   `claude-sonnet-4-20250514` identifiers are examples. Use the model IDs
   current at the time of setup.

4. **Subscription patterns are fnmatch globs**, not regexes. `report.*`
   matches `report.submitted`, `report.updated`, etc. Use `*` for single-level
   wildcards.

5. **RKA must be running before agents start.** If agents poll before Docker is
   up, events will fail silently. Start RKA first: `docker compose up -d`.

6. **Per-project scoping.** All RKA tools scope to the active project. Ensure
   the correct project is set before registering roles. Roles registered in one
   project are not visible in another.

7. **The Reviewer has restricted tools** (`deny: ["exec", "write", "browser"]`).
   This is intentional — the Reviewer should only read and communicate, never
   modify code or data directly.

8. **No automatic agent restart.** If an agent crashes mid-event-processing,
   the event remains in `pending` or `processing` status. The next poll cycle
   will pick it up again (events are not lost).
