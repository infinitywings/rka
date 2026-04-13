-- Phase 2: Knowledge Freshness Layer
-- Add staleness tracking to claims and clusters, assumptions to decisions.

-- Staleness on claims
ALTER TABLE claims ADD COLUMN staleness TEXT DEFAULT 'green';
ALTER TABLE claims ADD COLUMN stale_reason TEXT;
ALTER TABLE claims ADD COLUMN valid_from TEXT;

-- Staleness on clusters
ALTER TABLE evidence_clusters ADD COLUMN staleness TEXT DEFAULT 'green';
ALTER TABLE evidence_clusters ADD COLUMN stale_reason TEXT;

-- Assumptions on decisions
ALTER TABLE decisions ADD COLUMN assumptions TEXT;

-- Populate valid_from from existing created_at
UPDATE claims SET valid_from = created_at WHERE valid_from IS NULL;
