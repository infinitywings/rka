-- Migration 043: recoverable manuscript-planning branches and artifacts.
-- requires-table: projects, manuscripts, change_events, project_deletion_authorizations
--
-- Planning artifacts are a provisional deliberation layer. They may cite
-- canonical RKA entities, but they are never themselves evidence, manuscript
-- claims, PI decisions, or authoring files. Branch ancestry provides copy-on-
-- write alternatives; immutable versions preserve every edit.

CREATE TABLE IF NOT EXISTS manuscript_planning_branches (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'mpb_' AND length(id) > 4),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    manuscript_id TEXT,
    context_key TEXT NOT NULL CHECK (length(trim(context_key)) > 0),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    purpose TEXT NOT NULL CHECK (length(trim(purpose)) > 0),
    parent_branch_id TEXT,
    parent_branch_revision INTEGER CHECK (parent_branch_revision >= 1),
    base_manuscript_revision INTEGER CHECK (base_manuscript_revision >= 1),
    state TEXT NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'selected', 'archived', 'superseded')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_by TEXT NOT NULL
        CHECK (created_by IN ('pi', 'brain', 'executor', 'web_ui', 'llm', 'import')),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (project_id, context_key, name),
    FOREIGN KEY (manuscript_id, project_id)
        REFERENCES manuscripts(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (parent_branch_id, project_id)
        REFERENCES manuscript_planning_branches(id, project_id) ON DELETE RESTRICT,
    CHECK (
        (manuscript_id IS NULL AND context_key = 'project'
         AND base_manuscript_revision IS NULL)
        OR
        (manuscript_id IS NOT NULL AND context_key = manuscript_id
         AND base_manuscript_revision IS NOT NULL)
    ),
    CHECK (
        (parent_branch_id IS NULL AND parent_branch_revision IS NULL)
        OR (parent_branch_id IS NOT NULL AND parent_branch_revision IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_planning_branch_selected_context
    ON manuscript_planning_branches(project_id, context_key)
    WHERE state = 'selected';
CREATE INDEX IF NOT EXISTS idx_planning_branches_context
    ON manuscript_planning_branches(project_id, context_key, state, updated_at DESC, id);

CREATE TRIGGER IF NOT EXISTS trg_planning_branches_parent_context_insert
BEFORE INSERT ON manuscript_planning_branches
WHEN NEW.parent_branch_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM manuscript_planning_branches AS parent
    WHERE parent.id = NEW.parent_branch_id
      AND parent.project_id = NEW.project_id
      AND parent.context_key = NEW.context_key
)
BEGIN
    SELECT RAISE(ABORT, 'planning branch parent must share project and manuscript context');
END;

CREATE TRIGGER IF NOT EXISTS trg_planning_branches_validate_update
BEFORE UPDATE ON manuscript_planning_branches
WHEN NEW.id IS NOT OLD.id
  OR NEW.project_id IS NOT OLD.project_id
  OR NEW.manuscript_id IS NOT OLD.manuscript_id
  OR NEW.context_key IS NOT OLD.context_key
  OR NEW.name IS NOT OLD.name
  OR NEW.purpose IS NOT OLD.purpose
  OR NEW.parent_branch_id IS NOT OLD.parent_branch_id
  OR NEW.parent_branch_revision IS NOT OLD.parent_branch_revision
  OR NEW.base_manuscript_revision IS NOT OLD.base_manuscript_revision
  OR NEW.created_by IS NOT OLD.created_by
  OR NEW.created_at IS NOT OLD.created_at
  OR NEW.revision <> OLD.revision + 1
BEGIN
    SELECT RAISE(ABORT, 'planning branch identity is immutable and updates require next revision');
END;

CREATE TRIGGER IF NOT EXISTS trg_planning_branches_no_delete
BEFORE DELETE ON manuscript_planning_branches
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'planning branches require project-authorized deletion');
END;

CREATE TABLE IF NOT EXISTS manuscript_planning_branch_events (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'pbe_' AND length(id) > 4),
    branch_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    branch_revision INTEGER NOT NULL CHECK (branch_revision >= 1),
    action TEXT NOT NULL
        CHECK (action IN ('created', 'selected', 'activated', 'archived',
                          'superseded', 'artifact_version_appended')),
    from_state TEXT CHECK (
        from_state IS NULL OR from_state IN ('active', 'selected', 'archived', 'superseded')
    ),
    to_state TEXT NOT NULL
        CHECK (to_state IN ('active', 'selected', 'archived', 'superseded')),
    actor TEXT NOT NULL
        CHECK (actor IN ('pi', 'brain', 'executor', 'web_ui', 'llm', 'import')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    details TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(details) AND json_type(details) = 'object'),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (branch_id, branch_revision),
    FOREIGN KEY (branch_id, project_id)
        REFERENCES manuscript_planning_branches(id, project_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_planning_branch_events
    ON manuscript_planning_branch_events(project_id, branch_id, branch_revision);

CREATE TABLE IF NOT EXISTS manuscript_planning_artifacts (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'pla_' AND length(id) > 4),
    branch_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    local_key TEXT NOT NULL CHECK (length(trim(local_key)) > 0),
    stage_type TEXT NOT NULL CHECK (stage_type IN (
        'seed', 'paragraph_spine', 'problem_scope', 'landscape_gap',
        'response_mechanism', 'challenge_innovation', 'rq_contribution',
        'evaluation', 'outline', 'review'
    )),
    current_version INTEGER NOT NULL DEFAULT 0 CHECK (current_version >= 0),
    current_version_id TEXT,
    created_by TEXT NOT NULL
        CHECK (created_by IN ('pi', 'brain', 'executor', 'web_ui', 'llm', 'import')),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (branch_id, project_id, stage_type, local_key),
    FOREIGN KEY (branch_id, project_id)
        REFERENCES manuscript_planning_branches(id, project_id) ON DELETE RESTRICT,
    CHECK (
        (current_version = 0 AND current_version_id IS NULL)
        OR (current_version > 0 AND current_version_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_planning_artifacts_branch
    ON manuscript_planning_artifacts(project_id, branch_id, stage_type, local_key);

CREATE TRIGGER IF NOT EXISTS trg_planning_artifacts_validate_update
BEFORE UPDATE ON manuscript_planning_artifacts
WHEN NEW.id IS NOT OLD.id
  OR NEW.branch_id IS NOT OLD.branch_id
  OR NEW.project_id IS NOT OLD.project_id
  OR NEW.local_key IS NOT OLD.local_key
  OR NEW.stage_type IS NOT OLD.stage_type
  OR NEW.created_by IS NOT OLD.created_by
  OR NEW.created_at IS NOT OLD.created_at
  OR NEW.current_version <> OLD.current_version + 1
BEGIN
    SELECT RAISE(ABORT, 'planning artifact identity is immutable and updates require next version');
END;

CREATE TRIGGER IF NOT EXISTS trg_planning_artifacts_no_delete
BEFORE DELETE ON manuscript_planning_artifacts
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'planning artifacts require project-authorized deletion');
END;

CREATE TABLE IF NOT EXISTS manuscript_planning_artifact_versions (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'plv_' AND length(id) > 4),
    artifact_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    branch_revision INTEGER NOT NULL CHECK (branch_revision >= 2),
    lifecycle TEXT NOT NULL DEFAULT 'candidate'
        CHECK (lifecycle IN (
            'candidate', 'reviewed', 'selected', 'parked', 'superseded', 'archived'
        )),
    summary TEXT NOT NULL CHECK (length(trim(summary)) > 0),
    payload TEXT NOT NULL
        CHECK (json_valid(payload) AND json_type(payload) = 'object'),
    origin TEXT NOT NULL
        CHECK (origin IN ('user', 'ai_suggested', 'imported', 'user_revised')),
    provider TEXT,
    model TEXT,
    context_hash TEXT,
    unresolved_items TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(unresolved_items) AND json_type(unresolved_items) = 'array'),
    readiness_state TEXT NOT NULL DEFAULT 'in_progress'
        CHECK (readiness_state IN ('blocked', 'in_progress', 'ready')),
    readiness_missing TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(readiness_missing) AND json_type(readiness_missing) = 'array'),
    readiness_notes TEXT,
    promotion_target_type TEXT CHECK (
        promotion_target_type IS NULL OR promotion_target_type IN (
            'manuscript', 'manuscript_claim', 'manuscript_unit',
            'experiment', 'decision'
        )
    ),
    promotion_target_id TEXT,
    created_by TEXT NOT NULL
        CHECK (created_by IN ('pi', 'brain', 'executor', 'web_ui', 'llm', 'import')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    supersedes_version_id TEXT,
    derived_from_version_id TEXT,
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (id, artifact_id, project_id),
    UNIQUE (artifact_id, project_id, version),
    UNIQUE (branch_id, project_id, branch_revision),
    FOREIGN KEY (artifact_id, project_id)
        REFERENCES manuscript_planning_artifacts(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (branch_id, project_id)
        REFERENCES manuscript_planning_branches(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (supersedes_version_id, project_id)
        REFERENCES manuscript_planning_artifact_versions(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (derived_from_version_id, project_id)
        REFERENCES manuscript_planning_artifact_versions(id, project_id) ON DELETE RESTRICT,
    CHECK (
        (version = 1 AND supersedes_version_id IS NULL)
        OR (version > 1 AND supersedes_version_id IS NOT NULL)
    ),
    CHECK (
        (origin = 'ai_suggested' AND provider IS NOT NULL
         AND model IS NOT NULL AND context_hash IS NOT NULL)
        OR origin <> 'ai_suggested'
    ),
    CHECK (
        (promotion_target_type IS NULL AND promotion_target_id IS NULL)
        OR (promotion_target_type IS NOT NULL AND promotion_target_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_planning_versions_artifact
    ON manuscript_planning_artifact_versions(project_id, artifact_id, version DESC);

CREATE TRIGGER IF NOT EXISTS trg_planning_versions_no_update
BEFORE UPDATE ON manuscript_planning_artifact_versions
BEGIN
    SELECT RAISE(ABORT, 'planning artifact versions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_planning_versions_no_delete
BEFORE DELETE ON manuscript_planning_artifact_versions
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'planning artifact versions are immutable');
END;

CREATE TABLE IF NOT EXISTS manuscript_planning_evidence_bindings (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'plb_' AND length(id) > 4),
    artifact_version_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'journal', 'literature', 'decision', 'claim', 'claim_scope', 'cluster',
        'interpretation_candidate', 'experiment', 'experiment_plan_version',
        'experiment_run', 'experiment_observation', 'evidence_locator',
        'artifact', 'manuscript', 'manuscript_claim', 'manuscript_unit'
    )),
    entity_id TEXT NOT NULL CHECK (length(trim(entity_id)) > 0),
    role TEXT NOT NULL CHECK (role IN (
        'support', 'qualifier', 'counterevidence', 'context',
        'inspiration', 'unresolved'
    )),
    source_version TEXT,
    locator_kind TEXT CHECK (
        locator_kind IS NULL OR locator_kind IN (
            'whole_entity', 'page', 'line_range', 'table', 'table_cell',
            'json_pointer', 'notebook_cell', 'record', 'section', 'quote'
        )
    ),
    locator_value TEXT,
    locator_start INTEGER CHECK (locator_start IS NULL OR locator_start >= 0),
    locator_end INTEGER CHECK (locator_end IS NULL OR locator_end >= 0),
    content_hash TEXT,
    ordinal INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
    note TEXT,
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (artifact_version_id, entity_type, entity_id, role, ordinal),
    FOREIGN KEY (artifact_version_id, artifact_id, project_id)
        REFERENCES manuscript_planning_artifact_versions(id, artifact_id, project_id)
        ON DELETE RESTRICT,
    CHECK (
        (locator_kind IS NULL AND locator_value IS NULL
         AND locator_start IS NULL AND locator_end IS NULL)
        OR (locator_kind IS NOT NULL AND locator_value IS NOT NULL)
    ),
    CHECK (locator_end IS NULL OR locator_start IS NULL OR locator_end >= locator_start)
);

CREATE INDEX IF NOT EXISTS idx_planning_bindings_entity
    ON manuscript_planning_evidence_bindings(project_id, entity_type, entity_id);

CREATE TRIGGER IF NOT EXISTS trg_planning_branch_events_no_update
BEFORE UPDATE ON manuscript_planning_branch_events
BEGIN
    SELECT RAISE(ABORT, 'planning branch events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_planning_branch_events_no_delete
BEFORE DELETE ON manuscript_planning_branch_events
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'planning branch events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_planning_bindings_no_update
BEFORE UPDATE ON manuscript_planning_evidence_bindings
BEGIN
    SELECT RAISE(ABORT, 'planning evidence bindings are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_planning_bindings_no_delete
BEFORE DELETE ON manuscript_planning_evidence_bindings
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'planning evidence bindings are immutable');
END;

-- Semantic cursor integration. The current branch row is the resumable head;
-- immutable child rows retain exact provenance and evidence bindings.
CREATE TRIGGER IF NOT EXISTS trg_change_planning_branches_insert
AFTER INSERT ON manuscript_planning_branches
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_planning_branches', 'insert',
        'manuscript_planning_branch', NEW.id, NEW.manuscript_id,
        json_object('state', NEW.state, 'revision', NEW.revision,
                    'context_key', NEW.context_key)
    );
END;
CREATE TRIGGER IF NOT EXISTS trg_change_planning_branches_update
AFTER UPDATE ON manuscript_planning_branches
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_planning_branches', 'update',
        'manuscript_planning_branch', NEW.id, NEW.manuscript_id,
        json_object('state', NEW.state, 'revision', NEW.revision,
                    'context_key', NEW.context_key)
    );
END;
CREATE TRIGGER IF NOT EXISTS trg_change_planning_artifacts_insert
AFTER INSERT ON manuscript_planning_artifacts
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_planning_artifacts', 'insert',
        'manuscript_planning_artifact', NEW.id,
        (SELECT branch.manuscript_id
         FROM manuscript_planning_branches AS branch
         WHERE branch.id = NEW.branch_id AND branch.project_id = NEW.project_id),
        'manuscript_planning_branch', NEW.branch_id,
        json_object('stage_type', NEW.stage_type, 'local_key', NEW.local_key)
    );
END;
CREATE TRIGGER IF NOT EXISTS trg_change_planning_versions_insert
AFTER INSERT ON manuscript_planning_artifact_versions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_planning_artifact_versions', 'insert',
        'manuscript_planning_artifact_version', NEW.id,
        (SELECT branch.manuscript_id
         FROM manuscript_planning_branches AS branch
         WHERE branch.id = NEW.branch_id AND branch.project_id = NEW.project_id),
        'manuscript_planning_artifact', NEW.artifact_id,
        json_object('version', NEW.version, 'branch_revision', NEW.branch_revision,
                    'lifecycle', NEW.lifecycle,
                    'origin', NEW.origin)
    );
END;
