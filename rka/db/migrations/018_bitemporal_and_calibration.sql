-- ============================================================
-- Migration 018 — bi-temporal valid_until + calibration_outcomes
-- ============================================================
-- Mission 1B: mis_01KPEFG22FDHCX0ZRDXA827CKR
-- Decision: dec_01KPE4ZVYJAG7MSN9MGMXTHR2Q (augment 014, don't replace)
--
-- Augments migration 014's staleness scheme: adds valid_until to claims and
-- synthesis_valid_until to evidence_clusters. Introduces calibration_outcomes
-- for periodic Brier/ECE calculation on decisions with recorded outcomes.
-- Strictly additive: valid_from, staleness, stale_reason from 014 stay intact.
-- ============================================================

ALTER TABLE claims ADD COLUMN valid_until TEXT;
ALTER TABLE evidence_clusters ADD COLUMN synthesis_valid_until TEXT;

CREATE TABLE IF NOT EXISTS calibration_outcomes (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('succeeded','failed','mixed','unresolved')),
    outcome_details TEXT,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    recorded_by TEXT NOT NULL DEFAULT 'pi'
);

CREATE INDEX IF NOT EXISTS idx_calibration_decision ON calibration_outcomes(decision_id);
CREATE INDEX IF NOT EXISTS idx_calibration_project ON calibration_outcomes(project_id);
