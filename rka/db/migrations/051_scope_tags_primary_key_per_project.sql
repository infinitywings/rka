-- Migration 051: make the tags primary key project-scoped.
--
-- `tags` was created with PRIMARY KEY (tag, entity_type, entity_id) before
-- RKA was multi-project. Migration 004 added `project_id` as a nullable
-- column but left the key alone, so tag uniqueness is global while every
-- other table's uniqueness is per-project.
--
-- That is invisible in normal use, because entity ids are unique across
-- projects anyway. It bites when a knowledge pack is imported into a
-- database that already holds its source project: import preserves entity
-- ids, so the first duplicated tag aborts the whole import with
--
--     UNIQUE constraint failed: tags.tag, tags.entity_type, tags.entity_id
--
-- Cloning a project for testing is exactly that operation, and so is
-- importing the published example pack into an instance that already has it.
--
-- No row is lost or merged: at the time of writing every existing row is
-- already unique under the new key. `project_id` stays nullable so the
-- pre-multi-project rows keep their current meaning rather than being
-- assigned to a project this migration cannot know.

ALTER TABLE tags RENAME TO tags_legacy_051;

CREATE TABLE tags (
    tag TEXT NOT NULL COLLATE NOCASE,
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'decision', 'literature', 'journal', 'mission'
    )),
    entity_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    project_id TEXT,
    PRIMARY KEY (project_id, tag, entity_type, entity_id)
);

INSERT INTO tags (tag, entity_type, entity_id, created_at, project_id)
SELECT tag, entity_type, entity_id, created_at, project_id
FROM tags_legacy_051;

DROP TABLE tags_legacy_051;

CREATE INDEX IF NOT EXISTS idx_tags_entity ON tags(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
CREATE INDEX IF NOT EXISTS idx_tags_project ON tags(project_id);

-- Recreate the change-tracking triggers. A table rebuild drops them along
-- with the old table, and their absence is silent: writes keep working and
-- the change cursor simply stops seeing tag edges.
--
-- They are recreated *after* the row copy on purpose. Creating them first
-- would emit one change event per copied row — eleven thousand of them here —
-- for a migration that changes no tag.

CREATE TRIGGER trg_change_tags_insert
AFTER INSERT ON tags
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id, details
    ) VALUES (
        COALESCE(NEW.project_id, 'proj_default'),
        'tags', 'insert', NEW.entity_type, NEW.entity_id,
        json_object('tag', NEW.tag)
    );
END;

CREATE TRIGGER trg_change_tags_update
AFTER UPDATE ON tags
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id, details
    ) VALUES (
        COALESCE(NEW.project_id, OLD.project_id, 'proj_default'),
        'tags', 'update', NEW.entity_type, NEW.entity_id,
        json_object('tag', NEW.tag, 'previous_tag', OLD.tag)
    );
END;

CREATE TRIGGER trg_change_tags_delete
AFTER DELETE ON tags
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id, details
    ) VALUES (
        COALESCE(OLD.project_id, 'proj_default'),
        'tags', 'delete', OLD.entity_type, OLD.entity_id,
        json_object('tag', OLD.tag)
    );
END;
