-- Migration 046: immutable canonical-action lineage for evaluation contracts.
-- requires-table: projects, missions, manuscript_planning_branches, manuscript_planning_artifacts, manuscript_planning_artifact_versions, semantic_patch_proposals, change_events, project_deletion_authorizations

CREATE UNIQUE INDEX IF NOT EXISTS uq_missions_id_project_evaluation
    ON missions(id, project_id);

CREATE TABLE IF NOT EXISTS manuscript_evaluation_events (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'eva_' AND length(id) > 4),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    branch_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_version_id TEXT NOT NULL,
    artifact_version INTEGER NOT NULL CHECK (artifact_version >= 1),
    branch_revision INTEGER NOT NULL CHECK (branch_revision >= 1),
    commitment_key TEXT NOT NULL CHECK (length(trim(commitment_key)) > 0),
    requirement_key TEXT,
    action TEXT NOT NULL CHECK (action IN (
        'missing_evidence_mission_created',
        'result_unit_proposal_prepared',
        'result_unit_proposal_applied'
    )),
    target_type TEXT NOT NULL CHECK (target_type IN (
        'mission', 'semantic_patch_proposal', 'manuscript_unit'
    )),
    target_id TEXT NOT NULL CHECK (length(trim(target_id)) > 0),
    target_version INTEGER CHECK (target_version IS NULL OR target_version >= 1),
    proposal_id TEXT,
    mission_id TEXT,
    actor TEXT NOT NULL CHECK (actor IN ('pi', 'brain', 'executor', 'web_ui')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    details TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(details) AND json_type(details) = 'object'),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (
        project_id, artifact_version_id, commitment_key,
        requirement_key, action, target_id
    ),
    FOREIGN KEY (branch_id, project_id)
        REFERENCES manuscript_planning_branches(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (artifact_id, project_id)
        REFERENCES manuscript_planning_artifacts(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (artifact_version_id, artifact_id, project_id)
        REFERENCES manuscript_planning_artifact_versions(id, artifact_id, project_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (proposal_id, project_id)
        REFERENCES semantic_patch_proposals(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (mission_id, project_id)
        REFERENCES missions(id, project_id) ON DELETE RESTRICT,
    CHECK (
        (action = 'missing_evidence_mission_created'
         AND target_type = 'mission' AND mission_id = target_id
         AND proposal_id IS NULL AND requirement_key IS NOT NULL
         AND target_version IS NULL)
        OR
        (action = 'result_unit_proposal_prepared'
         AND target_type = 'semantic_patch_proposal' AND proposal_id = target_id
         AND mission_id IS NULL AND requirement_key IS NULL
         AND target_version IS NULL)
        OR
        (action = 'result_unit_proposal_applied'
         AND target_type = 'manuscript_unit' AND proposal_id IS NOT NULL
         AND mission_id IS NULL AND requirement_key IS NULL
         AND target_version IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_manuscript_evaluation_contract
    ON manuscript_evaluation_events(
        project_id, branch_id, artifact_version_id, commitment_key,
        requirement_key, created_at, id
    );
CREATE INDEX IF NOT EXISTS idx_manuscript_evaluation_proposal
    ON manuscript_evaluation_events(project_id, proposal_id)
    WHERE proposal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_manuscript_evaluation_mission
    ON manuscript_evaluation_events(project_id, mission_id)
    WHERE mission_id IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS trg_manuscript_evaluation_events_no_update
BEFORE UPDATE ON manuscript_evaluation_events
BEGIN
    SELECT RAISE(ABORT, 'manuscript evaluation events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_manuscript_evaluation_events_no_delete
BEFORE DELETE ON manuscript_evaluation_events
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations
    WHERE project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'manuscript evaluation events require project-authorized deletion');
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_evaluation_events_insert
AFTER INSERT ON manuscript_evaluation_events
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id, details
    ) VALUES (
        NEW.project_id,
        'manuscript_evaluation_events',
        'insert',
        'manuscript_evaluation_event',
        NEW.id,
        json_object(
            'branch_id', NEW.branch_id,
            'artifact_version_id', NEW.artifact_version_id,
            'commitment_key', NEW.commitment_key,
            'requirement_key', NEW.requirement_key,
            'action', NEW.action,
            'target_type', NEW.target_type,
            'target_id', NEW.target_id
        )
    );
END;
