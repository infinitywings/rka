-- ============================================================
-- Migration 017 — decision_options table + decisions columns
-- ============================================================
-- Mission 1A: mis_01KPEFE7GBAJ9TJMMAN3SB06BP
-- Decision: dec_01KPE2RKT838TJXDYT7W23K26B (multi-choice decision spec)
--
-- Creates the schema substrate for the Multi-Choice Decision UX.
-- Adds a new decision_options table with 22 columns covering the full
-- structured option schema (label / summary / justification / explanation /
-- 3-pros / 3-cons / evidence / confidence / effort / dominated_by) plus
-- four new columns on decisions for the recommendation + selection loop.
-- Strictly additive: legacy decisions.options JSON stays untouched per
-- dec_01KPE50A87TV9JPXB7Z9XMCQ4H.
-- ============================================================

CREATE TABLE IF NOT EXISTS decision_options (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    label TEXT NOT NULL,
    summary TEXT NOT NULL,
    justification TEXT NOT NULL,
    expert_archetype TEXT,
    explanation TEXT NOT NULL,
    pros TEXT NOT NULL,                           -- JSON array of exactly 3 strings
    cons TEXT NOT NULL,                           -- JSON array of exactly 3 strings (last = steelman)
    evidence TEXT NOT NULL,                       -- JSON array of {claim_id, strength_tier}
    confidence_verbal TEXT NOT NULL,              -- low | moderate | high
    confidence_numeric REAL NOT NULL CHECK (confidence_numeric BETWEEN 0 AND 1),
    confidence_evidence_strength TEXT NOT NULL,   -- weak | moderate | strong
    confidence_known_unknowns TEXT NOT NULL,      -- JSON array of 1-2 strings
    effort_time TEXT NOT NULL,                    -- S | M | L | XL
    effort_cost TEXT,
    effort_reversibility TEXT NOT NULL,           -- reversible | costly | irreversible
    dominated_by TEXT REFERENCES decision_options(id),
    presentation_order_seed INTEGER NOT NULL,
    is_recommended INTEGER NOT NULL DEFAULT 0,    -- 0 or 1 (SQLite bool convention)
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (json_array_length(pros) = 3),
    CHECK (json_array_length(cons) = 3),
    CHECK (json_array_length(confidence_known_unknowns) BETWEEN 1 AND 2)
);

CREATE INDEX IF NOT EXISTS idx_decision_options_decision ON decision_options(decision_id);
CREATE INDEX IF NOT EXISTS idx_decision_options_project ON decision_options(project_id);

-- New columns on decisions — additive, default NULL for all existing rows.
ALTER TABLE decisions ADD COLUMN recommended_option_id TEXT REFERENCES decision_options(id);
ALTER TABLE decisions ADD COLUMN pi_selected_option_id TEXT REFERENCES decision_options(id);
ALTER TABLE decisions ADD COLUMN pi_override_rationale TEXT;
ALTER TABLE decisions ADD COLUMN presentation_method TEXT;
