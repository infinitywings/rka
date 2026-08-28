-- sqlite-vec table for image/artifact embeddings (requires sqlite-vec extension)
-- Dimension 768 to match nomic-embed-text-v1.5
-- project_id/entity_type are ordinary KNN metadata filters by design. Do not
-- make sparse project ids partition keys: that allocates oversized vec chunks.
CREATE VIRTUAL TABLE IF NOT EXISTS vec_artifacts USING vec0(
  id TEXT PRIMARY KEY,
  project_id TEXT,
  entity_type TEXT,
  embedding float[768]
);
