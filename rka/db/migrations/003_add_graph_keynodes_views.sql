-- Add richer edge metadata for graph ranking and explainability
ALTER TABLE entity_links ADD COLUMN link_weight REAL DEFAULT 0.0;
ALTER TABLE entity_links ADD COLUMN link_reason TEXT;

-- Materialized key nodes for condensed graph views
CREATE TABLE IF NOT EXISTS keynodes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('finding', 'literature', 'decision', 'milestone')),
    title TEXT NOT NULL,
    summary TEXT,
    produced_by TEXT,
    importance REAL DEFAULT 0.0,
    node_refs TEXT,
    blessed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_keynodes_kind ON keynodes(kind);
CREATE INDEX IF NOT EXISTS idx_keynodes_importance ON keynodes(importance DESC);
CREATE INDEX IF NOT EXISTS idx_keynodes_blessed ON keynodes(blessed);

-- Cached graph payloads for UI rendering and tuning
CREATE TABLE IF NOT EXISTS graph_views (
    id TEXT PRIMARY KEY,
    name TEXT,
    params TEXT,
    nodes TEXT,
    edges TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_graph_views_created_at ON graph_views(created_at DESC);
