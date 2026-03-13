CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    entity_type TEXT,
    entity_id TEXT,
    payload TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    priority INTEGER NOT NULL DEFAULT 100,
    run_after TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    lease_until TEXT,
    worker_id TEXT,
    dedupe_key TEXT,
    last_error TEXT,
    result TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_claim
    ON jobs(status, priority, run_after, created_at);

CREATE INDEX IF NOT EXISTS idx_jobs_entity
    ON jobs(project_id, entity_type, entity_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedupe_active
    ON jobs(dedupe_key)
    WHERE dedupe_key IS NOT NULL AND status IN ('pending', 'running');
