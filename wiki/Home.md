# RKA Wiki — Deployment + operational reference

Welcome. This wiki is the **deployment and operational reference** for the Research Knowledge Agent (RKA). It is not a replacement for the in-tree [`CLAUDE.md`](../blob/main/CLAUDE.md), which remains the canonical project-instructions file for agents working on the code itself. Start with [Deployment-Main](Deployment-Main.md) to run RKA Core.

## What is RKA?

The **Research Knowledge Agent** is a local-first knowledge graph and provenance store for research projects. It tracks decisions, missions, claims, evidence clusters, journal entries, and literature in a SQLite database (FTS5 + sqlite-vec for hybrid search), exposes them via a FastAPI REST surface and an MCP stdio binary, and ships a React/Vite web UI for browsing. Every write is attributed to an `actor` (`brain | executor | pi | llm | web_ui | system`) and carries provenance links, so a manuscript citation traces back through claims → evidence → literature without manual bookkeeping.

The repo encodes a deliberate three-actor pattern — **Brain** (strategy + evidence interpretation), **Executor** (mission implementation + backbriefs), and **PI** (the researcher who ratifies direction). These are human-driven usage roles over RKA Core's REST/MCP contract. The former `agentic` LangGraph runtime is shelved and unsupported; its documentation remains only as historical material. See [ADR 0013](../blob/main/docs/adr/0013-shelve-agentic-and-focus-core-writer.md).

## Supported deployment

Use [Deployment-Main](Deployment-Main.md) for the supported RKA Core
deployment. The runbook is macOS-focused as written; the Docker services also
run on Linux, but host-side MCP configuration paths must be adapted.

The historical [Deployment-Agentic](Deployment-Agentic.md) page is retained
for provenance only. Do not use it as an installation runbook.

## Architecture-at-a-glance

The Brain ⇄ Executor ⇄ PI loop is a human-driven operating pattern over one
RKA Core knowledge store. RKA SQLite remains the domain truth for decisions,
missions, journals, claims, evidence, and provenance.

## Cross-references inside the repo

- [`CLAUDE.md`](../blob/main/CLAUDE.md) — canonical project instructions and hard invariants. Read this before contributing.
- [`rka/skills/`](../tree/main/rka/skills) — Core Brain, Executor, and PI usage guidance.
- [`docs/embedding_backends.md`](../blob/main/docs/embedding_backends.md) — FastEmbed / OpenAI-compat / Ollama backend configuration (Settings → Embeddings in the web UI).
- [`CHANGELOG.md`](../blob/main/CHANGELOG.md) — release notes, BREAKING-IN-MINOR markers (v2.4 LLM removal, v2.6 `project_id` required).

## Mirroring this wiki to GitHub

Wiki content is version-controlled **in-repo** under `wiki/` on `main`, so it versions alongside code. GitHub Wiki uses a separate `.wiki.git` repo; operators publish updates by mirroring:

```bash
# One-time clone of the wiki repo as a sibling worktree
git clone git@github.com:<owner>/<repo>.wiki.git /tmp/rka-wiki

# Sync from in-repo wiki/ to the GitHub wiki repo (run from rka repo root, on main)
cp wiki/*.md /tmp/rka-wiki/
cd /tmp/rka-wiki
git add -A && git commit -m "wiki: sync from main@$(git -C - rev-parse --short HEAD)"
git push
```

Edits made on github.com's wiki UI will **not** flow back automatically — treat `wiki/` on `main` as the source of truth and the GitHub wiki as a publishing target. Re-run the mirror after any merge that touches `wiki/`. GitHub renders `Home.md` as the landing page automatically; page-to-page links work with bare basenames (`[Deployment-Main](Deployment-Main.md)`) in both the in-repo view and the rendered wiki.

---

*Last updated: 2026-08-27 — supported deployment is RKA Core on `main`; Agentic is shelved.*
