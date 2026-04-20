-- ============================================================
-- Migration 019 — hooks + hook_executions + brain_notifications
-- ============================================================
-- Mission: mis_01KPJY7B5E232DMKVGV5HCK29F
-- Decision: dec_01KPJXN5QJ029FC93EK2WRNDFJ (hook system v1 minimal)
--
-- Architectural addition — adds the hook primitive to RKA. Hooks are
-- registered handlers that fire on lifecycle events (session_start,
-- post_journal_create, post_claim_extract, post_record_outcome, periodic).
-- Three handler types in v1: sql, mcp_tool, brain_notify. Scope is
-- project-only (global deferred).
--
-- Strictly additive. No existing tables touched.
-- ============================================================

CREATE TABLE IF NOT EXISTS hooks (
    id TEXT PRIMARY KEY,                          -- hk_... ULID
    event TEXT NOT NULL CHECK (event IN (
        'session_start', 'post_journal_create', 'post_claim_extract',
        'post_record_outcome', 'periodic'
    )),
    scope TEXT NOT NULL DEFAULT 'project' CHECK (scope IN ('project')),
    project_id TEXT NOT NULL,
    handler_type TEXT NOT NULL CHECK (handler_type IN (
        'sql', 'mcp_tool', 'brain_notify'
    )),
    handler_config TEXT NOT NULL,                 -- JSON; shape depends on handler_type
    enabled INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT 'pi'
        CHECK (created_by IN ('pi', 'brain', 'executor', 'system')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    failure_policy TEXT NOT NULL DEFAULT 'silent'
        CHECK (failure_policy IN ('silent'))      -- v1 only
);

CREATE INDEX IF NOT EXISTS idx_hooks_dispatch
    ON hooks(project_id, event, enabled);
CREATE INDEX IF NOT EXISTS idx_hooks_created_at
    ON hooks(created_at);


CREATE TABLE IF NOT EXISTS hook_executions (
    id TEXT PRIMARY KEY,                          -- hkx_... ULID
    hook_id TEXT NOT NULL REFERENCES hooks(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    fired_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    payload TEXT,                                 -- JSON; the event payload received
    handler_result TEXT,                          -- JSON; handler's return value (nullable)
    status TEXT NOT NULL CHECK (status IN (
        'success', 'error', 'aborted_depth_limit', 'skipped_disabled'
    )),
    error_message TEXT,                           -- non-null on status='error'
    depth INTEGER NOT NULL DEFAULT 0              -- nesting depth for audit
);

CREATE INDEX IF NOT EXISTS idx_hook_executions_hook
    ON hook_executions(hook_id, fired_at);
CREATE INDEX IF NOT EXISTS idx_hook_executions_project_fired
    ON hook_executions(project_id, fired_at);


CREATE TABLE IF NOT EXISTS brain_notifications (
    id TEXT PRIMARY KEY,                          -- bnt_... ULID
    project_id TEXT NOT NULL,
    hook_id TEXT REFERENCES hooks(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    cleared_at TEXT,                              -- NULL = unread; set when Brain sees it
    content TEXT NOT NULL,                        -- JSON; arbitrary payload
    severity TEXT NOT NULL DEFAULT 'info'
        CHECK (severity IN ('info', 'warning', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_brain_notifications_active
    ON brain_notifications(project_id, cleared_at);
CREATE INDEX IF NOT EXISTS idx_brain_notifications_created
    ON brain_notifications(project_id, created_at);
