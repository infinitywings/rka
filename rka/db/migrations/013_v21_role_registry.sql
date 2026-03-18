-- ============================================================
-- Migration 013: v2.1 Role Registry + Event Queue
-- ============================================================
-- Phase 1 of RKA v2.1:
--   - agent_roles: persistent role definitions with JSON subscriptions
--   - role_events: durable role-targeted event inbox/queue

-- ============================================================
-- agent_roles: persistent role definitions
-- ============================================================

CREATE TABLE IF NOT EXISTS agent_roles (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    system_prompt_template TEXT,
    subscriptions TEXT,                -- JSON array of fnmatch-style globs
    subscription_filters TEXT,         -- optional JSON for future filter extensions
    role_state TEXT,                   -- JSON blob for role-specific state
    learnings_digest TEXT,
    autonomy_profile TEXT,             -- JSON: {level, constraints, escalation_rules}
    model TEXT,
    model_tier TEXT,
    tools_config TEXT,                 -- JSON: {allowed_tools, denied_tools, ...}
    active_session_id TEXT,
    last_active_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_agent_roles_project ON agent_roles(project_id);
CREATE INDEX IF NOT EXISTS idx_agent_roles_name ON agent_roles(name);

-- ============================================================
-- role_events: durable role-targeted event queue
-- ============================================================

CREATE TABLE IF NOT EXISTS role_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    target_role_id TEXT NOT NULL REFERENCES agent_roles(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    source_role_id TEXT REFERENCES agent_roles(id) ON DELETE SET NULL,
    source_entity_id TEXT,
    source_entity_type TEXT,
    payload TEXT,                       -- JSON
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'acked', 'expired')),
    priority INTEGER NOT NULL DEFAULT 100,
    depends_on TEXT REFERENCES role_events(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    processed_at TEXT,
    acked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_role_events_project ON role_events(project_id);
CREATE INDEX IF NOT EXISTS idx_role_events_target ON role_events(target_role_id);
CREATE INDEX IF NOT EXISTS idx_role_events_status ON role_events(status);
CREATE INDEX IF NOT EXISTS idx_role_events_type ON role_events(event_type);
CREATE INDEX IF NOT EXISTS idx_role_events_created ON role_events(created_at);
