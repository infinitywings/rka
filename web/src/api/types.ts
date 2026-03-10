// TypeScript interfaces matching RKA Pydantic models

// ---- Journal ----

export type JournalType =
  | "finding" | "insight" | "pi_instruction" | "exploration"
  | "idea" | "observation" | "hypothesis" | "methodology" | "summary"

export type Source = "brain" | "executor" | "pi" | "web_ui" | "llm"
export type Confidence = "hypothesis" | "tested" | "verified" | "superseded" | "retracted"
export type Importance = "critical" | "high" | "normal" | "low" | "archived"

export interface JournalEntry {
  id: string
  type: string
  content: string
  summary: string | null
  source: string
  phase: string | null
  related_decisions: string[] | null
  related_literature: string[] | null
  related_mission: string | null
  supersedes: string | null
  superseded_by: string | null
  confidence: string
  importance: string
  tags: string[]
  created_at: string | null
  updated_at: string | null
}

export interface JournalEntryCreate {
  content: string
  type?: JournalType
  source?: Source
  phase?: string
  related_decisions?: string[]
  related_literature?: string[]
  related_mission?: string
  supersedes?: string
  confidence?: Confidence
  importance?: Importance
  tags?: string[]
}

export interface JournalEntryUpdate {
  content?: string
  type?: JournalType
  summary?: string
  confidence?: Confidence
  importance?: Importance
  related_decisions?: string[]
  related_literature?: string[]
  related_mission?: string
  tags?: string[]
}

// ---- Decisions ----

export interface DecisionOption {
  label: string
  description?: string
  explored?: boolean
}

export type DecisionStatus = "active" | "abandoned" | "superseded" | "merged" | "revisit"
export type DecidedBy = "pi" | "brain" | "executor"

export interface Decision {
  id: string
  parent_id: string | null
  phase: string
  question: string
  options: DecisionOption[] | null
  chosen: string | null
  rationale: string | null
  decided_by: string
  status: string
  abandonment_reason: string | null
  related_missions: string[] | null
  related_literature: string[] | null
  tags: string[]
  created_at: string | null
  updated_at: string | null
}

export interface DecisionCreate {
  question: string
  decided_by: DecidedBy
  phase: string
  options?: DecisionOption[]
  chosen?: string
  rationale?: string
  parent_id?: string
  related_missions?: string[]
  related_literature?: string[]
  status?: DecisionStatus
  tags?: string[]
}

export interface DecisionUpdate {
  question?: string
  options?: DecisionOption[]
  chosen?: string
  rationale?: string
  status?: DecisionStatus
  abandonment_reason?: string
  related_missions?: string[]
  related_literature?: string[]
  tags?: string[]
}

export interface DecisionTreeNode {
  id: string
  question: string
  status: string
  chosen: string | null
  phase: string
  children: DecisionTreeNode[]
}

// ---- Literature ----

export type LiteratureStatus = "to_read" | "reading" | "read" | "cited" | "excluded"

export interface Literature {
  id: string
  title: string
  authors: string[] | null
  year: number | null
  venue: string | null
  doi: string | null
  url: string | null
  bibtex: string | null
  pdf_path: string | null
  abstract: string | null
  status: string
  key_findings: string[] | null
  methodology_notes: string | null
  relevance: string | null
  relevance_score: number | null
  related_decisions: string[] | null
  added_by: string | null
  notes: string | null
  tags: string[]
  created_at: string | null
  updated_at: string | null
}

export interface LiteratureCreate {
  title: string
  authors?: string[]
  year?: number
  venue?: string
  doi?: string
  url?: string
  bibtex?: string
  abstract?: string
  status?: LiteratureStatus
  key_findings?: string[]
  methodology_notes?: string
  relevance?: string
  relevance_score?: number
  related_decisions?: string[]
  added_by?: "brain" | "executor" | "pi" | "import" | "web_ui"
  notes?: string
  tags?: string[]
}

export interface LiteratureUpdate {
  title?: string
  authors?: string[]
  year?: number
  venue?: string
  doi?: string
  url?: string
  abstract?: string
  status?: LiteratureStatus
  key_findings?: string[]
  methodology_notes?: string
  relevance?: string
  relevance_score?: number
  related_decisions?: string[]
  notes?: string
  tags?: string[]
}

// ---- Missions ----

export type TaskStatus = "pending" | "in_progress" | "complete" | "blocked" | "skipped"
export type MissionStatus = "pending" | "active" | "complete" | "partial" | "blocked" | "cancelled"

export interface MissionTask {
  description: string
  status?: TaskStatus
  commit_hash?: string | null
  completed_at?: string | null
}

export interface Mission {
  id: string
  phase: string
  objective: string
  tasks: MissionTask[] | null
  context: string | null
  acceptance_criteria: string | null
  scope_boundaries: string | null
  checkpoint_triggers: string | null
  status: string
  depends_on: string | null
  report: MissionReport | null
  tags: string[]
  created_at: string | null
  completed_at: string | null
}

export interface MissionCreate {
  phase: string
  objective: string
  tasks?: MissionTask[]
  context?: string
  acceptance_criteria?: string
  scope_boundaries?: string
  checkpoint_triggers?: string
  depends_on?: string
  tags?: string[]
}

export interface MissionUpdate {
  status?: MissionStatus
  tasks?: MissionTask[]
  objective?: string
}

export interface MissionReport {
  mission_id: string
  tasks_completed: string[] | null
  findings: string[] | null
  anomalies: string[] | null
  questions: string[] | null
  codebase_state: string | null
  recommended_next: string | null
  submitted_at: string | null
}

export interface MissionReportCreate {
  tasks_completed?: string[]
  findings?: string[]
  anomalies?: string[]
  questions?: string[]
  codebase_state?: string
  recommended_next?: string
}

// ---- Checkpoints ----

export interface CheckpointOption {
  label: string
  description?: string
  consequence?: string
}

export interface Checkpoint {
  id: string
  mission_id: string | null
  task_reference: string | null
  type: string
  description: string
  context: string | null
  options: CheckpointOption[] | null
  recommendation: string | null
  blocking: boolean
  resolution: string | null
  resolved_by: string | null
  resolution_rationale: string | null
  linked_decision_id: string | null
  status: string
  created_at: string | null
  resolved_at: string | null
}

export interface CheckpointResolve {
  resolution: string
  resolved_by: "pi" | "brain"
  rationale?: string
  create_decision?: boolean
}

// ---- Events ----

export interface Event {
  id: string
  timestamp: string | null
  event_type: string
  entity_type: string
  entity_id: string
  actor: string
  summary: string
  caused_by_event: string | null
  caused_by_entity: string | null
  phase: string | null
  details: Record<string, unknown> | null
}

// ---- Project ----

export interface ProjectState {
  project_name: string
  project_description: string | null
  current_phase: string | null
  phases_config: string[] | null
  summary: string | null
  blockers: string | null
  metrics: Record<string, unknown> | null
  created_at: string | null
  updated_at: string | null
}

export interface ProjectStateUpdate {
  project_name?: string
  project_description?: string
  current_phase?: string
  phases_config?: string[]
  summary?: string
  blockers?: string
  metrics?: Record<string, unknown>
}

// ---- Context ----

export interface ContextRequest {
  topic?: string
  phase?: string
  depth?: "summary" | "detailed"
  max_tokens?: number
}

export interface ContextPackage {
  topic: string | null
  phase: string | null
  hot_entries: string[]
  warm_entries: string[]
  cold_entries: string[]
  sources: string[]
  narrative: string | null
  note: string | null
  token_estimate: number
}

// ---- Search ----

export interface SearchResult {
  entity_type: string
  entity_id: string
  title: string
  snippet: string
  score: number
}

export interface SearchRequest {
  query: string
  entity_types?: string[]
  limit?: number
}

// ---- Tags ----

export interface TagCount {
  tag: string
  count: number
}

// ---- Audit ----

export interface AuditEntry {
  id: number
  action: string
  entity_type: string
  entity_id: string | null
  actor: string | null
  details: Record<string, unknown> | null
  created_at: string | null
}

// ---- Health ----

export interface HealthStatus {
  status: string
  version: string
  vec_available: boolean
}

// ---- Academic Import ----

export interface BibtexImportResult {
  total_parsed: number
  imported: Array<{ id: string; title: string }>
  skipped: Array<{ title: string; reason: string }>
  errors: Array<{ title: string; error: string }>
}

export interface MermaidExport {
  mermaid: string
}
