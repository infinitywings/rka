-- Migration 029: extend review_queue.flag CHECK with the KB-wide
-- verification categories (eval-v3 theme-B follow-ups, 2026-06-12):
--
--   'stale_dependency'  -- entity rests on a superseded/retracted upstream
--                          (filed by the staleness blast-radius walker)
--   'unsupported_link'  -- a provenance link exists but the dependent's
--                          content is not supported by the linked evidence
--                          (filed by the claim-support audit)
--
-- Uses the documented table-swap pattern (migrations 006/020/021/023):
-- rename -> CREATE with the new CHECK -> INSERT SELECT -> DROP old ->
-- recreate indexes. Idempotent via IF NOT EXISTS on the final objects;
-- the swap itself is guarded by the migration runner's schema_migrations
-- tracking (one application per database).

ALTER TABLE review_queue RENAME TO review_queue_old;

CREATE TABLE review_queue (
    id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,
    item_id TEXT NOT NULL,
    flag TEXT NOT NULL CHECK (flag IN (
        'low_confidence_cluster', 'potential_contradiction',
        'complex_synthesis_needed', 're_distill_review',
        'cross_topic_link', 'stale_theme',
        'stale_dependency', 'unsupported_link'
    )),
    context TEXT,
    priority INTEGER DEFAULT 100,
    status TEXT DEFAULT 'pending'
        CHECK (status IN ('pending', 'acknowledged', 'resolved', 'dismissed')),
    raised_by TEXT DEFAULT 'llm',
    resolved_by TEXT,
    resolution TEXT,
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    resolved_at TEXT
);

INSERT INTO review_queue (
    id, item_type, item_id, flag, context, priority, status,
    raised_by, resolved_by, resolution, project_id, created_at, resolved_at
)
SELECT
    id, item_type, item_id, flag, context, priority, status,
    raised_by, resolved_by, resolution, project_id, created_at, resolved_at
FROM review_queue_old;

DROP TABLE review_queue_old;

CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status);
CREATE INDEX IF NOT EXISTS idx_review_queue_project ON review_queue(project_id);
