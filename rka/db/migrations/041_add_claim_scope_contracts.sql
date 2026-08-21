-- Migration 041: immutable canonical claim-scope contracts.
-- requires-table: projects, claims, interpretation_candidates, change_events, project_deletion_authorizations

ALTER TABLE claims ADD COLUMN scope_revision INTEGER NOT NULL DEFAULT 0
    CHECK (scope_revision >= 0);

CREATE TABLE IF NOT EXISTS claim_scope_versions (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'csc_' AND length(id) > 4),
    claim_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    claim_content_hash TEXT NOT NULL
        CHECK (length(claim_content_hash) = 64),
    conditions TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(conditions) AND json_type(conditions) = 'array'),
    uncertainty TEXT NOT NULL DEFAULT 'unknown'
        CHECK (uncertainty IN ('none', 'low', 'medium', 'high', 'unknown')),
    uncertainty_note TEXT,
    extension_policy TEXT
        CHECK (extension_policy IS NULL OR extension_policy IN (
            'exact_only', 'bounded'
        )),
    allowed_extensions TEXT NOT NULL DEFAULT '[]'
        CHECK (
            json_valid(allowed_extensions)
            AND json_type(allowed_extensions) = 'array'
        ),
    prohibited_extensions TEXT NOT NULL DEFAULT '[]'
        CHECK (
            json_valid(prohibited_extensions)
            AND json_type(prohibited_extensions) = 'array'
        ),
    falsifier_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (falsifier_status IN ('unknown', 'applicable', 'not_applicable')),
    falsifier TEXT,
    falsifier_rationale TEXT,
    disconfirming_claim_ids TEXT NOT NULL DEFAULT '[]'
        CHECK (
            json_valid(disconfirming_claim_ids)
            AND json_type(disconfirming_claim_ids) = 'array'
        ),
    review_status TEXT NOT NULL DEFAULT 'draft'
        CHECK (review_status IN ('draft', 'reviewed')),
    created_by TEXT NOT NULL
        CHECK (created_by IN (
            'pi', 'brain', 'executor', 'web_ui', 'llm', 'import'
        )),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    source_candidate_id TEXT,
    supersedes_scope_id TEXT,
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (claim_id, project_id, revision),
    FOREIGN KEY (claim_id, project_id)
        REFERENCES claims(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (source_candidate_id, project_id)
        REFERENCES interpretation_candidates(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (supersedes_scope_id, project_id)
        REFERENCES claim_scope_versions(id, project_id) ON DELETE RESTRICT,
    CHECK (
        (extension_policy = 'exact_only' AND json_array_length(allowed_extensions) = 0)
        OR extension_policy = 'bounded'
        OR extension_policy IS NULL
    ),
    CHECK (
        falsifier_status <> 'applicable'
        OR (falsifier IS NOT NULL AND length(trim(falsifier)) > 0)
    ),
    CHECK (
        falsifier_status <> 'not_applicable'
        OR (
            falsifier_rationale IS NOT NULL
            AND length(trim(falsifier_rationale)) > 0
        )
    ),
    CHECK (
        review_status <> 'reviewed'
        OR (
            json_array_length(conditions) >= 1
            AND uncertainty <> 'unknown'
            AND extension_policy IS NOT NULL
            AND (
                extension_policy = 'exact_only'
                OR json_array_length(allowed_extensions) >= 1
            )
            AND json_array_length(prohibited_extensions) >= 1
            AND falsifier_status <> 'unknown'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_claim_scope_versions_claim
    ON claim_scope_versions(project_id, claim_id, revision DESC);
CREATE INDEX IF NOT EXISTS idx_claim_scope_versions_review
    ON claim_scope_versions(project_id, review_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_claim_scope_versions_source_candidate
    ON claim_scope_versions(project_id, source_candidate_id)
    WHERE source_candidate_id IS NOT NULL;

-- A new immutable version must be exactly one revision beyond the claim's
-- current pointer and must name the current version as its predecessor.
CREATE TRIGGER IF NOT EXISTS trg_claim_scope_versions_validate_insert
BEFORE INSERT ON claim_scope_versions
WHEN NEW.revision <> COALESCE((
        SELECT scope_revision FROM claims
        WHERE id = NEW.claim_id AND project_id = NEW.project_id
    ), -1) + 1
  OR (
        NEW.revision = 1
        AND NEW.supersedes_scope_id IS NOT NULL
    )
  OR (
        NEW.revision > 1
        AND NEW.supersedes_scope_id IS NOT (
            SELECT id FROM claim_scope_versions
            WHERE claim_id = NEW.claim_id
              AND project_id = NEW.project_id
              AND revision = NEW.revision - 1
        )
    )
BEGIN
    SELECT RAISE(ABORT, 'claim scope version must append to the current revision');
END;

CREATE TRIGGER IF NOT EXISTS trg_claim_scope_versions_no_update
BEFORE UPDATE ON claim_scope_versions
BEGIN
    SELECT RAISE(ABORT, 'claim scope versions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_claim_scope_versions_no_delete
BEFORE DELETE ON claim_scope_versions
WHEN NOT EXISTS (
    SELECT 1 FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'claim scope versions require project-authorized deletion');
END;

-- The head pointer can only advance by one and only after the immutable row
-- exists in the same transaction. Other claim fields remain governed by their
-- existing update contract.
CREATE TRIGGER IF NOT EXISTS trg_claims_validate_scope_revision_update
BEFORE UPDATE OF scope_revision ON claims
WHEN NEW.scope_revision IS NOT OLD.scope_revision
 AND (
        NEW.scope_revision <> OLD.scope_revision + 1
        OR NOT EXISTS (
            SELECT 1 FROM claim_scope_versions AS scope
            WHERE scope.claim_id = NEW.id
              AND scope.project_id = NEW.project_id
              AND scope.revision = NEW.scope_revision
        )
    )
BEGIN
    SELECT RAISE(ABORT, 'claim scope revision must advance to an existing next version');
END;

CREATE TRIGGER IF NOT EXISTS trg_change_claim_scope_versions_insert
AFTER INSERT ON claim_scope_versions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'claim_scope_versions', 'insert',
        'claim_scope', NEW.id, 'claim', NEW.claim_id,
        json_object(
            'revision', NEW.revision,
            'review_status', NEW.review_status,
            'uncertainty', NEW.uncertainty,
            'extension_policy', NEW.extension_policy
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_claim_scope_versions_delete
AFTER DELETE ON claim_scope_versions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        OLD.project_id, 'claim_scope_versions', 'delete',
        'claim_scope', OLD.id, 'claim', OLD.claim_id,
        json_object('revision', OLD.revision)
    );
END;
