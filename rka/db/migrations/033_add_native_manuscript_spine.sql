-- Migration 033: native, project-scoped manuscript and claim-spine foundation.
--
-- This migration is intentionally additive.  Legacy Writer manuscripts remain
-- journal rows tagged ``manuscript`` and are not copied, reclassified, or
-- ratified automatically.  A later compatibility workflow may explicitly bind
-- one of those rows through ``manuscripts.legacy_journal_id``.
--
-- Composite unique indexes on existing project-scoped tables provide legal
-- SQLite parent keys for same-project foreign keys below.  ``id`` is already a
-- primary key on each table, so these indexes do not change row identity.

CREATE UNIQUE INDEX IF NOT EXISTS uq_journal_id_project
    ON journal(id, project_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_decisions_id_project
    ON decisions(id, project_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_claims_id_project
    ON claims(id, project_id);

CREATE TABLE IF NOT EXISTS manuscripts (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'man_' AND length(id) > 4),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    abstract TEXT,
    venue TEXT,
    phase TEXT NOT NULL DEFAULT 'planning'
        CHECK (length(trim(phase)) > 0),
    state TEXT NOT NULL DEFAULT 'active'
        CHECK (state IN (
            'active', 'on_hold', 'submitted', 'accepted',
            'rejected', 'withdrawn', 'archived'
        )),
    workspace_ref TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    legacy_journal_id TEXT,
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, project_id),
    UNIQUE (legacy_journal_id, project_id),
    FOREIGN KEY (legacy_journal_id, project_id)
        REFERENCES journal(id, project_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_manuscripts_project_state
    ON manuscripts(project_id, state, updated_at);
CREATE INDEX IF NOT EXISTS idx_manuscripts_project_phase
    ON manuscripts(project_id, phase, updated_at);

-- Stable claim identity.  Wording is never stored here: every wording change
-- appends a row to manuscript_claim_versions.
CREATE TABLE IF NOT EXISTS manuscript_claims (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'mcl_' AND length(id) > 4),
    manuscript_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    local_key TEXT NOT NULL CHECK (length(trim(local_key)) > 0),
    kind TEXT NOT NULL
        CHECK (kind IN (
            'empirical', 'methodological', 'theoretical', 'survey', 'position'
        )),
    state TEXT NOT NULL DEFAULT 'candidate'
        CHECK (state IN ('candidate', 'active', 'retired')),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, manuscript_id, project_id),
    UNIQUE (manuscript_id, project_id, local_key),
    FOREIGN KEY (manuscript_id, project_id)
        REFERENCES manuscripts(id, project_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_manuscript_claims_manuscript
    ON manuscript_claims(project_id, manuscript_id, state, kind);

CREATE TABLE IF NOT EXISTS manuscript_claim_versions (
    claim_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    manuscript_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    exact_wording TEXT NOT NULL CHECK (length(trim(exact_wording)) > 0),
    allowed_wording TEXT NOT NULL CHECK (length(trim(allowed_wording)) > 0),
    prohibited_wording TEXT NOT NULL
        CHECK (
            json_valid(prohibited_wording)
            AND json_type(prohibited_wording) = 'array'
            AND json_array_length(prohibited_wording) >= 1
        ),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (claim_id, version),
    UNIQUE (claim_id, version, manuscript_id, project_id),
    FOREIGN KEY (claim_id, manuscript_id, project_id)
        REFERENCES manuscript_claims(id, manuscript_id, project_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_manuscript_claim_versions_manuscript
    ON manuscript_claim_versions(project_id, manuscript_id, claim_id, version);

CREATE TRIGGER IF NOT EXISTS trg_manuscript_claim_versions_no_update
BEFORE UPDATE ON manuscript_claim_versions
BEGIN
    SELECT RAISE(ABORT, 'manuscript claim versions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_manuscript_claim_versions_no_delete
BEFORE DELETE ON manuscript_claim_versions
BEGIN
    SELECT RAISE(ABORT, 'manuscript claim versions are immutable');
END;

-- A ratification is an immutable attestation that one active PI decision
-- selected the exact wording of one claim version.  The trigger deliberately
-- does not synthesize or infer ratification from legacy data.
CREATE TABLE IF NOT EXISTS manuscript_claim_ratifications (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'mra_' AND length(id) > 4),
    manuscript_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    claim_version INTEGER NOT NULL,
    decision_id TEXT NOT NULL,
    ratified_at TEXT NOT NULL,
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (decision_id, project_id),
    UNIQUE (claim_id, claim_version, decision_id),
    FOREIGN KEY (manuscript_id, project_id)
        REFERENCES manuscripts(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (claim_id, claim_version, manuscript_id, project_id)
        REFERENCES manuscript_claim_versions(
            claim_id, version, manuscript_id, project_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (decision_id, project_id)
        REFERENCES decisions(id, project_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_manuscript_claim_ratifications_claim
    ON manuscript_claim_ratifications(
        project_id, manuscript_id, claim_id, claim_version, ratified_at
    );

CREATE TRIGGER IF NOT EXISTS trg_manuscript_claim_ratifications_validate
BEFORE INSERT ON manuscript_claim_ratifications
WHEN
    NOT EXISTS (
        SELECT 1
        FROM decisions AS d
        JOIN manuscript_claim_versions AS v
          ON v.claim_id = NEW.claim_id
         AND v.version = NEW.claim_version
         AND v.manuscript_id = NEW.manuscript_id
         AND v.project_id = NEW.project_id
        WHERE d.id = NEW.decision_id
          AND d.project_id = NEW.project_id
          AND d.decided_by = 'pi'
          AND d.status = 'active'
          AND d.chosen = v.exact_wording
    )
    OR EXISTS (
        SELECT 1
        FROM manuscript_claim_ratifications AS prior
        JOIN decisions AS prior_decision
          ON prior_decision.id = prior.decision_id
         AND prior_decision.project_id = prior.project_id
        WHERE prior.claim_id = NEW.claim_id
          AND prior.project_id = NEW.project_id
          AND prior_decision.status = 'active'
    )
BEGIN
    SELECT RAISE(
        ABORT,
        'claim ratification requires one active same-project PI decision selecting exact wording'
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_manuscript_claim_ratifications_no_update
BEFORE UPDATE ON manuscript_claim_ratifications
BEGIN
    SELECT RAISE(ABORT, 'manuscript claim ratifications are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_manuscript_claim_ratifications_no_delete
BEFORE DELETE ON manuscript_claim_ratifications
BEGIN
    SELECT RAISE(ABORT, 'manuscript claim ratifications are immutable');
END;

CREATE TABLE IF NOT EXISTS manuscript_units (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'mun_' AND length(id) > 4),
    manuscript_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    local_key TEXT NOT NULL CHECK (length(trim(local_key)) > 0),
    kind TEXT NOT NULL
        CHECK (kind IN (
            'abstract', 'introduction', 'related_work', 'background',
            'method', 'result', 'discussion', 'limitation', 'conclusion',
            'caption', 'appendix', 'other'
        )),
    location TEXT NOT NULL CHECK (length(trim(location)) > 0),
    title TEXT,
    artifact_ref TEXT,
    allowed_interpretation TEXT,
    prohibited_interpretation TEXT,
    sequence INTEGER NOT NULL DEFAULT 0 CHECK (sequence >= 0),
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'drafted', 'reviewed', 'final', 'removed')),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, manuscript_id, project_id),
    UNIQUE (manuscript_id, project_id, local_key),
    FOREIGN KEY (manuscript_id, project_id)
        REFERENCES manuscripts(id, project_id) ON DELETE RESTRICT,
    CHECK (
        kind <> 'result'
        OR (
            artifact_ref IS NOT NULL
            AND length(trim(artifact_ref)) > 0
            AND allowed_interpretation IS NOT NULL
            AND length(trim(allowed_interpretation)) > 0
            AND prohibited_interpretation IS NOT NULL
            AND length(trim(prohibited_interpretation)) > 0
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_manuscript_units_manuscript
    ON manuscript_units(project_id, manuscript_id, sequence, kind);

-- Evidence joins name core RKA claims only.  Role is explicit so qualifiers
-- and counterevidence can never be laundered into positive support.
CREATE TABLE IF NOT EXISTS manuscript_claim_evidence (
    manuscript_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    manuscript_claim_id TEXT NOT NULL,
    claim_version INTEGER NOT NULL,
    evidence_claim_id TEXT NOT NULL,
    role TEXT NOT NULL
        CHECK (role IN ('support', 'qualifier', 'counterevidence')),
    ordinal INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (
        manuscript_claim_id, claim_version, evidence_claim_id, role
    ),
    FOREIGN KEY (
        manuscript_claim_id, claim_version, manuscript_id, project_id
    ) REFERENCES manuscript_claim_versions(
        claim_id, version, manuscript_id, project_id
    ) ON DELETE RESTRICT,
    FOREIGN KEY (evidence_claim_id, project_id)
        REFERENCES claims(id, project_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_manuscript_claim_evidence_source
    ON manuscript_claim_evidence(project_id, evidence_claim_id, role);

CREATE TABLE IF NOT EXISTS manuscript_unit_evidence (
    manuscript_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    evidence_claim_id TEXT NOT NULL,
    role TEXT NOT NULL
        CHECK (role IN ('support', 'qualifier', 'counterevidence')),
    ordinal INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (unit_id, evidence_claim_id, role),
    FOREIGN KEY (unit_id, manuscript_id, project_id)
        REFERENCES manuscript_units(id, manuscript_id, project_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (evidence_claim_id, project_id)
        REFERENCES claims(id, project_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_manuscript_unit_evidence_source
    ON manuscript_unit_evidence(project_id, evidence_claim_id, role);

CREATE TABLE IF NOT EXISTS manuscript_claim_units (
    manuscript_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    manuscript_claim_id TEXT NOT NULL,
    claim_version INTEGER NOT NULL,
    unit_id TEXT NOT NULL,
    relationship TEXT NOT NULL
        CHECK (relationship IN ('advances', 'tests', 'bounds', 'mentions')),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (
        manuscript_claim_id, claim_version, unit_id, relationship
    ),
    FOREIGN KEY (
        manuscript_claim_id, claim_version, manuscript_id, project_id
    ) REFERENCES manuscript_claim_versions(
        claim_id, version, manuscript_id, project_id
    ) ON DELETE RESTRICT,
    FOREIGN KEY (unit_id, manuscript_id, project_id)
        REFERENCES manuscript_units(id, manuscript_id, project_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_manuscript_claim_units_unit
    ON manuscript_claim_units(project_id, manuscript_id, unit_id);

CREATE TABLE IF NOT EXISTS manuscript_checkpoints (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'mck_' AND length(id) > 4),
    manuscript_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL
        CHECK (kind IN (
            'venue', 'outline', 'table_figure_plan',
            'reference_set', 'draft_section', 'final_layout'
        )),
    unit_id TEXT,
    decision_id TEXT,
    approved_choice TEXT,
    dependency_snapshot TEXT NOT NULL DEFAULT '{}'
        CHECK (
            json_valid(dependency_snapshot)
            AND json_type(dependency_snapshot) = 'object'
        ),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'resolved', 'rejected', 'superseded')),
    supersedes_id TEXT,
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    resolved_at TEXT,
    UNIQUE (id, manuscript_id, project_id),
    UNIQUE (decision_id, project_id),
    FOREIGN KEY (manuscript_id, project_id)
        REFERENCES manuscripts(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (unit_id, manuscript_id, project_id)
        REFERENCES manuscript_units(id, manuscript_id, project_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (decision_id, project_id)
        REFERENCES decisions(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (supersedes_id, manuscript_id, project_id)
        REFERENCES manuscript_checkpoints(id, manuscript_id, project_id)
        ON DELETE RESTRICT,
    CHECK (
        (kind = 'draft_section' AND unit_id IS NOT NULL)
        OR (kind <> 'draft_section' AND unit_id IS NULL)
    ),
    CHECK (
        (
            status = 'pending'
            AND decision_id IS NULL
            AND approved_choice IS NULL
            AND dependency_snapshot = '{}'
            AND resolved_at IS NULL
        )
        OR (
            status <> 'pending'
            AND decision_id IS NOT NULL
            AND approved_choice IS NOT NULL
            AND dependency_snapshot <> '{}'
            AND resolved_at IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_manuscript_checkpoints_manuscript
    ON manuscript_checkpoints(project_id, manuscript_id, kind, status);

CREATE TRIGGER IF NOT EXISTS trg_manuscript_checkpoints_validate_insert
BEFORE INSERT ON manuscript_checkpoints
WHEN NEW.status <> 'pending' AND NOT EXISTS (
    SELECT 1
    FROM decisions AS d
    WHERE d.id = NEW.decision_id
      AND d.project_id = NEW.project_id
      AND d.decided_by = 'pi'
      AND d.status = 'active'
      AND d.phase = 'paper_writing'
      AND length(trim(coalesce(d.chosen, ''))) > 0
      AND d.chosen = NEW.approved_choice
)
BEGIN
    SELECT RAISE(
        ABORT,
        'checkpoint resolution requires an active same-project PI decision'
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_manuscript_checkpoints_validate_resolution
BEFORE UPDATE OF status, decision_id, approved_choice, resolved_at
ON manuscript_checkpoints
WHEN OLD.status = 'pending'
 AND NEW.status <> 'pending'
 AND NOT EXISTS (
    SELECT 1
    FROM decisions AS d
    WHERE d.id = NEW.decision_id
      AND d.project_id = NEW.project_id
      AND d.decided_by = 'pi'
      AND d.status = 'active'
      AND d.phase = 'paper_writing'
      AND length(trim(coalesce(d.chosen, ''))) > 0
      AND d.chosen = NEW.approved_choice
)
BEGIN
    SELECT RAISE(
        ABORT,
        'checkpoint resolution requires an active same-project PI decision'
    );
END;

-- Verification is an append-only observation, not mutable claim state.  The
-- six dimensions keep grounding, evidence, contradiction, currency,
-- ratification, and unit coverage independently auditable.
CREATE TABLE IF NOT EXISTS manuscript_claim_verification_attestations (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'mva_' AND length(id) > 4),
    manuscript_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    claim_version INTEGER NOT NULL,
    overall_verdict TEXT NOT NULL
        CHECK (overall_verdict IN ('pass', 'warn', 'block', 'error')),
    grounding_verdict TEXT NOT NULL
        CHECK (grounding_verdict IN (
            'pass', 'warn', 'block', 'error', 'not_checked'
        )),
    evidence_verdict TEXT NOT NULL
        CHECK (evidence_verdict IN (
            'pass', 'warn', 'block', 'error', 'not_checked'
        )),
    contradiction_verdict TEXT NOT NULL
        CHECK (contradiction_verdict IN (
            'pass', 'warn', 'block', 'error', 'not_checked'
        )),
    currency_verdict TEXT NOT NULL
        CHECK (currency_verdict IN (
            'pass', 'warn', 'block', 'error', 'not_checked'
        )),
    ratification_verdict TEXT NOT NULL
        CHECK (ratification_verdict IN (
            'pass', 'warn', 'block', 'error', 'not_checked'
        )),
    unit_coverage_verdict TEXT NOT NULL
        CHECK (unit_coverage_verdict IN (
            'pass', 'warn', 'block', 'error', 'not_checked'
        )),
    changelog_cursor TEXT,
    dependency_snapshot TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(dependency_snapshot)),
    full_json_payload TEXT NOT NULL
        CHECK (json_valid(full_json_payload)),
    validator_version TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (manuscript_id, project_id)
        REFERENCES manuscripts(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (claim_id, claim_version, manuscript_id, project_id)
        REFERENCES manuscript_claim_versions(
            claim_id, version, manuscript_id, project_id
        ) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_manuscript_claim_verifications_claim
    ON manuscript_claim_verification_attestations(
        project_id, manuscript_id, claim_id, claim_version, created_at
    );
CREATE INDEX IF NOT EXISTS idx_manuscript_claim_verifications_verdict
    ON manuscript_claim_verification_attestations(
        project_id, manuscript_id, overall_verdict, created_at
    );

CREATE TRIGGER IF NOT EXISTS trg_manuscript_claim_verifications_no_update
BEFORE UPDATE ON manuscript_claim_verification_attestations
BEGIN
    SELECT RAISE(ABORT, 'manuscript claim verification attestations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_manuscript_claim_verifications_no_delete
BEFORE DELETE ON manuscript_claim_verification_attestations
BEGIN
    SELECT RAISE(ABORT, 'manuscript claim verification attestations are immutable');
END;
