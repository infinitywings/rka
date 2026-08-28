-- requires-table: claims
-- sqlite-vec vector table for claims (768-dim nomic-embed-text-v1.5)
-- project_id is ordinary KNN metadata by design; sparse project ids must not
-- become sqlite-vec partition keys because each partition allocates a chunk.

CREATE VIRTUAL TABLE IF NOT EXISTS vec_claims USING vec0(
    id TEXT PRIMARY KEY,
    project_id TEXT,
    embedding float[768]
);
