-- Per-claim fencing token for durable workers.
--
-- worker_id alone is not a lease: the same worker identity can reclaim an
-- expired job, and a slow attempt can otherwise complete after a newer
-- attempt has taken ownership.  A fresh token on every claim lets completion
-- and retry updates prove they still own the exact lease they started with.

ALTER TABLE jobs ADD COLUMN lease_token TEXT;

-- The queue resolves dedupe conflicts within one project and job type.  Keep
-- the database uniqueness rule identical so an otherwise-valid job in a
-- different scope cannot be mistaken for an ID collision.
DROP INDEX IF EXISTS idx_jobs_dedupe_active;
CREATE UNIQUE INDEX idx_jobs_dedupe_active
    ON jobs(project_id, job_type, dedupe_key)
    WHERE dedupe_key IS NOT NULL AND status IN ('pending', 'running');

CREATE INDEX IF NOT EXISTS idx_jobs_active_lease
    ON jobs(id, worker_id, lease_token)
    WHERE status = 'running';

CREATE TRIGGER IF NOT EXISTS trg_jobs_lease_token_insert
BEFORE INSERT ON jobs
WHEN NEW.lease_token IS NOT NULL AND NEW.status <> 'running'
BEGIN
    SELECT RAISE(ABORT, 'job lease token requires running status');
END;

CREATE TRIGGER IF NOT EXISTS trg_jobs_lease_token_update
BEFORE UPDATE ON jobs
WHEN NEW.lease_token IS NOT NULL AND NEW.status <> 'running'
BEGIN
    SELECT RAISE(ABORT, 'job lease token requires running status');
END;
