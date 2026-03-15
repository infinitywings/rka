-- requires-table: claims
-- sqlite-vec vector table for claims (768-dim nomic-embed-text-v1.5)

CREATE VIRTUAL TABLE IF NOT EXISTS vec_claims USING vec0(
    id TEXT PRIMARY KEY, embedding float[768]
);
