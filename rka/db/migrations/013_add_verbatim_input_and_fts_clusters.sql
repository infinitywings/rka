-- 013: Add verbatim_input to journal (P0) and fts_clusters (P2a)

-- P0: PI attribution — store the PI's exact words alongside Brain's analysis
ALTER TABLE journal ADD COLUMN verbatim_input TEXT;

-- P2a: FTS5 for evidence clusters (label + synthesis)
CREATE VIRTUAL TABLE IF NOT EXISTS fts_clusters USING fts5(
    id UNINDEXED,
    label,
    synthesis,
    tokenize='porter unicode61'
);

-- Populate fts_clusters from existing data
INSERT OR IGNORE INTO fts_clusters (id, label, synthesis)
SELECT id, COALESCE(label, ''), COALESCE(synthesis, '')
FROM evidence_clusters;

-- Populate fts_claims from existing data (may be empty)
INSERT OR IGNORE INTO fts_claims (id, content)
SELECT id, COALESCE(content, '')
FROM claims;
