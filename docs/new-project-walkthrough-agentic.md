# Running a new project on agentic RKA — walkthrough

A concrete end-to-end guide for starting a brand-new research project on this machine using the **agentic** branch (orchestrator + Phase O onboarding + Phase B credential bootstrap + Writer skill). Assumes the install audit from 2026-05-27 succeeded — both `rka` and `rka-orchestrator-mcp` are on PATH and Claude Desktop sees them.

> **Branch context**: agentic is a permanent downstream fork that absorbs `main`'s core RKA features and adds the LangGraph orchestrator on top. They do not merge back. Phase A / D / O / B workflows below are agentic-only; the core RKA tools (`rka_*`) work on both branches.

---

## Prerequisites — verify first

Run these once before starting any new project. If any check fails, fix that before continuing.

### Daemons + binaries

```bash
# 1. Both daemons healthy
docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml ps
# Expect: rka-server, rka-worker, rka-orchestrator all "Up (healthy)"

# 2. REST endpoints respond
curl -fsS http://localhost:9712/api/health     # rka
curl -fsS http://localhost:9713/health         # orchestrator

# 3. MCP binaries reachable
ls -la ~/.local/bin/rka ~/.local/bin/rka-orchestrator-mcp \
       ~/.local/bin/rka-writer-tools ~/.local/bin/zotero-mcp ~/.local/bin/nano-pdf

# 4. Claude Desktop sees all MCP servers
# Open Claude Desktop -> Settings -> MCP -> verify these are green:
#   rka, rka-orchestrator, paper-search, zotero
```

### Required global API keys (set once per machine, used by every project)

These keys live in two places — Claude Desktop config's `env` blocks (read by MCP binaries) AND `orchestrator/.env` (read by the orchestrator container):

| Key | Used by | How to get one |
|---|---|---|
| **SEMANTIC_SCHOLAR_API_KEY** | `rka` MCP, `paper-search` MCP, orchestrator | Apply at https://www.semanticscholar.org/product/api#api-key-form — free, ~3 day approval. Without it, S2 throttles you to 1 request per 5 minutes. |
| **ZOTERO_API_KEY** + **ZOTERO_LIBRARY_ID** | `zotero` MCP, orchestrator | Generate a "Save to Server" + "Full library access" key at https://www.zotero.org/settings/keys. Library ID is the 7-digit userID shown on the same page. |
| **CLAUDE_CODE_OAUTH_TOKEN** | orchestrator daemon (Claude SDK subprocess) | Run `claude setup-token` on the host. Required for Phase O/D Brain reasoning. |
| **PAPER_SEARCH_MCP_UNPAYWALL_EMAIL** | `paper-search` MCP | Any institutional email (used for rate-limit identification, not authentication). |

Optional but recommended:
| Key | Purpose |
|---|---|
| `SERPAPI_KEY` | Web search fallback when curated catalogs miss something |
| `PAPER_SEARCH_MCP_CORE_API_KEY` | Full-text open-access search via CORE |

### Required local apps

- **Zotero desktop** (`brew install --cask zotero`) — runs in the background, syncs your library to the Zotero cloud
- **Zotero Connector browser extension** (https://www.zotero.org/download/connectors) — one-click capture of papers from any publisher site you're authenticated to via your institution
- **Docker Desktop** — for the rka + orchestrator daemons

If you've never run **Phase B** on this machine, do it now (see section 1 below). Phase B writes `orchestrator/.env` so the orchestrator can call Claude at all.

---

## The flow at a glance

A new project moves through up to seven phases. Steps 1-5 happen in Claude Desktop driven by the `rka-orchestrator-pi` skill; step 6 is the actual research work; step 7 is optional.

```
1. Bootstrap (Phase B)    one-time per machine — orchestrator/.env
              ↓
2. Create RKA project     one rka_create_project() call
              ↓
3. Onboard (Phase O)      capture idea → polished idea → ratify → workspace path →
                          (orchestrator auto-creates Zotero collection here) →
                          deep research → hygiene → claim extraction → plan →
                          ratified plan + auto-created missions → Phase-H entry
              ↓
4. Literature ingestion   ongoing — PI captures papers via Zotero Connector
   via Zotero             into the project's collection; AI reads full text
              ↓
5. Per-project tools      Phase D registers per-project credentials in the
   (Phase D, optional)    orchestrator store (sec-edgar key, FRED, WRDS, etc.)
              ↓
6. Execute missions       Phase A mission graph: Brain ⇄ Executor ⇄ PI loops
              ↓
7. Draft a manuscript     /rka-start-manuscript with venue + CFP URL
   (Writer skill, optional)
```

Each gate that needs your approval **parks an interrupt** in `orchestrator_inbox()`. You drive it via Claude Desktop using the orchestrator-pi skill, which renders the prompt + offers accept/reject/correct. Interrupts are durable — you can walk away for days and resume.

---

## 1. (One-time) Bootstrap — orchestrator credentials

Skip this if you've already filled `orchestrator/.env` with at least one Claude credential. Run it on a fresh install OR when switching from API key to OAuth.

**In Claude Desktop**, type:

```
/orchestrator-bootstrap
```

Claude will:

1. Verify `orchestrator_health()`.
2. Call `orchestrator_bootstrap_start()` — parks at `pi_bootstrap_intent`.
3. Render the intent prompt — describe your install state in one sentence:
   - *"fresh install, I have Claude Max"* → picks claude-oauth
   - *"I want everything including SerpAPI"* → picks all 5 catalog entries
   - *"minimal"* → just claude-oauth + anthropic-api-key (the required group) + semantic-scholar (recommended)
4. After you respond, the daemon runs `bootstrap_propose` → parks at `pi_bootstrap_ratify` with the shortlist.
5. **TWO-TAP gate**: Claude shows you the candidate list (label / env_var / criticality / sign-up URL). You explicitly accept or correct. Claude will not auto-accept.
6. On accept, `bootstrap_emit_template` writes `orchestrator/.env.example`. Claude points you at the file and lists the env vars to fill.
7. **Edit the file out of band**:
   ```bash
   $EDITOR /Volumes/base/workspace/rka/orchestrator/.env
   ```
   Paste each value next to its `<paste-here>` slot. **Never paste keys into the chat.** For `CLAUDE_CODE_OAUTH_TOKEN`, mint one with `claude setup-token` on the host.
8. Tell Claude "done" — it calls `orchestrator_accept(interrupt_id)` for the `pi_bootstrap_fill_ack` interrupt.
9. `bootstrap_verify` probes each filled key without logging values; Claude renders the pass/fail report.
10. Recreate the orchestrator container so it picks up the new env:
    ```bash
    docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml \
                   up -d --force-recreate rka-orchestrator
    ```

**Security invariant**: key values never appear in interrupt payloads, logs, or verify reports. Probe details contain only `env_var` + classification + a non-secret reason.

---

## 2. Create the RKA project

The orchestrator does **not** create projects — that's an upstream `rka_create_project()` call. Do this in Claude Desktop:

```
Create a new RKA project called "ML-systems-eval" with the description
"Evaluation framework for ML systems benchmarks across MLPerf/MLSys 2026."
```

Claude will:
1. Call `rka_create_project(name=..., description=...)`.
2. Return the new project id (looks like `prj_01KS...`).
3. (Optional) `rka_set_project(id)` so subsequent calls are auto-scoped.

Copy the `prj_…` id — you'll use it for steps 3 + 4.

---

## 3. Onboard the project (Phase O)

This is the big one. Phase O walks you through capturing the idea, polishing it, defining scope, queuing literature ingestion, extracting claims, synthesizing a research plan, and auto-creating the milestone mission queue. **8-12 PI interrupts** depending on path. Plan ~30-60 minutes of focused attention OR spread it across multiple sittings (the workflow parks durably between gates).

**In Claude Desktop**:

```
/orchestrator-onboard prj_01KS…YOUR_ID
```

Or for the full Phase O surface (vs. just per-project tool setup, which Phase D handles separately):

```
Start Phase O for prj_01KS…YOUR_ID
```

The skill loads automatically. Here's what to expect at each gate:

### O1.1 — pi_idea_capture (free-form input)

Claude asks: *"Describe the project — research question, motivation, anything I should know."*

Type the description in plain prose (1-3 paragraphs). You can also ingest source material BEFORE responding:
```
rka_add_note(body="<paper title + key claims>", tags=["ingested-source", "prj_..."], actor="pi", source="pi", verbatim_input="...")
```
The PI's response text becomes seed material for **O1.2 idea_polish** — the Brain extracts a structured PolishedIdea (research_question, motivation, scope, novelty_hypothesis, target_venue).

### O1.3 — pi_scope_ratify (TWO-TAP)

Claude renders the PolishedIdea as markdown sections. **Read carefully** — the Brain's polish is the contract. If it captured your intent correctly, accept. Otherwise:

- **Reject**: workflow ends; restart Phase O later
- **Correct**: provide a redirect ("the scope should exclude X; tighten the novelty hypothesis to Y") — Brain re-polishes

**TWO-TAP**: Claude will not auto-accept. It shows you the polished idea, you explicitly accept, then it calls `orchestrator_accept(id)`.

### O2.1 — workspace_setup (background)

Creates `~/rka-workspaces/<project_slug>/` with `.rka/` scaffolding. No interrupt.

### O2.2 — pi_deepresearch_prompt (async-pause)

Claude renders a prompt designed for OpenAI Deep Research / Claude Research mode. **You run the literature search OUT OF BAND** (a different Claude session, OpenAI Deep Research, Google Scholar, manual reading — your choice) and ingest the results via `rka_add_literature()` + `rka_enrich_doi(id)` calls.

When you're done — could be minutes or days later — respond:

```
I've ingested the literature. Accept the deepresearch interrupt.
```

The interrupt is replayable; the orchestrator picks up where it left off.

### O3.1 — hygiene_pass (background)

Brain sweeps the workspace via `rka_check_integrity()`, `rka_check_freshness()`, `rka_get_pending_maintenance()`. Surfaces stale or contradictory entries. No interrupt — just a journal write summarizing what was found.

### O3.2 — pi_claims_review (TWO-TAP)

Brain extracts atomic claims from your ingested sources. Claude renders the claims table. **TWO-TAP**: accept to lock the set as inputs for plan synthesis. Reject to re-run with a redirect.

### O4.1 — plan_synthesis (background)

Brain composes a structured `ResearchPlan` (milestones, dependencies, variables, mission specs). No interrupt.

### O4.2 — pi_plan_ratify (TWO-TAP — the contract gate)

This is the **plan-licensing contract gate**. Claude shows you the full ResearchPlan. On accept:

1. A `dec_…` decision is recorded (with `related_journal` provenance to the synthesis journal).
2. A `jrn_…` journal entry containing the plan JSON is recorded.
3. **Missions are auto-created** — one `mis_…` per milestone, all with `motivated_by_decision` pointing at the dec above. The topological sort respects `depends_on`.

Reject ends the workflow cleanly; the workspace is preserved.

### Phase H — pi_phase_entry_ack (per-milestone)

Before each mission dispatches, Phase H parks a `pi_phase_entry_ack` interrupt. You approve dispatch of milestone N or reject (defer the milestone). Repeat for each milestone.

When the last `pi_phase_entry_ack` accepts, Phase O exits cleanly. Your project now has:
- A polished idea + ratified plan in RKA
- A mission queue ready to execute
- A workspace at `~/rka-workspaces/<slug>/`

---

## 4. Literature ingestion via Zotero (per project, ongoing)

Each project gets its own **Zotero collection** auto-created during onboarding (Phase O step O1). The collection name matches your workspace folder's basename. The orchestrator records `(project_id → zotero_collection_key)` in its store; query it with `orchestrator_get_zotero_collection(project_id)`.

The workflow:

1. **Search for relevant papers** using any source (paper-search-mcp, Google Scholar, arXiv, journal sites)
2. **Open the paper's URL in your browser** while authenticated to your institution (SSO/EZproxy)
3. **Click the Zotero Connector icon** in your browser — it captures metadata + downloads the PDF using your authenticated session, then saves it to your library
4. **Move (or initially save) the paper into the project's collection** in Zotero (drag-and-drop, or the Connector's "Choose collection" dropdown)
5. **Tell Brain or Executor**: "Read [paper title] from this project's Zotero collection and extract claims"

What the AI does:
- `orchestrator_get_zotero_collection(project_id)` → gets the collection key
- `zotero_search(query="<title>")` filtered to that collection → finds the item
- `zotero_get_fulltext(item_key=...)` → reads the full PDF text
- Extracts claims grounded in direct quotes (confidence 0.7-0.9 instead of abstract-level 0.5-0.65)

**Why this matters**: Claims extracted from abstracts cap at 0.65 confidence by Brain's rules. Full-text claims with quoted evidence can reach 0.8+. For any paper that's central to your argument, you want the full text in Zotero.

When the AI needs a paper that isn't in the collection, it will emit a checkpoint asking you to capture it — you'll see something like:

> "I need full text of [Smith, 2024, 'Hidden Leverage in Cloud Contracts']. Please open the paper in your browser, save it via Zotero Connector into the **hyperscaler-auditing** collection, and tell me 'ready'."

---

## 5. (Optional) Wire per-project tools (Phase D)

Phase D is for tools that need **per-project credentials**: HuggingFace token for a specific gated dataset, SEC EDGAR user-agent for finance projects, NCBI key for bioinformatics, etc. Different from Phase B which is daemon-level.

Skip this if your project doesn't need per-project tooling beyond the always-on baseline (rka, context7, filesystem, git).

**In Claude Desktop**:

```
/orchestrator-onboard prj_01KS…YOUR_ID
```

(Same slash command — it dispatches to Phase D if Phase O already completed for this project.) The flow:

1. **pi_onboarding_topic** — describe the project's domain (Claude reads `proposed_idea` from RKA if Phase O ran)
2. **research_toolkit_node** (background) — Brain consults `orchestrator/data/tool_registry.yaml` + scores candidates against your domain
3. **pi_toolkit_ratify** (TWO-TAP) — accept the shortlist
4. **draft_manifest_node** (background) — writes `~/rka-projects/<id>/tools.json` + `.env` template
5. **pi_credentials_ready** (replayable) — edit `~/rka-projects/<id>/.env`, accept when done
6. **finalize_node** (background) — `probe_all_secrets` verifies each key; emits audit journal entry

After Phase D, the project has a `tools.json` baseline manifest the mission graph reads.

---

## 6. Execute missions

For each mission Phase O auto-created (or any mission you create later with `rka_create_mission`), you launch the Phase A mission graph:

**In Claude Desktop**:

```
/orchestrator-start mis_01KS…
```

Or, equivalently:
```
orchestrator_run_start(mission_id="mis_…", project_id="prj_…", budget_usd=10)
```

This kicks off the **16-node mission graph** (Brain ⇄ Executor ⇄ PI loops). Three PI gates:

| Gate | Stakes | Pattern |
|---|---|---|
| **pi_greenlight** | Confirmation Brief approval before execution starts | Single tap (approve / reject) |
| **pi_decision_select** | Choose between Brain-drafted decision options | TWO-TAP (set-identity: ratified_actions copied iff accept) |
| **pi_acceptance** | Final mission review + report acceptance | Single tap |

Monitor in-flight runs:
```
orchestrator_list_runs(status="running")       # all active
orchestrator_inbox()                            # all parked interrupts
orchestrator_get_run("thr_…")                   # one run's state
orchestrator_cancel("thr_…")                    # kill it
```

When a mission completes, its `rep_…` report is recorded with `motivated_by_decision` chained back to the ratified plan.

### Pattern: replayable interrupts

You don't have to be at the keyboard when an interrupt parks. Walk away. Come back tomorrow. Open Claude Desktop, type:

```
/orchestrator-inbox
```

It lists every parked interrupt across every run with the parked time. Drive each in turn. The SqliteSaver durability is intentional — long-running missions with PI ratification gates are the killer feature of the orchestrator.

---

## 7. (Optional) Draft a manuscript with the Writer skill

The Writer skill (W1-W4) ships 58 curated venues + NSF proposal templates + a CFP-overlay system. Bootstrap a workspace:

```
/rka-start-manuscript --project-id prj_01KS… \
                      --venue NeurIPS \
                      --title "Your paper title" \
                      --cfp-url https://neurips.cc/Conferences/2025/CallForPapers
```

This:
1. Creates a workspace at `~/rka-workspaces/<slug>/manuscripts/<title-slug>/` from `rka/skills/writer/workspace-template/`
2. Substitutes placeholders in `manuscript.yaml` (venue_id, project_id, title, cfp_url)
3. If `--cfp-url` is given: runs `cfp_loader.py fetch` against the URL → emits a draft `cfp_overrides.yaml` with detected page limit / anonymization / abstract cap / etc., all marked `review_required:`

After drafting, run the layout audit:
```bash
python rka/skills/writer/scripts/layout_audit.py \
       --manuscript-yaml ~/rka-workspaces/<slug>/manuscripts/<title-slug>/manuscript.yaml
```

The audit reads the page limit from **three layers** (most-specific wins): `manuscript.yaml -> overrides` → `cfp_overrides.yaml` → `venue.yaml` baseline.

Supported venues (W1-W4):
- **CS conferences**: NeurIPS, ICML, ICLR, AAAI, IJCAI, KDD, CVPR, ICCV, ECCV, ACL, ACL-Short, NAACL, EMNLP, EMNLP-Short, SOSP, OSDI, ASPLOS, ISCA, MICRO, PLDI, POPL, OOPSLA, SIGCOMM, NSDI, CCS, NDSS, IEEE-SP, USENIX, UIST, CSCW, CHI, IUI, SIGIR, WWW
- **CS journals**: TPAMI, TOPLAS, TOCS, TON, JACM, CACM
- **FT50 (acct/fin/mgmt)**: JAR, JAE, TAR, RAST, CAR, JF, JFE, RFS, JFQA, AMJ, AMR, ASQ, JOM, MS, OS, SMJ
- **General**: Nature
- **Proposals**: NSF-PAPPG, NSF-CAREER

Missing your venue? Add a `<venue>.yaml` under `rka/skills/writer/references/venue/` following any existing file as a template — each is ~30 lines.

---

## The PI inbox pattern (drive interrupts in chat)

Every interrupt has the same lifecycle. Three responses are valid:

| Response | When | Effect |
|---|---|---|
| **accept** | The interrupt's question is satisfied as posed | Graph routes to the "accept" branch |
| **reject** | Something is fundamentally wrong; end the workflow | Graph routes to END; state preserved for inspection |
| **correct** | The question is close but needs adjustment | Free-text response replaces the response token; graph re-runs from the corrected state |

The orchestrator-pi skill enforces **TWO-TAP** on privileged gates (pi_decision_select, pi_scope_ratify, pi_claims_review, pi_plan_ratify, pi_toolkit_ratify, pi_bootstrap_ratify). At a TWO-TAP gate, Claude:

1. Renders the proposal in markdown.
2. **Does NOT** call `orchestrator_accept()` automatically.
3. Asks you to confirm explicitly.
4. On your confirm, calls `orchestrator_accept(interrupt_id)`.

This prevents a runaway accept on a misread proposal.

**PI provenance discipline**: when recording your input via `rka_*` calls, always use:
```python
source="pi"
verbatim_input="<your exact wording>"
```
Brain reads `verbatim_input` for replay; the rest of the body is paraphrased context. The schema enforces this at the DB layer.

---

## Recovery — common issues

### "orchestrator_health 500"
The daemon is down. Bring it up:
```bash
docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d
```

### "ANTHROPIC_API_KEY is set in env (would route to API billing)"
Phase B detected an API key alongside the OAuth token. The OAuth path is preferred; the API key gets scrubbed from the subprocess env (see `llm_client._verify_claude_max_routing`). Not an error — just informational.

### Mission graph errored mid-flight
```
orchestrator_get_run("thr_…")    # see last_error + current_node
orchestrator_cancel("thr_…")     # mark cancelled
rka_get_journal(tags=["thr_…"])  # see what got written before the failure
```
Then re-run with a corrected mission spec.

### "Phase B verify shows ✗ rejected on Anthropic API key"
The key was filled but the endpoint rejected it. Mint a new key at the sign-up URL the catalog provided, re-run `/orchestrator-bootstrap`. The .env.example is preserved on disk for re-entry.

### "I want to wipe and start over"
The orchestrator's SQLite lives at `/data/orchestrator.db` inside the container (Docker volume `rka-data`). To reset:
```bash
docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml down
docker volume rm rka_rka-data       # WARNING: wipes ALL RKA data
docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d
```
Almost never the right call — usually `cancel` + re-launch is better.

### Auto-mode push-to-main is blocked
When the Executor runs in auto-mode (no per-tool-call confirmation), direct `git push origin main` requires explicit PI authorization in the transcript. Say "push to main" or "go ahead and push to main" to unblock. One-shot per push.

---

## Cheat sheet

### Slash commands (Claude Desktop)
| Command | Purpose |
|---|---|
| `/orchestrator-bootstrap` | Phase B — orchestrator-level credentials |
| `/orchestrator-onboard prj_…` | Phase O (new project) or Phase D (existing project, tools) |
| `/orchestrator-start mis_…` | Launch a mission |
| `/orchestrator-status` | List active runs |
| `/orchestrator-inbox` | Render all parked interrupts |
| `/orchestrator-manifest prj_…` | Dump a project's effective manifest |
| `/rka-status` | RKA project status + blockers |
| `/rka-pending` | Provenance gaps + stale knowledge |
| `/rka-search <q>` | Search the knowledge base |
| `/rka-set-project prj_…` | Switch active project |
| `/rka-start-manuscript --venue X --title Y` | Bootstrap a writer workspace |

### Key MCP tool families
| Prefix | Server | Use |
|---|---|---|
| `rka_*` (90 tools) | rka @ 9712 | Database — notes, decisions, missions, claims, literature, search, workspace tree/scan/ingest |
| `orchestrator_*` (14 tools) | orchestrator @ 9713 | Workflow control — start, inbox, accept/reject/correct, bootstrap, onboard, get_manifest, get_zotero_collection |
| `zotero_*` | zotero-mcp (host stdio) | Search your Zotero library, read full-text PDFs, filter by collection_key |
| `search_papers`, `download_*` | paper-search (uvx) | Multi-source academic search (arXiv, PubMed, bioRxiv, Google Scholar, Unpaywall, CORE) |
| `writer_*` (via rka-writer-tools, optional) | local stdio | Literature search backends (S2, OpenAlex, arXiv, Crossref, SerpAPI) |

### Key file paths
| Path | What |
|---|---|
| `orchestrator/.env` | Daemon-level credentials (Phase B writes here) |
| `~/rka-projects/<id>/.env` | Per-project credentials (Phase D writes here) |
| `~/rka-projects/<id>/tools.json` | Per-project tool manifest |
| `~/rka-workspaces/<slug>/` | Per-project work directory (Phase O creates) |
| `rka/skills/writer/references/venue/<id>.yaml` | Venue spec (Writer skill) |
| Docker volume `rka_rka-data` | RKA SQLite + embeddings + orchestrator DB |
| `/Users/ceron/.local/bin/rka` | rka MCP binary (proxies to localhost:9712) |
| `/Users/ceron/.local/bin/rka-orchestrator-mcp` | orchestrator MCP binary (proxies to 9713) |

### Re-installing after orchestrator code changes
```bash
# Purge AppleDouble files first (external-volume quirk; see CLAUDE.md)
find . -maxdepth 2 -name '._*' -not -path './.git/*' -delete

# Reinstall the orchestrator MCP binary
rm -rf /tmp/rka-orch-build && cp -R orchestrator /tmp/rka-orch-build
find /tmp/rka-orch-build -name '._*' -delete
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force /tmp/rka-orch-build

# Rebuild + recreate the docker stack
docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml \
               up -d --build --force-recreate

# Restart Claude Desktop (Cmd+Q + relaunch) so it re-launches MCP servers
```

### Re-installing after rka core code changes
```bash
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .
docker compose up -d --build --force-recreate    # restart rka-server + rka-worker
# Restart Claude Desktop
```

---

## When to use what — quick decision tree

```
Starting fresh on this machine?
  → /orchestrator-bootstrap  (one-time)

New research idea, no project yet?
  → rka_create_project(...)
  → /orchestrator-onboard <new-prj-id>   (Phase O)

Existing project, need to wire per-project tools?
  → /orchestrator-onboard <prj-id>       (Phase D)

Mission ready to run?
  → /orchestrator-start <mis-id>

Need to read a paper that's behind a paywall?
  → Open it in your browser (institutional SSO) → click Zotero Connector
  → Save into the project's collection → ask AI to read it

Need to draft a manuscript?
  → /rka-start-manuscript --venue X --title Y

Don't know what's waiting?
  → /orchestrator-inbox  +  /rka-pending

Catastrophic disagreement with an interrupt?
  → orchestrator_reject(id, reason="...")
  → restart from the parent phase

Want to see what got recorded recently?
  → rka_get_journal(limit=20)
  → rka_get_research_map()
```
