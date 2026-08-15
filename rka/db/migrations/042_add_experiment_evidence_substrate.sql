-- Migration 042: project-scoped experiment/run/observation evidence substrate.
-- requires-table: projects, artifacts, claims, interpretation_candidates, interpretation_review_events, change_events, project_deletion_authorizations

-- Artifact IDs are globally unique in existing databases. This composite key
-- lets new evidence locators also enforce project equality at the FK layer.
CREATE UNIQUE INDEX IF NOT EXISTS uq_artifacts_id_project
    ON artifacts(id, project_id);

CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'exp_' AND length(id) > 4),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'active', 'completed', 'abandoned')),
    current_plan_version INTEGER NOT NULL DEFAULT 1
        CHECK (current_plan_version >= 1),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_by TEXT NOT NULL
        CHECK (created_by IN ('pi', 'brain', 'executor', 'web_ui', 'llm', 'import')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id)
);

CREATE INDEX IF NOT EXISTS idx_experiments_project_status
    ON experiments(project_id, status, updated_at DESC, id);

CREATE TABLE IF NOT EXISTS experiment_plan_versions (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'epv_' AND length(id) > 4),
    experiment_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    objective TEXT NOT NULL CHECK (length(trim(objective)) > 0),
    hypothesis TEXT,
    protocol TEXT NOT NULL CHECK (length(trim(protocol)) > 0),
    conditions TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(conditions) AND json_type(conditions) = 'array'),
    variables TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(variables) AND json_type(variables) = 'array'),
    metrics TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(metrics) AND json_type(metrics) = 'array'),
    baselines TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(baselines) AND json_type(baselines) = 'array'),
    success_criteria TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(success_criteria) AND json_type(success_criteria) = 'array'),
    failure_criteria TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(failure_criteria) AND json_type(failure_criteria) = 'array'),
    repository_url TEXT,
    commit_sha TEXT,
    working_tree_state TEXT
        CHECK (working_tree_state IS NULL OR working_tree_state IN ('clean', 'dirty', 'unknown')),
    created_by TEXT NOT NULL
        CHECK (created_by IN ('pi', 'brain', 'executor', 'web_ui', 'llm', 'import')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    supersedes_plan_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (experiment_id, project_id, version),
    FOREIGN KEY (experiment_id, project_id)
        REFERENCES experiments(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (supersedes_plan_id, project_id)
        REFERENCES experiment_plan_versions(id, project_id) ON DELETE RESTRICT,
    CHECK (
        (version = 1 AND supersedes_plan_id IS NULL)
        OR (version > 1 AND supersedes_plan_id IS NOT NULL)
    ),
    CHECK (
        (repository_url IS NULL AND commit_sha IS NULL AND working_tree_state IS NULL)
        OR (repository_url IS NOT NULL AND commit_sha IS NOT NULL AND working_tree_state IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_experiment_plan_versions_head
    ON experiment_plan_versions(project_id, experiment_id, version DESC);

CREATE TABLE IF NOT EXISTS experiment_runs (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'run_' AND length(id) > 4),
    experiment_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL CHECK (plan_version >= 1),
    label TEXT NOT NULL CHECK (length(trim(label)) > 0),
    runner TEXT NOT NULL
        CHECK (runner IN ('local', 'docker', 'cluster', 'manual', 'import')),
    command TEXT,
    config TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(config) AND json_type(config) = 'object'),
    environment TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(environment) AND json_type(environment) = 'object'),
    repository_url TEXT,
    commit_sha TEXT,
    working_tree_state TEXT
        CHECK (working_tree_state IS NULL OR working_tree_state IN ('clean', 'dirty', 'unknown')),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    started_at TEXT,
    completed_at TEXT,
    exit_code INTEGER,
    failure_summary TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_by TEXT NOT NULL
        CHECK (created_by IN ('pi', 'brain', 'executor', 'web_ui', 'llm', 'import')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    FOREIGN KEY (experiment_id, project_id, plan_version)
        REFERENCES experiment_plan_versions(experiment_id, project_id, version)
        ON DELETE RESTRICT,
    CHECK (
        (repository_url IS NULL AND commit_sha IS NULL AND working_tree_state IS NULL)
        OR (repository_url IS NOT NULL AND commit_sha IS NOT NULL AND working_tree_state IS NOT NULL)
    ),
    CHECK (status <> 'running' OR started_at IS NOT NULL),
    CHECK (status NOT IN ('succeeded', 'failed', 'cancelled') OR completed_at IS NOT NULL),
    CHECK (status <> 'failed' OR failure_summary IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_experiment_runs_experiment
    ON experiment_runs(project_id, experiment_id, created_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_experiment_runs_status
    ON experiment_runs(project_id, status, updated_at DESC, id);

CREATE TABLE IF NOT EXISTS experiment_run_events (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'rue_' AND length(id) > 4),
    run_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('created', 'start', 'succeed', 'fail', 'cancel')),
    from_status TEXT,
    to_status TEXT NOT NULL
        CHECK (to_status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    run_revision INTEGER NOT NULL CHECK (run_revision >= 1),
    actor TEXT NOT NULL
        CHECK (actor IN ('pi', 'brain', 'executor', 'web_ui', 'llm', 'import')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    exit_code INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (run_id, project_id)
        REFERENCES experiment_runs(id, project_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_experiment_run_events_run
    ON experiment_run_events(project_id, run_id, run_revision, created_at, id);

CREATE TABLE IF NOT EXISTS experiment_observations (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'obs_' AND length(id) > 4),
    run_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    kind TEXT NOT NULL
        CHECK (kind IN ('metric', 'comparison', 'test', 'qualitative', 'failure', 'artifact')),
    direction TEXT NOT NULL
        CHECK (direction IN ('positive', 'negative', 'inconclusive', 'neutral', 'error')),
    summary TEXT NOT NULL CHECK (length(trim(summary)) > 0),
    value_real REAL,
    value_text TEXT,
    unit TEXT,
    sample_size INTEGER CHECK (sample_size IS NULL OR sample_size >= 0),
    uncertainty_note TEXT,
    observed_at TEXT NOT NULL,
    recorded_by TEXT NOT NULL
        CHECK (recorded_by IN ('pi', 'brain', 'executor', 'web_ui', 'llm', 'import')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    FOREIGN KEY (run_id, project_id)
        REFERENCES experiment_runs(id, project_id) ON DELETE RESTRICT,
    CHECK (value_real IS NULL OR value_text IS NULL),
    CHECK (
        kind NOT IN ('metric', 'comparison', 'test')
        OR value_real IS NOT NULL
        OR (value_text IS NOT NULL AND length(trim(value_text)) > 0)
    ),
    CHECK (
        kind NOT IN ('qualitative', 'failure')
        OR (value_text IS NOT NULL AND length(trim(value_text)) > 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_experiment_observations_run
    ON experiment_observations(project_id, run_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_experiment_observations_direction
    ON experiment_observations(project_id, direction, created_at DESC, id);

CREATE TABLE IF NOT EXISTS evidence_locators (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'elc_' AND length(id) > 4),
    observation_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('artifact', 'repository')),
    artifact_id TEXT,
    repository_url TEXT,
    commit_sha TEXT,
    relative_path TEXT,
    locator_kind TEXT NOT NULL
        CHECK (locator_kind IN (
            'whole_artifact', 'page', 'line_range', 'table', 'table_cell',
            'json_pointer', 'notebook_cell', 'record'
        )),
    locator_start INTEGER CHECK (locator_start IS NULL OR locator_start >= 0),
    locator_end INTEGER CHECK (locator_end IS NULL OR locator_end >= locator_start),
    locator_value TEXT,
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    label TEXT,
    created_by TEXT NOT NULL
        CHECK (created_by IN ('pi', 'brain', 'executor', 'web_ui', 'llm', 'import')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    FOREIGN KEY (observation_id, project_id)
        REFERENCES experiment_observations(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (artifact_id, project_id)
        REFERENCES artifacts(id, project_id) ON DELETE RESTRICT,
    CHECK (
        (source_kind = 'artifact' AND artifact_id IS NOT NULL
         AND repository_url IS NULL AND commit_sha IS NULL AND relative_path IS NULL)
        OR
        (source_kind = 'repository' AND artifact_id IS NULL
         AND repository_url IS NOT NULL AND commit_sha IS NOT NULL
         AND relative_path IS NOT NULL)
    ),
    CHECK (
        (locator_kind IN ('page', 'line_range') AND locator_start IS NOT NULL)
        OR
        (locator_kind IN (
            'whole_artifact', 'table', 'table_cell', 'json_pointer',
            'notebook_cell', 'record'
        ) AND locator_value IS NOT NULL AND length(trim(locator_value)) > 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_evidence_locators_observation
    ON evidence_locators(project_id, observation_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_evidence_locators_artifact
    ON evidence_locators(project_id, artifact_id);

-- Expand Interpretation Staging to accept observation records and reviewed
-- evidence classification. The legacy-alter switch keeps foreign keys in the
-- dependent hint/promotion/scope tables pointed at the canonical table name.
PRAGMA foreign_keys = OFF;
PRAGMA legacy_alter_table = ON;

DROP TRIGGER IF EXISTS trg_interpretation_candidates_validate_update;
DROP TRIGGER IF EXISTS trg_interpretation_candidates_no_delete;
DROP TRIGGER IF EXISTS trg_change_interpretation_candidates_insert;
DROP TRIGGER IF EXISTS trg_change_interpretation_candidates_update;
DROP TRIGGER IF EXISTS trg_change_interpretation_candidates_delete;

ALTER TABLE interpretation_candidates RENAME TO interpretation_candidates_041;

CREATE TABLE interpretation_candidates (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'icd_' AND length(id) > 4),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    source_type TEXT NOT NULL
        CHECK (source_type IN ('journal', 'literature', 'artifact', 'experiment_observation')),
    source_id TEXT NOT NULL,
    locator_kind TEXT NOT NULL
        CHECK (locator_kind IN (
            'text_offset', 'page', 'line_range', 'section', 'url_fragment', 'record'
        )),
    locator_start INTEGER CHECK (locator_start IS NULL OR locator_start >= 0),
    locator_end INTEGER CHECK (locator_end IS NULL OR locator_end >= locator_start),
    locator_value TEXT,
    statement TEXT NOT NULL CHECK (length(trim(statement)) > 0),
    epistemic_kind TEXT NOT NULL
        CHECK (epistemic_kind IN (
            'observation', 'reported_fact', 'inference', 'hypothesis', 'plan',
            'author_intent'
        )),
    scope_conditions TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(scope_conditions) AND json_type(scope_conditions) = 'array'),
    uncertainty TEXT NOT NULL DEFAULT 'unknown'
        CHECK (uncertainty IN ('none', 'low', 'medium', 'high', 'unknown')),
    uncertainty_note TEXT,
    falsifier TEXT,
    proposed_claim_type TEXT
        CHECK (proposed_claim_type IS NULL OR proposed_claim_type IN (
            'hypothesis', 'evidence', 'method', 'result', 'observation', 'assumption'
        )),
    created_by TEXT NOT NULL
        CHECK (created_by IN ('pi', 'brain', 'executor', 'web_ui', 'llm', 'import')),
    extraction_tool TEXT NOT NULL CHECK (length(trim(extraction_tool)) > 0),
    extraction_model TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'in_review', 'resolved')),
    disposition TEXT
        CHECK (disposition IS NULL OR disposition IN (
            'promoted', 'merged', 'deferred', 'rejected', 'classified_decision',
            'classified_plan', 'classified_author_intent',
            'evidence_mission_requested', 'classified_evidence'
        )),
    disposition_reason TEXT,
    disposition_target_type TEXT,
    disposition_target_id TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    CHECK (
        (locator_kind IN ('text_offset', 'page', 'line_range')
         AND locator_start IS NOT NULL)
        OR
        (locator_kind IN ('section', 'url_fragment', 'record')
         AND locator_value IS NOT NULL AND length(trim(locator_value)) > 0)
    ),
    CHECK (
        (review_status = 'resolved' AND disposition IS NOT NULL)
        OR (review_status <> 'resolved' AND disposition IS NULL)
    )
);

INSERT INTO interpretation_candidates (
    id, project_id, source_type, source_id, locator_kind, locator_start,
    locator_end, locator_value, statement, epistemic_kind, scope_conditions,
    uncertainty, uncertainty_note, falsifier, proposed_claim_type, created_by,
    extraction_tool, extraction_model, review_status, disposition,
    disposition_reason, disposition_target_type, disposition_target_id,
    reviewed_by, reviewed_at, revision, created_at, updated_at
)
SELECT
    id, project_id, source_type, source_id, locator_kind, locator_start,
    locator_end, locator_value, statement, epistemic_kind, scope_conditions,
    uncertainty, uncertainty_note, falsifier, proposed_claim_type, created_by,
    extraction_tool, extraction_model, review_status, disposition,
    disposition_reason, disposition_target_type, disposition_target_id,
    reviewed_by, reviewed_at, revision, created_at, updated_at
FROM interpretation_candidates_041;

DROP TABLE interpretation_candidates_041;

CREATE INDEX IF NOT EXISTS idx_interpretation_candidates_review
    ON interpretation_candidates(project_id, review_status, created_at, id);
CREATE INDEX IF NOT EXISTS idx_interpretation_candidates_source
    ON interpretation_candidates(project_id, source_type, source_id, created_at);
CREATE INDEX IF NOT EXISTS idx_interpretation_candidates_kind
    ON interpretation_candidates(project_id, epistemic_kind, proposed_claim_type);

DROP TRIGGER IF EXISTS trg_interpretation_review_events_no_update;
DROP TRIGGER IF EXISTS trg_interpretation_review_events_no_delete;

ALTER TABLE interpretation_review_events RENAME TO interpretation_review_events_041;

CREATE TABLE interpretation_review_events (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'icv_' AND length(id) > 4),
    project_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN (
        'created', 'hint_added', 'start_review', 'promote', 'merge', 'defer',
        'reject', 'classify_decision', 'classify_plan',
        'classify_author_intent', 'request_evidence_mission', 'reopen',
        'revoke_promotion', 'classify_evidence', 'revoke_evidence'
    )),
    from_status TEXT,
    to_status TEXT NOT NULL CHECK (to_status IN ('pending', 'in_review', 'resolved')),
    disposition TEXT,
    actor TEXT NOT NULL,
    reason TEXT,
    target_type TEXT,
    target_id TEXT,
    candidate_revision INTEGER NOT NULL CHECK (candidate_revision >= 1),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (candidate_id, project_id)
        REFERENCES interpretation_candidates(id, project_id) ON DELETE RESTRICT
);

INSERT INTO interpretation_review_events (
    id, project_id, candidate_id, action, from_status, to_status, disposition,
    actor, reason, target_type, target_id, candidate_revision, created_at
)
SELECT
    id, project_id, candidate_id, action, from_status, to_status, disposition,
    actor, reason, target_type, target_id, candidate_revision, created_at
FROM interpretation_review_events_041;

DROP TABLE interpretation_review_events_041;

CREATE INDEX IF NOT EXISTS idx_interpretation_review_events_candidate
    ON interpretation_review_events(project_id, candidate_id, created_at, id);

PRAGMA legacy_alter_table = OFF;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS claim_evidence_relations (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'evr_' AND length(id) > 4),
    project_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    role TEXT NOT NULL
        CHECK (role IN ('support', 'qualifier', 'counterevidence', 'context')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    reviewed_by TEXT NOT NULL
        CHECK (reviewed_by IN ('pi', 'brain', 'executor', 'web_ui')),
    review_reason TEXT NOT NULL CHECK (length(trim(review_reason)) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revoked_by TEXT,
    revocation_reason TEXT,
    revoked_at TEXT,
    UNIQUE (id, project_id),
    UNIQUE (candidate_id, project_id),
    FOREIGN KEY (claim_id, project_id)
        REFERENCES claims(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (observation_id, project_id)
        REFERENCES experiment_observations(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (candidate_id, project_id)
        REFERENCES interpretation_candidates(id, project_id) ON DELETE RESTRICT,
    CHECK (
        (status = 'active' AND revoked_by IS NULL
         AND revocation_reason IS NULL AND revoked_at IS NULL)
        OR
        (status = 'revoked' AND revoked_by IS NOT NULL
         AND revocation_reason IS NOT NULL AND revoked_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_claim_evidence_relations_claim
    ON claim_evidence_relations(project_id, claim_id, status, created_at, id);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_relations_observation
    ON claim_evidence_relations(project_id, observation_id, status, created_at, id);

-- Immutable/revision guards.
CREATE TRIGGER IF NOT EXISTS trg_experiments_validate_update
BEFORE UPDATE ON experiments
WHEN NEW.id IS NOT OLD.id
  OR NEW.project_id IS NOT OLD.project_id
  OR NEW.title IS NOT OLD.title
  OR NEW.created_by IS NOT OLD.created_by
  OR NEW.created_at IS NOT OLD.created_at
  OR NEW.revision <> OLD.revision + 1
  OR NEW.current_plan_version < OLD.current_plan_version
  OR NEW.current_plan_version > OLD.current_plan_version + 1
  OR NOT (
      NEW.status = OLD.status
      OR (OLD.status = 'planned' AND NEW.status IN ('active', 'abandoned'))
      OR (OLD.status = 'active' AND NEW.status IN ('completed', 'abandoned'))
  )
BEGIN
    SELECT RAISE(ABORT, 'experiment updates require a valid next revision');
END;
CREATE TRIGGER IF NOT EXISTS trg_experiments_no_delete
BEFORE DELETE ON experiments
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'experiments require project-authorized deletion');
END;

CREATE TRIGGER IF NOT EXISTS trg_experiment_plan_versions_no_update
BEFORE UPDATE ON experiment_plan_versions
BEGIN
    SELECT RAISE(ABORT, 'experiment plan versions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_experiment_plan_versions_no_delete
BEFORE DELETE ON experiment_plan_versions
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'experiment plan versions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_experiment_runs_validate_update
BEFORE UPDATE ON experiment_runs
WHEN NEW.id IS NOT OLD.id
  OR NEW.experiment_id IS NOT OLD.experiment_id
  OR NEW.project_id IS NOT OLD.project_id
  OR NEW.plan_version IS NOT OLD.plan_version
  OR NEW.label IS NOT OLD.label
  OR NEW.runner IS NOT OLD.runner
  OR NEW.command IS NOT OLD.command
  OR NEW.config IS NOT OLD.config
  OR NEW.environment IS NOT OLD.environment
  OR NEW.repository_url IS NOT OLD.repository_url
  OR NEW.commit_sha IS NOT OLD.commit_sha
  OR NEW.working_tree_state IS NOT OLD.working_tree_state
  OR NEW.created_by IS NOT OLD.created_by
  OR NEW.created_at IS NOT OLD.created_at
  OR NEW.revision <> OLD.revision + 1
  OR NOT (
      (OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled'))
      OR (OLD.status = 'running' AND NEW.status IN ('succeeded', 'failed', 'cancelled'))
  )
BEGIN
    SELECT RAISE(ABORT, 'experiment run updates require a valid next transition');
END;

CREATE TRIGGER IF NOT EXISTS trg_experiment_runs_no_delete
BEFORE DELETE ON experiment_runs
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'experiment runs require project-authorized deletion');
END;

CREATE TRIGGER IF NOT EXISTS trg_experiment_run_events_no_update
BEFORE UPDATE ON experiment_run_events
BEGIN
    SELECT RAISE(ABORT, 'experiment run events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_experiment_run_events_no_delete
BEFORE DELETE ON experiment_run_events
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'experiment run events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_experiment_observations_no_update
BEFORE UPDATE ON experiment_observations
BEGIN
    SELECT RAISE(ABORT, 'experiment observations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_experiment_observations_no_delete
BEFORE DELETE ON experiment_observations
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'experiment observations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_evidence_locators_no_update
BEFORE UPDATE ON evidence_locators
BEGIN
    SELECT RAISE(ABORT, 'evidence locators are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_evidence_locators_no_delete
BEFORE DELETE ON evidence_locators
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'evidence locators are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_claim_evidence_relations_validate_update
BEFORE UPDATE ON claim_evidence_relations
WHEN OLD.status <> 'active'
  OR NEW.status <> 'revoked'
  OR NEW.id IS NOT OLD.id
  OR NEW.project_id IS NOT OLD.project_id
  OR NEW.claim_id IS NOT OLD.claim_id
  OR NEW.observation_id IS NOT OLD.observation_id
  OR NEW.candidate_id IS NOT OLD.candidate_id
  OR NEW.role IS NOT OLD.role
  OR NEW.reviewed_by IS NOT OLD.reviewed_by
  OR NEW.review_reason IS NOT OLD.review_reason
  OR NEW.created_at IS NOT OLD.created_at
  OR NEW.revoked_by IS NULL
  OR NEW.revocation_reason IS NULL
  OR NEW.revoked_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'claim evidence relation history is immutable except revocation');
END;

CREATE TRIGGER IF NOT EXISTS trg_claim_evidence_relations_no_delete
BEFORE DELETE ON claim_evidence_relations
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'claim evidence relations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_interpretation_candidates_validate_update
BEFORE UPDATE ON interpretation_candidates
WHEN NEW.id IS NOT OLD.id
  OR NEW.project_id IS NOT OLD.project_id
  OR NEW.source_type IS NOT OLD.source_type
  OR NEW.source_id IS NOT OLD.source_id
  OR NEW.locator_kind IS NOT OLD.locator_kind
  OR NEW.locator_start IS NOT OLD.locator_start
  OR NEW.locator_end IS NOT OLD.locator_end
  OR NEW.locator_value IS NOT OLD.locator_value
  OR NEW.statement IS NOT OLD.statement
  OR NEW.epistemic_kind IS NOT OLD.epistemic_kind
  OR NEW.scope_conditions IS NOT OLD.scope_conditions
  OR NEW.uncertainty IS NOT OLD.uncertainty
  OR NEW.uncertainty_note IS NOT OLD.uncertainty_note
  OR NEW.falsifier IS NOT OLD.falsifier
  OR NEW.proposed_claim_type IS NOT OLD.proposed_claim_type
  OR NEW.created_by IS NOT OLD.created_by
  OR NEW.extraction_tool IS NOT OLD.extraction_tool
  OR NEW.extraction_model IS NOT OLD.extraction_model
  OR NEW.created_at IS NOT OLD.created_at
  OR NEW.revision <> OLD.revision + 1
BEGIN
    SELECT RAISE(ABORT, 'interpretation candidate meaning is immutable and updates require next revision');
END;

CREATE TRIGGER IF NOT EXISTS trg_interpretation_candidates_no_delete
BEFORE DELETE ON interpretation_candidates
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'interpretation candidates require project-authorized deletion');
END;

CREATE TRIGGER IF NOT EXISTS trg_interpretation_review_events_no_update
BEFORE UPDATE ON interpretation_review_events
BEGIN
    SELECT RAISE(ABORT, 'interpretation review events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_interpretation_review_events_no_delete
BEFORE DELETE ON interpretation_review_events
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'interpretation review events are immutable');
END;

-- Semantic change cursor integration.
CREATE TRIGGER IF NOT EXISTS trg_change_experiments_insert
AFTER INSERT ON experiments
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id, details
    ) VALUES (
        NEW.project_id, 'experiments', 'insert', 'experiment', NEW.id,
        json_object('status', NEW.status, 'plan_version', NEW.current_plan_version,
                    'revision', NEW.revision)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_experiments_update
AFTER UPDATE ON experiments
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id, details
    ) VALUES (
        NEW.project_id, 'experiments', 'update', 'experiment', NEW.id,
        json_object('status', NEW.status, 'plan_version', NEW.current_plan_version,
                    'revision', NEW.revision)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_experiment_plan_versions_insert
AFTER INSERT ON experiment_plan_versions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'experiment_plan_versions', 'insert',
        'experiment_plan_version', NEW.id, 'experiment', NEW.experiment_id,
        json_object('version', NEW.version)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_experiment_runs_insert
AFTER INSERT ON experiment_runs
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'experiment_runs', 'insert', 'experiment_run', NEW.id,
        'experiment', NEW.experiment_id,
        json_object('status', NEW.status, 'plan_version', NEW.plan_version,
                    'revision', NEW.revision)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_experiment_runs_update
AFTER UPDATE ON experiment_runs
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'experiment_runs', 'update', 'experiment_run', NEW.id,
        'experiment', NEW.experiment_id,
        json_object('status', NEW.status, 'plan_version', NEW.plan_version,
                    'revision', NEW.revision)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_experiment_run_events_insert
AFTER INSERT ON experiment_run_events
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'experiment_run_events', 'insert',
        'experiment_run_event', NEW.id, 'experiment_run', NEW.run_id,
        json_object('action', NEW.action, 'to_status', NEW.to_status,
                    'run_revision', NEW.run_revision)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_experiment_observations_insert
AFTER INSERT ON experiment_observations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'experiment_observations', 'insert',
        'experiment_observation', NEW.id, 'experiment_run', NEW.run_id,
        json_object('kind', NEW.kind, 'direction', NEW.direction)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_evidence_locators_insert
AFTER INSERT ON evidence_locators
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'evidence_locators', 'insert', 'evidence_locator', NEW.id,
        'experiment_observation', NEW.observation_id,
        json_object('source_kind', NEW.source_kind,
                    'locator_kind', NEW.locator_kind,
                    'artifact_id', NEW.artifact_id)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_claim_evidence_relations_insert
AFTER INSERT ON claim_evidence_relations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'claim_evidence_relations', 'insert',
        'claim_evidence_relation', NEW.id, 'claim', NEW.claim_id,
        json_object('observation_id', NEW.observation_id,
                    'candidate_id', NEW.candidate_id,
                    'role', NEW.role, 'status', NEW.status)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_claim_evidence_relations_update
AFTER UPDATE ON claim_evidence_relations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'claim_evidence_relations', 'update',
        'claim_evidence_relation', NEW.id, 'claim', NEW.claim_id,
        json_object('observation_id', NEW.observation_id,
                    'candidate_id', NEW.candidate_id,
                    'role', NEW.role, 'status', NEW.status)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_interpretation_candidates_insert
AFTER INSERT ON interpretation_candidates
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'interpretation_candidates', 'insert',
        'interpretation_candidate', NEW.id, NEW.source_type, NEW.source_id,
        json_object('review_status', NEW.review_status, 'epistemic_kind', NEW.epistemic_kind)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_interpretation_candidates_update
AFTER UPDATE ON interpretation_candidates
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'interpretation_candidates', 'update',
        'interpretation_candidate', NEW.id, NEW.source_type, NEW.source_id,
        json_object('review_status', NEW.review_status,
                    'disposition', NEW.disposition, 'revision', NEW.revision)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_interpretation_candidates_delete
AFTER DELETE ON interpretation_candidates
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id
    ) VALUES (
        OLD.project_id, 'interpretation_candidates', 'delete',
        'interpretation_candidate', OLD.id, OLD.source_type, OLD.source_id
    );
END;
