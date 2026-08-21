-- Migration 044: unified, reviewable semantic patch proposals.
-- requires-table: projects, manuscripts, manuscript_planning_branches, change_events, project_deletion_authorizations

CREATE TABLE IF NOT EXISTS semantic_patch_context_manifests (
    id TEXT PRIMARY KEY CHECK (substr(id, 1, 4) = 'pcm_' AND length(id) > 4),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    origin TEXT NOT NULL CHECK (origin IN ('host_agent', 'lm_studio')),
    provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
    model TEXT NOT NULL CHECK (length(trim(model)) > 0),
    boundary TEXT NOT NULL CHECK (boundary IN ('host_conversation', 'local_loopback')),
    selected_context TEXT NOT NULL CHECK (json_valid(selected_context) AND json_type(selected_context) = 'array'),
    resolved_context TEXT NOT NULL CHECK (json_valid(resolved_context) AND json_type(resolved_context) = 'object'),
    target_bases TEXT NOT NULL CHECK (json_valid(target_bases) AND json_type(target_bases) = 'array'),
    constraints TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(constraints) AND json_type(constraints) = 'array'),
    omissions TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(omissions) AND json_type(omissions) = 'array'),
    truncation_notes TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(truncation_notes) AND json_type(truncation_notes) = 'array'),
    manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    CHECK ((origin = 'host_agent' AND boundary = 'host_conversation')
        OR (origin = 'lm_studio' AND boundary = 'local_loopback'))
);

CREATE TABLE IF NOT EXISTS semantic_patch_proposals (
    id TEXT PRIMARY KEY CHECK (substr(id, 1, 4) = 'spp_' AND length(id) > 4),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    origin TEXT NOT NULL CHECK (origin IN ('human', 'host_agent', 'lm_studio')),
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'applied', 'rejected', 'conflicted', 'superseded', 'expired')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    intent TEXT NOT NULL CHECK (length(trim(intent)) > 0),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    created_by TEXT NOT NULL CHECK (created_by IN ('pi', 'brain', 'executor', 'web_ui')),
    operations TEXT NOT NULL CHECK (json_valid(operations) AND json_type(operations) = 'array'),
    target_bases TEXT NOT NULL CHECK (json_valid(target_bases) AND json_type(target_bases) = 'array'),
    semantic_diff TEXT NOT NULL CHECK (json_valid(semantic_diff) AND json_type(semantic_diff) = 'array'),
    validation_findings TEXT NOT NULL CHECK (json_valid(validation_findings) AND json_type(validation_findings) = 'array'),
    context_manifest_id TEXT,
    provider TEXT,
    model TEXT,
    boundary TEXT NOT NULL CHECK (boundary IN ('none', 'host_conversation', 'local_loopback')),
    supersedes_proposal_id TEXT,
    applied_at TEXT,
    closed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    FOREIGN KEY (context_manifest_id, project_id) REFERENCES semantic_patch_context_manifests(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (supersedes_proposal_id, project_id) REFERENCES semantic_patch_proposals(id, project_id) ON DELETE RESTRICT,
    CHECK ((origin = 'human' AND context_manifest_id IS NULL AND provider IS NULL AND model IS NULL AND boundary = 'none')
        OR (origin <> 'human' AND context_manifest_id IS NOT NULL AND provider IS NOT NULL AND model IS NOT NULL AND boundary <> 'none'))
);

CREATE INDEX IF NOT EXISTS idx_semantic_patch_proposals_project
    ON semantic_patch_proposals(project_id, status, updated_at DESC, id);

CREATE TABLE IF NOT EXISTS semantic_patch_proposal_events (
    id TEXT PRIMARY KEY CHECK (substr(id, 1, 4) = 'spe_' AND length(id) > 4),
    proposal_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    proposal_revision INTEGER NOT NULL CHECK (proposal_revision >= 1),
    action TEXT NOT NULL CHECK (action IN ('proposed', 'applied', 'rejected', 'conflicted', 'superseded', 'expired')),
    actor TEXT NOT NULL CHECK (actor IN ('pi', 'brain', 'executor', 'web_ui', 'llm', 'system')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    details TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details) AND json_type(details) = 'object'),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (proposal_id, proposal_revision),
    FOREIGN KEY (proposal_id, project_id) REFERENCES semantic_patch_proposals(id, project_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS semantic_patch_provider_events (
    id TEXT PRIMARY KEY CHECK (substr(id, 1, 4) = 'pce_' AND length(id) > 4),
    call_id TEXT NOT NULL CHECK (substr(call_id, 1, 4) = 'spc_' AND length(call_id) > 4),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    context_manifest_id TEXT NOT NULL,
    event TEXT NOT NULL CHECK (event IN ('started', 'succeeded', 'failed')),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    boundary TEXT NOT NULL CHECK (boundary IN ('host_conversation', 'local_loopback')),
    details TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details) AND json_type(details) = 'object'),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (project_id, call_id, event),
    FOREIGN KEY (context_manifest_id, project_id) REFERENCES semantic_patch_context_manifests(id, project_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_patch_provider_terminal
    ON semantic_patch_provider_events(project_id, call_id)
    WHERE event IN ('succeeded', 'failed');

CREATE TRIGGER IF NOT EXISTS trg_semantic_patch_manifests_no_update
BEFORE UPDATE ON semantic_patch_context_manifests BEGIN
    SELECT RAISE(ABORT, 'semantic patch context manifests are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_semantic_patch_events_no_update
BEFORE UPDATE ON semantic_patch_proposal_events BEGIN
    SELECT RAISE(ABORT, 'semantic patch proposal events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_semantic_patch_provider_events_no_update
BEFORE UPDATE ON semantic_patch_provider_events BEGIN
    SELECT RAISE(ABORT, 'semantic patch provider events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_semantic_patch_proposals_validate_update
BEFORE UPDATE ON semantic_patch_proposals
WHEN NEW.id IS NOT OLD.id OR NEW.project_id IS NOT OLD.project_id
 OR NEW.origin IS NOT OLD.origin OR NEW.intent IS NOT OLD.intent OR NEW.reason IS NOT OLD.reason
 OR NEW.created_by IS NOT OLD.created_by OR NEW.operations IS NOT OLD.operations
 OR NEW.target_bases IS NOT OLD.target_bases OR NEW.semantic_diff IS NOT OLD.semantic_diff
 OR NEW.validation_findings IS NOT OLD.validation_findings
 OR NEW.context_manifest_id IS NOT OLD.context_manifest_id OR NEW.provider IS NOT OLD.provider
 OR NEW.model IS NOT OLD.model OR NEW.boundary IS NOT OLD.boundary
 OR NEW.supersedes_proposal_id IS NOT OLD.supersedes_proposal_id OR NEW.created_at IS NOT OLD.created_at
 OR NEW.revision <> OLD.revision + 1
 OR NOT (
     (OLD.status = 'proposed'
      AND NEW.status IN ('applied', 'rejected', 'conflicted', 'superseded', 'expired'))
     OR (OLD.status = 'conflicted' AND NEW.status = 'superseded')
 )
 OR NEW.closed_at IS NULL OR NEW.closed_at IS NOT NEW.updated_at
 OR (NEW.status = 'applied'
     AND (NEW.applied_at IS NULL OR NEW.applied_at IS NOT NEW.updated_at))
 OR (NEW.status <> 'applied' AND NEW.applied_at IS NOT OLD.applied_at)
BEGIN
    SELECT RAISE(ABORT, 'semantic patch proposal content is immutable and only proposed records may transition');
END;

CREATE TRIGGER IF NOT EXISTS trg_semantic_patch_rows_no_delete_manifest
BEFORE DELETE ON semantic_patch_context_manifests
WHEN NOT EXISTS (SELECT 1 FROM project_deletion_authorizations WHERE project_id = OLD.project_id)
BEGIN SELECT RAISE(ABORT, 'semantic patch manifests require project-authorized deletion'); END;
CREATE TRIGGER IF NOT EXISTS trg_semantic_patch_rows_no_delete_proposal
BEFORE DELETE ON semantic_patch_proposals
WHEN NOT EXISTS (SELECT 1 FROM project_deletion_authorizations WHERE project_id = OLD.project_id)
BEGIN SELECT RAISE(ABORT, 'semantic patch proposals require project-authorized deletion'); END;
CREATE TRIGGER IF NOT EXISTS trg_semantic_patch_rows_no_delete_event
BEFORE DELETE ON semantic_patch_proposal_events
WHEN NOT EXISTS (SELECT 1 FROM project_deletion_authorizations WHERE project_id = OLD.project_id)
BEGIN SELECT RAISE(ABORT, 'semantic patch proposal events require project-authorized deletion'); END;
CREATE TRIGGER IF NOT EXISTS trg_semantic_patch_rows_no_delete_provider
BEFORE DELETE ON semantic_patch_provider_events
WHEN NOT EXISTS (SELECT 1 FROM project_deletion_authorizations WHERE project_id = OLD.project_id)
BEGIN SELECT RAISE(ABORT, 'semantic patch provider events require project-authorized deletion'); END;

CREATE TRIGGER IF NOT EXISTS trg_change_semantic_patch_proposals_insert
AFTER INSERT ON semantic_patch_proposals BEGIN
    INSERT INTO change_events (project_id, source_table, operation, entity_type, entity_id, details)
    VALUES (NEW.project_id, 'semantic_patch_proposals', 'insert', 'semantic_patch_proposal', NEW.id,
            json_object('status', NEW.status, 'revision', NEW.revision, 'origin', NEW.origin));
END;
CREATE TRIGGER IF NOT EXISTS trg_change_semantic_patch_proposals_update
AFTER UPDATE ON semantic_patch_proposals BEGIN
    INSERT INTO change_events (project_id, source_table, operation, entity_type, entity_id, details)
    VALUES (NEW.project_id, 'semantic_patch_proposals', 'update', 'semantic_patch_proposal', NEW.id,
            json_object('status', NEW.status, 'revision', NEW.revision, 'origin', NEW.origin));
END;
