-- Phase 3: Validation Gates — expand checkpoint types to include 'gate'.
-- SQLite doesn't support ALTER CHECK, so we rebuild the table.

CREATE TABLE IF NOT EXISTS checkpoints_v2 (
    id TEXT PRIMARY KEY,
    mission_id TEXT REFERENCES missions(id) ON DELETE CASCADE,
    task_reference TEXT,
    type TEXT NOT NULL CHECK (type IN ('decision', 'clarification', 'inspection', 'gate')),
    description TEXT NOT NULL,
    context TEXT,
    options TEXT,
    recommendation TEXT,
    blocking INTEGER NOT NULL DEFAULT 1,
    resolution TEXT,
    resolved_by TEXT CHECK (resolved_by IN ('pi', 'brain')),
    resolution_rationale TEXT,
    linked_decision_id TEXT REFERENCES decisions(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'resolved', 'dismissed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    resolved_at TEXT,
    project_id TEXT
);

INSERT INTO checkpoints_v2
SELECT id, mission_id, task_reference, type, description, context, options,
       recommendation, blocking, resolution, resolved_by, resolution_rationale,
       linked_decision_id, status, created_at, resolved_at, project_id
FROM checkpoints;

DROP TABLE checkpoints;
ALTER TABLE checkpoints_v2 RENAME TO checkpoints;

CREATE INDEX IF NOT EXISTS idx_checkpoints_status ON checkpoints(status);
CREATE INDEX IF NOT EXISTS idx_checkpoints_mission ON checkpoints(mission_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_type ON checkpoints(type);
