-- ============================================================
-- RKA Schema v2.0 — Phase 1 (Core tables only)
-- FTS5 and sqlite-vec tables added in Phase 2
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- ============================================================
-- 1. Project State (singleton per database)
-- ============================================================

CREATE TABLE IF NOT EXISTS project_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    project_name TEXT NOT NULL,
    project_description TEXT,
    current_phase TEXT,
    phases_config TEXT,               -- JSON: ordered list of phase names
    summary TEXT,                     -- LLM-maintained rolling summary
    blockers TEXT,                    -- Current blockers (free text)
    metrics TEXT,                     -- JSON: {name: {value, trend, updated_at}}
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ============================================================
-- 2. Decisions (tree structure with branching/merging)
-- ============================================================

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES decisions(id) ON DELETE SET NULL,
    phase TEXT NOT NULL,
    question TEXT NOT NULL,
    options TEXT,                     -- JSON: [{label, description, explored: bool}]
    chosen TEXT,                      -- Label of chosen option
    rationale TEXT,
    decided_by TEXT NOT NULL CHECK (decided_by IN ('pi', 'brain', 'executor')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'abandoned', 'superseded', 'merged', 'revisit')),
    abandonment_reason TEXT,
    related_missions TEXT,            -- JSON: ["mis_01H...", ...]
    related_literature TEXT,          -- JSON: ["lit_01H...", ...]
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_decisions_parent ON decisions(parent_id);
CREATE INDEX IF NOT EXISTS idx_decisions_phase ON decisions(phase);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);

-- ============================================================
-- 3. Literature
-- ============================================================

CREATE TABLE IF NOT EXISTS literature (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT,                     -- JSON: ["Author A", "Author B"]
    year INTEGER,
    venue TEXT,
    doi TEXT UNIQUE,
    url TEXT,
    bibtex TEXT,
    pdf_path TEXT,
    abstract TEXT,
    status TEXT NOT NULL DEFAULT 'to_read'
        CHECK (status IN ('to_read', 'reading', 'read', 'cited', 'excluded')),
    key_findings TEXT,                -- JSON: ["Finding 1", ...]
    methodology_notes TEXT,
    relevance TEXT,
    relevance_score REAL,
    related_decisions TEXT,           -- JSON: ["dec_01H...", ...]
    added_by TEXT CHECK (added_by IN ('brain', 'executor', 'pi', 'import', 'web_ui')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_literature_status ON literature(status);
CREATE INDEX IF NOT EXISTS idx_literature_year ON literature(year);

-- ============================================================
-- 4. Research Journal
-- ============================================================

CREATE TABLE IF NOT EXISTS journal (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN (
        'finding', 'insight', 'pi_instruction', 'exploration',
        'idea', 'observation', 'hypothesis', 'methodology', 'summary'
    )),
    content TEXT NOT NULL,
    summary TEXT,
    source TEXT NOT NULL CHECK (source IN ('brain', 'executor', 'pi', 'web_ui', 'llm')),
    phase TEXT,
    related_decisions TEXT,           -- JSON: ["dec_01H...", ...]
    related_literature TEXT,          -- JSON: ["lit_01H...", ...]
    related_mission TEXT,
    supersedes TEXT REFERENCES journal(id) ON DELETE SET NULL,
    superseded_by TEXT,
    confidence TEXT NOT NULL DEFAULT 'hypothesis'
        CHECK (confidence IN ('hypothesis', 'tested', 'verified', 'superseded', 'retracted')),
    importance TEXT NOT NULL DEFAULT 'normal'
        CHECK (importance IN ('critical', 'high', 'normal', 'low', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_journal_type ON journal(type);
CREATE INDEX IF NOT EXISTS idx_journal_phase ON journal(phase);
CREATE INDEX IF NOT EXISTS idx_journal_confidence ON journal(confidence);
CREATE INDEX IF NOT EXISTS idx_journal_importance ON journal(importance);
CREATE INDEX IF NOT EXISTS idx_journal_created ON journal(created_at);

-- ============================================================
-- 5. Missions
-- ============================================================

CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    objective TEXT NOT NULL,
    tasks TEXT,                       -- JSON: [{description, status, commit_hash, completed_at}]
    context TEXT,
    acceptance_criteria TEXT,
    scope_boundaries TEXT,
    checkpoint_triggers TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'active', 'complete', 'partial', 'blocked', 'cancelled')),
    depends_on TEXT REFERENCES missions(id) ON DELETE SET NULL,
    report TEXT,                      -- JSON: Executor's structured report
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status);
CREATE INDEX IF NOT EXISTS idx_missions_phase ON missions(phase);

-- ============================================================
-- 6. Checkpoints
-- ============================================================

CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    mission_id TEXT REFERENCES missions(id) ON DELETE CASCADE,
    task_reference TEXT,
    type TEXT NOT NULL CHECK (type IN ('decision', 'clarification', 'inspection')),
    description TEXT NOT NULL,
    context TEXT,
    options TEXT,                     -- JSON: [{label, description, consequence}]
    recommendation TEXT,
    blocking INTEGER NOT NULL DEFAULT 1,
    resolution TEXT,
    resolved_by TEXT CHECK (resolved_by IN ('pi', 'brain')),
    resolution_rationale TEXT,
    linked_decision_id TEXT REFERENCES decisions(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'resolved', 'dismissed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_status ON checkpoints(status);
CREATE INDEX IF NOT EXISTS idx_checkpoints_mission ON checkpoints(mission_id);

-- ============================================================
-- 7. Tags (junction table)
-- ============================================================

CREATE TABLE IF NOT EXISTS tags (
    tag TEXT NOT NULL COLLATE NOCASE,
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'decision', 'literature', 'journal', 'mission'
    )),
    entity_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (tag, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_tags_entity ON tags(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);

-- ============================================================
-- 8. Event Stream (cross-entity causal chain)
-- ============================================================

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'decision_created', 'decision_updated', 'decision_abandoned',
        'mission_created', 'mission_completed', 'mission_blocked',
        'finding_recorded', 'insight_recorded', 'pi_instruction',
        'checkpoint_created', 'checkpoint_resolved',
        'literature_added', 'literature_cited',
        'phase_changed', 'status_updated'
    )),
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    actor TEXT NOT NULL CHECK (actor IN ('brain', 'executor', 'pi', 'llm', 'web_ui', 'system')),
    summary TEXT NOT NULL,
    caused_by_event TEXT REFERENCES events(id),
    caused_by_entity TEXT,
    phase TEXT,
    details TEXT                      -- JSON
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_events_caused_by ON events(caused_by_event);
CREATE INDEX IF NOT EXISTS idx_events_phase ON events(phase);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

-- ============================================================
-- 9. Audit Log
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL CHECK (action IN ('create', 'update', 'delete', 'query', 'enrich')),
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    actor TEXT CHECK (actor IN ('brain', 'executor', 'pi', 'llm', 'web_ui', 'system')),
    details TEXT,                     -- JSON
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);

-- ============================================================
-- 10. Bootstrap Log (workspace import dedup)
-- ============================================================

CREATE TABLE IF NOT EXISTS bootstrap_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    file_path TEXT NOT NULL,
    category TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_bootstrap_hash ON bootstrap_log(file_hash);
CREATE INDEX IF NOT EXISTS idx_bootstrap_scan ON bootstrap_log(scan_id);
