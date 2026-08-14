-- Migration 040: typed Interpretation Staging upstream of canonical claims.
-- requires-table: projects, journal, literature, artifacts, claims, entity_links, change_events, project_deletion_authorizations

CREATE TABLE IF NOT EXISTS interpretation_candidates (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'icd_' AND length(id) > 4),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    source_type TEXT NOT NULL
        CHECK (source_type IN ('journal', 'literature', 'artifact')),
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
            'evidence_mission_requested'
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

CREATE INDEX IF NOT EXISTS idx_interpretation_candidates_review
    ON interpretation_candidates(project_id, review_status, created_at, id);
CREATE INDEX IF NOT EXISTS idx_interpretation_candidates_source
    ON interpretation_candidates(project_id, source_type, source_id, created_at);
CREATE INDEX IF NOT EXISTS idx_interpretation_candidates_kind
    ON interpretation_candidates(project_id, epistemic_kind, proposed_claim_type);

CREATE TABLE IF NOT EXISTS interpretation_candidate_hints (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'ich_' AND length(id) > 4),
    project_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    related_candidate_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('duplicate', 'conflict')),
    confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    created_by TEXT NOT NULL
        CHECK (created_by IN ('pi', 'brain', 'executor', 'web_ui', 'llm', 'import')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (candidate_id, related_candidate_id, kind),
    CHECK (candidate_id <> related_candidate_id),
    FOREIGN KEY (candidate_id, project_id)
        REFERENCES interpretation_candidates(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (related_candidate_id, project_id)
        REFERENCES interpretation_candidates(id, project_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_interpretation_hints_candidate
    ON interpretation_candidate_hints(project_id, candidate_id, kind);

CREATE TABLE IF NOT EXISTS interpretation_promotions (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'ipm_' AND length(id) > 4),
    project_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'revoked')),
    promoted_by TEXT NOT NULL
        CHECK (promoted_by IN ('pi', 'brain', 'executor', 'web_ui')),
    promotion_reason TEXT NOT NULL CHECK (length(trim(promotion_reason)) > 0),
    promoted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revoked_by TEXT,
    revocation_reason TEXT,
    revoked_at TEXT,
    UNIQUE (id, project_id),
    UNIQUE (claim_id, project_id),
    FOREIGN KEY (candidate_id, project_id)
        REFERENCES interpretation_candidates(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (claim_id, project_id)
        REFERENCES claims(id, project_id) ON DELETE RESTRICT,
    CHECK (
        (status = 'active' AND revoked_by IS NULL AND revocation_reason IS NULL AND revoked_at IS NULL)
        OR
        (status = 'revoked' AND revoked_by IS NOT NULL
         AND revocation_reason IS NOT NULL AND revoked_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_interpretation_active_promotion
    ON interpretation_promotions(candidate_id, project_id)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS interpretation_review_events (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'icv_' AND length(id) > 4),
    project_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN (
        'created', 'hint_added', 'start_review', 'promote', 'merge', 'defer',
        'reject', 'classify_decision', 'classify_plan',
        'classify_author_intent', 'request_evidence_mission', 'reopen',
        'revoke_promotion'
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

CREATE INDEX IF NOT EXISTS idx_interpretation_review_events_candidate
    ON interpretation_review_events(project_id, candidate_id, created_at, id);

-- Candidate source meaning is append-only. Review state may change, but every
-- service-managed change must advance the optimistic revision exactly once.
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

CREATE TRIGGER IF NOT EXISTS trg_interpretation_promotions_validate_update
BEFORE UPDATE ON interpretation_promotions
WHEN OLD.status <> 'active'
  OR NEW.status <> 'revoked'
  OR NEW.id <> OLD.id
  OR NEW.project_id <> OLD.project_id
  OR NEW.candidate_id <> OLD.candidate_id
  OR NEW.claim_id <> OLD.claim_id
  OR NEW.promoted_by <> OLD.promoted_by
  OR NEW.promotion_reason <> OLD.promotion_reason
  OR NEW.promoted_at <> OLD.promoted_at
  OR NEW.revoked_by IS NULL
  OR NEW.revocation_reason IS NULL
  OR NEW.revoked_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'interpretation promotion history is immutable except revocation');
END;

CREATE TRIGGER IF NOT EXISTS trg_interpretation_promotions_no_delete
BEFORE DELETE ON interpretation_promotions
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'interpretation promotions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_interpretation_hints_no_update
BEFORE UPDATE ON interpretation_candidate_hints
BEGIN
    SELECT RAISE(ABORT, 'interpretation candidate hints are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_interpretation_hints_no_delete
BEFORE DELETE ON interpretation_candidate_hints
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'interpretation candidate hints are immutable');
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
        json_object(
            'review_status', NEW.review_status,
            'disposition', NEW.disposition,
            'revision', NEW.revision
        )
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

CREATE TRIGGER IF NOT EXISTS trg_change_interpretation_hints_insert
AFTER INSERT ON interpretation_candidate_hints
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'interpretation_candidate_hints', 'insert',
        'interpretation_hint', NEW.id, 'interpretation_candidate', NEW.candidate_id,
        json_object('kind', NEW.kind, 'related_candidate_id', NEW.related_candidate_id)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_interpretation_promotions_insert
AFTER INSERT ON interpretation_promotions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'interpretation_promotions', 'insert',
        'interpretation_promotion', NEW.id, 'claim', NEW.claim_id,
        json_object('candidate_id', NEW.candidate_id, 'status', NEW.status)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_interpretation_promotions_update
AFTER UPDATE ON interpretation_promotions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'interpretation_promotions', 'update',
        'interpretation_promotion', NEW.id, 'claim', NEW.claim_id,
        json_object('candidate_id', NEW.candidate_id, 'status', NEW.status)
    );
END;
