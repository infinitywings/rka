-- Migration 032: immutable manuscript reference-validation attestations.
--
-- Every completed validation attempt is retained with its exact inputs,
-- source trace, full validator payload, and timing.  The application may
-- append attestations but may never rewrite or delete them.

CREATE TABLE IF NOT EXISTS reference_validation_attestations (
    id TEXT PRIMARY KEY,                         -- rvd_... ULID
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    manuscript_id TEXT NOT NULL REFERENCES journal(id) ON DELETE RESTRICT,
    literature_id TEXT REFERENCES literature(id) ON DELETE RESTRICT,
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
    stage_trace TEXT NOT NULL DEFAULT '{}',      -- JSON: attempted/completed/not reached
    full_json_payload TEXT NOT NULL,              -- complete attempt result
    pipeline_version TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_reference_validations_manuscript
    ON reference_validation_attestations(project_id, manuscript_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reference_validations_literature
    ON reference_validation_attestations(project_id, literature_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reference_validations_status
    ON reference_validation_attestations(project_id, status, created_at);

CREATE TRIGGER IF NOT EXISTS trg_reference_validations_no_update
BEFORE UPDATE ON reference_validation_attestations
BEGIN
    SELECT RAISE(ABORT, 'reference validation attestations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_reference_validations_no_delete
BEFORE DELETE ON reference_validation_attestations
BEGIN
    SELECT RAISE(ABORT, 'reference validation attestations are immutable');
END;
