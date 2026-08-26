-- Runtime schema upgrades can preserve data while rebuilding sqlite virtual
-- tables, which plain migration SQL cannot express safely. Keep their success
-- markers separate from the SQL-file ledger so operators can verify both.

CREATE TABLE IF NOT EXISTS runtime_schema_upgrades (
    name TEXT PRIMARY KEY,
    completed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    details TEXT
);
