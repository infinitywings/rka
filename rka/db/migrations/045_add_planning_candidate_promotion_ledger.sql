-- Migration 045: immutable lineage for independently promoted planning candidates.
-- requires-table: projects, manuscript_planning_branches, manuscript_planning_artifacts, manuscript_planning_artifact_versions, semantic_patch_proposals, decisions, change_events, project_deletion_authorizations

CREATE TABLE IF NOT EXISTS manuscript_planning_promotion_events (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'ppe_' AND length(id) > 4),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    branch_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_version_id TEXT NOT NULL,
    artifact_version INTEGER NOT NULL CHECK (artifact_version >= 1),
    branch_revision INTEGER NOT NULL CHECK (branch_revision >= 1),
    candidate_kind TEXT NOT NULL
        CHECK (candidate_kind IN ('research_question', 'contribution')),
    candidate_key TEXT NOT NULL CHECK (length(trim(candidate_key)) > 0),
    action TEXT NOT NULL CHECK (action IN (
        'rq_promoted',
        'contribution_proposal_prepared',
        'contribution_proposal_applied',
        'contribution_ratified'
    )),
    target_type TEXT NOT NULL CHECK (target_type IN (
        'decision', 'semantic_patch_proposal',
        'manuscript_claim', 'manuscript_claim_ratification'
    )),
    target_id TEXT NOT NULL CHECK (length(trim(target_id)) > 0),
    target_version INTEGER CHECK (target_version IS NULL OR target_version >= 1),
    proposal_id TEXT,
    decision_id TEXT,
    actor TEXT NOT NULL CHECK (actor IN ('pi', 'brain', 'executor', 'web_ui')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    details TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(details) AND json_type(details) = 'object'),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (
        project_id, artifact_version_id, candidate_kind, candidate_key,
        action, target_id
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
    FOREIGN KEY (decision_id, project_id)
        REFERENCES decisions(id, project_id) ON DELETE RESTRICT,
    CHECK (
        (action = 'rq_promoted' AND candidate_kind = 'research_question'
         AND target_type = 'decision' AND decision_id = target_id
         AND proposal_id IS NULL AND target_version IS NULL)
        OR
        (action = 'contribution_proposal_prepared' AND candidate_kind = 'contribution'
         AND target_type = 'semantic_patch_proposal' AND proposal_id = target_id
         AND decision_id IS NULL AND target_version IS NULL)
        OR
        (action = 'contribution_proposal_applied' AND candidate_kind = 'contribution'
         AND target_type = 'manuscript_claim' AND proposal_id IS NOT NULL
         AND decision_id IS NULL AND target_version IS NOT NULL)
        OR
        (action = 'contribution_ratified' AND candidate_kind = 'contribution'
         AND target_type = 'manuscript_claim_ratification'
         AND proposal_id IS NOT NULL AND decision_id IS NOT NULL
         AND target_version IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_planning_promotion_candidate
    ON manuscript_planning_promotion_events(
        project_id, branch_id, artifact_version_id, candidate_kind, candidate_key,
        created_at, id
    );
CREATE INDEX IF NOT EXISTS idx_planning_promotion_proposal
    ON manuscript_planning_promotion_events(project_id, proposal_id)
    WHERE proposal_id IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS trg_planning_promotion_events_no_update
BEFORE UPDATE ON manuscript_planning_promotion_events
BEGIN
    SELECT RAISE(ABORT, 'planning promotion events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_planning_promotion_events_no_delete
BEFORE DELETE ON manuscript_planning_promotion_events
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations
    WHERE project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'planning promotion events require project-authorized deletion');
END;

CREATE TRIGGER IF NOT EXISTS trg_change_planning_promotion_events_insert
AFTER INSERT ON manuscript_planning_promotion_events
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id, details
    ) VALUES (
        NEW.project_id,
        'manuscript_planning_promotion_events',
        'insert',
        'manuscript_planning_promotion_event',
        NEW.id,
        json_object(
            'branch_id', NEW.branch_id,
            'artifact_version_id', NEW.artifact_version_id,
            'candidate_kind', NEW.candidate_kind,
            'candidate_key', NEW.candidate_key,
            'action', NEW.action,
            'target_type', NEW.target_type,
            'target_id', NEW.target_id
        )
    );
END;
