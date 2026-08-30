-- Migration 055: durable identity and lifecycle for the derived embedding index.
-- requires-table: embedding_metadata

-- Canonical research records remain authoritative.  This singleton only
-- coordinates the rebuildable vector index across the API and worker
-- processes so an interrupted model/input-space transition can resume safely.
CREATE TABLE embedding_index_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    generation INTEGER NOT NULL CHECK (generation >= 1),
    space_signature TEXT NOT NULL CHECK (length(trim(space_signature)) > 0),
    model_name TEXT NOT NULL CHECK (length(trim(model_name)) > 0),
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    status TEXT NOT NULL
        CHECK (status IN ('ready', 'reindexing', 'failed')),
    last_error TEXT,
    updated_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
