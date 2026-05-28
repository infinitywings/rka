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
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_status
    ON workflow_runs(status, updated_at);

-- ============================================================
-- parked_interrupts — one row per PI interrupt awaiting response
--
-- Phase-D added 4 new interrupt types for the onboarding subgraph
-- (pi_onboarding_topic, pi_toolkit_ratify, pi_credentials_ready,
-- pi_extend_toolkit). The first three drive baseline onboarding; the
-- fourth surfaces when a mission mid-stream requests a tool not in
-- the project's baseline manifest (Q1 hybrid lifecycle).
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
            'pi_extend_toolkit',
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
    parked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
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
    registered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
