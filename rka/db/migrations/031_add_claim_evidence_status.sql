-- Migration 031: separate scientific evidence assessment from source grounding.
--
-- ``claims.verified`` is retained for backward compatibility and now has one
-- narrow meaning: the extracted proposition is faithfully grounded in its
-- source entry (including number and direction checks).  It does not establish
-- that the proposition is scientifically supported.
--
-- ``evidence_status`` records that independent assessment.  Existing claims
-- migrate conservatively to ``unassessed``; no scientific-support conclusion
-- is inferred from the legacy ``verified`` bit.

ALTER TABLE claims ADD COLUMN evidence_status TEXT NOT NULL DEFAULT 'unassessed'
    CHECK (evidence_status IN (
        'unassessed', 'supported', 'partially_supported',
        'inconclusive', 'contradicted'
    ));

CREATE INDEX IF NOT EXISTS idx_claims_evidence_status
    ON claims(project_id, evidence_status);
