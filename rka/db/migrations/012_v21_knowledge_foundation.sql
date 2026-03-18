-- ============================================================
-- Migration 012: v2.1 Knowledge Organization Foundation
-- ============================================================
-- Phase 0 of RKA v2.1:
--   - journal.provenance (optional JSON for structured origin tracking)
--   - journal.role_id (nullable text — no FK until Phase 1 agent_roles table)
--   - missions.role_id
--   - checkpoints.role_id
--   - decisions.role_id
--   - jobs.model_tier (nullable text for tiered model routing groundwork)

-- Journal: add provenance and role_id
ALTER TABLE journal ADD COLUMN provenance TEXT;
ALTER TABLE journal ADD COLUMN role_id TEXT;

-- Missions: add role_id
ALTER TABLE missions ADD COLUMN role_id TEXT;

-- Checkpoints: add role_id
ALTER TABLE checkpoints ADD COLUMN role_id TEXT;

-- Decisions: add role_id
ALTER TABLE decisions ADD COLUMN role_id TEXT;

-- Jobs: add model_tier for future tiered model routing
ALTER TABLE jobs ADD COLUMN model_tier TEXT;
