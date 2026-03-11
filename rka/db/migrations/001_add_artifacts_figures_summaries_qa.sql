-- Artifacts: uploaded files / extracted images
CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  filepath TEXT NOT NULL,
  filetype TEXT,
  file_size INTEGER,
  mime TEXT,
  content_hash TEXT,
  extraction_status TEXT DEFAULT 'pending' CHECK (extraction_status IN ('pending','processing','complete','failed')),
  created_by TEXT,
  metadata TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_artifacts_hash ON artifacts(content_hash);
CREATE INDEX IF NOT EXISTS idx_artifacts_status ON artifacts(extraction_status);

-- Figures: extracted from artifacts (PDF pages, images)
CREATE TABLE IF NOT EXISTS figures (
  id TEXT PRIMARY KEY,
  artifact_id TEXT REFERENCES artifacts(id) ON DELETE CASCADE,
  page INTEGER,
  bbox TEXT,
  caption TEXT,
  caption_confidence REAL,
  summary TEXT,
  claims TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_figures_artifact ON figures(artifact_id);

-- Exploration summaries: multi-granularity LLM-generated summaries
CREATE TABLE IF NOT EXISTS exploration_summaries (
  id TEXT PRIMARY KEY,
  scope_type TEXT NOT NULL,
  scope_id TEXT,
  granularity TEXT NOT NULL CHECK (granularity IN ('one_line','paragraph','narrative')),
  content TEXT NOT NULL,
  produced_by TEXT,
  confidence REAL,
  blessed INTEGER DEFAULT 0,
  source_refs TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_summaries_scope ON exploration_summaries(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_summaries_blessed ON exploration_summaries(blessed);

-- QA sessions
CREATE TABLE IF NOT EXISTS qa_sessions (
  id TEXT PRIMARY KEY,
  project_id TEXT,
  created_by TEXT,
  title TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  metadata TEXT
);

-- QA conversation logs
CREATE TABLE IF NOT EXISTS qa_logs (
  id TEXT PRIMARY KEY,
  session_id TEXT REFERENCES qa_sessions(id) ON DELETE CASCADE,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  answer_structured TEXT,
  sources TEXT,
  confidence REAL,
  verified INTEGER DEFAULT 0,
  corrected_by TEXT,
  correction TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_qa_logs_session ON qa_logs(session_id);
