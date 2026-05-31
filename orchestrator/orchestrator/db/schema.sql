-- ============================================================
-- Orchestrator schema v1 — Phase A (MCP-tools PI surface)
-- Orchestrator-owned SQLite ONLY. Never written to rka.db.
-- Three-storage discipline: workflow position lives in the
-- LangGraph SqliteSaver; this schema holds the PI inbox queue
-- + a thin run-status row keyed on workflow_thread_id.
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- ============================================================
-- workflow_runs — one row per orchestrator_run_start call
-- ============================================================
CREATE TABLE IF NOT EXISTS workflow_runs (
    workflow_thread_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    budget_usd REAL NOT NULL DEFAULT 5.0,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'awaiting_pi', 'complete', 'escalated', 'failed', 'cancelled')),
    current_node TEXT,
    terminal_state TEXT
        CHECK (terminal_state IS NULL OR terminal_state IN ('complete', 'escalated', 'failed')),
    final_report_id TEXT,
    usd_spent REAL NOT NULL DEFAULT 0.0,
    last_error TEXT,
    -- Phase-X (Cross-Run Correction Channel): JSON dict carrying per-run
    -- PI overrides (manual run_instructions kwarg from orchestrator_run_start
    -- AND auto-rehydrated prior pi_greenlight redirects for the same mission).
    -- Stored as TEXT; SQLite's json1 extension queries the contents. Read by
    -- start_run_drive into state["run_overrides"] and prefixed into Brain's
    -- strategy prompt under a delimited "PI OVERRIDES" block. Defaulting to
    -- NULL (not '{}') so the existing `idx_workflow_runs_status` doesn't get
    -- a phantom rebuild on migration.
    run_overrides TEXT DEFAULT NULL,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_status
    ON workflow_runs(status, updated_at);

-- ============================================================
-- parked_interrupts — one row per PI interrupt awaiting response
--
-- Phase-D added 3 interrupt types for the onboarding subgraph
-- (pi_onboarding_topic, pi_toolkit_ratify, pi_credentials_ready).
-- Phase E3 removed the originally-planned pi_extend_toolkit type
-- (mid-stream tool addition) from this table — the runner's accept-
-- token map and the InterruptType literal — because the half-built
-- node was never wired into the graph. Mid-stream tool addition will
-- be reintroduced under a different name when Phase D6 ships.
-- ============================================================
CREATE TABLE IF NOT EXISTS parked_interrupts (
    interrupt_id TEXT PRIMARY KEY,
    workflow_thread_id TEXT NOT NULL
        REFERENCES workflow_runs(workflow_thread_id) ON DELETE CASCADE,
    mission_id TEXT NOT NULL,
    interrupt_type TEXT NOT NULL
        CHECK (interrupt_type IN (
            -- Mission-level interrupts (Phase A)
            'pi_greenlight',
            'pi_decision_select',
            'pi_acceptance',
            -- Onboarding subgraph interrupts (Phase D)
            'pi_onboarding_topic',
            'pi_toolkit_ratify',
            'pi_credentials_ready',
            -- Phase O — project-onboarding workflow interrupts
            'pi_idea_capture',
            'pi_scope_ratify',
            'pi_deepresearch_prompt',
            'pi_claims_review',
            'pi_plan_ratify',
            'pi_phase_entry_ack',
            -- Phase B — orchestrator-level bootstrap (orchestrator/.env)
            'pi_bootstrap_intent',
            'pi_bootstrap_ratify',
            'pi_bootstrap_fill_ack'
        )),
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'answered', 'cancelled')),
    response_action TEXT
        CHECK (response_action IS NULL OR response_action IN ('accept', 'reject', 'correct')),
    response_text TEXT,
    parked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    responded_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_parked_inbox
    ON parked_interrupts(status, parked_at);

CREATE INDEX IF NOT EXISTS idx_parked_by_run
    ON parked_interrupts(workflow_thread_id, status);

-- ============================================================
-- project_workspaces — PI-provided workspace path per project
--
-- The orchestrator does NOT create directories or write files to
-- the host filesystem. Instead, the PI provides an absolute path
-- to their existing project workspace during pi_onboarding_topic.
-- This table records that mapping so downstream operations
-- (manifest read, .env probe, audit journal entry) can locate
-- the PI's files. Each project's tools.json + .env live under
-- {workspace_path}/.rka/.
-- ============================================================
CREATE TABLE IF NOT EXISTS project_workspaces (
    project_id TEXT PRIMARY KEY,
    workspace_path TEXT NOT NULL,
    manifest_json TEXT,             -- ToolManifest JSON (set when draft_manifest emits it)
    manifest_hash TEXT,             -- sha256 of the manifest JSON
    audit_journal_id TEXT,          -- rka_add_note id set by finalize_node
    zotero_collection_key TEXT,     -- Zotero Collection key (8-char alnum) where this project's papers live
    zotero_collection_name TEXT,    -- human-readable name of the collection (project slug)
    registered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ============================================================
-- mission_metadata — per-mission orchestrator-side metadata
--
-- Phase-X (Cross-Run Correction Channel). Tracks an
-- `overrides_cleared_at` timestamp the PI can set via the
-- orchestrator_cancel_overrides MCP tool. The auto-rehydration
-- query in start_run_commit filters parked_interrupts.responded_at
-- > overrides_cleared_at, so the PI has an explicit affordance to
-- declare "all prior redirects absorbed, start fresh" without
-- having to garbage-collect the parked_interrupts table.
-- ============================================================
CREATE TABLE IF NOT EXISTS mission_metadata (
    mission_id TEXT PRIMARY KEY,
    overrides_cleared_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ============================================================
-- schema_migrations — version tracking
--
-- Replaces the sniff-sqlite_master pattern in parked_store.py's
-- `_migrate_*_if_needed` methods. New migrations land as
-- migration_N(conn) functions; their version is recorded here on
-- success. ParkedStore._init_schema reads max(version) and applies
-- newer migrations in order.
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
