-- Migration 034: conservatively project unambiguous legacy Writer manifests
-- into the native manuscript aggregate introduced by migration 033.
--
-- requires-table: projects, journal, tags, manuscripts
--
-- Legacy manuscript identity remains intact: no journal or tag is updated or
-- deleted.  For a conventional ``jrn_<suffix>`` identity, the canonical
-- candidate is deterministically ``man_<suffix>``.  A row is imported only
-- when all of the following are true:
--   * the exact ``manuscript`` tag is in the journal's own project;
--   * exactly one non-empty venue tag is in that project;
--   * exactly one supported Writer phase tag is in that project;
--   * the first verbatim-input paragraph supplies a non-empty title;
--   * the legacy journal is still draft/active and its project exists; and
--   * neither its legacy binding nor its deterministic ID conflicts.
--
-- Every incomplete, ambiguous, or conflicting candidate is recorded below.
-- This migration never infers claims, claim wording, evidence relationships,
-- PI ratifications, or checkpoints.

CREATE TABLE IF NOT EXISTS manuscript_migration_issues (
    legacy_journal_id TEXT NOT NULL,
    project_id TEXT,
    canonical_candidate_id TEXT,
    reason TEXT NOT NULL
        CHECK (reason IN (
            'missing_project',
            'missing_project_record',
            'tag_project_mismatch',
            'invalid_legacy_id',
            'missing_title',
            'missing_venue',
            'ambiguous_venue',
            'missing_phase',
            'ambiguous_phase',
            'unsupported_phase',
            'inactive_legacy_status',
            'deterministic_id_conflict'
        )),
    details TEXT NOT NULL CHECK (json_valid(details)),
    detected_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (legacy_journal_id, reason)
);

CREATE INDEX IF NOT EXISTS idx_manuscript_migration_issues_project
    ON manuscript_migration_issues(project_id, reason, legacy_journal_id);

WITH tagged AS (
    SELECT
        j.id AS legacy_journal_id,
        j.project_id,
        j.verbatim_input,
        j.status AS legacy_status,
        j.created_at,
        j.updated_at,
        'man_' || substr(j.id, 5) AS canonical_candidate_id,
        (
            SELECT count(*)
            FROM tags AS mt
            WHERE mt.entity_type = 'journal'
              AND mt.entity_id = j.id
              AND lower(mt.tag) = 'manuscript'
        ) AS manuscript_tag_count,
        (
            SELECT count(*)
            FROM tags AS mt
            WHERE mt.entity_type = 'journal'
              AND mt.entity_id = j.id
              AND lower(mt.tag) = 'manuscript'
              AND mt.project_id = j.project_id
        ) AS scoped_manuscript_tag_count,
        (
            SELECT count(*)
            FROM tags AS vt
            WHERE vt.entity_type = 'journal'
              AND vt.entity_id = j.id
              AND vt.project_id = j.project_id
              AND lower(substr(vt.tag, 1, 6)) = 'venue:'
        ) AS venue_tag_count,
        (
            SELECT trim(substr(vt.tag, 7))
            FROM tags AS vt
            WHERE vt.entity_type = 'journal'
              AND vt.entity_id = j.id
              AND vt.project_id = j.project_id
              AND lower(substr(vt.tag, 1, 6)) = 'venue:'
            ORDER BY vt.tag COLLATE NOCASE
            LIMIT 1
        ) AS venue,
        (
            SELECT count(*)
            FROM tags AS pt
            WHERE pt.entity_type = 'journal'
              AND pt.entity_id = j.id
              AND pt.project_id = j.project_id
              AND lower(substr(pt.tag, 1, 6)) = 'phase:'
        ) AS phase_tag_count,
        (
            SELECT lower(trim(substr(pt.tag, 7)))
            FROM tags AS pt
            WHERE pt.entity_type = 'journal'
              AND pt.entity_id = j.id
              AND pt.project_id = j.project_id
              AND lower(substr(pt.tag, 1, 6)) = 'phase:'
            ORDER BY pt.tag COLLATE NOCASE
            LIMIT 1
        ) AS phase,
        replace(coalesce(j.verbatim_input, ''), char(13), '') AS normalized_input
    FROM journal AS j
    WHERE EXISTS (
        SELECT 1
        FROM tags AS mt
        WHERE mt.entity_type = 'journal'
          AND mt.entity_id = j.id
          AND lower(mt.tag) = 'manuscript'
    )
),
candidates AS (
    SELECT
        tagged.*,
        CASE
            WHEN instr(normalized_input, char(10) || char(10)) > 0
            THEN trim(substr(
                normalized_input,
                1,
                instr(normalized_input, char(10) || char(10)) - 1
            ))
            ELSE trim(normalized_input)
        END AS title
    FROM tagged
)
INSERT OR IGNORE INTO manuscript_migration_issues (
    legacy_journal_id,
    project_id,
    canonical_candidate_id,
    reason,
    details
)
SELECT
    legacy_journal_id,
    project_id,
    canonical_candidate_id,
    'missing_project',
    json_object('project_id', project_id)
FROM candidates
WHERE project_id IS NULL OR length(trim(project_id)) = 0

UNION ALL

SELECT
    legacy_journal_id,
    project_id,
    canonical_candidate_id,
    'missing_project_record',
    json_object('project_id', project_id)
FROM candidates
WHERE project_id IS NOT NULL
  AND length(trim(project_id)) > 0
  AND NOT EXISTS (
      SELECT 1 FROM projects AS p WHERE p.id = candidates.project_id
  )

UNION ALL

SELECT
    legacy_journal_id,
    project_id,
    canonical_candidate_id,
    'tag_project_mismatch',
    json_object(
        'manuscript_tag_count', manuscript_tag_count,
        'same_project_tag_count', scoped_manuscript_tag_count
    )
FROM candidates
WHERE manuscript_tag_count > 0
  AND manuscript_tag_count <> scoped_manuscript_tag_count

UNION ALL

SELECT
    legacy_journal_id,
    project_id,
    canonical_candidate_id,
    'invalid_legacy_id',
    json_object('expected_prefix', 'jrn_', 'actual_id', legacy_journal_id)
FROM candidates
WHERE substr(legacy_journal_id, 1, 4) <> 'jrn_'
   OR length(legacy_journal_id) <= 4

UNION ALL

SELECT
    legacy_journal_id,
    project_id,
    canonical_candidate_id,
    'missing_title',
    json_object('source', 'journal.verbatim_input:first_paragraph')
FROM candidates
WHERE length(title) = 0

UNION ALL

SELECT
    legacy_journal_id,
    project_id,
    canonical_candidate_id,
    'missing_venue',
    json_object('venue_tag_count', venue_tag_count)
FROM candidates
WHERE venue_tag_count = 0
   OR (venue_tag_count = 1 AND length(coalesce(venue, '')) = 0)

UNION ALL

SELECT
    legacy_journal_id,
    project_id,
    canonical_candidate_id,
    'ambiguous_venue',
    json_object('venue_tag_count', venue_tag_count)
FROM candidates
WHERE venue_tag_count > 1

UNION ALL

SELECT
    legacy_journal_id,
    project_id,
    canonical_candidate_id,
    'missing_phase',
    json_object('phase_tag_count', phase_tag_count)
FROM candidates
WHERE phase_tag_count = 0
   OR (phase_tag_count = 1 AND length(coalesce(phase, '')) = 0)

UNION ALL

SELECT
    legacy_journal_id,
    project_id,
    canonical_candidate_id,
    'ambiguous_phase',
    json_object('phase_tag_count', phase_tag_count)
FROM candidates
WHERE phase_tag_count > 1

UNION ALL

SELECT
    legacy_journal_id,
    project_id,
    canonical_candidate_id,
    'unsupported_phase',
    json_object(
        'phase', phase,
        'supported', json_array('draft', 'drafting', 'review', 'final')
    )
FROM candidates
WHERE phase_tag_count = 1
  AND length(coalesce(phase, '')) > 0
  AND phase NOT IN ('draft', 'drafting', 'review', 'final')

UNION ALL

SELECT
    legacy_journal_id,
    project_id,
    canonical_candidate_id,
    'inactive_legacy_status',
    json_object('status', legacy_status)
FROM candidates
WHERE legacy_status NOT IN ('draft', 'active')

UNION ALL

SELECT
    legacy_journal_id,
    project_id,
    canonical_candidate_id,
    'deterministic_id_conflict',
    json_object(
        'candidate_id', canonical_candidate_id,
        'existing_legacy_journal_id', (
            SELECT m.legacy_journal_id
            FROM manuscripts AS m
            WHERE m.id = candidates.canonical_candidate_id
        ),
        'existing_project_id', (
            SELECT m.project_id
            FROM manuscripts AS m
            WHERE m.id = candidates.canonical_candidate_id
        )
    )
FROM candidates
WHERE NOT EXISTS (
          SELECT 1
          FROM manuscripts AS bound
          WHERE bound.legacy_journal_id = candidates.legacy_journal_id
            AND bound.project_id = candidates.project_id
      )
  AND EXISTS (
      SELECT 1
      FROM manuscripts AS collision
      WHERE collision.id = candidates.canonical_candidate_id
  );

WITH tagged AS (
    SELECT
        j.id AS legacy_journal_id,
        j.project_id,
        j.verbatim_input,
        j.status AS legacy_status,
        j.created_at,
        j.updated_at,
        'man_' || substr(j.id, 5) AS canonical_candidate_id,
        (
            SELECT count(*)
            FROM tags AS mt
            WHERE mt.entity_type = 'journal'
              AND mt.entity_id = j.id
              AND lower(mt.tag) = 'manuscript'
        ) AS manuscript_tag_count,
        (
            SELECT count(*)
            FROM tags AS mt
            WHERE mt.entity_type = 'journal'
              AND mt.entity_id = j.id
              AND lower(mt.tag) = 'manuscript'
              AND mt.project_id = j.project_id
        ) AS scoped_manuscript_tag_count,
        (
            SELECT count(*)
            FROM tags AS vt
            WHERE vt.entity_type = 'journal'
              AND vt.entity_id = j.id
              AND vt.project_id = j.project_id
              AND lower(substr(vt.tag, 1, 6)) = 'venue:'
        ) AS venue_tag_count,
        (
            SELECT trim(substr(vt.tag, 7))
            FROM tags AS vt
            WHERE vt.entity_type = 'journal'
              AND vt.entity_id = j.id
              AND vt.project_id = j.project_id
              AND lower(substr(vt.tag, 1, 6)) = 'venue:'
            ORDER BY vt.tag COLLATE NOCASE
            LIMIT 1
        ) AS venue,
        (
            SELECT count(*)
            FROM tags AS pt
            WHERE pt.entity_type = 'journal'
              AND pt.entity_id = j.id
              AND pt.project_id = j.project_id
              AND lower(substr(pt.tag, 1, 6)) = 'phase:'
        ) AS phase_tag_count,
        (
            SELECT lower(trim(substr(pt.tag, 7)))
            FROM tags AS pt
            WHERE pt.entity_type = 'journal'
              AND pt.entity_id = j.id
              AND pt.project_id = j.project_id
              AND lower(substr(pt.tag, 1, 6)) = 'phase:'
            ORDER BY pt.tag COLLATE NOCASE
            LIMIT 1
        ) AS phase,
        replace(coalesce(j.verbatim_input, ''), char(13), '') AS normalized_input
    FROM journal AS j
    WHERE EXISTS (
        SELECT 1
        FROM tags AS mt
        WHERE mt.entity_type = 'journal'
          AND mt.entity_id = j.id
          AND lower(mt.tag) = 'manuscript'
    )
),
candidates AS (
    SELECT
        tagged.*,
        CASE
            WHEN instr(normalized_input, char(10) || char(10)) > 0
            THEN trim(substr(
                normalized_input,
                1,
                instr(normalized_input, char(10) || char(10)) - 1
            ))
            ELSE trim(normalized_input)
        END AS title,
        CASE
            WHEN instr(normalized_input, char(10) || char(10)) > 0
            THEN nullif(trim(substr(
                normalized_input,
                instr(normalized_input, char(10) || char(10)) + 2
            )), '')
            ELSE NULL
        END AS abstract
    FROM tagged
)
INSERT OR IGNORE INTO manuscripts (
    id,
    project_id,
    title,
    abstract,
    venue,
    phase,
    state,
    legacy_journal_id,
    created_at,
    updated_at
)
SELECT
    canonical_candidate_id,
    project_id,
    title,
    abstract,
    venue,
    CASE phase WHEN 'draft' THEN 'drafting' ELSE phase END,
    'active',
    legacy_journal_id,
    created_at,
    updated_at
FROM candidates
WHERE scoped_manuscript_tag_count = 1
  AND manuscript_tag_count = scoped_manuscript_tag_count
  AND project_id IS NOT NULL
  AND length(trim(project_id)) > 0
  AND EXISTS (
      SELECT 1 FROM projects AS p WHERE p.id = candidates.project_id
  )
  AND substr(legacy_journal_id, 1, 4) = 'jrn_'
  AND length(legacy_journal_id) > 4
  AND length(title) > 0
  AND venue_tag_count = 1
  AND length(coalesce(venue, '')) > 0
  AND phase_tag_count = 1
  AND phase IN ('draft', 'drafting', 'review', 'final')
  AND legacy_status IN ('draft', 'active')
  AND NOT EXISTS (
      SELECT 1
      FROM manuscripts AS bound
      WHERE bound.legacy_journal_id = candidates.legacy_journal_id
        AND bound.project_id = candidates.project_id
  )
  AND NOT EXISTS (
      SELECT 1
      FROM manuscripts AS collision
      WHERE collision.id = candidates.canonical_candidate_id
  );
