-- Migration 054: safe, project-scoped external source registration.
-- requires-table: projects, artifacts, interpretation_candidates, change_events, project_deletion_authorizations

-- A registered source is an immutable provenance envelope around one managed
-- artifact.  The artifact contains either exact supplied bytes or a canonical
-- locator manifest.  Registration alone never creates canonical research
-- knowledge.
CREATE TABLE registered_sources (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'src_' AND length(id) > 4),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    artifact_id TEXT NOT NULL,
    source_kind TEXT NOT NULL
        CHECK (source_kind IN ('file', 'pasted_text', 'url', 'repository', 'zotero')),
    content_mode TEXT NOT NULL
        CHECK (content_mode IN ('bytes', 'locator_manifest')),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    stable_locator TEXT,
    content_hash TEXT NOT NULL
        CHECK (length(content_hash) = 64 AND content_hash = lower(content_hash)),
    manifest_hash TEXT NOT NULL
        CHECK (length(manifest_hash) = 64 AND manifest_hash = lower(manifest_hash)),
    ownership_kind TEXT NOT NULL
        CHECK (ownership_kind IN (
            'researcher', 'institution', 'third_party', 'public_domain', 'unknown'
        )),
    ownership_note TEXT,
    provenance TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(provenance) AND json_type(provenance) = 'object'),
    registered_by TEXT NOT NULL
        CHECK (registered_by IN (
            'pi', 'brain', 'executor', 'web_ui', 'llm', 'import', 'system'
        )),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (project_id, manifest_hash),
    FOREIGN KEY (artifact_id, project_id)
        REFERENCES artifacts(id, project_id) ON DELETE RESTRICT,
    CHECK (
        (source_kind IN ('url', 'repository', 'zotero')
         AND stable_locator IS NOT NULL
         AND length(trim(stable_locator)) > 0)
        OR source_kind IN ('file', 'pasted_text')
    )
);

CREATE INDEX idx_registered_sources_project_created
    ON registered_sources(project_id, created_at, id);
CREATE INDEX idx_registered_sources_artifact
    ON registered_sources(project_id, artifact_id);

-- Admission records the one explicit, grounded review that connects a source
-- interpretation to an already-existing canonical journal/claim/decision.
-- The canonical target is deliberately polymorphic and is validated by the
-- service and the post-import integrity gate.
CREATE TABLE source_admissions (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'sad_' AND length(id) > 4),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    source_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    candidate_revision INTEGER NOT NULL CHECK (candidate_revision >= 2),
    target_type TEXT NOT NULL
        CHECK (target_type IN ('journal', 'claim', 'decision')),
    target_id TEXT NOT NULL CHECK (length(trim(target_id)) > 0),
    source_manifest_hash TEXT NOT NULL
        CHECK (
            length(source_manifest_hash) = 64
            AND source_manifest_hash = lower(source_manifest_hash)
        ),
    actor TEXT NOT NULL
        CHECK (actor IN ('pi', 'brain', 'executor', 'web_ui')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    grounding_verified INTEGER NOT NULL DEFAULT 1
        CHECK (grounding_verified = 1),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (project_id, candidate_id),
    FOREIGN KEY (source_id, project_id)
        REFERENCES registered_sources(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (candidate_id, project_id)
        REFERENCES interpretation_candidates(id, project_id) ON DELETE RESTRICT
);

CREATE INDEX idx_source_admissions_source
    ON source_admissions(project_id, source_id, created_at, id);
CREATE INDEX idx_source_admissions_target
    ON source_admissions(project_id, target_type, target_id);

CREATE TRIGGER trg_registered_sources_no_update
BEFORE UPDATE ON registered_sources
BEGIN
    SELECT RAISE(ABORT, 'registered sources are immutable');
END;

CREATE TRIGGER trg_registered_sources_no_delete
BEFORE DELETE ON registered_sources
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations
    WHERE project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'registered sources require project-authorized deletion');
END;

CREATE TRIGGER trg_source_admissions_no_update
BEFORE UPDATE ON source_admissions
BEGIN
    SELECT RAISE(ABORT, 'source admissions are immutable');
END;

CREATE TRIGGER trg_source_admissions_no_delete
BEFORE DELETE ON source_admissions
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations
    WHERE project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'source admissions require project-authorized deletion');
END;

CREATE TRIGGER trg_change_registered_sources_insert
AFTER INSERT ON registered_sources
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'registered_sources', 'insert', 'registered_source', NEW.id,
        'artifact', NEW.artifact_id,
        json_object(
            'source_kind', NEW.source_kind,
            'content_mode', NEW.content_mode,
            'manifest_hash', NEW.manifest_hash
        )
    );
END;

CREATE TRIGGER trg_change_source_admissions_insert
AFTER INSERT ON source_admissions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'source_admissions', 'insert', 'source_admission', NEW.id,
        NEW.target_type, NEW.target_id,
        json_object(
            'source_id', NEW.source_id,
            'candidate_id', NEW.candidate_id,
            'candidate_revision', NEW.candidate_revision
        )
    );
END;
