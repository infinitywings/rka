-- Migration 023: cluster → parent-RQ entity_links backfill (new link_type 'answers').
--
-- Background. Eval-v2's v2.5.0 + v2.5.1 baseline runs scored cluster-anchored
-- scenarios S7 + S9 at 0.67 critical-recall because every traversal from a
-- cluster anchor missed the cluster's parent research-question. Root cause
-- (Brain 2026-05-16 code-trace): `evidence_clusters.research_question_id`
-- is a FOREIGN KEY column that's populated for 101/101 clusters across all
-- 9 projects, but `GraphService.multi_hop_retrieval` and `.get_ego_graph`
-- only walk `entity_links` + `claim_edges`. The FK column is invisible to
-- graph traversal — the edge type simply never existed.
--
-- Fix shape (ratified by Brain in dec_01KRS1ADPD4W6AW2X54MKVXMCR; mission
-- mis_01KRS1D8C0E2FP52D0P6JNB3SX, v2.5.2 patch):
--   - Introduce new link_type 'answers' (cluster -> decision-as-RQ).
--   - Backfill one entity_link per evidence_clusters row with a non-null
--     research_question_id. 101 rows total; idempotent via the
--     project-scoped UNIQUE constraint from migration 020.
--   - FK column remains source of truth. entity_link is a derived index.
--   - ClusterService.create/.update will write the link going forward
--     (parity hook in the same release; see rka/services/clusters.py).
--   - DEFAULT_EDGE_WEIGHTS['answers'] = 1.0 in rka/services/graph.py.
--
-- CHECK constraint extension. Migration 021 added a `CHECK (link_type IN
-- (...))` enumeration to entity_links. Its header documents the procedure
-- for adding new types: "Future types must be added to this CHECK in a
-- follow-up migration." This migration is that follow-up. We use the same
-- table-swap pattern migration 021 used: rename old → CREATE new with the
-- extended CHECK → INSERT SELECT → DROP old → recreate indexes. The new
-- CHECK is strictly looser than 021's (one additional allowed value), so
-- every pre-existing row migrates trivially. No data conflicts possible
-- by construction.
--
-- Mechanical safety of the backfill. Three properties combine:
--   (a) INSERT OR IGNORE against the post-020 unique triple
--       (project_id, source_id, link_type, target_id) — re-runs produce
--       no duplicate rows.
--   (b) WHERE research_question_id IS NOT NULL — clusters with no RQ are
--       silently skipped. Production state today: all 101 have non-null
--       FK; this clause is defensive.
--   (c) Random-suffix ID generation via `printf('lnk_023_%s', lower(...))`
--       — collisions astronomically unlikely; IDs differ on a fresh-DB
--       re-run, but the unique triple drops duplicates regardless.
--
-- Provenance. Mission mis_01KRS1D8C0E2FP52D0P6JNB3SX (D3 from Eval-v2
-- Phase-3 sequencing dec_01KRRM5WKSSX7C3ZXZME0BMVQ9). Fix-shape decision
-- dec_01KRS1ADPD4W6AW2X54MKVXMCR. Eval-v2 source observation in
-- eval-harness/v2/report.md (Finding 3, S7 + S9 cluster-anchored 0.67
-- recall) and the Brain code-trace journal jrn_01KRPGFPPKDB3AHP2DP2M03FY8.

PRAGMA foreign_keys = OFF;

-- =============================================================
-- Step 1: rebuild entity_links with the extended CHECK constraint.
-- Mirrors migration 021's table-swap; one additional allowed
-- link_type value ('answers') in the active group.
-- =============================================================

ALTER TABLE entity_links RENAME TO entity_links_old;

CREATE TABLE entity_links (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    link_type   TEXT NOT NULL CHECK (link_type IN (
        -- Active types (emitted by production code paths)
        'justified_by',
        'informed_by',
        'supersedes',
        'motivated',
        'references',
        'cites',
        'produced',
        'derived_from',
        'resolved_as',
        'answers',
        -- Legacy types preserved for historical rows + backfill compatibility
        'evidence_for',
        'triggered'
    )),
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

-- Recreate the index set from migration 004 (base indexes) + migration 020
-- (project-scoped UNIQUE triple). These are the same definitions migration
-- 021 used to restore post-swap.

CREATE INDEX IF NOT EXISTS idx_entity_links_source ON entity_links(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_target ON entity_links(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_type   ON entity_links(link_type);
CREATE INDEX IF NOT EXISTS idx_entity_links_project ON entity_links(project_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_links_project_triple
    ON entity_links(project_id, source_id, link_type, target_id);

-- =============================================================
-- Step 2: backfill one entity_link per evidence_clusters row with a
-- non-null research_question_id. The link is source=cluster -> target=
-- decision (the RQ), link_type='answers', link_weight=1.0,
-- link_reason names the migration so the row's provenance is self-
-- documenting in audit queries.
-- =============================================================

INSERT OR IGNORE INTO entity_links (
    id, source_type, source_id, link_type, target_type, target_id,
    created_by, link_weight, link_reason, project_id
)
SELECT
    printf('lnk_023_%s', lower(hex(randomblob(13)))) AS id,
    'cluster' AS source_type,
    ec.id AS source_id,
    'answers' AS link_type,
    'decision' AS target_type,
    ec.research_question_id AS target_id,
    'migration_023' AS created_by,
    1.0 AS link_weight,
    'backfill from evidence_clusters.research_question_id FK (migration 023)' AS link_reason,
    ec.project_id AS project_id
FROM evidence_clusters AS ec
WHERE ec.research_question_id IS NOT NULL;

PRAGMA foreign_keys = ON;
