-- Migration 036: canonical, worker-owned asynchronous reference validation.
--
-- Migration 032 made validation attestations immutable but bound
-- ``manuscript_id`` directly to the legacy journal table.  Native
-- manuscripts may not have a journal alias, so retain the historical/requested
-- id while adding the canonical ``man_`` identity and durable job provenance.
--
-- The table is rebuilt instead of altered so native-only manuscript ids can
-- be stored in ``manuscript_id``.  Existing rows are copied byte-for-byte in
-- their original columns; canonical ids are filled only by an exact
-- legacy_journal_id match and are otherwise left NULL.  No manuscript,
-- semantic claim, or validation result is inferred.

DROP TRIGGER IF EXISTS trg_reference_validations_no_update;
DROP TRIGGER IF EXISTS trg_reference_validations_no_delete;
DROP TRIGGER IF EXISTS trg_change_reference_validations_insert;
DROP TRIGGER IF EXISTS trg_change_reference_validations_update;
DROP TRIGGER IF EXISTS trg_change_reference_validations_delete;
DROP INDEX IF EXISTS idx_reference_validations_manuscript;
DROP INDEX IF EXISTS idx_reference_validations_literature;
DROP INDEX IF EXISTS idx_reference_validations_status;

-- Composite parent keys let every optional provenance edge prove that the
-- referenced row belongs to the attestation's project.  Migration 032 used
-- global id-only foreign keys, so invalid historical edges are quarantined
-- below rather than allowed to abort the upgrade.
CREATE UNIQUE INDEX IF NOT EXISTS uq_literature_id_project
    ON literature(id, project_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_id_project
    ON jobs(id, project_id);

ALTER TABLE reference_validation_attestations
    RENAME TO reference_validation_attestations_legacy_036;

CREATE TABLE IF NOT EXISTS reference_validation_migration_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    attestation_id TEXT NOT NULL,
    issue_code TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}'
        CHECK (
            CASE WHEN json_valid(details)
                THEN json_type(details) = 'object'
                ELSE 0
            END
        ),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (attestation_id, issue_code)
);

CREATE TABLE reference_validation_attestations (
    id TEXT PRIMARY KEY,                         -- rvd_... ULID
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    manuscript_id TEXT NOT NULL,                 -- requested/historical id
    canonical_manuscript_id TEXT,                -- authoritative man_ id
    legacy_journal_id TEXT,                      -- optional requested jrn_ alias
    validation_job_id TEXT,                      -- durable job provenance
    literature_id TEXT,
    input_doi TEXT,
    input_title TEXT,
    input_authors TEXT NOT NULL DEFAULT '[]',    -- JSON
    status TEXT NOT NULL,
    retraction_check_enabled INTEGER NOT NULL
        CHECK (retraction_check_enabled IN (0, 1)),
    retraction_checked INTEGER NOT NULL
        CHECK (retraction_checked IN (0, 1)),
    sources_tried TEXT NOT NULL DEFAULT '[]',    -- JSON
    sources_confirmed TEXT NOT NULL DEFAULT '[]',-- JSON
    notes TEXT NOT NULL DEFAULT '[]',            -- JSON
    stage_trace TEXT NOT NULL DEFAULT '{}',      -- JSON
    full_json_payload TEXT NOT NULL,
    pipeline_version TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (
        canonical_manuscript_id IS NULL
        OR substr(canonical_manuscript_id, 1, 4) = 'man_'
    ),
    CHECK (
        legacy_journal_id IS NULL
        OR substr(legacy_journal_id, 1, 4) = 'jrn_'
    ),
    CHECK (
        CASE WHEN json_valid(input_authors)
            THEN json_type(input_authors) = 'array'
            ELSE 0
        END
    ),
    CHECK (
        CASE WHEN json_valid(sources_tried)
            THEN json_type(sources_tried) = 'array'
            ELSE 0
        END
    ),
    CHECK (
        CASE WHEN json_valid(sources_confirmed)
            THEN json_type(sources_confirmed) = 'array'
            ELSE 0
        END
    ),
    CHECK (
        CASE WHEN json_valid(notes)
            THEN json_type(notes) = 'array'
            ELSE 0
        END
    ),
    CHECK (
        CASE WHEN json_valid(stage_trace)
            THEN json_type(stage_trace) = 'object'
            ELSE 0
        END
    ),
    CHECK (
        CASE WHEN json_valid(full_json_payload)
            THEN json_type(full_json_payload) = 'object'
            ELSE 0
        END
    ),
    FOREIGN KEY (canonical_manuscript_id, project_id)
        REFERENCES manuscripts(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (legacy_journal_id, project_id)
        REFERENCES journal(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (validation_job_id, project_id)
        REFERENCES jobs(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (literature_id, project_id)
        REFERENCES literature(id, project_id) ON DELETE RESTRICT
);

INSERT INTO reference_validation_attestations (
    id, project_id, manuscript_id, canonical_manuscript_id,
    legacy_journal_id, validation_job_id, literature_id,
    input_doi, input_title, input_authors, status,
    retraction_check_enabled, retraction_checked,
    sources_tried, sources_confirmed, notes, stage_trace,
    full_json_payload, pipeline_version, started_at, completed_at, created_at
)
SELECT
    old.id,
    old.project_id,
    old.manuscript_id,
    (
        SELECT m.id
        FROM manuscripts AS m
        WHERE m.project_id = old.project_id
          AND m.legacy_journal_id = old.manuscript_id
        LIMIT 1
    ),
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM journal AS j
            WHERE j.id = old.manuscript_id
              AND j.project_id = old.project_id
        )
        THEN old.manuscript_id
        ELSE NULL
    END,
    NULL,
    CASE
        WHEN old.literature_id IS NULL THEN NULL
        WHEN EXISTS (
            SELECT 1
            FROM literature AS l
            WHERE l.id = old.literature_id
              AND l.project_id = old.project_id
        )
        THEN old.literature_id
        ELSE NULL
    END,
    old.input_doi,
    old.input_title,
    CASE
        WHEN json_valid(old.input_authors) THEN
            CASE WHEN json_type(old.input_authors) = 'array'
                THEN old.input_authors ELSE '[]' END
        ELSE '[]'
    END,
    old.status,
    old.retraction_check_enabled,
    old.retraction_checked,
    CASE
        WHEN json_valid(old.sources_tried) THEN
            CASE WHEN json_type(old.sources_tried) = 'array'
                THEN old.sources_tried ELSE '[]' END
        ELSE '[]'
    END,
    CASE
        WHEN json_valid(old.sources_confirmed) THEN
            CASE WHEN json_type(old.sources_confirmed) = 'array'
                THEN old.sources_confirmed ELSE '[]' END
        ELSE '[]'
    END,
    CASE
        WHEN json_valid(old.notes) THEN
            CASE WHEN json_type(old.notes) = 'array'
                THEN old.notes ELSE '[]' END
        ELSE '[]'
    END,
    CASE
        WHEN json_valid(old.stage_trace) THEN
            CASE WHEN json_type(old.stage_trace) = 'object'
                THEN old.stage_trace ELSE '{}' END
        ELSE '{}'
    END,
    CASE
        WHEN json_valid(old.full_json_payload) THEN
            CASE WHEN json_type(old.full_json_payload) = 'object'
                THEN old.full_json_payload
                ELSE json_object(
                    'migration_normalized', 1,
                    'legacy_payload', json(old.full_json_payload)
                )
            END
        ELSE json_object(
            'migration_normalized', 1,
            'legacy_payload_text', old.full_json_payload
        )
    END,
    old.pipeline_version,
    old.started_at,
    old.completed_at,
    old.created_at
FROM reference_validation_attestations_legacy_036 AS old;

INSERT INTO reference_validation_migration_issues (
    project_id, attestation_id, issue_code, details
)
SELECT
    old.project_id,
    old.id,
    'manuscript_project_mismatch',
    json_object('requested_manuscript_id', old.manuscript_id)
FROM reference_validation_attestations_legacy_036 AS old
WHERE NOT EXISTS (
    SELECT 1
    FROM journal AS j
    WHERE j.id = old.manuscript_id
      AND j.project_id = old.project_id
);

INSERT INTO reference_validation_migration_issues (
    project_id, attestation_id, issue_code, details
)
SELECT
    old.project_id,
    old.id,
    'literature_project_mismatch',
    json_object('requested_literature_id', old.literature_id)
FROM reference_validation_attestations_legacy_036 AS old
WHERE old.literature_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM literature AS l
      WHERE l.id = old.literature_id
        AND l.project_id = old.project_id
  );

INSERT INTO reference_validation_migration_issues (
    project_id, attestation_id, issue_code, details
)
SELECT old.project_id, old.id, 'invalid_json_input_authors',
       json_object('field', 'input_authors')
FROM reference_validation_attestations_legacy_036 AS old
WHERE CASE WHEN json_valid(old.input_authors)
        THEN json_type(old.input_authors) <> 'array'
        ELSE 1
      END
UNION ALL
SELECT old.project_id, old.id, 'invalid_json_sources_tried',
       json_object('field', 'sources_tried')
FROM reference_validation_attestations_legacy_036 AS old
WHERE CASE WHEN json_valid(old.sources_tried)
        THEN json_type(old.sources_tried) <> 'array'
        ELSE 1
      END
UNION ALL
SELECT old.project_id, old.id, 'invalid_json_sources_confirmed',
       json_object('field', 'sources_confirmed')
FROM reference_validation_attestations_legacy_036 AS old
WHERE CASE WHEN json_valid(old.sources_confirmed)
        THEN json_type(old.sources_confirmed) <> 'array'
        ELSE 1
      END
UNION ALL
SELECT old.project_id, old.id, 'invalid_json_notes',
       json_object('field', 'notes')
FROM reference_validation_attestations_legacy_036 AS old
WHERE CASE WHEN json_valid(old.notes)
        THEN json_type(old.notes) <> 'array'
        ELSE 1
      END
UNION ALL
SELECT old.project_id, old.id, 'invalid_json_stage_trace',
       json_object('field', 'stage_trace')
FROM reference_validation_attestations_legacy_036 AS old
WHERE CASE WHEN json_valid(old.stage_trace)
        THEN json_type(old.stage_trace) <> 'object'
        ELSE 1
      END
UNION ALL
SELECT old.project_id, old.id, 'invalid_json_full_json_payload',
       json_object('field', 'full_json_payload')
FROM reference_validation_attestations_legacy_036 AS old
WHERE CASE WHEN json_valid(old.full_json_payload)
        THEN json_type(old.full_json_payload) <> 'object'
        ELSE 1
      END;

DROP TABLE reference_validation_attestations_legacy_036;

CREATE INDEX idx_reference_validations_manuscript
    ON reference_validation_attestations(
        project_id, manuscript_id, created_at
    );
CREATE INDEX idx_reference_validations_canonical
    ON reference_validation_attestations(
        project_id, canonical_manuscript_id, created_at
    );
CREATE INDEX idx_reference_validations_job
    ON reference_validation_attestations(validation_job_id);
CREATE UNIQUE INDEX uq_reference_validations_job
    ON reference_validation_attestations(validation_job_id)
    WHERE validation_job_id IS NOT NULL;
CREATE INDEX idx_reference_validations_literature
    ON reference_validation_attestations(
        project_id, literature_id, created_at
    );
CREATE INDEX idx_reference_validations_status
    ON reference_validation_attestations(project_id, status, created_at);

CREATE TRIGGER trg_reference_validations_no_update
BEFORE UPDATE ON reference_validation_attestations
BEGIN
    SELECT RAISE(ABORT, 'reference validation attestations are immutable');
END;

CREATE TRIGGER trg_reference_validations_no_delete
BEFORE DELETE ON reference_validation_attestations
BEGIN
    SELECT RAISE(ABORT, 'reference validation attestations are immutable');
END;

CREATE TRIGGER trg_reference_validations_validate_job
BEFORE INSERT ON reference_validation_attestations
WHEN NEW.validation_job_id IS NOT NULL
 AND (
    NEW.canonical_manuscript_id IS NULL
    OR NOT EXISTS (
        SELECT 1
        FROM jobs AS j
        WHERE j.id = NEW.validation_job_id
          AND j.project_id = NEW.project_id
          AND j.job_type = 'reference_validate'
          AND j.entity_type = 'manuscript'
          AND j.entity_id = NEW.canonical_manuscript_id
    )
 )
BEGIN
    SELECT RAISE(
        ABORT,
        'validation job must be a same-project reference_validate manuscript job'
    );
END;

-- Preserve the semantic cursor contract from migration 035, now using the
-- canonical manuscript id directly when it is known.
CREATE TRIGGER trg_change_reference_validations_insert
AFTER INSERT ON reference_validation_attestations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'reference_validation_attestations', 'insert',
        'reference_validation_attestation', NEW.id,
        NEW.canonical_manuscript_id,
        CASE
            WHEN NEW.legacy_journal_id IS NOT NULL THEN 'journal'
            ELSE 'manuscript'
        END,
        COALESCE(NEW.legacy_journal_id, NEW.canonical_manuscript_id),
        json_object(
            'literature_id', NEW.literature_id,
            'status', NEW.status,
            'validation_job_id', NEW.validation_job_id
        )
    );
END;

CREATE TRIGGER trg_change_reference_validations_update
AFTER UPDATE ON reference_validation_attestations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'reference_validation_attestations', 'update',
        'reference_validation_attestation', NEW.id,
        NEW.canonical_manuscript_id,
        CASE
            WHEN NEW.legacy_journal_id IS NOT NULL THEN 'journal'
            ELSE 'manuscript'
        END,
        COALESCE(NEW.legacy_journal_id, NEW.canonical_manuscript_id),
        json_object(
            'literature_id', NEW.literature_id,
            'status', NEW.status,
            'validation_job_id', NEW.validation_job_id
        )
    );
END;

CREATE TRIGGER trg_change_reference_validations_delete
AFTER DELETE ON reference_validation_attestations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, related_entity_type, related_entity_id, details
    ) VALUES (
        OLD.project_id, 'reference_validation_attestations', 'delete',
        'reference_validation_attestation', OLD.id,
        OLD.canonical_manuscript_id,
        CASE
            WHEN OLD.legacy_journal_id IS NOT NULL THEN 'journal'
            ELSE 'manuscript'
        END,
        COALESCE(OLD.legacy_journal_id, OLD.canonical_manuscript_id),
        json_object(
            'literature_id', OLD.literature_id,
            'status', OLD.status,
            'validation_job_id', OLD.validation_job_id
        )
    );
END;
