-- Multi-project foundation (shared DB, project-scoped data)

-- Canonical projects registry
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Per-project state (replacement for singleton project_state id=1 model)
CREATE TABLE IF NOT EXISTS project_states (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    project_name TEXT NOT NULL,
    project_description TEXT,
    current_phase TEXT,
    phases_config TEXT,
    summary TEXT,
    blockers TEXT,
    metrics TEXT,
    created_at TEXT,
    updated_at TEXT
);

-- Ensure the default legacy-compatible project exists
INSERT OR IGNORE INTO projects (id, name, description, created_by)
VALUES ('proj_default', 'Default Project', 'Migrated legacy singleton project', 'system');

-- Seed project_states from singleton project_state if present
INSERT OR IGNORE INTO project_states (
    project_id,
    project_name,
    project_description,
    current_phase,
    phases_config,
    summary,
    blockers,
    metrics,
    created_at,
    updated_at
)
SELECT
    'proj_default',
    project_name,
    project_description,
    current_phase,
    phases_config,
    summary,
    blockers,
    metrics,
    created_at,
    updated_at
FROM project_state
WHERE id = 1;

-- Project scoping columns (nullable for backward compatibility during rollout)
ALTER TABLE decisions ADD COLUMN project_id TEXT;
ALTER TABLE missions ADD COLUMN project_id TEXT;
ALTER TABLE literature ADD COLUMN project_id TEXT;
ALTER TABLE journal ADD COLUMN project_id TEXT;
ALTER TABLE checkpoints ADD COLUMN project_id TEXT;
ALTER TABLE events ADD COLUMN project_id TEXT;
ALTER TABLE audit_log ADD COLUMN project_id TEXT;
ALTER TABLE tags ADD COLUMN project_id TEXT;
ALTER TABLE bootstrap_log ADD COLUMN project_id TEXT;
ALTER TABLE entity_links ADD COLUMN project_id TEXT;
ALTER TABLE keynodes ADD COLUMN project_id TEXT;
ALTER TABLE graph_views ADD COLUMN project_id TEXT;

-- Backfill existing rows into default project scope
UPDATE decisions SET project_id = 'proj_default' WHERE project_id IS NULL;
UPDATE missions SET project_id = 'proj_default' WHERE project_id IS NULL;
UPDATE literature SET project_id = 'proj_default' WHERE project_id IS NULL;
UPDATE journal SET project_id = 'proj_default' WHERE project_id IS NULL;
UPDATE checkpoints SET project_id = 'proj_default' WHERE project_id IS NULL;
UPDATE events SET project_id = 'proj_default' WHERE project_id IS NULL;
UPDATE audit_log SET project_id = 'proj_default' WHERE project_id IS NULL;
UPDATE tags SET project_id = 'proj_default' WHERE project_id IS NULL;
UPDATE bootstrap_log SET project_id = 'proj_default' WHERE project_id IS NULL;
UPDATE entity_links SET project_id = 'proj_default' WHERE project_id IS NULL;
UPDATE keynodes SET project_id = 'proj_default' WHERE project_id IS NULL;
UPDATE graph_views SET project_id = 'proj_default' WHERE project_id IS NULL;

-- Indexes for project-scoped queries
CREATE INDEX IF NOT EXISTS idx_decisions_project ON decisions(project_id);
CREATE INDEX IF NOT EXISTS idx_missions_project ON missions(project_id);
CREATE INDEX IF NOT EXISTS idx_literature_project ON literature(project_id);
CREATE INDEX IF NOT EXISTS idx_journal_project ON journal(project_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_project ON checkpoints(project_id);
CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id);
CREATE INDEX IF NOT EXISTS idx_audit_project ON audit_log(project_id);
CREATE INDEX IF NOT EXISTS idx_tags_project ON tags(project_id);
CREATE INDEX IF NOT EXISTS idx_bootstrap_project ON bootstrap_log(project_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_project ON entity_links(project_id);
CREATE INDEX IF NOT EXISTS idx_keynodes_project ON keynodes(project_id);
CREATE INDEX IF NOT EXISTS idx_graph_views_project ON graph_views(project_id);
