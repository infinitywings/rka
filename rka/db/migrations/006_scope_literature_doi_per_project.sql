-- Make literature DOI uniqueness project-scoped so projects can import/clone packs independently.

PRAGMA foreign_keys = OFF;

ALTER TABLE literature RENAME TO literature_old;

CREATE TABLE literature (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT,
    year INTEGER,
    venue TEXT,
    doi TEXT,
    url TEXT,
    bibtex TEXT,
    pdf_path TEXT,
    abstract TEXT,
    status TEXT NOT NULL DEFAULT 'to_read'
        CHECK (status IN ('to_read', 'reading', 'read', 'cited', 'excluded')),
    key_findings TEXT,
    methodology_notes TEXT,
    relevance TEXT,
    relevance_score REAL,
    related_decisions TEXT,
    added_by TEXT CHECK (added_by IN ('brain', 'executor', 'pi', 'import', 'web_ui')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE
);

INSERT INTO literature (
    id,
    title,
    authors,
    year,
    venue,
    doi,
    url,
    bibtex,
    pdf_path,
    abstract,
    status,
    key_findings,
    methodology_notes,
    relevance,
    relevance_score,
    related_decisions,
    added_by,
    notes,
    created_at,
    updated_at,
    project_id
)
SELECT
    id,
    title,
    authors,
    year,
    venue,
    doi,
    url,
    bibtex,
    pdf_path,
    abstract,
    status,
    key_findings,
    methodology_notes,
    relevance,
    relevance_score,
    related_decisions,
    added_by,
    notes,
    created_at,
    updated_at,
    project_id
FROM literature_old;

DROP TABLE literature_old;

CREATE INDEX IF NOT EXISTS idx_literature_status ON literature(status);
CREATE INDEX IF NOT EXISTS idx_literature_year ON literature(year);
CREATE INDEX IF NOT EXISTS idx_literature_project ON literature(project_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_literature_project_doi
    ON literature(project_id, doi)
    WHERE doi IS NOT NULL;

PRAGMA foreign_keys = ON;
