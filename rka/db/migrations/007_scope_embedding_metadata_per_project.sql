-- requires-table: embedding_metadata
PRAGMA foreign_keys = OFF;

ALTER TABLE embedding_metadata RENAME TO embedding_metadata_old;

CREATE TABLE embedding_metadata (
  project_id TEXT NOT NULL DEFAULT 'proj_default',
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  model_name TEXT NOT NULL,
  dimensions INTEGER NOT NULL DEFAULT 768,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  PRIMARY KEY (project_id, entity_type, entity_id)
);

INSERT INTO embedding_metadata (project_id, entity_type, entity_id, content_hash, model_name, dimensions, created_at)
SELECT COALESCE(project_id, 'proj_default'), entity_type, entity_id, content_hash, model_name, dimensions, created_at
FROM embedding_metadata_old;

DROP TABLE embedding_metadata_old;

CREATE INDEX IF NOT EXISTS idx_embedding_metadata_project ON embedding_metadata(project_id);

PRAGMA foreign_keys = ON;
