/**
 * RKA API client — thin fetch wrapper with typed endpoints.
 */

const BASE_URL = "/api"

class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(`API Error ${status}: ${detail}`)
    this.name = "ApiError"
    this.status = status
    this.detail = detail
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${BASE_URL}${path}`
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  })

  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || JSON.stringify(body)
    } catch {
      // use statusText
    }
    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return undefined as T
  return res.json()
}

function get<T>(path: string): Promise<T> {
  return request<T>(path)
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  })
}

function put<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    body: body ? JSON.stringify(body) : undefined,
  })
}

// ---- Typed API methods ----

import type {
  JournalEntry,
  JournalEntryCreate,
  JournalEntryUpdate,
  Decision,
  DecisionCreate,
  DecisionUpdate,
  DecisionTreeNode,
  Literature,
  LiteratureCreate,
  LiteratureUpdate,
  Mission,
  MissionCreate,
  MissionUpdate,
  MissionReportCreate,
  MissionReport,
  Checkpoint,
  CheckpointResolve,
  Event,
  ProjectState,
  ProjectStateUpdate,
  ContextRequest,
  ContextPackage,
  SearchResult,
  TagCount,
  HealthStatus,
  AuditEntry,
  BibtexImportResult,
  MermaidExport,
  GraphData,
  GraphStats,
  SummaryResult,
  ExplorationSummary,
  QAResult,
  QASession,
  LLMStatus,
  LLMConfigUpdate,
  LLMModel,
} from "./types"

export const api = {
  // Health
  health: () => get<HealthStatus>("/health"),

  // Project
  getStatus: () => get<ProjectState>("/status"),
  updateStatus: (data: ProjectStateUpdate) => put<ProjectState>("/status", data),

  // Notes / Journal
  listNotes: (params?: { phase?: string; type?: string; since?: string; limit?: number }) => {
    const search = new URLSearchParams()
    if (params?.phase) search.set("phase", params.phase)
    if (params?.type) search.set("type", params.type)
    if (params?.since) search.set("since", params.since)
    if (params?.limit) search.set("limit", String(params.limit))
    const qs = search.toString()
    return get<JournalEntry[]>(`/notes${qs ? `?${qs}` : ""}`)
  },
  getNote: (id: string) => get<JournalEntry>(`/notes/${id}`),
  createNote: (data: JournalEntryCreate) => post<JournalEntry>("/notes", data),
  updateNote: (id: string, data: JournalEntryUpdate) => put<JournalEntry>(`/notes/${id}`, data),

  // Decisions
  listDecisions: (params?: { phase?: string; status?: string }) => {
    const search = new URLSearchParams()
    if (params?.phase) search.set("phase", params.phase)
    if (params?.status) search.set("status", params.status)
    const qs = search.toString()
    return get<Decision[]>(`/decisions${qs ? `?${qs}` : ""}`)
  },
  getDecision: (id: string) => get<Decision>(`/decisions/${id}`),
  createDecision: (data: DecisionCreate) => post<Decision>("/decisions", data),
  updateDecision: (id: string, data: DecisionUpdate) => put<Decision>(`/decisions/${id}`, data),
  getDecisionTree: (phase?: string) => {
    const qs = phase ? `?phase=${phase}` : ""
    return get<DecisionTreeNode[]>(`/decisions/tree${qs}`)
  },

  // Literature
  listLiterature: (params?: { status?: string }) => {
    const search = new URLSearchParams()
    if (params?.status) search.set("status", params.status)
    const qs = search.toString()
    return get<Literature[]>(`/literature${qs ? `?${qs}` : ""}`)
  },
  getLiterature: (id: string) => get<Literature>(`/literature/${id}`),
  createLiterature: (data: LiteratureCreate) => post<Literature>("/literature", data),
  updateLiterature: (id: string, data: LiteratureUpdate) =>
    put<Literature>(`/literature/${id}`, data),

  // Missions
  listMissions: (params?: { status?: string }) => {
    const search = new URLSearchParams()
    if (params?.status) search.set("status", params.status)
    const qs = search.toString()
    return get<Mission[]>(`/missions${qs ? `?${qs}` : ""}`)
  },
  getMission: (id: string) => get<Mission>(`/missions/${id}`),
  createMission: (data: MissionCreate) => post<Mission>("/missions", data),
  updateMission: (id: string, data: MissionUpdate) => put<Mission>(`/missions/${id}`, data),
  submitReport: (id: string, data: MissionReportCreate) =>
    post<Mission>(`/missions/${id}/report`, data),
  getReport: (id: string) => get<MissionReport | null>(`/missions/${id}/report`),

  // Checkpoints
  listCheckpoints: (params?: { status?: string; mission_id?: string }) => {
    const search = new URLSearchParams()
    if (params?.status) search.set("status", params.status)
    if (params?.mission_id) search.set("mission_id", params.mission_id)
    const qs = search.toString()
    return get<Checkpoint[]>(`/checkpoints${qs ? `?${qs}` : ""}`)
  },
  getCheckpoint: (id: string) => get<Checkpoint>(`/checkpoints/${id}`),
  resolveCheckpoint: (id: string, data: CheckpointResolve) =>
    put<Checkpoint>(`/checkpoints/${id}/resolve`, data),

  // Events
  listEvents: (params?: { entity_type?: string; entity_id?: string; limit?: number }) => {
    const search = new URLSearchParams()
    if (params?.entity_type) search.set("entity_type", params.entity_type)
    if (params?.entity_id) search.set("entity_id", params.entity_id)
    if (params?.limit) search.set("limit", String(params.limit))
    const qs = search.toString()
    return get<Event[]>(`/events${qs ? `?${qs}` : ""}`)
  },

  // Search
  search: (query: string, entityTypes?: string[], limit?: number) =>
    post<SearchResult[]>("/search", { query, entity_types: entityTypes, limit }),

  // Tags
  listTags: () => get<TagCount[]>("/tags"),

  // Context
  getContext: (data: ContextRequest) => post<ContextPackage>("/context", data),

  // Summarize
  summarize: (data: { topic?: string; phase?: string; entity_ids?: string[] }) =>
    post<{ summary_id: string | null; summary: string; source_count: number }>("/summarize", data),

  // Audit
  listAudit: (params?: {
    action?: string; entity_type?: string; actor?: string; since?: string; limit?: number
  }) => {
    const search = new URLSearchParams()
    if (params?.action) search.set("action", params.action)
    if (params?.entity_type) search.set("entity_type", params.entity_type)
    if (params?.actor) search.set("actor", params.actor)
    if (params?.since) search.set("since", params.since)
    if (params?.limit) search.set("limit", String(params.limit))
    const qs = search.toString()
    return get<AuditEntry[]>(`/audit${qs ? `?${qs}` : ""}`)
  },
  auditCounts: () => get<Record<string, number>>("/audit/counts"),

  // Academic Import
  importBibtex: (bibtex: string, skipDuplicates?: boolean) =>
    post<BibtexImportResult>("/import/bibtex", {
      bibtex,
      skip_duplicates: skipDuplicates ?? true,
    }),
  enrichDoi: (litId: string) =>
    post<{ status: string; fields_updated?: string[] }>(`/literature/${litId}/enrich-doi`),
  getMermaid: (phase?: string) => {
    const qs = phase ? `?phase=${phase}` : ""
    return get<MermaidExport>(`/decisions/mermaid${qs}`)
  },

  // Graph
  getGraph: (params?: { include_types?: string; phase?: string; limit?: number }) => {
    const search = new URLSearchParams()
    if (params?.include_types) search.set("include_types", params.include_types)
    if (params?.phase) search.set("phase", params.phase)
    if (params?.limit) search.set("limit", String(params.limit))
    const qs = search.toString()
    return get<GraphData>(`/graph${qs ? `?${qs}` : ""}`)
  },
  getEgoGraph: (entityId: string, depth?: number) => {
    const qs = depth ? `?depth=${depth}` : ""
    return get<GraphData>(`/graph/ego/${entityId}${qs}`)
  },
  getGraphStats: () => get<GraphStats>("/graph/stats"),

  // Summaries
  generateSummary: (data: { scope_type: string; scope_id?: string; granularity?: string }) =>
    post<SummaryResult>("/summaries/generate", data),
  listSummaries: (params?: { scope_type?: string; blessed_only?: boolean }) => {
    const search = new URLSearchParams()
    if (params?.scope_type) search.set("scope_type", params.scope_type)
    if (params?.blessed_only) search.set("blessed_only", "true")
    const qs = search.toString()
    return get<ExplorationSummary[]>(`/summaries${qs ? `?${qs}` : ""}`)
  },
  blessSummary: (id: string) => post<ExplorationSummary>(`/summaries/${id}/bless`, { actor: "pi" }),

  // QA
  askQuestion: (data: { question: string; session_id?: string; scope_type?: string; scope_id?: string }) =>
    post<QAResult>("/qa/ask", data),
  listQASessions: () => get<QASession[]>("/qa/sessions"),
  getQASession: (id: string) => get<QASession>(`/qa/sessions/${id}`),

  // LLM
  getLLMStatus: () => get<LLMStatus>("/llm/status"),
  updateLLMConfig: (data: LLMConfigUpdate) => put<LLMStatus>("/llm/config", data),
  checkLLM: () => post<LLMStatus>("/llm/check"),
  getLLMModels: () => get<LLMModel[]>("/llm/models"),
}

export { ApiError }
