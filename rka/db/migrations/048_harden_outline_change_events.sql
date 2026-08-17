-- Migration 048: make outline-profile changes first-class manuscript events.
-- requires-table: manuscript_unit_outline_profiles, change_events

DROP TRIGGER IF EXISTS trg_change_manuscript_unit_outline_insert;
DROP TRIGGER IF EXISTS trg_change_manuscript_unit_outline_update;
DROP TRIGGER IF EXISTS trg_change_manuscript_unit_outline_delete;

CREATE TRIGGER trg_change_manuscript_unit_outline_insert
AFTER INSERT ON manuscript_unit_outline_profiles
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id, details
    ) VALUES (
        NEW.project_id,
        'manuscript_unit_outline_profiles',
        'insert',
        'manuscript_unit',
        NEW.unit_id,
        NEW.manuscript_id,
        NEW.unit_id,
        json_object(
            'outline_level', NEW.outline_level,
            'parent_unit_id', NEW.parent_unit_id
        )
    );
END;

CREATE TRIGGER trg_change_manuscript_unit_outline_update
AFTER UPDATE ON manuscript_unit_outline_profiles
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id, details
    ) VALUES (
        NEW.project_id,
        'manuscript_unit_outline_profiles',
        'update',
        'manuscript_unit',
        NEW.unit_id,
        NEW.manuscript_id,
        NEW.unit_id,
        json_object(
            'outline_level', NEW.outline_level,
            'parent_unit_id', NEW.parent_unit_id
        )
    );
END;

CREATE TRIGGER trg_change_manuscript_unit_outline_delete
AFTER DELETE ON manuscript_unit_outline_profiles
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id, details
    ) VALUES (
        OLD.project_id,
        'manuscript_unit_outline_profiles',
        'delete',
        'manuscript_unit',
        OLD.unit_id,
        OLD.manuscript_id,
        OLD.unit_id,
        json_object(
            'outline_level', OLD.outline_level,
            'parent_unit_id', OLD.parent_unit_id
        )
    );
END;
