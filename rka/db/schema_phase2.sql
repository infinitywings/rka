-- Phase 2 schema additions: FTS5 + sqlite-vec + embedding metadata
-- Run AFTER schema.sql. Idempotent (uses IF NOT EXISTS).

-- ============ FTS5 Full-Text Search ============

CREATE VIRTUAL TABLE IF NOT EXISTS fts_journal USING fts5(
    id UNINDEXED,
    content,
    summary,
    tokenize='porter unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_decisions USING fts5(
    id UNINDEXED,
    question,
    rationale,
    tokenize='porter unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_literature USING fts5(
    id UNINDEXED,
    title,
    abstract,
    notes,
    tokenize='porter unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_missions USING fts5(
    id UNINDEXED,
    objective,
    context,
    tokenize='porter unicode61'
);

-- ============ sqlite-vec Vector Tables ============
-- These require the sqlite-vec extension to be loaded.
-- Each table stores 768-dimensional float32 vectors (nomic-embed-text-v1.5).

CREATE VIRTUAL TABLE IF NOT EXISTS vec_journal USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[768]
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_decisions USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[768]
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_literature USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[768]
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_missions USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[768]
);

-- ============ Embedding Metadata ============
-- Tracks which content was embedded (for staleness detection).

CREATE TABLE IF NOT EXISTS embedding_metadata (
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    model_name  TEXT NOT NULL,
    dimensions  INTEGER NOT NULL DEFAULT 768,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (project_id, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_embedding_metadata_project ON embedding_metadata(project_id);
