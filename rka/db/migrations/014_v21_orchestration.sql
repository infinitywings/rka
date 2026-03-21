-- ============================================================
-- Migration 014: v2.1 Phase 5 — Orchestration Control Plane
-- ============================================================
-- Adds:
--   - orchestration_config: project-level autonomy mode + circuit breaker settings
--   - role_cost_log: per-role, per-mission token cost tracking

-- ============================================================
-- orchestration_config: project-level orchestration settings
-- ============================================================

CREATE TABLE IF NOT EXISTS orchestration_config (
    project_id TEXT PRIMARY KEY,
    autonomy_mode TEXT NOT NULL DEFAULT 'manual'
        CHECK (autonomy_mode IN ('manual', 'supervised', 'autonomous', 'paused')),
    -- Circuit breaker settings
    circuit_breaker_enabled INTEGER NOT NULL DEFAULT 1,
    cost_limit_usd REAL NOT NULL DEFAULT 10.0,
    cost_window_hours INTEGER NOT NULL DEFAULT 24,
    circuit_breaker_tripped INTEGER NOT NULL DEFAULT 0,
    circuit_breaker_tripped_at TEXT,
    -- Metadata
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by TEXT  -- actor who last changed settings
);

-- ============================================================
-- role_cost_log: token usage tracking per role per mission
-- ============================================================

CREATE TABLE IF NOT EXISTS role_cost_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    role_id TEXT NOT NULL REFERENCES agent_roles(id) ON DELETE CASCADE,
    mission_id TEXT REFERENCES missions(id) ON DELETE SET NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    model TEXT,
    estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
    description TEXT,   -- what the tokens were spent on
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_role_cost_log_project ON role_cost_log(project_id);
CREATE INDEX IF NOT EXISTS idx_role_cost_log_role ON role_cost_log(role_id);
CREATE INDEX IF NOT EXISTS idx_role_cost_log_mission ON role_cost_log(mission_id);
CREATE INDEX IF NOT EXISTS idx_role_cost_log_created ON role_cost_log(created_at);
