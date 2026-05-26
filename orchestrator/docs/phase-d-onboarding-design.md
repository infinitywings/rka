# Phase D — Onboarding wizard (design)

Status: **design only**. Implementation deferred to a future session.

## Goal

Before any Brain⇄Executor⇄PI mission runs in a new project, the PI should be guided through a one-time onboarding flow that:

1. Discusses the project's topic, field, target venue with the PI.
2. Searches (via SerpAPI + Brain's training knowledge) for widely-accepted tools (MCP servers, plugins, skills) that fit the project's domain.
3. Suggests a candidate toolkit, awaits PI ratification.
4. Writes a per-project workspace manifest (`tools.json`) and a credentials template (`.env`).
5. Guides the PI through credential collection via file edits + server-side probe validation.
6. Registers the finalized manifest so subsequent missions' subprocess SDK config exposes the right tools.

Empirical driver: the IoT-edge-LLM live test surfaced that the orchestrator's tool surface is hardcoded (rka + context7). A *finance research* project would benefit from `sec-edgar-mcp`; a *bioinformatics* project from `ncbi-mcp`; a *legal-research* project from `westlaw-mcp`. Per-project tool affordance is the natural place for this.

## PI-ratified design choices (from this session)

| Question | Choice |
|---|---|
| Where do artifacts live? | Per-project files at `~/rka-projects/{project_id}/{tools.json, .env}` |
| Tool discovery method | Web search via SerpAPI + Brain's training knowledge |
| Credentials UX | Server writes template; PI edits the file; server probes each API to validate |
| Actuator (#6) in scope? | No — separate later |
| Q1 — Onboarding lifecycle | **Hybrid**: baseline manifest is frozen after initial onboarding; missions may request extension tools mid-stream via `pi_extend_toolkit` interrupt. Each ratified write records the active tool-set version (baseline hash + extensions) so reproduction can recreate the exact tool surface. |
| Q2 — Missing-credential handling | **Criticality-aware**. Each secret declares `criticality: required \| recommended \| optional`. `required` missing → escalate via checkpoint (PI must provide or downgrade); `recommended` → escalate once at session start; `optional` → skip with journal note. Brain proposes tier during `research_toolkit_node`; PI ratifies. |
| Q3 — Curated registry | **Yes, small (~10-15 entries)**. Ship `orchestrator/data/tool_registry.yaml` with canonical always-on (rka, context7, fs-mcp, git-mcp) + domain shortlists (finance: sec-edgar; bio: ncbi; legal: westlaw; ml-systems: hf, wandb). Brain consults registry FIRST (high-confidence priors), then web-searches for gaps. |
| Q4 — Auth patterns supported | **API key only in Phase D MVP** (~80% of MCP servers). Manifest schema designed extensibly (`auth_type: "api_key"` initially; `oauth_token`, `oauth_browser`, `keychain`, `service_account` added in Phase D2). |
| Q5 — Onboarding audit in RKA | **Yes — summary journal entry with manifest hash**. One-paragraph summary entry (`source=system`, `tags=[orchestrator, onboarding, baseline]`) referencing the manifest file path + sha256. Extensions trigger new entries with `supersedes` linkage. File remains the source of truth for execution; journal entry is the audit snapshot. |

## Subgraph topology

```
START
  → onboarding_intro_node       (Brain: load project metadata + prompt PI for topic/field/venue)
  → pi_topic_response           (PI interrupt: free-form description; up to 3 questions)
  → research_toolkit_node       (Brain: web-search + curated-knowledge → candidate tool list)
  → pi_toolkit_ratify           (PI interrupt: multi-select pick + add-custom; TWO-TAP for tools requiring secrets)
  → draft_manifest_node         (Brain: produces tools.json + .env template; writes to workspace)
  → pi_credentials_node         (PI interrupt: server tells PI which file to edit, probes when PI confirms ready)
  → finalize_node               (Brain: validates the full manifest, registers with orchestrator config)
  → END
```

**Distinct interrupt types** (not the 3 mission interrupts):
- `pi_onboarding_topic` (free-form input)
- `pi_toolkit_ratify` (multi-select with confidence scoring + TWO-TAP for credentialed tools)
- `pi_credentials_ready` (single-tap "I've edited the file" gate)

These need:
- Schema added to `parked_store.py` (the `interrupt_type` CHECK constraint must allow the new values; consider a separate table or column?).
- New skill rendering rules in `orchestrator-pi/SKILL.md` for each.
- Server endpoints similar to `/inbox/{id}/accept|reject|correct`.

## Artifacts produced

### `~/rka-projects/{project_id}/tools.json`

```jsonc
{
  "$schema": "https://example.org/rka/orchestrator-tools.v1.json",
  "project_id": "prj_01...",
  "created_at": "2026-05-26T17:00:00Z",
  "topic": {
    "summary": "IoT edge LLM hosting for smart-home intent handling",
    "field": "systems / on-device ML",
    "venue": "MLSys 2026"
  },
  "tools": [
    {
      "name": "rka",
      "type": "mcp_stdio",
      "command": "rka",
      "args": ["mcp"],
      "always_on": true,
      "secrets": []
    },
    {
      "name": "context7",
      "type": "mcp_stdio",
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp@latest"],
      "secrets": []
    },
    {
      "name": "sec-edgar",
      "type": "mcp_stdio",
      "command": "npx",
      "args": ["-y", "@sec-edgar/mcp-server@latest"],
      "secrets": [
        { "name": "SEC_EDGAR_API_KEY", "probe": "https://api.sec.gov/edgar/health" }
      ]
    }
  ],
  "skills": [
    { "name": "finance-paper-style", "source": "local:plugin/skills/finance/" }
  ]
}
```

### `~/rka-projects/{project_id}/.env`

```bash
# Generated by orchestrator-onboarding at <ISO>
# File mode 0600. NEVER commit to source control.

# sec-edgar-mcp
SEC_EDGAR_API_KEY=<paste-here>

# Other tools added during onboarding land below.
```

### orchestrator daemon config side

The runner's `_build_mcp_servers_config` should be refactored to:
1. Look up the project's `tools.json` at run start
2. Iterate `tools[*]` and add each to the subprocess `mcp_servers` dict
3. Source secrets from the project's `.env` (the env_file passthrough in docker-compose still applies)

```python
# Sketch:
def _build_mcp_servers_config(rka_binary, project_id=None):
    config = {}
    manifest = _load_project_manifest(project_id)
    for tool in manifest.tools:
        if tool.type == "mcp_stdio":
            config[tool.name] = {
                "type": "stdio",
                "command": tool.command,
                "args": tool.args,
                "env": _resolve_secrets(tool.secrets, project_id),
            }
    return config
```

## Web-search tool discovery

The `research_toolkit_node` uses two sources:

1. **SerpAPI** (existing, key in `orchestrator/.env`):
   - Queries like `"site:github.com mcp-server {field}"`, `"awesome MCP servers {field}"`, `"{venue} tools {topic}"`
   - Filter for >100 stars, last commit ≤6 mo, recognizable orgs

2. **Brain's training knowledge**:
   - Brain already knows the major MCP ecosystem (context7, mcp-fs, mcp-git, etc.)
   - Combines this with the search results for ranking

Output to PI is a structured candidate list with confidence scoring:

```
| Tool | Type | Source | Confidence | Why |
|---|---|---|---|---|
| sec-edgar-mcp | MCP server | npm | HIGH | Official SEC EDGAR API wrapper, 800+ stars, active |
| finbert-mcp | MCP server | npm | MEDIUM | Sentiment analysis on filings; 150 stars, useful but new |
| westlaw-mcp | MCP server | github | LOW | Legal research; depends on Westlaw subscription |
```

PI picks via `AskUserQuestion` (multi-select).

## Credential collection UX

After PI ratifies the toolkit, the daemon:
1. Writes the `.env` template with placeholder values.
2. Parks a `pi_credentials_ready` interrupt with:
   - File path: `~/rka-projects/{project_id}/.env`
   - List of expected keys: `["SEC_EDGAR_API_KEY", "OPENAI_API_KEY", ...]`
   - Instruction: "Edit the file (file-mode 0600), save, then accept this interrupt."
3. On accept, the server reads the file and probes each tool's `secrets[*].probe` URL with the secret as auth.
4. Records pass/fail per key. Successful keys are marked verified in the manifest.
5. Failed keys re-prompt: "SEC_EDGAR_API_KEY rejected (401). Re-edit and accept again, or skip this tool."

**Security invariants:**
- Token values never appear in any RKA journal entry.
- Token values never appear in the orchestrator daemon's logs.
- Token values never appear in the Claude Code transcript (the PI's assistant only sees key names + validation results).
- The `.env` file is `chmod 600` on creation.
- The `~/rka-projects/{project_id}/` directory has perms `0700`.

## Build order (recommended) — updated for ratified answers

1. **D1** — schema work (~0.75 day)
   - parked_store extension for new interrupt types: `pi_onboarding_topic`, `pi_toolkit_ratify`, `pi_credentials_ready`, `pi_extend_toolkit`
   - Manifest schema (`tools.json`) with `manifest_version`, `supersedes`, criticality, auth_type
   - Initial seed of `orchestrator/data/tool_registry.yaml` (~10-15 entries)
2. **D2** — per-project workspace dir creation + manifest read/write (~1 day)
   - `~/rka-projects/{project_id}/` with mode 0700; `.env` with mode 0600
   - Manifest hash computation + supersedes chain logic for Q1's hybrid lifecycle
3. **D3** — `research_toolkit_node` (~1.5 days)
   - Registry consultation first
   - SerpAPI augmentation for gaps
   - Confidence scoring + Brain proposes criticality tier per Q2
4. **D4** — credential UX (~1.25 days)
   - `pi_credentials_ready` interrupt
   - Probe validation per secret (HTTP HEAD/GET with `probe_url` + `probe_header`)
   - Criticality-aware behavior on missing/failed probes (Q2)
5. **D5** — onboarding subgraph wiring + new MCP tools (~1 day)
   - New tools: `orchestrator_onboard_start`, `orchestrator_get_manifest`, `orchestrator_extend_toolkit`
   - Manifest-driven `_build_mcp_servers_config` refactor
6. **D6** — `pi_extend_toolkit` mid-stream extensions (Q1 hybrid) (~0.5 day)
   - Mini-onboarding for a single added tool
   - Per-mission extension manifest layered on the baseline
7. **D7** — audit-entry integration (~0.25 day)
   - `rka_add_note` call at onboarding completion with manifest hash (Q5)
   - `supersedes` linkage for extensions
8. **D8** — skill update + integration tests + live test with one credentialed tool (~1 day)
   - Update `plugin/skills/orchestrator-pi/SKILL.md` with onboarding rendering rules
   - Synthesized integration tests for the 4 new interrupt types

Total: ~7.25 days of implementation work (was ~5-6 before ratification expanded scope on Q1+Q2+Q3+Q5).

## ~~Open design questions for next session~~ → All resolved (this session)

All five questions were tackled and PI-ratified — see the choices table at the top of this document for the bound decisions. The implementation can proceed without further design review.

### Concrete impact of the ratified answers on the build

**Q1 (hybrid lifecycle)** changes the manifest schema:

```jsonc
{
  "project_id": "prj_01...",
  "manifest_version": "baseline_v1",       // baseline | extension_v2 | ...
  "supersedes": null,                      // or a previous manifest hash for extensions
  "tools": [ ... ],
  // ...
}
```

And adds a new interrupt type `pi_extend_toolkit` (used by missions that discover they need a new tool mid-stream).

**Q2 (criticality)** changes the per-secret schema:

```jsonc
"secrets": [
  {
    "name": "SEC_EDGAR_API_KEY",
    "auth_type": "api_key",
    "criticality": "required",           // required | recommended | optional
    "probe_url": "https://...",
    "probe_header": "X-API-Key"
  }
]
```

And adds dispatcher logic: at session start, check all required+recommended secrets are present and probed; escalate accordingly.

**Q3 (small registry)** adds a new data file:

```
orchestrator/data/tool_registry.yaml
```

Seeded with ~10-15 entries. Loaded at `research_toolkit_node` startup; results combine with SerpAPI results before being scored and presented to PI.

**Q4 (api_key only MVP)** simplifies the credential UX to a single flow (paste-into-`.env` + probe). The `auth_type` field is in the schema from day one so future patterns can land without breaking changes.

**Q5 (audit entry)** adds one call at onboarding completion:

```python
mcp.rka_add_note(
    content=summary_text,
    source="system",
    type="note",
    tags=["orchestrator", "onboarding", "baseline"],
    related_decisions=[onboarding_decision_id],
)
```

And for extensions, the new entry's `supersedes` field points to the previous baseline's journal id.

## Cross-cutting impact

Phase D affects (will need re-work):
- `_build_mcp_servers_config` in `llm_client.py` — read manifest instead of hardcoded servers
- `_default_mcp_factory` in `server.py` — pass project_id through to the config builder
- Existing `parked_interrupts.interrupt_type` CHECK constraint — extend with onboarding types OR introduce a parallel onboarding table

Phase D does NOT depend on (orthogonal):
- Phase E (capability categories) — though E builds on D's manifest for category derivation
- Phase F (topology variants) — independent
- Phase G (actuator) — independent
