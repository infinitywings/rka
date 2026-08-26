-- Migration 052: make cluster membership a set, not a multiset.
--
-- Historical write paths could create the same member_of edge repeatedly.
-- Keep the first recorded edge for each project/claim/cluster tuple, prevent
-- recurrence, and repair the cached cluster counts from the unique graph.

DELETE FROM claim_edges
WHERE relation = 'member_of'
  AND rowid NOT IN (
      SELECT MIN(rowid)
      FROM claim_edges
      WHERE relation = 'member_of'
      GROUP BY project_id, source_claim_id, cluster_id, relation
  );

CREATE UNIQUE INDEX IF NOT EXISTS uq_claim_edges_member_of
ON claim_edges(project_id, source_claim_id, cluster_id, relation)
WHERE relation = 'member_of';

UPDATE evidence_clusters
SET claim_count = (
        SELECT COUNT(DISTINCT claim_edges.source_claim_id)
        FROM claim_edges
        WHERE claim_edges.cluster_id = evidence_clusters.id
          AND claim_edges.relation = 'member_of'
          AND claim_edges.project_id = evidence_clusters.project_id
    ),
    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE claim_count != (
    SELECT COUNT(DISTINCT claim_edges.source_claim_id)
    FROM claim_edges
    WHERE claim_edges.cluster_id = evidence_clusters.id
      AND claim_edges.relation = 'member_of'
      AND claim_edges.project_id = evidence_clusters.project_id
);
