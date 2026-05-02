-- Migration 020: project-scope the entity_links UNIQUE constraint.
--
-- Background. Migration 004 added project_id to entity_links but did not
-- update the UNIQUE constraint. Result: cross-project (source_id, link_type,
-- target_id) collisions were silently dropped via INSERT OR IGNORE. The
-- constraint pre-dated multi-project support; this migration retrofits it,
-- mirroring migration 006's per-project DOI treatment for literature.
--
-- Mechanical safety of the migration. The old UNIQUE(source_id, link_type,
-- target_id) enforced GLOBAL uniqueness across all projects. The new
-- UNIQUE(project_id, source_id, link_type, target_id) is STRICTLY LOOSER —
-- it permits the same triple across different projects. Migrating from a
-- strict constraint to a strictly-weaker one cannot produce conflicts: any
-- row that satisfied the old constraint also satisfies the new one. No
-- migration-time data conflicts are possible by construction. The data
-- cleanup steps below correct rows whose project_id was mistagged at create
-- time (24 rows surfaced by the pre-migration audit in
-- mis_01KQMWJ5EA9GKMQKQ8JT4M4FJE) so the data accurately reflects each
-- relationship's project context — they aren't required for the migration
-- to succeed, only to make the state correct.
--
-- Provenance. Mission mis_01KQMWJ5EA9GKMQKQ8JT4M4FJE; pre-migration audit
-- and resolution rationale in checkpoint chk_01KQMXH6WA8T3WKPN312RWW45S
-- (ratified-with-surfaces). Latent bug log in jrn_01KQJKPDD80HABE12GFAMZ3GW6.

PRAGMA foreign_keys = OFF;

-- =============================================================
-- Step 1: data cleanup. Set project_id from source's project_id
-- for rows where it's NULL or mismatched. One UPDATE per source_type
-- because each source table is named differently. Each UPDATE is a
-- no-op for rows already correctly tagged.
-- =============================================================

UPDATE entity_links
SET project_id = (
    SELECT project_id FROM journal WHERE journal.id = entity_links.source_id
)
WHERE source_type = 'journal'
  AND EXISTS (SELECT 1 FROM journal WHERE journal.id = entity_links.source_id)
  AND (
    project_id IS NULL OR
    project_id != (SELECT project_id FROM journal WHERE journal.id = entity_links.source_id)
  );

UPDATE entity_links
SET project_id = (
    SELECT project_id FROM decisions WHERE decisions.id = entity_links.source_id
)
WHERE source_type = 'decision'
  AND EXISTS (SELECT 1 FROM decisions WHERE decisions.id = entity_links.source_id)
  AND (
    project_id IS NULL OR
    project_id != (SELECT project_id FROM decisions WHERE decisions.id = entity_links.source_id)
  );

UPDATE entity_links
SET project_id = (
    SELECT project_id FROM missions WHERE missions.id = entity_links.source_id
)
WHERE source_type = 'mission'
  AND EXISTS (SELECT 1 FROM missions WHERE missions.id = entity_links.source_id)
  AND (
    project_id IS NULL OR
    project_id != (SELECT project_id FROM missions WHERE missions.id = entity_links.source_id)
  );

UPDATE entity_links
SET project_id = (
    SELECT project_id FROM literature WHERE literature.id = entity_links.source_id
)
WHERE source_type = 'literature'
  AND EXISTS (SELECT 1 FROM literature WHERE literature.id = entity_links.source_id)
  AND (
    project_id IS NULL OR
    project_id != (SELECT project_id FROM literature WHERE literature.id = entity_links.source_id)
  );

UPDATE entity_links
SET project_id = (
    SELECT project_id FROM checkpoints WHERE checkpoints.id = entity_links.source_id
)
WHERE source_type = 'checkpoint'
  AND EXISTS (SELECT 1 FROM checkpoints WHERE checkpoints.id = entity_links.source_id)
  AND (
    project_id IS NULL OR
    project_id != (SELECT project_id FROM checkpoints WHERE checkpoints.id = entity_links.source_id)
  );

UPDATE entity_links
SET project_id = (
    SELECT project_id FROM claims WHERE claims.id = entity_links.source_id
)
WHERE source_type = 'claim'
  AND EXISTS (SELECT 1 FROM claims WHERE claims.id = entity_links.source_id)
  AND (
    project_id IS NULL OR
    project_id != (SELECT project_id FROM claims WHERE claims.id = entity_links.source_id)
  );

UPDATE entity_links
SET project_id = (
    SELECT project_id FROM evidence_clusters WHERE evidence_clusters.id = entity_links.source_id
)
WHERE source_type = 'cluster'
  AND EXISTS (SELECT 1 FROM evidence_clusters WHERE evidence_clusters.id = entity_links.source_id)
  AND (
    project_id IS NULL OR
    project_id != (SELECT project_id FROM evidence_clusters WHERE evidence_clusters.id = entity_links.source_id)
  );

-- =============================================================
-- Step 2: rebuild entity_links with new constraint structure.
-- SQLite cannot ALTER an existing UNIQUE constraint, so we follow
-- migration 006's table-swap pattern.
-- =============================================================

ALTER TABLE entity_links RENAME TO entity_links_old;

CREATE TABLE entity_links (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    link_type   TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by  TEXT,
    link_weight REAL DEFAULT 0.0,
    link_reason TEXT,
    project_id  TEXT
);

INSERT INTO entity_links (
    id, source_type, source_id, link_type, target_type, target_id,
    created_at, created_by, link_weight, link_reason, project_id
)
SELECT
    id, source_type, source_id, link_type, target_type, target_id,
    created_at, created_by, link_weight, link_reason, project_id
FROM entity_links_old;

DROP TABLE entity_links_old;

-- =============================================================
-- Step 3: indices. Reapply existing index set; add the new
-- project-scoped UNIQUE as a partial index to mirror migration
-- 006's pattern (UNIQUE INDEX rather than table-level constraint).
-- =============================================================

CREATE INDEX IF NOT EXISTS idx_entity_links_source ON entity_links(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_target ON entity_links(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_type   ON entity_links(link_type);
CREATE INDEX IF NOT EXISTS idx_entity_links_project ON entity_links(project_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_links_project_triple
    ON entity_links(project_id, source_id, link_type, target_id);

PRAGMA foreign_keys = ON;
