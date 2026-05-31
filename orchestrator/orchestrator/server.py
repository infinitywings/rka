"""FastAPI server — HTTP surface for the orchestrator daemon.

This is the daemon side of the Claude-Code-native PI workflow:

  POST   /runs                       — start a new workflow
  GET    /runs                       — list runs (active + recent)
  GET    /runs/{thread_id}           — run detail
  DELETE /runs/{thread_id}           — cancel
  GET    /inbox                      — list pending PI interrupts
  POST   /inbox/{interrupt_id}/accept   — PI accepts (server emits type-correct token)
  POST   /inbox/{interrupt_id}/reject   — PI rejects → escalation_router
  POST   /inbox/{interrupt_id}/correct  — PI redirects with freeform text
  GET    /health                     — liveness

The runner does the heavy work; this module is thin glue. Graph
invocation happens inside `asyncio.to_thread` so a long-running segment
(seconds-to-minutes for LLM calls) doesn't block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from orchestrator.parked_store import ParkedStore
from orchestrator.runner import (
    MissionNotFoundError,
    OrchestratorRunner,
    SegmentOutcome,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = os.environ.get(
    "ORCHESTRATOR_DB_PATH", "/data/orchestrator.db"
)
DEFAULT_SAVER_PATH = os.environ.get(
    "ORCHESTRATOR_SAVER_PATH", "/data/orchestrator-saver.db"
)
DEFAULT_RKA_URL = os.environ.get("RKA_API_URL", "http://rka:9712")


class WorkspaceMountUnsafeError(RuntimeError):
    """Raised at startup if the daemon's workspace bind mount resolves to
    a path that would over-expose host state ($HOME, `/`, ancestor of
    well-known credential dirs)."""


def _enforce_workspace_mount_safety() -> None:
    """Refuse to start if the bind-mounted workspace is dangerously broad.

    Phase E1 safety guard. The Compose overlay mounts
    `${HOST_WORKSPACE_ROOT:-${HOME}}` rw into the container at the same
    absolute path. If `HOST_WORKSPACE_ROOT` is unset, the fallback is
    `$HOME` — which gives the SDK subprocess RW access to `~/.ssh`,
    `~/.aws`, `~/.gnupg`, `~/.config`, the entire `~/Documents`, etc.
    That's wildly over-broad for a workspace mount whose purpose is the
    PI's per-project files.

    This check refuses to start when the resolved path is:
      - empty / None
      - `/` (the host root)
      - `$HOME` itself (set HOST_WORKSPACE_ROOT to a child dir, e.g.
        `$HOME/Research` or an absolute project parent)
      - an ancestor of well-known credential directories

    The check reads the HOST_WORKSPACE_ROOT env var that Compose
    interpolates the same way (project-root `.env` or shell env).
    Workspace operations within the container resolve via the same
    absolute path the PI sees on the host.

    Bypass: set `ORCHESTRATOR_ALLOW_HOME_MOUNT=1` to explicitly accept the
    over-broad mount (for development / single-purpose installs that
    don't have sensitive host state). Logged as a warning each startup
    so the override is visible in the daemon logs.
    """
    if os.environ.get("ORCHESTRATOR_ALLOW_HOME_MOUNT") == "1":
        logger.warning(
            "ORCHESTRATOR_ALLOW_HOME_MOUNT=1 set; skipping workspace mount "
            "safety check. The daemon will accept any HOST_WORKSPACE_ROOT, "
            "including $HOME and `/`. Use only when you trust the daemon's "
            "host environment has no sensitive state."
        )
        return

    host_root_raw = os.environ.get("HOST_WORKSPACE_ROOT", "").strip()
    home = os.environ.get("HOME", "").strip()

    # Effective mount target — matches the Compose interpolation
    # `${HOST_WORKSPACE_ROOT:-${HOME}}`.
    effective = host_root_raw or home
    if not effective:
        raise WorkspaceMountUnsafeError(
            "Refusing to start: neither HOST_WORKSPACE_ROOT nor HOME is set. "
            "Set HOST_WORKSPACE_ROOT in the repo-root .env (or shell env) to "
            "the absolute path of your projects-parent directory (e.g., "
            "/Volumes/base/projects or /Users/you/Research)."
        )

    # Normalize: strip trailing slashes, resolve relative
    effective_norm = effective.rstrip("/") or "/"
    home_norm = home.rstrip("/") if home else ""

    # Refuse `/`
    if effective_norm == "/":
        raise WorkspaceMountUnsafeError(
            "Refusing to start: HOST_WORKSPACE_ROOT=`/` would mount the host "
            "root read-write into the daemon container — extreme over-exposure. "
            "Set HOST_WORKSPACE_ROOT to a specific projects-parent directory "
            "(e.g., $HOME/Research or /Volumes/.../projects). Override with "
            "ORCHESTRATOR_ALLOW_HOME_MOUNT=1 if you genuinely intend this."
        )

    # Refuse $HOME exactly (whether explicit or via fallback)
    if home_norm and effective_norm == home_norm:
        suggestion_dir = f"{home_norm}/Research"
        raise WorkspaceMountUnsafeError(
            f"Refusing to start: HOST_WORKSPACE_ROOT resolves to your $HOME "
            f"({home_norm!r}). Mounting $HOME rw into the daemon exposes "
            f"~/.ssh, ~/.aws, ~/.gnupg, ~/.config, ~/Documents, etc. to the "
            f"SDK subprocess. Set HOST_WORKSPACE_ROOT to a specific child "
            f"directory in the repo-root .env, e.g.:\n"
            f"  echo 'HOST_WORKSPACE_ROOT={suggestion_dir}' >> "
            f"/Volumes/base/workspace/rka/.env\n"
            f"(or another absolute path that holds your project workspaces). "
            f"Override with ORCHESTRATOR_ALLOW_HOME_MOUNT=1 if you genuinely "
            f"intend this."
        )

    # Refuse if the effective path is an ancestor of credential paths.
    # We only check this for host-style paths (POSIX); skip for Windows-
    # style paths that an external installer might pass.
    if effective_norm.startswith("/"):
        sensitive_children = (".ssh", ".aws", ".gnupg", ".config")
        for child in sensitive_children:
            if home_norm:
                cred_path = f"{home_norm}/{child}"
                # Refuse if the effective path is a strict ancestor of cred_path.
                if cred_path.startswith(effective_norm + "/") or cred_path == effective_norm:
                    raise WorkspaceMountUnsafeError(
                        f"Refusing to start: HOST_WORKSPACE_ROOT={effective_norm!r} "
                        f"is an ancestor of {cred_path!r}, which would expose "
                        f"the credentials there to the daemon's SDK subprocess. "
                        f"Choose a narrower path. Override with "
                        f"ORCHESTRATOR_ALLOW_HOME_MOUNT=1 if you genuinely intend this."
                    )

    logger.info("workspace mount safety check passed: %s", effective_norm)


def _maybe_load_oauth_secret() -> None:
    """Gap 5 — read a Docker-secret OAuth token file (if present) and
    export to env as CLAUDE_CODE_OAUTH_TOKEN so the claude-agent-sdk
    subprocess picks it up.

    Path comes from ORCHESTRATOR_OAUTH_SECRET_PATH (default
    /run/secrets/claude_oauth_token). When the file doesn't exist or
    is empty, we silently fall back — env_file (orchestrator/.env)
    remains the back-compat auth source. The secret value never lands
    in logs.
    """
    path = os.environ.get(
        "ORCHESTRATOR_OAUTH_SECRET_PATH", "/run/secrets/claude_oauth_token"
    )
    try:
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return  # silent fall-through
    except OSError as e:
        logger.warning(
            "oauth secret at %s could not be read: %s; falling back to env_file",
            path, e,
        )
        return
    if not token:
        return  # empty file — treat as absent
    # Don't clobber an explicit env_file override unless the secret
    # is actually different. (Operator who sets BOTH probably wants
    # the secret to win — but log the override so it's debuggable.)
    existing = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if existing and existing != token:
        logger.info(
            "oauth secret at %s overrides CLAUDE_CODE_OAUTH_TOKEN from env_file",
            path,
        )
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
    logger.info("oauth secret loaded from %s (value redacted)", path)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class StartRunRequest(BaseModel):
    mission_id: str
    project_id: str
    budget_usd: float = 5.0
    workflow_thread_id: Optional[str] = None
    # Phase-X (Cross-Run Correction Channel): per-run PI override text.
    # Persisted into workflow_runs.run_overrides["pi_instructions"] and
    # rendered into Brain's strategy prompt under a delimited PI OVERRIDES
    # block. Supersedes contradictory framing in the mission body for THIS
    # run only. Redacted from the ack dict in the response (the value is
    # passthrough to runner; the ack returns the literal string "<set>"
    # in its place to avoid leaking PI prose to FastAPI access logs /
    # downstream proxies). Defaults to None (no override).
    run_instructions: Optional[str] = None


class StartOnboardingRequest(BaseModel):
    project_id: str
    workflow_thread_id: Optional[str] = None


class StartBootstrapRequest(BaseModel):
    """Phase B: orchestrator-level credential bootstrap. No project_id;
    Phase B is daemon-level setup."""
    workflow_thread_id: Optional[str] = None


class CorrectRequest(BaseModel):
    response_text: str = Field(min_length=1)


class RejectRequest(BaseModel):
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Phase H — PI monitoring dashboard HTML
# ---------------------------------------------------------------------------
#
# Single self-contained HTML page; no build step, no framework. Polls
# /runs, /inbox, /runs/{id} every 4s and renders the state. Sized for
# the PI's actual workflow:
#   - Top: list of active and recent runs
#   - Middle: parked interrupts (PI's action queue)
#   - Bottom: a detail panel that fills when you click a run
# Read-only by design — every state change must go through Claude
# Desktop's MCP tools so the TWO-TAP ratification stays the only path
# to writes.

_DASHBOARD_HTML = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>RKA Orchestrator — PI Monitor</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    :root {
      --bg: #0f1419;
      --panel: #1c2127;
      --border: #2a3038;
      --fg: #e6edf3;
      --muted: #7d8590;
      --accent: #58a6ff;
      --good: #56d364;
      --warn: #d29922;
      --bad: #f85149;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; padding: 18px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      background: var(--bg); color: var(--fg);
      font-size: 14px; line-height: 1.45;
    }
    h1 { font-size: 18px; margin: 0 0 12px; font-weight: 600; }
    h2 { font-size: 14px; margin: 0 0 8px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; font-weight: 600; }
    .row { display: flex; gap: 18px; flex-wrap: wrap; }
    .col { flex: 1 1 360px; min-width: 0; }
    .panel {
      background: var(--panel); border: 1px solid var(--border);
      border-radius: 8px; padding: 12px; margin-bottom: 14px;
    }
    .meta { color: var(--muted); font-size: 12px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
    th { color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
    tr.clickable { cursor: pointer; }
    tr.clickable:hover { background: rgba(88,166,255,.07); }
    tr.selected { background: rgba(88,166,255,.13); }
    .badge {
      display: inline-block; padding: 2px 8px; border-radius: 999px;
      font-size: 11px; font-weight: 600; letter-spacing: .03em;
    }
    .b-running { background: rgba(88,166,255,.18); color: var(--accent); }
    .b-awaiting { background: rgba(210,153,34,.18); color: var(--warn); }
    .b-complete { background: rgba(86,211,100,.18); color: var(--good); }
    .b-failed { background: rgba(248,81,73,.18); color: var(--bad); }
    .b-cancelled { background: rgba(125,133,144,.18); color: var(--muted); }
    code, pre {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
    }
    pre {
      background: #0d1117; padding: 10px; border-radius: 6px;
      overflow: auto; max-height: 280px;
      border: 1px solid var(--border);
    }
    .truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
    .muted { color: var(--muted); }
    .note {
      background: rgba(248,81,73,.08); border-left: 3px solid var(--bad);
      padding: 8px 10px; margin: 8px 0; font-size: 12px;
    }
    button.refresh {
      background: transparent; border: 1px solid var(--border);
      color: var(--fg); border-radius: 6px; padding: 4px 12px;
      font-size: 12px; cursor: pointer;
    }
    button.refresh:hover { border-color: var(--accent); color: var(--accent); }
    .header-row {
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 12px;
    }
    .empty { color: var(--muted); font-style: italic; padding: 12px 4px; }
    .kv { display: grid; grid-template-columns: 130px 1fr; gap: 4px 12px; font-size: 13px; }
    .kv .k { color: var(--muted); }
    .kv .v { word-break: break-all; }
  </style>
</head>
<body>
  <div class="header-row">
    <h1>RKA Orchestrator — PI Monitor <span class="meta" id="lastUpdated"></span></h1>
    <button class="refresh" onclick="loadAll()">Refresh now</button>
  </div>

  <div class="row">
    <div class="col">
      <div class="panel">
        <h2>Runs</h2>
        <div id="runsContainer"><div class="empty">Loading…</div></div>
      </div>

      <div class="panel">
        <h2>Parked interrupts (PI action queue)</h2>
        <div id="inboxContainer"><div class="empty">Loading…</div></div>
      </div>
    </div>

    <div class="col">
      <div class="panel">
        <h2 id="detailHeader">Run detail</h2>
        <div id="detailContainer"><div class="empty">Click a run on the left to see its full state.</div></div>
      </div>
    </div>
  </div>

  <p class="meta" style="margin-top: 16px">
    Read-only view. Every accept / reject / correct still goes through the MCP tools in
    your Claude Desktop / Claude Code session so the two-tap ratification gate stays the
    only path to writes.
  </p>

<script>
const POLL_MS = 4000;
let selectedRunId = null;

function fmtTime(s) {
  if (!s) return '';
  try {
    const d = new Date(s);
    if (isNaN(d.getTime())) return s;
    return d.toLocaleTimeString();
  } catch (e) { return s; }
}

function badge(status) {
  const cls = ({
    running: 'b-running',
    awaiting_pi: 'b-awaiting',
    complete: 'b-complete',
    failed: 'b-failed',
    cancelled: 'b-cancelled',
  })[status] || 'b-running';
  return `<span class="badge ${cls}">${escapeHtml(status || '?')}</span>`;
}

function escapeHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

async function fetchJson(path) {
  const r = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`);
  return await r.json();
}

function renderRuns(runs) {
  const c = document.getElementById('runsContainer');
  if (!Array.isArray(runs) || runs.length === 0) {
    c.innerHTML = '<div class="empty">No runs yet. Start one with <code>orchestrator_run_start</code>.</div>';
    return;
  }
  const rows = runs.map(r => {
    const sel = r.workflow_thread_id === selectedRunId ? ' selected' : '';
    return `
      <tr class="clickable${sel}" data-id="${escapeHtml(r.workflow_thread_id)}">
        <td><code class="truncate">${escapeHtml(r.workflow_thread_id || '')}</code></td>
        <td>${badge(r.status)}</td>
        <td><code>${escapeHtml(r.current_node || '')}</code></td>
        <td><code class="truncate">${escapeHtml(r.project_id || '')}</code></td>
        <td>${escapeHtml(fmtTime(r.updated_at))}</td>
      </tr>
    `;
  }).join('');
  c.innerHTML = `
    <table>
      <thead><tr><th>workflow_thread_id</th><th>status</th><th>node</th><th>project_id</th><th>updated</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
  c.querySelectorAll('tr.clickable').forEach(tr => {
    tr.addEventListener('click', () => {
      selectedRunId = tr.getAttribute('data-id');
      loadAll();
    });
  });
}

function renderInbox(inbox) {
  const c = document.getElementById('inboxContainer');
  if (!Array.isArray(inbox) || inbox.length === 0) {
    c.innerHTML = '<div class="empty">No parked interrupts.</div>';
    return;
  }
  const rows = inbox.map(i => `
    <tr>
      <td><code class="truncate">${escapeHtml(i.interrupt_id || '')}</code></td>
      <td><code>${escapeHtml(i.interrupt_type || '')}</code></td>
      <td><code class="truncate">${escapeHtml(i.workflow_thread_id || '')}</code></td>
      <td>${escapeHtml(fmtTime(i.parked_at))}</td>
    </tr>
  `).join('');
  c.innerHTML = `
    <table>
      <thead><tr><th>interrupt_id</th><th>type</th><th>workflow_thread_id</th><th>parked_at</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderDetail(run, lastError) {
  const c = document.getElementById('detailContainer');
  const h = document.getElementById('detailHeader');
  if (!run) {
    h.textContent = 'Run detail';
    c.innerHTML = '<div class="empty">Click a run on the left to see its full state.</div>';
    return;
  }
  h.innerHTML = `Run detail — <code>${escapeHtml(run.workflow_thread_id || '')}</code>`;
  const kv = [
    ['status', badge(run.status)],
    ['current_node', `<code>${escapeHtml(run.current_node || '')}</code>`],
    ['project_id', `<code>${escapeHtml(run.project_id || '')}</code>`],
    ['mission_id', `<code>${escapeHtml(run.mission_id || '')}</code>`],
    ['created_at', escapeHtml(fmtTime(run.created_at) || '—')],
    ['updated_at', escapeHtml(fmtTime(run.updated_at) || '—')],
    ['terminal_state', escapeHtml(run.terminal_state || '')],
  ].map(([k, v]) => `<div class="k">${escapeHtml(k)}</div><div class="v">${v}</div>`).join('');
  let errBlock = '';
  if (lastError) {
    errBlock = `<div class="note"><strong>last_error:</strong><br><code>${escapeHtml(lastError)}</code></div>`;
  }
  c.innerHTML = `<div class="kv">${kv}</div>${errBlock}<pre>${escapeHtml(JSON.stringify(run, null, 2))}</pre>`;
}

async function loadAll() {
  try {
    const runs = await fetchJson('/runs?limit=50');
    renderRuns(runs);
    const inbox = await fetchJson('/inbox');
    renderInbox(inbox);
    let detail = null, lastError = null;
    if (selectedRunId) {
      try {
        detail = await fetchJson(`/runs/${encodeURIComponent(selectedRunId)}`);
        lastError = detail && detail.last_error;
      } catch (e) {
        detail = null;
      }
    }
    renderDetail(detail, lastError);
    document.getElementById('lastUpdated').textContent = ' • last poll ' + new Date().toLocaleTimeString();
  } catch (e) {
    const c = document.getElementById('runsContainer');
    c.innerHTML = `<div class="note">Failed to load: ${escapeHtml(String(e))}</div>`;
  }
}

loadAll();
setInterval(loadAll, POLL_MS);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Outcome → dict serializer
# ---------------------------------------------------------------------------


def _outcome_dict(o: SegmentOutcome) -> dict:
    return {
        "workflow_thread_id": o.workflow_thread_id,
        "parked_interrupt_id": o.parked_interrupt_id,
        "parked_interrupt_type": o.parked_interrupt_type,
        "terminal_state": o.terminal_state,
        "current_node": o.current_node,
        "usd_spent": o.usd_spent,
        "final_report_id": o.final_report_id,
    }


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _default_sdk_factory(project_id: str, workspace_path: str = ""):
    """Build the real Claude Agent SDK client. Lazy import so tests that
    inject a fake factory don't trigger the SDK's import-time auth probe.

    Gap 1 fix: forwards workspace_path to make_sdk so the Phase G2
    can_use_tool hook can scope FS escape detection to the workflow's
    per-project workspace rather than HOST_WORKSPACE_ROOT.
    """
    from orchestrator.llm_client import make_sdk

    return make_sdk(project_id=project_id, workspace_path=workspace_path)


def _default_mcp_factory(base_url: str):
    """Return a factory closure that builds a RestMCPClient per thread."""
    from orchestrator.mcp_client import make_client

    def _factory(thread_id: str, project_id: str):
        return make_client(
            workflow_thread_id=thread_id,
            base_url=base_url,
            project_id=project_id,
        )

    return _factory


def _default_saver_factory(saver_path: str):
    """Return a factory closure that opens a fresh SqliteSaver per call.

    Each call opens its own sqlite connection (thread-safe via
    check_same_thread=False inside open_checkpointer). The same file is
    safely reused across all runs — LangGraph's saver namespaces by
    thread_id internally.
    """
    from orchestrator import graph as graph_module

    def _factory(thread_id: str):
        # graph_module.open_checkpointer reads the saver_path even if
        # thread_id changes — the saver itself stores per-thread rows.
        return graph_module.open_checkpointer(saver_path)

    return _factory


def create_app(
    *,
    store: Optional[ParkedStore] = None,
    runner: Optional[OrchestratorRunner] = None,
    db_path: Optional[str] = None,
    saver_path: Optional[str] = None,
    rka_url: Optional[str] = None,
    enforce_mount_safety: Optional[bool] = None,
) -> FastAPI:
    """Construct the FastAPI app. All injection points are exposed for
    tests; defaults wire the production daemon.

    `enforce_mount_safety` controls the Phase E1 $HOME bind-mount
    refusal at lifespan start. When None (default), it's auto-True for
    pure-production (no store + no runner injected) and auto-False when
    EITHER store or runner is injected (test-mode signal). Pass True
    explicitly to force the check even with injection (e.g., to test
    the check itself); pass False to suppress it entirely (e.g., a
    custom-bootstrap caller that pre-validates its own mount).
    """

    resolved_db_path = db_path or DEFAULT_DB_PATH
    resolved_saver_path = saver_path or DEFAULT_SAVER_PATH
    resolved_rka_url = rka_url or DEFAULT_RKA_URL

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Phase E1: refuse to start if HOST_WORKSPACE_ROOT is unset (which
        # defaults to $HOME via Compose interpolation) or otherwise
        # resolves to $HOME / `/`. Mounting $HOME would expose ~/.ssh,
        # ~/.aws, ~/.gnupg, ~/.config, etc. read-write to the daemon's
        # claude-agent-sdk subprocess — wildly over-broad. Workspace
        # mounts should be a child of $HOME (e.g., $HOME/Research) or
        # an explicit absolute path (e.g., /Volumes/.../projects).
        #
        # When `enforce_mount_safety` is None (default), default to True
        # only on pure-production (no test injection). A factory that
        # injects only `store` (e.g., a future Phase O bootstrapper) no
        # longer accidentally suppresses the check — it must be set
        # explicitly. See Phase E1 adversarial review (MEDIUM #7).
        if enforce_mount_safety is True:
            should_check = True
        elif enforce_mount_safety is False:
            should_check = False
        else:  # None — auto-detect test mode by FULL injection
            should_check = store is None and runner is None
        if should_check:
            _enforce_workspace_mount_safety()

        # Gap 5 — load OAuth token from Docker secret if present. When
        # the operator opts into the secrets overlay, the token lives
        # at /run/secrets/claude_oauth_token (mounted tmpfs, read-only).
        # We read it once at startup and export to env so the
        # claude-agent-sdk subprocess picks it up unchanged. Falls back
        # cleanly to env_file (orchestrator/.env) when the secret isn't
        # mounted — back-compat path.
        _maybe_load_oauth_secret()

        # If the caller injected store/runner, use those; else build them.
        if store is not None:
            app.state.store = store
        else:
            Path(resolved_db_path).parent.mkdir(parents=True, exist_ok=True)
            app.state.store = ParkedStore(resolved_db_path)

        if runner is not None:
            app.state.runner = runner
        else:
            app.state.runner = OrchestratorRunner(
                store=app.state.store,
                sdk_factory=_default_sdk_factory,
                mcp_factory=_default_mcp_factory(resolved_rka_url),
                saver_factory=_default_saver_factory(resolved_saver_path),
            )

        # Wire the workspace path resolver so manifest.workspace_dir()
        # consults project_workspaces (PI-provided paths) before falling
        # back to the hardcoded $HOME/rka-projects convention.
        from orchestrator import manifest as _M
        _M.set_workspace_path_resolver(
            lambda pid: app.state.store.get_project_workspace(pid)
        )

        # Background-task registry. Async-resume segments (wait_segment=false)
        # are scheduled as fire-and-forget asyncio tasks; without retaining a
        # strong reference they can be garbage-collected mid-run (Python's
        # event loop only keeps weak references to Tasks). We add to the set
        # on creation and discard on completion via add_done_callback.
        app.state.bg_segments: set[asyncio.Task] = set()

        # Startup recovery sweep — runs left in 'running' from a previous
        # process can never make progress (no in-process task is driving
        # them). Mark them 'failed' with last_error so /runs surfaces the
        # state to the PI instead of showing them as live work in flight.
        # Conservative: only sweep on cold-start; don't touch 'awaiting_pi'
        # rows (those are durably parked and resumable when the PI responds).
        try:
            orphan_count = app.state.store.reap_orphaned_running_runs(
                last_error="daemon restarted while segment in flight"
            )
            if orphan_count:
                logger.warning(
                    "startup sweep: reaped %d run(s) left in 'running' from "
                    "previous process", orphan_count,
                )
        except Exception:  # noqa: BLE001 — best-effort; don't block startup
            logger.exception("startup sweep failed (non-fatal); continuing")

        logger.info(
            "orchestrator-server ready: db=%s saver=%s rka_url=%s",
            resolved_db_path, resolved_saver_path, resolved_rka_url,
        )
        try:
            yield
        finally:
            # Graceful drain: wait briefly for in-flight background segments
            # to finish their next interrupt-park or terminal; if they don't
            # complete in time, cancel them. The store's reap-on-startup
            # handles the corresponding workflow_runs rows on next boot.
            pending = list(app.state.bg_segments)
            if pending:
                logger.info(
                    "lifespan shutdown: draining %d background segment(s)",
                    len(pending),
                )
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "lifespan shutdown: background segments did not "
                        "drain in 30s; cancelling and leaving recovery to "
                        "next startup sweep"
                    )
                    for t in pending:
                        t.cancel()
            if store is None:
                app.state.store.close()

    app = FastAPI(title="rka-orchestrator", lifespan=lifespan)

    # -----------------------------------------------------------------
    # Routes
    # -----------------------------------------------------------------

    @app.get("/health")
    async def health(request: Request) -> dict:
        return {"status": "ok", "db_path": resolved_db_path}

    # ---------------------------------------------------------------
    # Phase H — PI monitoring dashboard
    # ---------------------------------------------------------------
    # The user runs the orchestrator daemon on 9713 alongside the RKA
    # core API on 9712. They asked for a "webpage to visualize the
    # progress so PI can clearly monitor". We can't put the dashboard
    # on 9712 without modifying the rka/ tree (the agentic bookkeeper
    # invariant forbids that), so the dashboard lives on the
    # orchestrator at 9713 instead. Open http://localhost:9713/dashboard
    # in any browser. The page polls the same JSON endpoints the MCP
    # tools use (/runs, /inbox), so what the PI sees in Claude Desktop
    # always matches what the dashboard shows — no separate data
    # source, no separate auth model.
    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request) -> str:
        return _DASHBOARD_HTML

    def _background_segment(
        request: Request,
        thread_id: str,
        coro_factory,
        *,
        log_tag: str,
    ) -> None:
        """Shared helper for /runs, /onboard, /bootstrap, /inbox/.../*
        async-resume paths. Schedules `coro_factory()` (a callable
        returning an awaitable) as a tracked asyncio task and wires
        last_error + bg_segments lifecycle. Errors land in
        workflow_runs.last_error so the PI can discover them by polling
        /runs/{id}."""
        store_ = request.app.state.store

        async def _drive() -> None:
            try:
                await coro_factory()
            except asyncio.CancelledError:
                logger.info(
                    "background %s cancelled for thread %s", log_tag, thread_id,
                )
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception(
                    "background %s failed for thread %s", log_tag, thread_id,
                )
                try:
                    store_.update_run(
                        thread_id,
                        status="failed",
                        last_error=f"background {log_tag} crashed: {e!r}"[:500],
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "failed to write last_error for thread %s", thread_id,
                    )

        task = asyncio.create_task(_drive())
        request.app.state.bg_segments.add(task)
        task.add_done_callback(request.app.state.bg_segments.discard)

    @app.post("/runs")
    async def start_run(
        req: StartRunRequest,
        request: Request,
        wait_segment: bool = True,
    ) -> dict:
        """Start a new mission run.

        wait_segment=True (default): synchronous — run create + load
            mission + drive the graph until the first interrupt or
            terminal. Used by tests and any caller that can tolerate
            minutes-long HTTP calls.

        wait_segment=False: commit the run row + load mission
            synchronously, return a `{status: "starting"}` ack
            immediately, and drive the first segment as a background
            task. Used by the MCP-stdio binary so the PI's Claude
            session doesn't time out while the Brain's strategy_node
            + confirmation_brief LLM calls run (typically minutes).
            The PI polls /runs/{id} and /inbox to discover the first
            parked interrupt or terminal state.
        """
        runner_: OrchestratorRunner = request.app.state.runner
        if wait_segment:
            try:
                outcome = await asyncio.to_thread(
                    runner_.start_run,
                    mission_id=req.mission_id,
                    project_id=req.project_id,
                    budget_usd=req.budget_usd,
                    workflow_thread_id=req.workflow_thread_id,
                    run_instructions=req.run_instructions,
                )
            except MissionNotFoundError as e:
                raise HTTPException(status_code=404, detail=str(e))
            return _outcome_dict(outcome)

        # async-start path
        try:
            ack = await asyncio.to_thread(
                runner_.start_run_commit,
                mission_id=req.mission_id,
                project_id=req.project_id,
                budget_usd=req.budget_usd,
                workflow_thread_id=req.workflow_thread_id,
                run_instructions=req.run_instructions,
            )
        except MissionNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

        _background_segment(
            request,
            ack["workflow_thread_id"],
            lambda: asyncio.to_thread(
                runner_.start_run_drive,
                workflow_thread_id=ack["workflow_thread_id"],
                project_id=ack["project_id"],
                mission_id=ack["mission_id"],
                motivated_by_decision_id=ack["motivated_by_decision_id"],
                allowed_capabilities=ack.get("allowed_capabilities"),
            ),
            log_tag="start_run",
        )
        # Phase-X: redact run_instructions from the ack so the value
        # doesn't bounce out to FastAPI access logs / MCP-caller traces.
        # The PI knows what they passed; the canonical record is on
        # workflow_runs.run_overrides accessible via /runs/{id}.
        #
        # Adversarial-review M3 clarification: this is LOG-HYGIENE
        # redaction, NOT a confidentiality guarantee. The value IS
        # retrievable via GET /runs/{id} (the PI needs an audit trail
        # of what they authorized). Operators who consider their
        # run_instructions sensitive must restrict access to /runs/{id}
        # at the proxy/network layer; the orchestrator does not gate it
        # behind a session header.
        run_instructions_status = (
            "<set>" if req.run_instructions and req.run_instructions.strip() else None
        )
        return {
            "workflow_thread_id": ack["workflow_thread_id"],
            "mission_id": ack["mission_id"],
            "project_id": ack["project_id"],
            "status": "starting",
            "wait_segment": False,
            "run_instructions": run_instructions_status,
        }

    @app.post("/onboard")
    async def start_onboarding(
        req: StartOnboardingRequest,
        request: Request,
        wait_segment: bool = True,
    ) -> dict:
        """Phase D5c: kick off the onboarding subgraph for a project.

        Same wait_segment semantics as /runs — default True (sync) for
        tests, False (background-task the first segment) for the MCP-stdio
        binary. PI polls /inbox to render the first interrupt
        (pi_onboarding_topic).
        """
        runner_: OrchestratorRunner = request.app.state.runner
        if wait_segment:
            outcome = await asyncio.to_thread(
                runner_.start_onboarding,
                project_id=req.project_id,
                workflow_thread_id=req.workflow_thread_id,
            )
            return _outcome_dict(outcome)

        ack = await asyncio.to_thread(
            runner_.start_onboarding_commit,
            project_id=req.project_id,
            workflow_thread_id=req.workflow_thread_id,
        )
        _background_segment(
            request,
            ack["workflow_thread_id"],
            lambda: asyncio.to_thread(
                runner_.start_onboarding_drive,
                workflow_thread_id=ack["workflow_thread_id"],
                project_id=ack["project_id"],
            ),
            log_tag="start_onboarding",
        )
        return {
            "workflow_thread_id": ack["workflow_thread_id"],
            "project_id": ack["project_id"],
            "status": "starting",
            "wait_segment": False,
        }

    @app.post("/bootstrap")
    async def start_bootstrap(
        req: StartBootstrapRequest,
        request: Request,
        wait_segment: bool = True,
    ) -> dict:
        """Phase B: kick off the orchestrator-level credential bootstrap.

        Same wait_segment semantics as /runs. The PI polls /inbox to
        render the first interrupt (pi_bootstrap_intent).
        """
        runner_: OrchestratorRunner = request.app.state.runner
        if wait_segment:
            outcome = await asyncio.to_thread(
                runner_.start_phase_b,
                workflow_thread_id=req.workflow_thread_id,
            )
            return _outcome_dict(outcome)

        ack = await asyncio.to_thread(
            runner_.start_phase_b_commit,
            workflow_thread_id=req.workflow_thread_id,
        )
        _background_segment(
            request,
            ack["workflow_thread_id"],
            lambda: asyncio.to_thread(
                runner_.start_phase_b_drive,
                workflow_thread_id=ack["workflow_thread_id"],
            ),
            log_tag="start_phase_b",
        )
        return {
            "workflow_thread_id": ack["workflow_thread_id"],
            "status": "starting",
            "wait_segment": False,
        }

    @app.get("/projects/{project_id}/zotero_collection")
    async def get_project_zotero_collection(
        project_id: str, request: Request
    ) -> dict:
        """Return the Zotero collection mapping for this project.

        The PI uses the Zotero Connector to save papers into this
        collection. Brain + Executor query zotero-mcp with the
        collection_key to retrieve only this project's papers.

        404 if the project hasn't been onboarded or Zotero wasn't
        configured at onboarding time.
        """
        store_: ParkedStore = request.app.state.store
        row = store_.get_project_manifest(project_id)
        if not row or not row.get("zotero_collection_key"):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"no Zotero collection registered for {project_id}. "
                    "Either onboarding hasn't run or Zotero env vars were "
                    "missing when it did."
                ),
            )
        return {
            "project_id": project_id,
            "zotero_collection_key": row["zotero_collection_key"],
            "zotero_collection_name": row.get("zotero_collection_name"),
            "workspace_path": row.get("workspace_path"),
        }

    @app.get("/projects/{project_id}/manifest")
    async def get_project_manifest(project_id: str, request: Request) -> dict:
        """Return the project's current effective manifest as JSON.

        Resolution order:
          1. project_workspaces.manifest_json in the orchestrator store
             (set by draft_manifest_node; doesn't depend on host FS)
          2. Fallback to compose_effective_manifest which reads from
             {workspace_path}/.rka/tools.json (requires bind mount or
             host-equivalent path access)
        """
        import json
        store_: ParkedStore = request.app.state.store
        row = store_.get_project_manifest(project_id)
        if row and row.get("manifest_json"):
            try:
                return json.loads(row["manifest_json"])
            except json.JSONDecodeError:
                pass  # corrupted; fall through to disk-based load

        from orchestrator import manifest as M
        manifest = M.compose_effective_manifest(project_id)
        if manifest is None:
            raise HTTPException(
                status_code=404,
                detail=f"no manifest found for project {project_id} — has onboarding completed?",
            )
        return manifest.to_dict()

    @app.get("/runs")
    async def list_runs(
        request: Request, status: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        store_: ParkedStore = request.app.state.store
        return store_.list_runs(status=status, limit=limit)

    @app.get("/runs/{workflow_thread_id}")
    async def get_run(workflow_thread_id: str, request: Request) -> dict:
        store_: ParkedStore = request.app.state.store
        row = store_.get_run(workflow_thread_id)
        if row is None:
            raise HTTPException(status_code=404, detail="run not found")
        return row

    @app.delete("/runs/{workflow_thread_id}")
    async def cancel_run(workflow_thread_id: str, request: Request) -> dict:
        store_: ParkedStore = request.app.state.store
        if store_.get_run(workflow_thread_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        runner_: OrchestratorRunner = request.app.state.runner
        count = runner_.cancel(workflow_thread_id)
        return {"cancelled_interrupts": count}

    @app.post("/missions/{mission_id}/overrides/cancel")
    async def cancel_mission_overrides(
        mission_id: str, request: Request
    ) -> dict:
        """Phase-X — PI's escape valve. Stamps mission_metadata.overrides_cleared_at
        so future runs' auto-rehydration filters out any prior redirects
        with responded_at <= cleared_at. Use when the PI considers all
        prior pi_greenlight redirects fully absorbed and wants a fresh
        planning slate without garbage-collecting parked_interrupts."""
        store_: ParkedStore = request.app.state.store
        ts = await asyncio.to_thread(
            store_.set_mission_overrides_cleared, mission_id
        )
        return {"mission_id": mission_id, "overrides_cleared_at": ts}

    @app.get("/inbox")
    async def inbox(
        request: Request, workflow_thread_id: Optional[str] = None
    ) -> list[dict]:
        store_: ParkedStore = request.app.state.store
        return store_.list_pending_interrupts(workflow_thread_id=workflow_thread_id)

    @app.post("/inbox/{interrupt_id}/accept")
    async def accept(
        interrupt_id: str, request: Request, wait_segment: bool = True
    ) -> dict:
        return await _respond(
            request, interrupt_id, "accept", None, wait_segment=wait_segment
        )

    @app.post("/inbox/{interrupt_id}/reject")
    async def reject(
        interrupt_id: str,
        body: RejectRequest,
        request: Request,
        wait_segment: bool = True,
    ) -> dict:
        return await _respond(
            request,
            interrupt_id,
            "reject",
            body.reason,
            wait_segment=wait_segment,
        )

    @app.post("/inbox/{interrupt_id}/correct")
    async def correct(
        interrupt_id: str,
        body: CorrectRequest,
        request: Request,
        wait_segment: bool = True,
    ) -> dict:
        return await _respond(
            request,
            interrupt_id,
            "correct",
            body.response_text,
            wait_segment=wait_segment,
        )

    async def _respond(
        request: Request,
        interrupt_id: str,
        action: str,
        response_text: Optional[str],
        *,
        wait_segment: bool,
    ) -> dict:
        """Drive a PI response into the runner.

        wait_segment=True (legacy): commit answer + run the graph
            segment synchronously, return the SegmentOutcome. Used by
            tests + any caller that can tolerate a long-running HTTP
            call (segments are LLM-driven and can run for minutes).

        wait_segment=False: commit the answer synchronously, return an
            ack immediately, and run the graph segment on a background
            task. Used by the MCP-stdio binary so the PI's Claude
            session is never blocked by a 120s httpx timeout while the
            server is happily working. The PI session polls
            `/inbox` and `/runs/{id}` to discover the next state.
        """
        runner_: OrchestratorRunner = request.app.state.runner
        if wait_segment:
            try:
                outcome = await asyncio.to_thread(
                    runner_.respond,
                    interrupt_id=interrupt_id,
                    action=action,
                    response_text=response_text,
                )
            except ValueError as e:
                msg = str(e)
                if "not found" in msg:
                    raise HTTPException(status_code=404, detail=msg)
                if "already in status" in msg:
                    raise HTTPException(status_code=409, detail=msg)
                raise HTTPException(status_code=400, detail=msg)
            return _outcome_dict(outcome)

        # async-resume path: commit synchronously, background the segment.
        try:
            ack = await asyncio.to_thread(
                runner_.commit_response,
                interrupt_id=interrupt_id,
                action=action,
                response_text=response_text,
            )
        except ValueError as e:
            msg = str(e)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg)
            if "already in status" in msg:
                raise HTTPException(status_code=409, detail=msg)
            raise HTTPException(status_code=400, detail=msg)

        # Background-task the segment. runner._execute_segment catches
        # exceptions raised by compiled.invoke and writes them to
        # workflow_runs.last_error itself; but exceptions raised BEFORE
        # invoke (factory/compile/saver instantiation in resume_segment)
        # would otherwise be swallowed and leave status='running' forever.
        # The except clause below covers that gap by writing last_error
        # explicitly so the PI's `/runs/{id}` shows the failure.
        store_ = request.app.state.store

        async def _drive_segment_bg(ack_: dict) -> None:
            try:
                await asyncio.to_thread(
                    runner_.resume_segment,
                    workflow_thread_id=ack_["workflow_thread_id"],
                    interrupt_type=ack_["interrupt_type"],
                    token=ack_["token"],
                    project_id=ack_["project_id"],
                )
            except asyncio.CancelledError:
                # Lifespan shutdown cancelled us; the startup-sweep on
                # next boot will surface the orphan. Re-raise per asyncio
                # convention.
                logger.info(
                    "background segment cancelled for thread %s",
                    ack_["workflow_thread_id"],
                )
                raise
            except Exception as e:  # noqa: BLE001 — background; surface via last_error
                logger.exception(
                    "background segment failed for thread %s after answering "
                    "interrupt %s",
                    ack_["workflow_thread_id"], ack_["interrupt_id"],
                )
                # Write the failure to workflow_runs.last_error so the PI's
                # poll of /runs/{id} surfaces it instead of seeing a stuck
                # status='running'.
                try:
                    store_.update_run(
                        ack_["workflow_thread_id"],
                        status="failed",
                        last_error=f"background segment crashed: {e!r}"[:500],
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "failed to write last_error for thread %s",
                        ack_["workflow_thread_id"],
                    )

        task = asyncio.create_task(_drive_segment_bg(ack))
        # Retain a strong reference so the GC doesn't collect the task
        # mid-run; discard on completion to bound memory.
        request.app.state.bg_segments.add(task)
        task.add_done_callback(request.app.state.bg_segments.discard)

        return {
            "workflow_thread_id": ack["workflow_thread_id"],
            "answered_interrupt_id": ack["interrupt_id"],
            "answered_interrupt_type": ack["interrupt_type"],
            "status": "resuming",
            "wait_segment": False,
        }

    return app
