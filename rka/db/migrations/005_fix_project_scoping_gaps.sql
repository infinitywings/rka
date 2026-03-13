-- Ensure the default project has an initialized project_state row.
INSERT OR IGNORE INTO project_states (
    project_id,
    project_name,
    project_description,
    current_phase,
    phases_config,
    created_at,
    updated_at
)
SELECT
    p.id,
    p.name,
    p.description,
    'literature',
    '["literature", "planning", "data_collection", "implementation", "evaluation", "paper_writing"]',
    COALESCE(p.created_at, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    COALESCE(p.updated_at, strftime('%Y-%m-%dT%H:%M:%SZ','now'))
FROM projects p
WHERE p.id = 'proj_default';

-- Extend project scoping to Phase 2 tables that were added before multi-project support.
ALTER TABLE artifacts ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE figures ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE exploration_summaries ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE CASCADE;

UPDATE qa_sessions SET project_id = 'proj_default' WHERE project_id IS NULL;
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
UPDATE artifacts SET project_id = 'proj_default' WHERE project_id IS NULL;
UPDATE exploration_summaries SET project_id = 'proj_default' WHERE project_id IS NULL;
UPDATE figures
SET project_id = COALESCE(
    (SELECT artifacts.project_id FROM artifacts WHERE artifacts.id = figures.artifact_id),
    'proj_default'
)
WHERE project_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id);
CREATE INDEX IF NOT EXISTS idx_figures_project ON figures(project_id);
CREATE INDEX IF NOT EXISTS idx_summaries_project ON exploration_summaries(project_id);
CREATE INDEX IF NOT EXISTS idx_qa_sessions_project ON qa_sessions(project_id);
