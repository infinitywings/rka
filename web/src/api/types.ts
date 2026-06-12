// TypeScript interfaces matching RKA Pydantic models

// ---- Journal ----

// v2.0 canonical types
export type JournalType = "note" | "log" | "directive"
// Legacy types still accepted by the API (auto-mapped to v2 types)
export type LegacyJournalType =
  | "finding" | "insight" | "pi_instruction" | "exploration"
  | "idea" | "observation" | "hypothesis" | "methodology" | "summary"
export type AnyJournalType = JournalType | LegacyJournalType

export type Source = "brain" | "executor" | "pi" | "web_ui" | "llm"
export type Confidence = "hypothesis" | "tested" | "verified" | "superseded" | "retracted"
export type Importance = "critical" | "high" | "normal" | "low" | "archived"
export type JournalStatus = "draft" | "active" | "superseded" | "retracted"

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
  status: string
  pinned: boolean
  tags: string[]
  created_at: string | null
  updated_at: string | null
}

export interface JournalEntryCreate {
  content: string
  type?: AnyJournalType
  source?: Source
  phase?: string
  related_decisions?: string[]
  related_literature?: string[]
  related_mission?: string
  supersedes?: string
  confidence?: Confidence
  importance?: Importance
  status?: JournalStatus
  pinned?: boolean
  tags?: string[]
}

export interface JournalEntryUpdate {
  content?: string
  type?: AnyJournalType
  summary?: string
  confidence?: Confidence
  importance?: Importance
  status?: JournalStatus
  pinned?: boolean
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
export type DecisionKind = "research_question" | "design_choice" | "decision" | "operational"

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
  related_journal: string[] | null
  superseded_by: string | null
  scope_version: number
  kind: string
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
  related_journal?: string[]
  status?: DecisionStatus
  kind?: DecisionKind
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
  related_journal?: string[]
  kind?: DecisionKind
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
  iteration: number
  parent_mission_id: string | null
  motivated_by_decision: string | null
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
  motivated_by_decision?: string
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

export interface ProjectInfo {
  id: string
  name: string
  description: string | null
  created_by: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ProjectCreate {
  id?: string
  name: string
  description?: string
  phases_config?: string[]
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

export interface KnowledgePackImportResult {
  project_id: string
  project_name: string
  source_project_id: string
  imported_counts: Record<string, number>
  artifact_files_restored: number
}

export interface KnowledgePackDownload {
  blob: Blob
  filename: string
}

// ---- Context ----

export interface ContextRequest {
  topic?: string
  phase?: string
  depth?: "summary" | "detailed"
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

// ---- Embedding configuration (v2.4.0, Mission D) ----

export type EmbeddingBackendKind = "fastembed" | "openai_compat" | "ollama"

export interface EmbeddingConfig {
  backend: EmbeddingBackendKind
  config: {
    base_url?: string
    model?: string
    model_name?: string
    api_key?: string
    dim?: number
  }
  updated_at?: string | null
  updated_by?: string | null
}

export interface ConnectionTestResult {
  ok: boolean
  detail: string
  detected_dim: number | null
  latency_ms: number | null
}

export interface BackfillStatus {
  job_id: string | null
  state: "idle" | "pending" | "running" | "complete" | "failed"
  processed?: number
  total?: number
  started_at?: string
  elapsed_seconds?: number
  error?: string | null
}

export interface EmbeddingConfigError {
  error: "embedding_config_invalid"
  detail: string
  hint: string
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

// ---- Graph ----

export interface GraphNode {
  id: string
  type: string
  label: string
  status: string | null
  phase: string
  created_at: string
}

export interface GraphEdge {
  source: string
  target: string
  link_type: string
  created_at: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface GraphStats {
  node_counts: Record<string, number>
  total_nodes: number
  total_edges: number
  edge_counts_by_type: Record<string, number>
}

// ---- Summaries ----

export interface SummaryResult {
  id: string
  scope_type: string
  scope_id: string | null
  granularity: string
  one_line: string
  paragraph: string
  narrative: string | null
  key_questions: string[]
  sources: Array<{ entity_type: string; entity_id: string; excerpt: string }>
  confidence: number
}

export interface ExplorationSummary {
  id: string
  scope_type: string
  scope_id: string | null
  granularity: string
  content: string
  produced_by: string | null
  confidence: number | null
  blessed: number
  source_refs: string | null
  created_at: string
  updated_at: string
}

// ---- QA ----

export interface QAResult {
  session_id: string
  log_id: string
  answer: string
  answer_type: string
  sources: Array<{ entity_type: string; entity_id: string; excerpt: string }>
  confidence: number
  followups: string[]
}

export interface QASession {
  id: string
  title: string | null
  created_by: string | null
  created_at: string
  logs: Array<{
    id: string
    question: string
    answer: string
    confidence: number | null
    created_at: string
  }>
}

// ---- v2.0: Claims & Research Map ----

export type ClaimType = "hypothesis" | "evidence" | "method" | "result" | "observation" | "assumption"
export type ClusterConfidence = "strong" | "moderate" | "emerging" | "contested" | "refuted"

export interface Claim {
  id: string
  source_entry_id: string
  claim_type: string
  content: string
  confidence: number
  verified: boolean
  stale: boolean
  source_offset_start: number | null
  source_offset_end: number | null
  source_type?: string | null
  source_actor?: string | null
  project_id?: string
  created_at?: string | null
  updated_at?: string | null
}

export interface EvidenceCluster {
  id: string
  research_question_id: string | null
  label: string
  synthesis: string | null
  confidence: string
  claim_count: number
  gap_count: number
  needs_reprocessing: boolean
  synthesized_by: string
  project_id?: string
  created_at?: string | null
  updated_at?: string | null
}

export interface EvidenceClusterUpdateRequest {
  label?: string
  synthesis?: string | null
  confidence?: ClusterConfidence
  needs_reprocessing?: boolean
  synthesized_by?: "llm" | "brain"
  research_question_id?: string | null
}

export interface ResearchQuestion {
  id: string
  question: string
  status: string
  phase: string | null
  cluster_count: number
  total_claims: number
  gap_count: number
  contradiction_count: number
  created_at: string | null
}

export interface ResearchMapData {
  research_questions: ResearchQuestion[]
  unassigned_clusters: Array<{
    id: string
    label: string
    claim_count: number
    confidence: string
  }>
  summary: {
    total_rqs: number
    total_clusters: number
    total_claims: number
    total_gaps: number
    total_contradictions: number
    pending_review: number
  }
}

export interface ClusterContradiction {
  id: string
  confidence: number
  source_claim_id: string
  source_claim_content: string
  source_entry_id: string | null
  target_claim_id: string | null
  target_claim_content: string | null
  target_source_entry_id: string | null
  created_at: string | null
}

export interface ResearchQuestionReference {
  id: string
  question: string
}

export interface ResearchMapClusterDetail extends EvidenceCluster {
  research_question: ResearchQuestionReference | null
  claims: Claim[]
  contradictions: ClusterContradiction[]
  review_items: ReviewItem[]
}

export interface ReviewItem {
  id: string
  item_type: string
  item_id: string
  flag: string
  context: unknown
  priority: number
  status: string
  raised_by: string
  resolved_by: string | null
  resolution: string | null
  project_id: string
  created_at: string | null
  resolved_at: string | null
}

// ---- Verification & Research Health (eval-v3 themes B/C) ----

export interface StalenessImpactNode {
  id: string
  type: string
  label: string
  status: string | null
  depth: number
  via: { from: string; link_type: string }
}

export interface StalenessImpact {
  root: string
  root_status: string | null
  root_is_stale: boolean
  impacted: StalenessImpactNode[]
  counts: Record<string, number>
  max_depth: number
}

export type MissionGuardKind = "retracted" | "superseded" | "contradicted"

export interface MissionGuardWarning {
  id: string
  kind: MissionGuardKind
  relevance: number
  excerpt: string
  guidance: string
  superseded_by?: string | null
  contradicts?: string | null
}

export interface MissionGuard {
  mission_id: string
  warnings: MissionGuardWarning[]
  checked: { stale_journal: number; contradictions: number }
}

export interface BeliefAsOfDecision {
  id: string
  question: string
  chosen: string
}

export interface BeliefAsOfJournalEntry {
  id: string
  excerpt: string
  confidence_now: string
  approximate?: boolean
}

export interface BeliefChange {
  id: string
  type: string
  was: string
  changed_at: string | null
  superseded_by?: string | null
  change?: string
  approximate?: boolean
}

export interface BeliefAsOf {
  as_of: string
  then_current: {
    decisions: BeliefAsOfDecision[]
    journal_count: number
    journal: BeliefAsOfJournalEntry[]
  }
  changed_since: BeliefChange[]
  note: string
}

export interface CoverageCounts {
  covered: number
  total: number
}

export interface ResearchHealth {
  provenance_coverage: {
    decisions_with_evidence_pct: number
    decisions: CoverageCounts
    missions_with_motivation_pct: number
    missions: CoverageCounts
    claims_with_source_pct: number
    claims: CoverageCounts
    supersede_chain_integrity: {
      superseded_decisions: number
      orphaned_pointers: number
    }
  }
  research_debt_trajectory_weekly: Array<{
    week: string
    created: number
    covered: number
  }>
  mission_cycle: {
    completed: number
    avg_days_to_complete: number | null
    max_days_to_complete: number | null
    checkpoints_total: number
    checkpoints_open: number
  }
  bookkeeping_overhead: {
    recorded_actions: Record<string, number>
    write_share_pct: number
  }
}

export interface ReportContextRequest {
  description: string
  angle_queries?: string[]
  max_depth?: number
  max_nodes?: number
}

export type ReportContextInclusion =
  | { via: "search"; query: string; rank: number }
  | { via: "link"; from: string; link_type: string }

export interface ReportContextNode {
  id: string
  type: string
  label: string
  score: number
  depth: number
  included_via: ReportContextInclusion
  tags: string[]
  status?: string | null
}

export interface ReportContextResult {
  nodes: ReportContextNode[]
  queries: string[]
  seed_count: number
  expanded_count: number
  truncated: boolean
}

export interface StalenessReviewFiling {
  stale_roots: number
  filed: number
  items: Array<{ review_id: string; item_id: string; stale_root: string }>
}

export interface LinkSupportFinding {
  item_type: string
  item_id: string
  label: string
  support: number
  detail: string
}

export interface LinkSupportAudit {
  checked_decisions: number
  checked_clusters: number
  unsupported: LinkSupportFinding[]
  method: string
}
