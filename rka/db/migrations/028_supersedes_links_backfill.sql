-- Migration 028: materialize supersession as entity_links edges
--
-- Eval-v3 (2026-06-11) found graph traversal from a superseded decision
-- never reaches its replacement: supersession lived only in status flags
-- and superseded_by/supersedes columns, which multi_hop_retrieval /
-- get_ego_graph / collect_report_context cannot see (they walk
-- entity_links + claim_edges only). Same failure class as migration 023's
-- cluster->parent-RQ FK invisibility.
--
-- The decisions live path writes the edge since v2.7.0.7
-- (DecisionService.supersede_decision); the journal path and all
-- pre-v2.7.0.7 rows do not. This migration backfills every supersession
-- recorded in columns; NotesService writes the journal edge going forward.
--
-- Idempotent: INSERT OR IGNORE against migration 020's project-scoped
-- UNIQUE (project_id, source_id, link_type, target_id) triple.

-- 1) journal.supersedes: new entry --supersedes--> old entry
INSERT OR IGNORE INTO entity_links (
    id, source_type, source_id, link_type, target_type, target_id,
    created_by, link_weight, link_reason, project_id
)
SELECT
    printf('lnk_028_%s', lower(hex(randomblob(13)))) AS id,
    'journal', j.id, 'supersedes', 'journal', j.supersedes,
    'migration_028', 1.0,
    'backfill from journal.supersedes column (migration 028)',
    j.project_id
FROM journal j
WHERE j.supersedes IS NOT NULL AND j.supersedes != ''
  AND EXISTS (SELECT 1 FROM journal o WHERE o.id = j.supersedes);

-- 2) journal.superseded_by: successor --supersedes--> this entry
--    (covers rows where only the back-reference survived, e.g. pack
--    round-trips; the UNIQUE triple dedupes overlap with (1))
INSERT OR IGNORE INTO entity_links (
    id, source_type, source_id, link_type, target_type, target_id,
    created_by, link_weight, link_reason, project_id
)
SELECT
    printf('lnk_028_%s', lower(hex(randomblob(13)))) AS id,
    'journal', j.superseded_by, 'supersedes', 'journal', j.id,
    'migration_028', 1.0,
    'backfill from journal.superseded_by column (migration 028)',
    j.project_id
FROM journal j
WHERE j.superseded_by IS NOT NULL AND j.superseded_by != ''
  AND EXISTS (SELECT 1 FROM journal s WHERE s.id = j.superseded_by);

-- 3) decisions.superseded_by: successor --supersedes--> this decision
--    (pre-v2.7.0.7 supersedes calls set columns without the edge)
INSERT OR IGNORE INTO entity_links (
    id, source_type, source_id, link_type, target_type, target_id,
    created_by, link_weight, link_reason, project_id
)
SELECT
    printf('lnk_028_%s', lower(hex(randomblob(13)))) AS id,
    'decision', d.superseded_by, 'supersedes', 'decision', d.id,
    'migration_028', 1.0,
    'backfill from decisions.superseded_by column (migration 028)',
    d.project_id
FROM decisions d
WHERE d.superseded_by IS NOT NULL AND d.superseded_by != ''
  AND EXISTS (SELECT 1 FROM decisions s WHERE s.id = d.superseded_by);
