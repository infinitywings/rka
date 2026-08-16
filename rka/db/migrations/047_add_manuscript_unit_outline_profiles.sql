-- Migration 047: progressive L2-L5 outline rationale over native manuscript units.
-- requires-table: projects, manuscripts, manuscript_units, change_events

CREATE TABLE IF NOT EXISTS manuscript_unit_outline_profiles (
    unit_id TEXT PRIMARY KEY,
    manuscript_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    parent_unit_id TEXT,
    outline_level INTEGER NOT NULL DEFAULT 4
        CHECK (outline_level BETWEEN 2 AND 5),
    communicative_job TEXT,
    intended_takeaway TEXT,
    transition_from_previous TEXT,
    quick_reader_role TEXT,
    evidence_plan TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(evidence_plan) AND json_type(evidence_plan) = 'array'),
    figure_intentions TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(figure_intentions) AND json_type(figure_intentions) = 'array'),
    table_intentions TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(table_intentions) AND json_type(table_intentions) = 'array'),
    citation_intentions TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(citation_intentions) AND json_type(citation_intentions) = 'array'),
    blocker TEXT,
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (unit_id, manuscript_id, project_id),
    FOREIGN KEY (unit_id, manuscript_id, project_id)
        REFERENCES manuscript_units(id, manuscript_id, project_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (parent_unit_id, manuscript_id, project_id)
        REFERENCES manuscript_units(id, manuscript_id, project_id)
        ON DELETE RESTRICT,
    CHECK (parent_unit_id IS NULL OR parent_unit_id <> unit_id)
);

CREATE INDEX IF NOT EXISTS idx_manuscript_unit_outline_parent
    ON manuscript_unit_outline_profiles(
        project_id, manuscript_id, parent_unit_id, outline_level, unit_id
    );

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_unit_outline_insert
AFTER INSERT ON manuscript_unit_outline_profiles
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id, details
    ) VALUES (
        NEW.project_id,
        'manuscript_unit_outline_profiles',
        'insert',
        'manuscript_unit',
        NEW.unit_id,
        json_object(
            'manuscript_id', NEW.manuscript_id,
            'outline_level', NEW.outline_level,
            'parent_unit_id', NEW.parent_unit_id
        )
    );
END;
CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_unit_outline_update
AFTER UPDATE ON manuscript_unit_outline_profiles
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id, details
    ) VALUES (
        NEW.project_id,
        'manuscript_unit_outline_profiles',
        'update',
        'manuscript_unit',
        NEW.unit_id,
        json_object(
            'manuscript_id', NEW.manuscript_id,
            'outline_level', NEW.outline_level,
            'parent_unit_id', NEW.parent_unit_id
        )
    );
END;
