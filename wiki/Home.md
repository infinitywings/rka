# RKA Wiki — Deployment + operational reference

Welcome. This wiki is the **deployment and operational reference** for the Research Knowledge Agent (RKA). It is not a replacement for the in-tree [`CLAUDE.md`](../blob/agentic/CLAUDE.md), which remains the canonical project-instructions file for agents working on the code itself. Start here when you want to **stand RKA up on your own machine** and decide which flavor to run.

## What is RKA?

The **Research Knowledge Agent** is a local-first knowledge graph and provenance store for research projects. It tracks decisions, missions, claims, evidence clusters, journal entries, and literature in a SQLite database (FTS5 + sqlite-vec for hybrid search), exposes them via a FastAPI REST surface and an MCP stdio binary, and ships a React/Vite web UI for browsing. Every write is attributed to an `actor` (`brain | executor | pi | llm | web_ui | system`) and carries provenance links, so a manuscript citation traces back through claims → evidence → literature without manual bookkeeping.

The repo encodes a deliberate three-actor pattern — **Brain** (strategy + evidence interpretation), **Executor** (mission implementation + backbriefs), **PI** (the only actor authorized to ratify privileged writes) — and ships in **two long-lived branches**. `main` is the core stack, driven manually by a human inside Claude Desktop or Claude Code. `agentic` is a **strict superset** that adds a LangGraph orchestrator daemon which automates Brain + Executor while preserving the PI ratification gate. A bookkeeper invariant (`git diff main -- rka/` always empty on agentic) guarantees the RKA core is byte-identical across branches; agentic is purely additive.

## Which deployment do you want? (start here)

```
                       ┌─────────────────────────────────────┐
                       │ Do you want an LLM daemon to drive  │
                       │ missions autonomously, with you     │
                       │ ratifying writes at checkpoints?    │
                       └──────────────┬──────────────────────┘
                                      │
                  ┌───────────────────┴──────────────────┐
                  │ NO — I drive Brain / Executor / PI   │ YES — I supervise a
                  │ myself by loading skill prompts in   │ LangGraph daemon via
                  │ Claude Desktop / Claude Code         │ a parked-interrupt inbox
                  ▼                                      ▼
        ┌──────────────────────┐             ┌──────────────────────────┐
        │  >> Deployment-Main  │             │  >> Deployment-Agentic   │
        │  (core RKA only)     │             │  (RKA core + orchestr.)  │
        └──────────────────────┘             └──────────────────────────┘
```

Both runbooks are **macOS-only** as written (Docker Desktop, Claude Desktop config paths, Keychain/OAuth token flow). The Docker services themselves run on Linux unmodified, but you'll need to adapt the host-side MCP install + config paths yourself — those steps are out of scope here.

## Deployment matrix — `main` vs `agentic`

The two branches are not alternatives in the usual sense: `agentic` is a strict superset. Everything in the left column is also true of the right column; the right column adds.

| Dimension | `main` (core RKA) | `agentic` (RKA + orchestrator) |
|---|---|---|
| **Target user** | PI who drives the loop manually | PI who supervises an autonomous loop |
| **Containers** | `rka-server`, `rka-worker` | `rka-server`, `rka-worker`, `orchestrator` |
| **HTTP ports** | `9712` (REST + web UI) | `9712` (RKA REST/UI) + `9713` (orchestrator daemon) |
| **MCP stdio binaries** | `rka` (one binary) | `rka` + `rka-orchestrator-mcp` (two binaries) |
| **Compose invocation** | `docker compose up -d --build` | `docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d --build` |
| **Workflow engine** | Human + Claude session, switching skill prompts | LangGraph + SqliteSaver (workflow position) + Claude Agent SDK (per-node prompts) |
| **PI surface** | Skills loaded directly in Claude (`rka/skills/{brain,executor,pi}.md`) | Parked-interrupt inbox; PI answers via `AskUserQuestion`; TWO-TAP confirm on `pi_decision_select` |
| **Write boundary** | Human-in-loop on every tool call | `WRITE_TOOLS` allowlist + ratified-action dispatcher + FS Actuator hook (Gap G2) + capability buckets (Phase 2.14) + per-project `workspace_path` threading (Gap 1) |
| **Docker memory** | 4 GB minimum | 6 GB minimum, 8 GB recommended (worker OOM-loops below ~6 GB) |
| **Auth** | Anthropic key in your Claude Desktop/Code config | `CLAUDE_CODE_OAUTH_TOKEN` in `orchestrator/.env` (mode 0600); host `~/.claude.json` bind-mounted read-only |
| **Workspace mount** | N/A | `HOST_WORKSPACE_ROOT` in **repo-root** `.env` bind-mounted at identity path |
| **Branch invariant** | N/A | `git diff main -- rka/` must be empty per commit |

There is no in-place migration path. Switch deployments by checking out the other branch and rebuilding.

## Architecture-at-a-glance

The Brain ⇄ Executor ⇄ PI loop is the load-bearing pattern across both deployments. On `main`, all three actors are the same human-driven Claude session switching skill prompts. On `agentic`, Brain and Executor become LLM subprocesses inside a LangGraph daemon that parks at every PI interrupt; the human ratifies through the parked-interrupt inbox surfaced by `rka-orchestrator-mcp`. Three storage layers stay strictly separated: **RKA SQLite** (domain truth — decisions, missions, journals, claims), **LangGraph SqliteSaver** (workflow position, agentic only), and the **Claude SDK session** (transient per-node prompt context). The agentic branch never persists workflow position back to RKA, and never uses the SDK session as a state bus across nodes.

## Cross-references inside the repo

- [`CLAUDE.md`](../blob/agentic/CLAUDE.md) — canonical project-instructions, hard invariants, branch model, agentic-specific operational notes (Phase D2 / D2.1 / D2.2 / D2.3 / D2.5 history is here). Read this before contributing.
- [`rka/skills/`](../tree/main/rka/skills) — Brain, Executor, PI, Writer skill prompts. **Required reading** if you run the `main` deployment; the orchestrator loads them under the hood on `agentic`.
- [`orchestrator/docs/`](../tree/agentic/orchestrator/docs) — orchestrator design notes (skill-prompt deltas, Phase O project-onboarding design, capability-bucket rationale). Agentic branch only.
- [`docs/embedding_backends.md`](../blob/main/docs/embedding_backends.md) — FastEmbed / OpenAI-compat / Ollama backend configuration (Settings → Embeddings in the web UI).
- [`CHANGELOG.md`](../blob/main/CHANGELOG.md) — release notes, BREAKING-IN-MINOR markers (v2.4 LLM removal, v2.6 `project_id` required).

## Mirroring this wiki to GitHub

Wiki content is version-controlled **in-repo** under `wiki/` on the `agentic` branch, so it versions alongside code. GitHub Wiki uses a separate `.wiki.git` repo; operators publish updates by mirroring:

```bash
# One-time clone of the wiki repo as a sibling worktree
git clone git@github.com:<owner>/<repo>.wiki.git /tmp/rka-wiki

# Sync from in-repo wiki/ to the GitHub wiki repo (run from rka repo root, on agentic)
cp wiki/*.md /tmp/rka-wiki/
cd /tmp/rka-wiki
git add -A && git commit -m "wiki: sync from agentic@$(git -C - rev-parse --short HEAD)"
git push
```

Edits made on github.com's wiki UI will **not** flow back automatically — treat `wiki/` on `agentic` as the source of truth and the GitHub wiki as a publishing target. Re-run the mirror after any merge that touches `wiki/`. GitHub renders `Home.md` as the landing page automatically; page-to-page links work with bare basenames (`[Deployment-Main](Deployment-Main.md)`) in both the in-repo view and the rendered wiki.

---

*Last updated: 2026-05-30 — covers `main` through v2.6 (`project_id` required) and `agentic` through Phase D2.5 (Bash EROFS fix + `CLAUDE_CODE_OAUTH_TOKEN` auth path).*