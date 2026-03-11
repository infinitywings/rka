-- sqlite-vec table for image/artifact embeddings (requires sqlite-vec extension)
-- Dimension 768 to match nomic-embed-text-v1.5
CREATE VIRTUAL TABLE IF NOT EXISTS vec_artifacts USING vec0(
  id TEXT PRIMARY KEY,
  embedding float[768]
);
