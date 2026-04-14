-- Fix stale claim_count on evidence_clusters by recomputing from actual claim_edges.
UPDATE evidence_clusters SET claim_count = (
    SELECT COUNT(*) FROM claim_edges
    WHERE claim_edges.cluster_id = evidence_clusters.id
      AND claim_edges.relation = 'member_of'
);
