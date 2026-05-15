-- requires-table: claims
-- Mission D T4: claims.embedding_pending flag + supporting partial index.
--
-- This SQL migration handles the schema-level change only (add column +
-- index + flag every existing claim as needing re-embed). The actual
-- vec_claims drop/recreate at a config-driven dim is a parameterized
-- runtime operation in `rka/services/embedding_reshape.py` — pure SQL
-- can't read /data/embedding_config.json to discover the target dim.
--
-- After this migration runs:
--   - every existing claim has embedding_pending = 1
--   - the partial index makes "claims where embedding_pending = 1" cheap
--   - rka/services/embedding_reshape.reshape_vec_claims is responsible
--     for dropping + recreating the vec_claims virtual table with the
--     correct dim and clearing the flag as each claim is re-embedded
--
-- Pre-flight safety:
--   - /data/embedding_config.backup.json is written by T2's save_config
--     on every PUT /api/config/embedding before the reshape runs
--   - if reshape fails mid-run, claims with embedding_pending=1 are
--     still queryable; semantic search returns empty for them while
--     FTS still works

ALTER TABLE claims ADD COLUMN embedding_pending INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_claims_embedding_pending
    ON claims(embedding_pending)
    WHERE embedding_pending = 1;

-- Flag every existing claim as needing re-embed under the configured backend.
-- The reshape service does this again as part of its operation, but doing it
-- here too means even a fresh container without sqlite-vec sees the right state.
UPDATE claims SET embedding_pending = 1;
