-- Migration 038: authoritative manuscript citation/reference membership.
--
-- Validation attestations prove metadata/retraction checks for a reference,
-- but they do not prove which references the manuscript currently cites.  This
-- project-scoped table closes that set-membership gap by binding each active
-- citation key to exactly one same-project literature record.
--
-- Rows are retired rather than deleted by the service so historical citation
-- membership remains auditable.  The active-literature partial index prevents
-- one paper from appearing under two active keys in the same manuscript.

-- Explicit project deletion is the sole exception to immutable-history
-- triggers. ProjectService inserts this marker inside its BEGIN IMMEDIATE
-- transaction, removes every project-scoped row, and deletes the marker before
-- commit. Other connections cannot observe or exploit the uncommitted marker.
CREATE TABLE IF NOT EXISTS project_deletion_authorizations (
    project_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS manuscript_reference_members (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'mrf_' AND length(id) > 4),
    manuscript_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    citation_key TEXT NOT NULL
        CHECK (
            length(trim(citation_key)) BETWEEN 1 AND 256
            AND citation_key = trim(citation_key)
            AND citation_key NOT GLOB '*[ ,{}]*'
        ),
    literature_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'retired')),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    retired_at TEXT,
    UNIQUE (id, manuscript_id, project_id),
    FOREIGN KEY (manuscript_id, project_id)
        REFERENCES manuscripts(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (literature_id, project_id)
        REFERENCES literature(id, project_id) ON DELETE RESTRICT,
    CHECK (
        (state = 'active' AND retired_at IS NULL)
        OR (state = 'retired' AND retired_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_manuscript_reference_active_key
    ON manuscript_reference_members(
        manuscript_id, project_id, citation_key COLLATE NOCASE
    )
    WHERE state = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS uq_manuscript_reference_active_literature
    ON manuscript_reference_members(manuscript_id, project_id, literature_id)
    WHERE state = 'active';

CREATE INDEX IF NOT EXISTS idx_manuscript_reference_members_active
    ON manuscript_reference_members(
        project_id, manuscript_id, state, citation_key
    );

-- Identity is append-only. Replacing or re-adding a citation retires the old
-- row and inserts a new membership, preserving the historical set.
CREATE TRIGGER IF NOT EXISTS trg_manuscript_reference_identity_immutable
BEFORE UPDATE ON manuscript_reference_members
WHEN NEW.id <> OLD.id
  OR NEW.manuscript_id <> OLD.manuscript_id
  OR NEW.project_id <> OLD.project_id
  OR NEW.citation_key <> OLD.citation_key
  OR NEW.literature_id <> OLD.literature_id
  OR NEW.created_at <> OLD.created_at
  OR NOT (
      OLD.state = 'active'
      AND NEW.state = 'retired'
      AND OLD.retired_at IS NULL
      AND NEW.retired_at IS NOT NULL
  )
BEGIN
    SELECT RAISE(ABORT, 'manuscript reference membership identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_manuscript_reference_no_delete
BEFORE DELETE ON manuscript_reference_members
WHEN NOT EXISTS (
    SELECT 1
    FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'manuscript reference memberships are append-only');
END;

-- Earlier immutable histories predate explicit project deletion. Recreate
-- their no-delete guards so they retain normal immutability while permitting
-- the same transaction-scoped, confirmed project teardown.
DROP TRIGGER IF EXISTS trg_reference_validations_no_delete;
CREATE TRIGGER trg_reference_validations_no_delete
BEFORE DELETE ON reference_validation_attestations
WHEN NOT EXISTS (
    SELECT 1
    FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'reference validation attestations are immutable');
END;

DROP TRIGGER IF EXISTS trg_manuscript_claim_versions_no_delete;
CREATE TRIGGER trg_manuscript_claim_versions_no_delete
BEFORE DELETE ON manuscript_claim_versions
WHEN NOT EXISTS (
    SELECT 1
    FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'manuscript claim versions are immutable');
END;

DROP TRIGGER IF EXISTS trg_manuscript_claim_ratifications_no_delete;
CREATE TRIGGER trg_manuscript_claim_ratifications_no_delete
BEFORE DELETE ON manuscript_claim_ratifications
WHEN NOT EXISTS (
    SELECT 1
    FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'manuscript claim ratifications are immutable');
END;

DROP TRIGGER IF EXISTS trg_manuscript_claim_verifications_no_delete;
CREATE TRIGGER trg_manuscript_claim_verifications_no_delete
BEFORE DELETE ON manuscript_claim_verification_attestations
WHEN NOT EXISTS (
    SELECT 1
    FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'manuscript claim verification attestations are immutable');
END;

DROP TRIGGER IF EXISTS trg_change_events_no_delete;
CREATE TRIGGER trg_change_events_no_delete
BEFORE DELETE ON change_events
WHEN NOT EXISTS (
    SELECT 1
    FROM project_deletion_authorizations AS authorization
    WHERE authorization.project_id = OLD.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'semantic change events are immutable');
END;

-- Reference-set changes participate in the same project-scoped semantic
-- change cursor as the rest of the native manuscript aggregate.
CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_reference_members_insert
AFTER INSERT ON manuscript_reference_members
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_reference_members', 'insert',
        'manuscript_reference', NEW.id, NEW.manuscript_id,
        'literature', NEW.literature_id,
        json_object(
            'citation_key', NEW.citation_key,
            'state', NEW.state
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_reference_members_update
AFTER UPDATE ON manuscript_reference_members
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_reference_members', 'update',
        'manuscript_reference', NEW.id, NEW.manuscript_id,
        'literature', NEW.literature_id,
        json_object(
            'citation_key', NEW.citation_key,
            'state', NEW.state,
            'previous_citation_key', OLD.citation_key,
            'previous_state', OLD.state,
            'previous_literature_id', OLD.literature_id
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_reference_members_delete
AFTER DELETE ON manuscript_reference_members
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, related_entity_type, related_entity_id, details
    ) VALUES (
        OLD.project_id, 'manuscript_reference_members', 'delete',
        'manuscript_reference', OLD.id, OLD.manuscript_id,
        'literature', OLD.literature_id,
        json_object(
            'citation_key', OLD.citation_key,
            'state', OLD.state
        )
    );
END;
