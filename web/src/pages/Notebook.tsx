import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { toast } from "sonner"
import { MessageSquare, Sparkles, Send, CheckCircle, Clock, AlertTriangle, Loader2 } from "lucide-react"
import { useLLMStatus } from "@/hooks/useLLM"
import { NavLink } from "react-router-dom"
import { Markdown } from "@/components/shared/Markdown"

export default function Notebook() {
  const { data: llm } = useLLMStatus()
  const llmReady = llm?.enabled && llm?.available

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Notebook</h1>
        <p className="text-sm text-muted-foreground">
          Ask questions about your research and generate summaries
        </p>
      </div>

      {!llmReady && (
        <Card className="border-amber-200 bg-amber-50/50">
          <CardContent className="pt-4 pb-4 flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium text-amber-800">Local LLM not available</p>
              <p className="text-xs text-amber-600 mt-0.5">
                Q&A and summary features require a connected local LLM (LM Studio or Ollama).{" "}
                <NavLink to="/settings" className="underline font-medium">
                  Configure it in Settings
                </NavLink>
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="qa" className="space-y-4">
        <TabsList>
          <TabsTrigger value="qa" className="gap-1.5">
            <MessageSquare className="h-3.5 w-3.5" /> Q&A
          </TabsTrigger>
          <TabsTrigger value="summaries" className="gap-1.5">
            <Sparkles className="h-3.5 w-3.5" /> Summaries
          </TabsTrigger>
        </TabsList>

        <TabsContent value="qa"><QAPanel disabled={!llmReady} /></TabsContent>
        <TabsContent value="summaries"><SummaryPanel disabled={!llmReady} /></TabsContent>
      </Tabs>
    </div>
  )
}

// ── Q&A Panel ──────────────────────────────────────────────────────────────

function QAPanel({ disabled = false }: { disabled?: boolean }) {
  const queryClient = useQueryClient()
  const [question, setQuestion] = useState("")
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [conversation, setConversation] = useState<Array<{
    question: string
    answer: string
    sources: Array<{ entity_type: string; entity_id: string; excerpt: string }>
    confidence: number
    followups: string[]
  }>>([])

  const askMutation = useMutation({
    mutationFn: (q: string) => api.askQuestion({
      question: q,
      session_id: sessionId ?? undefined,
    }),
    onSuccess: (data) => {
      if ("error" in data) {
        toast.error(String((data as { error: string }).error))
        return
      }
      setSessionId(data.session_id)
      setConversation(prev => [...prev, {
        question,
        answer: data.answer,
        sources: data.sources,
        confidence: data.confidence,
        followups: data.followups,
      }])
      setQuestion("")
      queryClient.invalidateQueries({ queryKey: ["qa-sessions"] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const { data: sessions = [] } = useQuery({
    queryKey: ["qa-sessions"],
    queryFn: () => api.listQASessions(),
  })

  const handleAsk = () => {
    if (!question.trim()) return
    askMutation.mutate(question.trim())
  }

  const loadSession = async (sid: string) => {
    const session = await api.getQASession(sid)
    if (session && "logs" in session && session.logs) {
      setSessionId(sid)
      setConversation(session.logs.map((l: { question: string; answer: string; confidence: number | null }) => ({
        question: l.question,
        answer: l.answer,
        sources: [],
        confidence: l.confidence ?? 0,
        followups: [],
      })))
    }
  }

  return (
    <div className="grid grid-cols-[1fr_240px] gap-4">
      {/* Main conversation */}
      <div className="space-y-4">
        {/* Messages */}
        <div className="space-y-3 min-h-[200px]">
          {conversation.length === 0 && (
            <div className="flex items-center justify-center h-48 text-muted-foreground text-sm">
              Ask a question about your research. Answers are grounded in your knowledge base.
            </div>
          )}
          {conversation.map((msg, i) => (
            <div key={i} className="space-y-2">
              {/* Question */}
              <div className="flex justify-end">
                <div className="bg-primary text-primary-foreground rounded-lg px-3 py-2 max-w-[80%] text-sm">
                  {msg.question}
                </div>
              </div>
              {/* Answer */}
              <Card>
                <CardContent className="pt-4 space-y-3">
                  <Markdown>{msg.answer}</Markdown>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-[10px]">
                      Confidence: {(msg.confidence * 100).toFixed(0)}%
                    </Badge>
                  </div>
                  {msg.sources.length > 0 && (
                    <div className="border-t pt-2">
                      <p className="text-[10px] font-bold text-muted-foreground uppercase mb-1">Sources</p>
                      <div className="space-y-1">
                        {msg.sources.map((s, j) => (
                          <div key={j} className="text-[11px] text-muted-foreground">
                            <Badge variant="secondary" className="text-[9px] mr-1">{s.entity_type}</Badge>
                            <span className="font-mono text-[10px]">{s.entity_id}</span>
                            {s.excerpt && (
                              <p className="mt-0.5 italic text-[10px] line-clamp-2">"{s.excerpt}"</p>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {msg.followups.length > 0 && (
                    <div className="border-t pt-2">
                      <p className="text-[10px] font-bold text-muted-foreground uppercase mb-1">Follow-up questions</p>
                      <div className="space-y-1">
                        {msg.followups.map((f, j) => (
                          <button
                            key={j}
                            onClick={() => setQuestion(f)}
                            className="block text-xs text-blue-600 hover:underline text-left"
                          >
                            {f}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          ))}
          {askMutation.isPending && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground px-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              Thinking...
            </div>
          )}
        </div>

        {/* Input */}
        <div className="flex gap-2">
          <Textarea
            value={question}
            onChange={e => setQuestion(e.target.value)}
            placeholder={disabled ? "LLM not available — configure in Settings" : "Ask a question about your research..."}
            className="min-h-[60px] resize-none"
            disabled={disabled}
            onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                handleAsk()
              }
            }}
          />
          <Button
            onClick={handleAsk}
            disabled={disabled || !question.trim() || askMutation.isPending}
            className="shrink-0"
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Sessions sidebar */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold text-muted-foreground uppercase">Sessions</p>
          <Button
            variant="ghost" size="sm"
            onClick={() => { setSessionId(null); setConversation([]) }}
            className="text-xs h-6"
          >
            New
          </Button>
        </div>
        <div className="space-y-1">
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => loadSession(s.id)}
              className={`w-full text-left p-2 rounded text-xs hover:bg-accent transition-colors ${
                sessionId === s.id ? "bg-accent" : ""
              }`}
            >
              <p className="truncate font-medium">{s.title || "Untitled"}</p>
              <p className="text-[10px] text-muted-foreground">{s.created_at?.slice(0, 10)}</p>
            </button>
          ))}
          {sessions.length === 0 && (
            <p className="text-[11px] text-muted-foreground text-center py-4">
              No sessions yet
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Summary Panel ──────────────────────────────────────────────────────────

function SummaryPanel({ disabled = false }: { disabled?: boolean }) {
  const queryClient = useQueryClient()
  const [scopeType, setScopeType] = useState("project")
  const [scopeId, setScopeId] = useState("")
  const [granularity, setGranularity] = useState("paragraph")
  const [activeResult, setActiveResult] = useState<{
    one_line: string; paragraph: string; narrative: string | null
    key_questions: string[]
    sources: Array<{ entity_type: string; entity_id: string; excerpt: string }>
    confidence: number
  } | null>(null)

  // Fetch data for scope dropdowns
  const { data: missions = [] } = useQuery({
    queryKey: ["missions"],
    queryFn: () => api.listMissions(),
  })
  const { data: project } = useQuery({
    queryKey: ["project-status"],
    queryFn: () => api.getStatus(),
  })
  const { data: tags = [] } = useQuery({
    queryKey: ["tags"],
    queryFn: () => api.listTags(),
  })

  const phases = project?.phases_config ?? []

  const { data: summaries = [] } = useQuery({
    queryKey: ["summaries"],
    queryFn: () => api.listSummaries(),
  })

  const generateMutation = useMutation({
    mutationFn: () => api.generateSummary({
      scope_type: scopeType,
      scope_id: scopeId || undefined,
      granularity,
    }),
    onSuccess: (data) => {
      if ("error" in data) {
        toast.error(String((data as { error: string }).error))
        return
      }
      setActiveResult(data)
      queryClient.invalidateQueries({ queryKey: ["summaries"] })
      toast.success("Summary generated")
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const blessMutation = useMutation({
    mutationFn: (id: string) => api.blessSummary(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["summaries"] })
      toast.success("Summary blessed")
    },
  })

  // Reset scope ID when scope type changes
  const handleScopeTypeChange = (v: string | null) => {
    if (!v) return
    setScopeType(v)
    setScopeId("")
  }

  // Build the scope ID options based on scope type
  const renderScopeIdPicker = () => {
    if (scopeType === "project") return null

    if (scopeType === "phase" && phases.length > 0) {
      return (
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">Phase</label>
          <Select value={scopeId} onValueChange={(v) => v && setScopeId(v)}>
            <SelectTrigger className="text-xs h-8">
              <SelectValue placeholder="Select a phase..." />
            </SelectTrigger>
            <SelectContent>
              {phases.map((p: string) => (
                <SelectItem key={p} value={p} className="text-xs">{p}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )
    }

    if (scopeType === "mission" && missions.length > 0) {
      return (
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">Mission</label>
          <Select value={scopeId} onValueChange={(v) => v && setScopeId(v)}>
            <SelectTrigger className="text-xs h-8">
              <SelectValue placeholder="Select a mission..." />
            </SelectTrigger>
            <SelectContent>
              {missions.map((m) => (
                <SelectItem key={m.id} value={m.id} className="text-xs">
                  {m.objective.length > 60 ? m.objective.slice(0, 60) + "..." : m.objective}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )
    }

    if (scopeType === "tag" && tags.length > 0) {
      return (
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">Tag</label>
          <Select value={scopeId} onValueChange={(v) => v && setScopeId(v)}>
            <SelectTrigger className="text-xs h-8">
              <SelectValue placeholder="Select a tag..." />
            </SelectTrigger>
            <SelectContent>
              {tags.slice(0, 30).map((t: { tag: string; count: number }) => (
                <SelectItem key={t.tag} value={t.tag} className="text-xs">
                  {t.tag} ({t.count})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )
    }

    // Fallback text input for empty lists
    return (
      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">
          {scopeType === "phase" ? "Phase" : scopeType === "mission" ? "Mission ID" : "Tag"}
        </label>
        <input
          value={scopeId}
          onChange={(e) => setScopeId(e.target.value)}
          placeholder={`Enter ${scopeType}...`}
          className="w-full text-xs h-8 rounded-md border border-input bg-background px-3"
        />
      </div>
    )
  }

  return (
    <div className="grid grid-cols-[1fr_300px] gap-4">
      {/* Generate + Result */}
      <div className="space-y-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Generate Summary</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              {/* Scope type */}
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Scope</label>
                <Select value={scopeType} onValueChange={handleScopeTypeChange}>
                  <SelectTrigger className="text-xs h-8">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="project" className="text-xs">Entire Project</SelectItem>
                    <SelectItem value="phase" className="text-xs">By Phase</SelectItem>
                    <SelectItem value="mission" className="text-xs">By Mission</SelectItem>
                    <SelectItem value="tag" className="text-xs">By Tag</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-[10px] text-muted-foreground">
                  {scopeType === "project" ? "Summarize everything" :
                   scopeType === "phase" ? "Summarize a research phase" :
                   scopeType === "mission" ? "Summarize a specific mission" :
                   "Summarize entries with a tag"}
                </p>
              </div>

              {/* Granularity */}
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Detail Level</label>
                <Select value={granularity} onValueChange={(v: string | null) => v && setGranularity(v)}>
                  <SelectTrigger className="text-xs h-8">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="one_line" className="text-xs">One-line</SelectItem>
                    <SelectItem value="paragraph" className="text-xs">Paragraph</SelectItem>
                    <SelectItem value="narrative" className="text-xs">Full Narrative</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-[10px] text-muted-foreground">
                  {granularity === "one_line" ? "Brief one-sentence summary" :
                   granularity === "paragraph" ? "Concise paragraph" :
                   "Detailed narrative with context"}
                </p>
              </div>
            </div>

            {/* Scope ID picker */}
            {renderScopeIdPicker()}

            <Button
              onClick={() => generateMutation.mutate()}
              disabled={disabled || generateMutation.isPending || (scopeType !== "project" && !scopeId)}
              size="sm"
            >
              {generateMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
              ) : (
                <Sparkles className="h-3.5 w-3.5 mr-1.5" />
              )}
              {generateMutation.isPending ? "Generating..." : "Generate"}
            </Button>
          </CardContent>
        </Card>

        {activeResult && (
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm">Result</CardTitle>
                <Badge variant="outline" className="text-[10px]">
                  Confidence: {(activeResult.confidence * 100).toFixed(0)}%
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {activeResult.one_line && (
                <div>
                  <p className="text-[10px] font-bold text-muted-foreground uppercase mb-0.5">One-line</p>
                  <p className="text-sm font-medium">{activeResult.one_line}</p>
                </div>
              )}
              {activeResult.paragraph && (
                <div>
                  <p className="text-[10px] font-bold text-muted-foreground uppercase mb-0.5">Summary</p>
                  <Markdown>{activeResult.paragraph}</Markdown>
                </div>
              )}
              {activeResult.narrative && (
                <div>
                  <p className="text-[10px] font-bold text-muted-foreground uppercase mb-0.5">Narrative</p>
                  <Markdown>{activeResult.narrative}</Markdown>
                </div>
              )}
              {activeResult.key_questions.length > 0 && (
                <div className="border-t pt-2">
                  <p className="text-[10px] font-bold text-muted-foreground uppercase mb-1">Open Questions</p>
                  <ul className="space-y-0.5">
                    {activeResult.key_questions.map((q, i) => (
                      <li key={i} className="text-xs text-muted-foreground">? {q}</li>
                    ))}
                  </ul>
                </div>
              )}
              {activeResult.sources.length > 0 && (
                <div className="border-t pt-2">
                  <p className="text-[10px] font-bold text-muted-foreground uppercase mb-1">
                    Sources ({activeResult.sources.length})
                  </p>
                  <div className="space-y-1">
                    {activeResult.sources.slice(0, 5).map((s, i) => (
                      <div key={i} className="text-[11px] text-muted-foreground">
                        <Badge variant="secondary" className="text-[9px] mr-1">{s.entity_type}</Badge>
                        <span className="font-mono text-[10px]">{s.entity_id}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      {/* Saved summaries */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-muted-foreground uppercase">Saved Summaries</p>
        <div className="space-y-2">
          {summaries.map(s => (
            <Card key={s.id} className="cursor-pointer hover:shadow-sm transition-shadow">
              <CardContent className="p-3 space-y-1">
                <div className="flex items-center justify-between">
                  <Badge variant="outline" className="text-[9px]">{s.scope_type}</Badge>
                  <div className="flex items-center gap-1">
                    {s.blessed ? (
                      <CheckCircle className="h-3 w-3 text-green-500" />
                    ) : (
                      <button
                        onClick={() => blessMutation.mutate(s.id)}
                        className="text-[10px] text-blue-600 hover:underline"
                      >
                        Bless
                      </button>
                    )}
                  </div>
                </div>
                <p className="text-xs line-clamp-3">{s.content}</p>
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                  <Clock className="h-2.5 w-2.5" />
                  {s.created_at?.slice(0, 10)}
                </div>
              </CardContent>
            </Card>
          ))}
          {summaries.length === 0 && (
            <p className="text-[11px] text-muted-foreground text-center py-4">
              No summaries yet. Generate one to get started.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
