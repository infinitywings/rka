-- ============================================================
-- Migration 011: Extend event_type CHECK constraint for v2.0
-- ============================================================
-- Adds: decision_superseded, claim_created, claim_verified,
--        cluster_created, cluster_synthesized

-- SQLite cannot ALTER CHECK constraints, so we recreate the table.

CREATE TABLE IF NOT EXISTS events_v2 (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'decision_created', 'decision_updated', 'decision_abandoned', 'decision_superseded',
        'mission_created', 'mission_completed', 'mission_blocked',
        'finding_recorded', 'insight_recorded', 'pi_instruction',
        'checkpoint_created', 'checkpoint_resolved',
        'literature_added', 'literature_cited',
        'phase_changed', 'status_updated',
        'claim_created', 'claim_verified',
        'cluster_created', 'cluster_synthesized',
        'review_flagged', 'review_resolved'
    )),
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    actor TEXT NOT NULL CHECK (actor IN ('brain', 'executor', 'pi', 'llm', 'web_ui', 'system')),
    summary TEXT NOT NULL,
    caused_by_event TEXT REFERENCES events_v2(id),
    caused_by_entity TEXT,
    phase TEXT,
    details TEXT,
    project_id TEXT NOT NULL DEFAULT 'proj_default'
);

INSERT INTO events_v2 (
    id, timestamp, event_type, entity_type, entity_id, actor,
    summary, caused_by_event, caused_by_entity, phase, details, project_id
)
SELECT
    id, timestamp, event_type, entity_type, entity_id, actor,
    summary, caused_by_event, caused_by_entity, phase, details, project_id
FROM events;

DROP TABLE events;
ALTER TABLE events_v2 RENAME TO events;

CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id);
