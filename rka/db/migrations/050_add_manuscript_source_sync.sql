-- Migration 050: conflict-safe manuscript source proposal and recovery ledger.
-- requires-table: projects, manuscripts, semantic_patch_context_manifests, change_events, project_deletion_authorizations

CREATE TABLE IF NOT EXISTS manuscript_source_proposals (
    id TEXT PRIMARY KEY CHECK (substr(id, 1, 4) = 'msp_' AND length(id) > 4),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    manuscript_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'applied', 'rejected', 'conflicted', 'superseded', 'expired')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    origin TEXT NOT NULL CHECK (origin IN ('human', 'host_agent', 'lm_studio')),
    relative_path TEXT NOT NULL CHECK (length(trim(relative_path)) > 0),
    source_format TEXT NOT NULL CHECK (source_format IN ('markdown', 'latex')),
    base_content_hash TEXT CHECK (base_content_hash IS NULL OR length(base_content_hash) = 64),
    proposed_content TEXT NOT NULL,
    proposed_content_hash TEXT NOT NULL CHECK (length(proposed_content_hash) = 64),
    created_by TEXT NOT NULL CHECK (created_by IN ('pi', 'brain', 'executor', 'web_ui')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    validation_findings TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(validation_findings) AND json_type(validation_findings) = 'array'),
    context_manifest_id TEXT,
    provider TEXT,
    model TEXT,
    boundary TEXT NOT NULL CHECK (boundary IN ('none', 'host_conversation', 'local_loopback')),
    supersedes_proposal_id TEXT,
    recovery_manifest_path TEXT,
    applied_at TEXT,
    closed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    FOREIGN KEY (manuscript_id, project_id) REFERENCES manuscripts(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (context_manifest_id, project_id) REFERENCES semantic_patch_context_manifests(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (supersedes_proposal_id, project_id) REFERENCES manuscript_source_proposals(id, project_id) ON DELETE RESTRICT,
    CHECK ((origin = 'human' AND context_manifest_id IS NULL AND provider IS NULL AND model IS NULL AND boundary = 'none')
        OR (origin <> 'human' AND context_manifest_id IS NOT NULL AND provider IS NOT NULL AND model IS NOT NULL AND boundary <> 'none'))
);

CREATE INDEX IF NOT EXISTS idx_manuscript_source_proposals_project
    ON manuscript_source_proposals(project_id, manuscript_id, status, updated_at DESC, id);

CREATE TABLE IF NOT EXISTS manuscript_source_events (
    id TEXT PRIMARY KEY CHECK (substr(id, 1, 4) = 'mse_' AND length(id) > 4),
    proposal_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    proposal_revision INTEGER NOT NULL CHECK (proposal_revision >= 1),
    action TEXT NOT NULL CHECK (action IN ('proposed', 'applied', 'rejected', 'conflicted', 'superseded', 'expired')),
    actor TEXT NOT NULL CHECK (actor IN ('pi', 'brain', 'executor', 'web_ui', 'system')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    details TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details) AND json_type(details) = 'object'),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (proposal_id, proposal_revision),
    FOREIGN KEY (proposal_id, project_id) REFERENCES manuscript_source_proposals(id, project_id) ON DELETE RESTRICT
);

CREATE TRIGGER IF NOT EXISTS trg_manuscript_source_events_no_update
BEFORE UPDATE ON manuscript_source_events BEGIN
    SELECT RAISE(ABORT, 'manuscript source events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_manuscript_source_proposals_validate_update
BEFORE UPDATE ON manuscript_source_proposals
WHEN NEW.id IS NOT OLD.id OR NEW.project_id IS NOT OLD.project_id
 OR NEW.manuscript_id IS NOT OLD.manuscript_id OR NEW.origin IS NOT OLD.origin
 OR NEW.relative_path IS NOT OLD.relative_path OR NEW.source_format IS NOT OLD.source_format
 OR NEW.base_content_hash IS NOT OLD.base_content_hash
 OR NEW.proposed_content IS NOT OLD.proposed_content
 OR NEW.proposed_content_hash IS NOT OLD.proposed_content_hash
 OR NEW.created_by IS NOT OLD.created_by OR NEW.reason IS NOT OLD.reason
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
     AND (NEW.applied_at IS NULL OR NEW.applied_at IS NOT NEW.updated_at
          OR NEW.recovery_manifest_path IS NULL))
 OR (NEW.status <> 'applied'
     AND (NEW.applied_at IS NOT OLD.applied_at
          OR NEW.recovery_manifest_path IS NOT OLD.recovery_manifest_path))
BEGIN
    SELECT RAISE(ABORT, 'manuscript source proposal content is immutable and only open records may transition');
END;

CREATE TRIGGER IF NOT EXISTS trg_manuscript_source_rows_no_delete_proposal
BEFORE DELETE ON manuscript_source_proposals
WHEN NOT EXISTS (SELECT 1 FROM project_deletion_authorizations WHERE project_id = OLD.project_id)
BEGIN SELECT RAISE(ABORT, 'manuscript source proposals require project-authorized deletion'); END;

CREATE TRIGGER IF NOT EXISTS trg_manuscript_source_rows_no_delete_event
BEFORE DELETE ON manuscript_source_events
WHEN NOT EXISTS (SELECT 1 FROM project_deletion_authorizations WHERE project_id = OLD.project_id)
BEGIN SELECT RAISE(ABORT, 'manuscript source events require project-authorized deletion'); END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_source_proposals_insert
AFTER INSERT ON manuscript_source_proposals BEGIN
    INSERT INTO change_events (project_id, source_table, operation, entity_type, entity_id, manuscript_id, details)
    VALUES (NEW.project_id, 'manuscript_source_proposals', 'insert', 'manuscript_source_proposal', NEW.id, NEW.manuscript_id,
            json_object('status', NEW.status, 'revision', NEW.revision, 'relative_path', NEW.relative_path));
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_source_proposals_update
AFTER UPDATE ON manuscript_source_proposals BEGIN
    INSERT INTO change_events (project_id, source_table, operation, entity_type, entity_id, manuscript_id, details)
    VALUES (NEW.project_id, 'manuscript_source_proposals', 'update', 'manuscript_source_proposal', NEW.id, NEW.manuscript_id,
            json_object('status', NEW.status, 'revision', NEW.revision, 'relative_path', NEW.relative_path));
END;
