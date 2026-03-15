-- ============================================================
-- Migration 009: RKA v2.0 — Claims, Clusters, Entity Redesign
-- ============================================================
-- Adds: claims, evidence_clusters, claim_edges, topics, entity_topics,
--        context_snapshots, review_queue tables
-- Modifies: journal (type CHECK expanded, new columns),
--           decisions (new columns), missions (new columns)
-- ============================================================

-- ============================================================
-- 1. Journal table recreation (expand type CHECK constraint)
-- ============================================================
-- SQLite cannot ALTER CHECK constraints, so we recreate the table.
-- The new CHECK includes both old types (backward compat) and new types.

CREATE TABLE IF NOT EXISTS journal_v2 (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN (
        'finding', 'insight', 'pi_instruction', 'exploration',
        'idea', 'observation', 'hypothesis', 'methodology', 'summary',
        'note', 'log', 'directive'
    )),
    content TEXT NOT NULL,
    summary TEXT,
    source TEXT NOT NULL CHECK (source IN ('brain', 'executor', 'pi', 'web_ui', 'llm')),
    phase TEXT,
    related_decisions TEXT,
    related_literature TEXT,
    related_mission TEXT,
    supersedes TEXT REFERENCES journal_v2(id) ON DELETE SET NULL,
    superseded_by TEXT,
    confidence TEXT NOT NULL DEFAULT 'hypothesis'
        CHECK (confidence IN ('hypothesis', 'tested', 'verified', 'superseded', 'retracted')),
    importance TEXT NOT NULL DEFAULT 'normal'
        CHECK (importance IN ('critical', 'high', 'normal', 'low', 'archived')),
    -- New v2.0 columns:
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('draft', 'active', 'superseded', 'retracted')),
    pinned INTEGER NOT NULL DEFAULT 0,
    -- Added by migration 004:
    project_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Copy all existing data (status defaults to 'active', pinned defaults to 0)
INSERT INTO journal_v2 (
    id, type, content, summary, source, phase,
    related_decisions, related_literature, related_mission,
    supersedes, superseded_by, confidence, importance,
    status, pinned, project_id, created_at, updated_at
)
SELECT
    id, type, content, summary, source, phase,
    related_decisions, related_literature, related_mission,
    supersedes, superseded_by, confidence, importance,
    'active', 0, project_id, created_at, updated_at
FROM journal;

-- Drop old table and rename
DROP TABLE journal;
ALTER TABLE journal_v2 RENAME TO journal;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_journal_type ON journal(type);
CREATE INDEX IF NOT EXISTS idx_journal_phase ON journal(phase);
CREATE INDEX IF NOT EXISTS idx_journal_confidence ON journal(confidence);
CREATE INDEX IF NOT EXISTS idx_journal_importance ON journal(importance);
CREATE INDEX IF NOT EXISTS idx_journal_created ON journal(created_at);
CREATE INDEX IF NOT EXISTS idx_journal_project ON journal(project_id);
CREATE INDEX IF NOT EXISTS idx_journal_status ON journal(status);

-- Migrate types: old → new
UPDATE journal SET type = 'note' WHERE type IN (
    'finding', 'insight', 'idea', 'observation', 'exploration', 'hypothesis', 'summary'
);
UPDATE journal SET type = 'log' WHERE type = 'methodology';
UPDATE journal SET type = 'directive' WHERE type = 'pi_instruction';

-- ============================================================
-- 2. Decision table modifications
-- ============================================================

ALTER TABLE decisions ADD COLUMN superseded_by TEXT REFERENCES decisions(id);
ALTER TABLE decisions ADD COLUMN scope_version INTEGER DEFAULT 1;
ALTER TABLE decisions ADD COLUMN kind TEXT DEFAULT 'decision'
    CHECK (kind IN ('research_question', 'design_choice', 'decision', 'operational'));
ALTER TABLE decisions ADD COLUMN related_journal TEXT;  -- JSON: ["jrn_01H...", ...]

-- ============================================================
-- 3. Mission table modifications
-- ============================================================

ALTER TABLE missions ADD COLUMN iteration INTEGER DEFAULT 1;
ALTER TABLE missions ADD COLUMN parent_mission_id TEXT REFERENCES missions(id);
ALTER TABLE missions ADD COLUMN motivated_by_decision TEXT REFERENCES decisions(id);

-- ============================================================
-- 4. New table: claims
-- ============================================================

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,                    -- ULID with clm_ prefix
    source_entry_id TEXT NOT NULL REFERENCES journal(id),
    claim_type TEXT NOT NULL CHECK (claim_type IN (
        'hypothesis', 'evidence', 'method', 'result', 'observation', 'assumption'
    )),
    content TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,            -- 0.0 to 1.0
    verified INTEGER DEFAULT 0,            -- 1 = passed factored verification
    stale INTEGER DEFAULT 0,               -- 1 = source decision was superseded
    source_offset_start INTEGER,           -- character offset in source entry
    source_offset_end INTEGER,
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_claims_source ON claims(source_entry_id);
CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type);
CREATE INDEX IF NOT EXISTS idx_claims_stale ON claims(stale);
CREATE INDEX IF NOT EXISTS idx_claims_project ON claims(project_id);

-- ============================================================
-- 5. New table: evidence_clusters
-- ============================================================

CREATE TABLE IF NOT EXISTS evidence_clusters (
    id TEXT PRIMARY KEY,                    -- ULID with ecl_ prefix
    research_question_id TEXT,             -- FK to decisions(id) where kind = 'research_question'
    label TEXT NOT NULL,                   -- short name, e.g. "broker limits"
    synthesis TEXT,                        -- LLM-generated paragraph summary
    confidence TEXT DEFAULT 'emerging'
        CHECK (confidence IN ('strong', 'moderate', 'emerging', 'contested', 'refuted')),
    claim_count INTEGER DEFAULT 0,         -- denormalized
    gap_count INTEGER DEFAULT 0,
    needs_reprocessing INTEGER DEFAULT 0,  -- 1 = flagged for re-distillation
    synthesized_by TEXT DEFAULT 'llm'
        CHECK (synthesized_by IN ('llm', 'brain')),
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_clusters_rq ON evidence_clusters(research_question_id);
CREATE INDEX IF NOT EXISTS idx_clusters_project ON evidence_clusters(project_id);

-- ============================================================
-- 6. New table: claim_edges
-- ============================================================

CREATE TABLE IF NOT EXISTS claim_edges (
    id TEXT PRIMARY KEY,
    source_claim_id TEXT NOT NULL REFERENCES claims(id),
    target_claim_id TEXT,                  -- null for cluster membership
    cluster_id TEXT REFERENCES evidence_clusters(id),
    relation TEXT NOT NULL CHECK (relation IN (
        'member_of', 'supports', 'contradicts', 'qualifies', 'supersedes'
    )),
    confidence REAL DEFAULT 0.5,
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_claim_edges_source ON claim_edges(source_claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_edges_cluster ON claim_edges(cluster_id);
CREATE INDEX IF NOT EXISTS idx_claim_edges_project ON claim_edges(project_id);

-- ============================================================
-- 7. New table: topics
-- ============================================================

CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,                    -- ULID with top_ prefix
    name TEXT NOT NULL,                    -- e.g. "mqtt/scalability"
    parent_id TEXT REFERENCES topics(id),  -- for hierarchy
    description TEXT,
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Junction: entity-to-topic membership
CREATE TABLE IF NOT EXISTS entity_topics (
    topic_id TEXT NOT NULL REFERENCES topics(id),
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    assigned_by TEXT DEFAULT 'llm',         -- llm | brain | pi
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (topic_id, entity_type, entity_id)
);

-- ============================================================
-- 8. New table: context_snapshots
-- ============================================================

CREATE TABLE IF NOT EXISTS context_snapshots (
    id TEXT PRIMARY KEY,
    entry_ids TEXT NOT NULL,               -- JSON array
    query TEXT,
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ============================================================
-- 9. New table: review_queue
-- ============================================================

CREATE TABLE IF NOT EXISTS review_queue (
    id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,              -- entity type needing review
    item_id TEXT NOT NULL,                -- entity ID
    flag TEXT NOT NULL CHECK (flag IN (
        'low_confidence_cluster', 'potential_contradiction',
        'complex_synthesis_needed', 're_distill_review',
        'cross_topic_link', 'stale_theme'
    )),
    context TEXT,                         -- JSON: what the local LLM noticed
    priority INTEGER DEFAULT 100,        -- lower = higher priority
    status TEXT DEFAULT 'pending'
        CHECK (status IN ('pending', 'acknowledged', 'resolved', 'dismissed')),
    raised_by TEXT DEFAULT 'llm',
    resolved_by TEXT,                    -- brain | pi
    resolution TEXT,
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status);
CREATE INDEX IF NOT EXISTS idx_review_queue_project ON review_queue(project_id);

-- ============================================================
-- 10. FTS5 for claims (no extension needed)
-- ============================================================

CREATE VIRTUAL TABLE IF NOT EXISTS fts_claims USING fts5(
    id UNINDEXED, content, tokenize='porter unicode61'
);

-- ============================================================
-- 11. entity_links link_type vocabulary update (documentation only)
-- ============================================================
-- The entity_links table has NO CHECK constraint on link_type.
-- New valid link types (enforced at service layer):
--   Provenance: informed_by, justified_by, motivated, produced, derived_from
--   Knowledge:  cites, references, supports, contradicts, builds_on
--   Lifecycle:  supersedes, resolved_as
--   Legacy:     triggered, evidence_for (deprecated, may exist in old data)
