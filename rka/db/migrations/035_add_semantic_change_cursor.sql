-- Migration 035: durable, project-scoped semantic change cursor.
--
-- ``change_events.cursor`` is an opaque, monotonically increasing watermark.
-- It is intentionally independent from wall-clock timestamps: concurrent or
-- same-millisecond writes still have a deterministic order.  The ledger stores
-- dependency hints needed by Writer impact analysis, but it never copies full
-- research content.
--
-- Triggers are used instead of service-level emission so writes from every
-- supported surface (REST, MCP, migrations, maintenance, or a transaction)
-- advance the same cursor.  In particular, tag-only and edge-only changes are
-- observable.

CREATE TABLE IF NOT EXISTS change_events (
    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    source_table TEXT NOT NULL,
    operation TEXT NOT NULL
        CHECK (operation IN ('insert', 'update', 'delete')),
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    manuscript_id TEXT,
    manuscript_claim_id TEXT,
    manuscript_unit_id TEXT,
    related_entity_type TEXT,
    related_entity_id TEXT,
    details TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(details) AND json_type(details) = 'object'),
    changed_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_change_events_project_cursor
    ON change_events(project_id, cursor);
CREATE INDEX IF NOT EXISTS idx_change_events_entity
    ON change_events(project_id, entity_type, entity_id, cursor);
CREATE INDEX IF NOT EXISTS idx_change_events_manuscript
    ON change_events(project_id, manuscript_id, cursor);
CREATE INDEX IF NOT EXISTS idx_change_events_related
    ON change_events(project_id, related_entity_type, related_entity_id, cursor);

CREATE TRIGGER IF NOT EXISTS trg_change_events_no_update
BEFORE UPDATE ON change_events
BEGIN
    SELECT RAISE(ABORT, 'semantic change events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_change_events_no_delete
BEFORE DELETE ON change_events
BEGIN
    SELECT RAISE(ABORT, 'semantic change events are immutable');
END;

-- -------------------------------------------------------------------------
-- Core RKA entities
-- -------------------------------------------------------------------------

CREATE TRIGGER IF NOT EXISTS trg_change_journal_insert
AFTER INSERT ON journal
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id
    ) VALUES (
        COALESCE(NEW.project_id, 'proj_default'),
        'journal', 'insert', 'journal', NEW.id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_journal_update
AFTER UPDATE ON journal
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id
    ) VALUES (
        COALESCE(NEW.project_id, OLD.project_id, 'proj_default'),
        'journal', 'update', 'journal', NEW.id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_journal_delete
AFTER DELETE ON journal
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id
    ) VALUES (
        COALESCE(OLD.project_id, 'proj_default'),
        'journal', 'delete', 'journal', OLD.id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_decisions_insert
AFTER INSERT ON decisions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        details
    ) VALUES (
        COALESCE(NEW.project_id, 'proj_default'),
        'decisions', 'insert', 'decision', NEW.id,
        json_object('kind', NEW.kind, 'status', NEW.status)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_decisions_update
AFTER UPDATE ON decisions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        details
    ) VALUES (
        COALESCE(NEW.project_id, OLD.project_id, 'proj_default'),
        'decisions', 'update', 'decision', NEW.id,
        json_object('kind', NEW.kind, 'status', NEW.status)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_decisions_delete
AFTER DELETE ON decisions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        details
    ) VALUES (
        COALESCE(OLD.project_id, 'proj_default'),
        'decisions', 'delete', 'decision', OLD.id,
        json_object('kind', OLD.kind, 'status', OLD.status)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_literature_insert
AFTER INSERT ON literature
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id
    ) VALUES (
        COALESCE(NEW.project_id, 'proj_default'),
        'literature', 'insert', 'literature', NEW.id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_literature_update
AFTER UPDATE ON literature
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id
    ) VALUES (
        COALESCE(NEW.project_id, OLD.project_id, 'proj_default'),
        'literature', 'update', 'literature', NEW.id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_literature_delete
AFTER DELETE ON literature
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id
    ) VALUES (
        COALESCE(OLD.project_id, 'proj_default'),
        'literature', 'delete', 'literature', OLD.id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_missions_insert
AFTER INSERT ON missions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id
    ) VALUES (
        COALESCE(NEW.project_id, 'proj_default'),
        'missions', 'insert', 'mission', NEW.id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_missions_update
AFTER UPDATE ON missions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id
    ) VALUES (
        COALESCE(NEW.project_id, OLD.project_id, 'proj_default'),
        'missions', 'update', 'mission', NEW.id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_missions_delete
AFTER DELETE ON missions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id
    ) VALUES (
        COALESCE(OLD.project_id, 'proj_default'),
        'missions', 'delete', 'mission', OLD.id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_checkpoints_insert
AFTER INSERT ON checkpoints
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id
    ) VALUES (
        COALESCE(NEW.project_id, 'proj_default'),
        'checkpoints', 'insert', 'checkpoint', NEW.id,
        CASE WHEN NEW.mission_id IS NULL THEN NULL ELSE 'mission' END,
        NEW.mission_id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_checkpoints_update
AFTER UPDATE ON checkpoints
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id
    ) VALUES (
        COALESCE(NEW.project_id, OLD.project_id, 'proj_default'),
        'checkpoints', 'update', 'checkpoint', NEW.id,
        CASE WHEN NEW.mission_id IS NULL THEN NULL ELSE 'mission' END,
        NEW.mission_id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_checkpoints_delete
AFTER DELETE ON checkpoints
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id
    ) VALUES (
        COALESCE(OLD.project_id, 'proj_default'),
        'checkpoints', 'delete', 'checkpoint', OLD.id,
        CASE WHEN OLD.mission_id IS NULL THEN NULL ELSE 'mission' END,
        OLD.mission_id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_claims_insert
AFTER INSERT ON claims
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'claims', 'insert', 'claim', NEW.id,
        'journal', NEW.source_entry_id,
        json_object(
            'verified', NEW.verified,
            'stale', NEW.stale,
            'evidence_status', NEW.evidence_status
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_claims_update
AFTER UPDATE ON claims
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'claims', 'update', 'claim', NEW.id,
        'journal', NEW.source_entry_id,
        json_object(
            'verified', NEW.verified,
            'stale', NEW.stale,
            'evidence_status', NEW.evidence_status
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_claims_delete
AFTER DELETE ON claims
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        OLD.project_id, 'claims', 'delete', 'claim', OLD.id,
        'journal', OLD.source_entry_id,
        json_object(
            'verified', OLD.verified,
            'stale', OLD.stale,
            'evidence_status', OLD.evidence_status
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_evidence_clusters_insert
AFTER INSERT ON evidence_clusters
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id
    ) VALUES (
        NEW.project_id, 'evidence_clusters', 'insert', 'cluster', NEW.id,
        CASE
            WHEN NEW.research_question_id IS NULL THEN NULL
            ELSE 'decision'
        END,
        NEW.research_question_id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_evidence_clusters_update
AFTER UPDATE ON evidence_clusters
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id
    ) VALUES (
        NEW.project_id, 'evidence_clusters', 'update', 'cluster', NEW.id,
        CASE
            WHEN NEW.research_question_id IS NULL THEN NULL
            ELSE 'decision'
        END,
        NEW.research_question_id
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_evidence_clusters_delete
AFTER DELETE ON evidence_clusters
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id
    ) VALUES (
        OLD.project_id, 'evidence_clusters', 'delete', 'cluster', OLD.id,
        CASE
            WHEN OLD.research_question_id IS NULL THEN NULL
            ELSE 'decision'
        END,
        OLD.research_question_id
    );
END;

-- -------------------------------------------------------------------------
-- Metadata and graph edges.  These are first-class semantic changes: no
-- parent-row update is required for the cursor to advance.
-- -------------------------------------------------------------------------

CREATE TRIGGER IF NOT EXISTS trg_change_tags_insert
AFTER INSERT ON tags
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id, details
    ) VALUES (
        COALESCE(NEW.project_id, 'proj_default'),
        'tags', 'insert', NEW.entity_type, NEW.entity_id,
        json_object('tag', NEW.tag)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_tags_update
AFTER UPDATE ON tags
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id, details
    ) VALUES (
        COALESCE(NEW.project_id, OLD.project_id, 'proj_default'),
        'tags', 'update', NEW.entity_type, NEW.entity_id,
        json_object('tag', NEW.tag, 'previous_tag', OLD.tag)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_tags_delete
AFTER DELETE ON tags
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id, details
    ) VALUES (
        COALESCE(OLD.project_id, 'proj_default'),
        'tags', 'delete', OLD.entity_type, OLD.entity_id,
        json_object('tag', OLD.tag)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_entity_links_insert
AFTER INSERT ON entity_links
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        COALESCE(NEW.project_id, 'proj_default'),
        'entity_links', 'insert', NEW.source_type, NEW.source_id,
        NEW.target_type, NEW.target_id,
        json_object('edge_id', NEW.id, 'link_type', NEW.link_type)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_entity_links_update
AFTER UPDATE ON entity_links
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        COALESCE(NEW.project_id, OLD.project_id, 'proj_default'),
        'entity_links', 'update', NEW.source_type, NEW.source_id,
        NEW.target_type, NEW.target_id,
        json_object(
            'edge_id', NEW.id,
            'link_type', NEW.link_type,
            'previous_source_type', OLD.source_type,
            'previous_source_id', OLD.source_id,
            'previous_target_type', OLD.target_type,
            'previous_target_id', OLD.target_id
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_entity_links_delete
AFTER DELETE ON entity_links
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        COALESCE(OLD.project_id, 'proj_default'),
        'entity_links', 'delete', OLD.source_type, OLD.source_id,
        OLD.target_type, OLD.target_id,
        json_object('edge_id', OLD.id, 'link_type', OLD.link_type)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_claim_edges_insert
AFTER INSERT ON claim_edges
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'claim_edges', 'insert', 'claim', NEW.source_claim_id,
        CASE
            WHEN NEW.target_claim_id IS NOT NULL THEN 'claim'
            WHEN NEW.cluster_id IS NOT NULL THEN 'cluster'
            ELSE NULL
        END,
        COALESCE(NEW.target_claim_id, NEW.cluster_id),
        json_object('edge_id', NEW.id, 'relation', NEW.relation)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_claim_edges_update
AFTER UPDATE ON claim_edges
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'claim_edges', 'update', 'claim', NEW.source_claim_id,
        CASE
            WHEN NEW.target_claim_id IS NOT NULL THEN 'claim'
            WHEN NEW.cluster_id IS NOT NULL THEN 'cluster'
            ELSE NULL
        END,
        COALESCE(NEW.target_claim_id, NEW.cluster_id),
        json_object(
            'edge_id', NEW.id,
            'relation', NEW.relation,
            'previous_source_claim_id', OLD.source_claim_id,
            'previous_target_claim_id', OLD.target_claim_id,
            'previous_cluster_id', OLD.cluster_id
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_claim_edges_delete
AFTER DELETE ON claim_edges
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        OLD.project_id, 'claim_edges', 'delete', 'claim', OLD.source_claim_id,
        CASE
            WHEN OLD.target_claim_id IS NOT NULL THEN 'claim'
            WHEN OLD.cluster_id IS NOT NULL THEN 'cluster'
            ELSE NULL
        END,
        COALESCE(OLD.target_claim_id, OLD.cluster_id),
        json_object('edge_id', OLD.id, 'relation', OLD.relation)
    );
END;

-- -------------------------------------------------------------------------
-- Native manuscript aggregate.  Every table in migration 033 is covered.
-- -------------------------------------------------------------------------

CREATE TRIGGER IF NOT EXISTS trg_change_manuscripts_insert
AFTER INSERT ON manuscripts
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscripts', 'insert', 'manuscript', NEW.id,
        NEW.id,
        CASE
            WHEN NEW.legacy_journal_id IS NULL THEN NULL
            ELSE 'journal'
        END,
        NEW.legacy_journal_id,
        json_object(
            'revision', NEW.revision, 'phase', NEW.phase, 'state', NEW.state
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscripts_update
AFTER UPDATE ON manuscripts
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscripts', 'update', 'manuscript', NEW.id,
        NEW.id,
        CASE
            WHEN NEW.legacy_journal_id IS NULL THEN NULL
            ELSE 'journal'
        END,
        NEW.legacy_journal_id,
        json_object(
            'revision', NEW.revision, 'phase', NEW.phase, 'state', NEW.state
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscripts_delete
AFTER DELETE ON manuscripts
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, related_entity_type, related_entity_id, details
    ) VALUES (
        OLD.project_id, 'manuscripts', 'delete', 'manuscript', OLD.id,
        OLD.id,
        CASE
            WHEN OLD.legacy_journal_id IS NULL THEN NULL
            ELSE 'journal'
        END,
        OLD.legacy_journal_id,
        json_object(
            'revision', OLD.revision, 'phase', OLD.phase, 'state', OLD.state
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claims_insert
AFTER INSERT ON manuscript_claims
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_claims', 'insert',
        'manuscript_claim', NEW.id,
        NEW.manuscript_id, NEW.id,
        json_object(
            'local_key', NEW.local_key, 'kind', NEW.kind, 'state', NEW.state
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claims_update
AFTER UPDATE ON manuscript_claims
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_claims', 'update',
        'manuscript_claim', NEW.id,
        NEW.manuscript_id, NEW.id,
        json_object(
            'local_key', NEW.local_key, 'kind', NEW.kind, 'state', NEW.state
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claims_delete
AFTER DELETE ON manuscript_claims
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id, details
    ) VALUES (
        OLD.project_id, 'manuscript_claims', 'delete',
        'manuscript_claim', OLD.id,
        OLD.manuscript_id, OLD.id,
        json_object(
            'local_key', OLD.local_key, 'kind', OLD.kind, 'state', OLD.state
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_versions_insert
AFTER INSERT ON manuscript_claim_versions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_claim_versions', 'insert',
        'manuscript_claim', NEW.claim_id,
        NEW.manuscript_id, NEW.claim_id,
        json_object('claim_version', NEW.version)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_versions_update
AFTER UPDATE ON manuscript_claim_versions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_claim_versions', 'update',
        'manuscript_claim', NEW.claim_id,
        NEW.manuscript_id, NEW.claim_id,
        json_object('claim_version', NEW.version)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_versions_delete
AFTER DELETE ON manuscript_claim_versions
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id, details
    ) VALUES (
        OLD.project_id, 'manuscript_claim_versions', 'delete',
        'manuscript_claim', OLD.claim_id,
        OLD.manuscript_id, OLD.claim_id,
        json_object('claim_version', OLD.version)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_ratifications_insert
AFTER INSERT ON manuscript_claim_ratifications
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_claim_ratifications', 'insert',
        'manuscript_claim_ratification', NEW.id,
        NEW.manuscript_id, NEW.claim_id,
        'decision', NEW.decision_id,
        json_object('claim_version', NEW.claim_version)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_ratifications_update
AFTER UPDATE ON manuscript_claim_ratifications
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_claim_ratifications', 'update',
        'manuscript_claim_ratification', NEW.id,
        NEW.manuscript_id, NEW.claim_id,
        'decision', NEW.decision_id,
        json_object('claim_version', NEW.claim_version)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_ratifications_delete
AFTER DELETE ON manuscript_claim_ratifications
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        OLD.project_id, 'manuscript_claim_ratifications', 'delete',
        'manuscript_claim_ratification', OLD.id,
        OLD.manuscript_id, OLD.claim_id,
        'decision', OLD.decision_id,
        json_object('claim_version', OLD.claim_version)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_units_insert
AFTER INSERT ON manuscript_units
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_units', 'insert',
        'manuscript_unit', NEW.id,
        NEW.manuscript_id, NEW.id,
        json_object(
            'local_key', NEW.local_key,
            'kind', NEW.kind,
            'location', NEW.location,
            'artifact_ref', NEW.artifact_ref,
            'status', NEW.status
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_units_update
AFTER UPDATE ON manuscript_units
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_units', 'update',
        'manuscript_unit', NEW.id,
        NEW.manuscript_id, NEW.id,
        json_object(
            'local_key', NEW.local_key,
            'kind', NEW.kind,
            'location', NEW.location,
            'artifact_ref', NEW.artifact_ref,
            'status', NEW.status
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_units_delete
AFTER DELETE ON manuscript_units
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id, details
    ) VALUES (
        OLD.project_id, 'manuscript_units', 'delete',
        'manuscript_unit', OLD.id,
        OLD.manuscript_id, OLD.id,
        json_object(
            'local_key', OLD.local_key,
            'kind', OLD.kind,
            'location', OLD.location,
            'artifact_ref', OLD.artifact_ref,
            'status', OLD.status
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_evidence_insert
AFTER INSERT ON manuscript_claim_evidence
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_claim_evidence', 'insert',
        'manuscript_claim', NEW.manuscript_claim_id,
        NEW.manuscript_id, NEW.manuscript_claim_id,
        'claim', NEW.evidence_claim_id,
        json_object(
            'claim_version', NEW.claim_version,
            'role', NEW.role,
            'ordinal', NEW.ordinal
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_evidence_update
AFTER UPDATE ON manuscript_claim_evidence
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_claim_evidence', 'update',
        'manuscript_claim', NEW.manuscript_claim_id,
        NEW.manuscript_id, NEW.manuscript_claim_id,
        'claim', NEW.evidence_claim_id,
        json_object(
            'claim_version', NEW.claim_version,
            'role', NEW.role,
            'ordinal', NEW.ordinal,
            'previous_evidence_claim_id', OLD.evidence_claim_id
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_evidence_delete
AFTER DELETE ON manuscript_claim_evidence
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        OLD.project_id, 'manuscript_claim_evidence', 'delete',
        'manuscript_claim', OLD.manuscript_claim_id,
        OLD.manuscript_id, OLD.manuscript_claim_id,
        'claim', OLD.evidence_claim_id,
        json_object(
            'claim_version', OLD.claim_version,
            'role', OLD.role,
            'ordinal', OLD.ordinal
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_unit_evidence_insert
AFTER INSERT ON manuscript_unit_evidence
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_unit_evidence', 'insert',
        'manuscript_unit', NEW.unit_id,
        NEW.manuscript_id, NEW.unit_id,
        'claim', NEW.evidence_claim_id,
        json_object('role', NEW.role, 'ordinal', NEW.ordinal)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_unit_evidence_update
AFTER UPDATE ON manuscript_unit_evidence
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_unit_evidence', 'update',
        'manuscript_unit', NEW.unit_id,
        NEW.manuscript_id, NEW.unit_id,
        'claim', NEW.evidence_claim_id,
        json_object(
            'role', NEW.role,
            'ordinal', NEW.ordinal,
            'previous_evidence_claim_id', OLD.evidence_claim_id
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_unit_evidence_delete
AFTER DELETE ON manuscript_unit_evidence
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        OLD.project_id, 'manuscript_unit_evidence', 'delete',
        'manuscript_unit', OLD.unit_id,
        OLD.manuscript_id, OLD.unit_id,
        'claim', OLD.evidence_claim_id,
        json_object('role', OLD.role, 'ordinal', OLD.ordinal)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_units_insert
AFTER INSERT ON manuscript_claim_units
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id, manuscript_unit_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_claim_units', 'insert',
        'manuscript_claim', NEW.manuscript_claim_id,
        NEW.manuscript_id, NEW.manuscript_claim_id, NEW.unit_id,
        json_object(
            'claim_version', NEW.claim_version,
            'relationship', NEW.relationship
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_units_update
AFTER UPDATE ON manuscript_claim_units
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id, manuscript_unit_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_claim_units', 'update',
        'manuscript_claim', NEW.manuscript_claim_id,
        NEW.manuscript_id, NEW.manuscript_claim_id, NEW.unit_id,
        json_object(
            'claim_version', NEW.claim_version,
            'relationship', NEW.relationship,
            'previous_unit_id', OLD.unit_id
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_units_delete
AFTER DELETE ON manuscript_claim_units
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id, manuscript_unit_id, details
    ) VALUES (
        OLD.project_id, 'manuscript_claim_units', 'delete',
        'manuscript_claim', OLD.manuscript_claim_id,
        OLD.manuscript_id, OLD.manuscript_claim_id, OLD.unit_id,
        json_object(
            'claim_version', OLD.claim_version,
            'relationship', OLD.relationship
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_checkpoints_insert
AFTER INSERT ON manuscript_checkpoints
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_checkpoints', 'insert',
        'manuscript_checkpoint', NEW.id,
        NEW.manuscript_id, NEW.unit_id,
        CASE
            WHEN NEW.decision_id IS NULL THEN NULL
            ELSE 'decision'
        END,
        NEW.decision_id,
        json_object('kind', NEW.kind, 'status', NEW.status)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_checkpoints_update
AFTER UPDATE ON manuscript_checkpoints
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_checkpoints', 'update',
        'manuscript_checkpoint', NEW.id,
        NEW.manuscript_id, NEW.unit_id,
        CASE
            WHEN NEW.decision_id IS NULL THEN NULL
            ELSE 'decision'
        END,
        NEW.decision_id,
        json_object('kind', NEW.kind, 'status', NEW.status)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_checkpoints_delete
AFTER DELETE ON manuscript_checkpoints
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        OLD.project_id, 'manuscript_checkpoints', 'delete',
        'manuscript_checkpoint', OLD.id,
        OLD.manuscript_id, OLD.unit_id,
        CASE
            WHEN OLD.decision_id IS NULL THEN NULL
            ELSE 'decision'
        END,
        OLD.decision_id,
        json_object('kind', OLD.kind, 'status', OLD.status)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_verifications_insert
AFTER INSERT ON manuscript_claim_verification_attestations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_claim_verification_attestations', 'insert',
        'manuscript_claim_verification', NEW.id,
        NEW.manuscript_id, NEW.claim_id,
        json_object(
            'claim_version', NEW.claim_version,
            'overall_verdict', NEW.overall_verdict,
            'changelog_cursor', NEW.changelog_cursor
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_verifications_update
AFTER UPDATE ON manuscript_claim_verification_attestations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_claim_verification_attestations', 'update',
        'manuscript_claim_verification', NEW.id,
        NEW.manuscript_id, NEW.claim_id,
        json_object(
            'claim_version', NEW.claim_version,
            'overall_verdict', NEW.overall_verdict,
            'changelog_cursor', NEW.changelog_cursor
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_manuscript_claim_verifications_delete
AFTER DELETE ON manuscript_claim_verification_attestations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_claim_id, details
    ) VALUES (
        OLD.project_id, 'manuscript_claim_verification_attestations', 'delete',
        'manuscript_claim_verification', OLD.id,
        OLD.manuscript_id, OLD.claim_id,
        json_object(
            'claim_version', OLD.claim_version,
            'overall_verdict', OLD.overall_verdict,
            'changelog_cursor', OLD.changelog_cursor
        )
    );
END;

-- Existing reference validation is also an immutable verification surface.
-- Its manuscript id is a legacy ``jrn_`` alias; native resolution remains a
-- read-time concern so this migration does not infer or backfill identity.
CREATE TRIGGER IF NOT EXISTS trg_change_reference_validations_insert
AFTER INSERT ON reference_validation_attestations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'reference_validation_attestations', 'insert',
        'reference_validation_attestation', NEW.id,
        'journal', NEW.manuscript_id,
        json_object(
            'literature_id', NEW.literature_id,
            'status', NEW.status
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_reference_validations_update
AFTER UPDATE ON reference_validation_attestations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        NEW.project_id, 'reference_validation_attestations', 'update',
        'reference_validation_attestation', NEW.id,
        'journal', NEW.manuscript_id,
        json_object(
            'literature_id', NEW.literature_id,
            'status', NEW.status
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_change_reference_validations_delete
AFTER DELETE ON reference_validation_attestations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        related_entity_type, related_entity_id, details
    ) VALUES (
        OLD.project_id, 'reference_validation_attestations', 'delete',
        'reference_validation_attestation', OLD.id,
        'journal', OLD.manuscript_id,
        json_object(
            'literature_id', OLD.literature_id,
            'status', OLD.status
        )
    );
END;
