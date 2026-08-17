-- Migration 030: durable, auditable resolution state for stale claims and
-- evidence clusters. A resolved item returns to staleness='green' while these
-- fields preserve its reviewed disposition; audit_log stores the event history.
--
-- This migration was first deployed by the agentic runtime and its filename is
-- already present in those databases. Main deliberately left 030 reserved.
-- Shipping the original additive schema here makes knowledge packs portable
-- without dropping semantic fields: agentic databases skip the recorded
-- migration, while main-line databases apply it exactly once.

ALTER TABLE claims ADD COLUMN staleness_reviewed_at TEXT;
ALTER TABLE claims ADD COLUMN staleness_verdict TEXT
    CHECK (staleness_verdict IS NULL OR staleness_verdict IN (
        'current', 'historical', 'retired', 'superseded', 'retracted', 'dismissed'
    ));
ALTER TABLE claims ADD COLUMN staleness_resolution TEXT;
ALTER TABLE claims ADD COLUMN staleness_resolution_journal_id TEXT;
ALTER TABLE claims ADD COLUMN staleness_resolved_by TEXT
    CHECK (staleness_resolved_by IS NULL OR staleness_resolved_by IN (
        'brain', 'executor', 'pi'
    ));

ALTER TABLE evidence_clusters ADD COLUMN staleness_reviewed_at TEXT;
ALTER TABLE evidence_clusters ADD COLUMN staleness_verdict TEXT
    CHECK (staleness_verdict IS NULL OR staleness_verdict IN (
        'current', 'historical', 'retired', 'superseded', 'retracted', 'dismissed'
    ));
ALTER TABLE evidence_clusters ADD COLUMN staleness_resolution TEXT;
ALTER TABLE evidence_clusters ADD COLUMN staleness_resolution_journal_id TEXT;
ALTER TABLE evidence_clusters ADD COLUMN staleness_resolved_by TEXT
    CHECK (staleness_resolved_by IS NULL OR staleness_resolved_by IN (
        'brain', 'executor', 'pi'
    ));

CREATE INDEX IF NOT EXISTS idx_claims_staleness_review
    ON claims(project_id, staleness, staleness_reviewed_at);
CREATE INDEX IF NOT EXISTS idx_clusters_staleness_review
    ON evidence_clusters(project_id, staleness, staleness_reviewed_at);
