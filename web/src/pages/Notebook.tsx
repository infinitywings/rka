import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { toast } from "sonner"
import { MessageSquare, Send, AlertTriangle, Loader2 } from "lucide-react"
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
          Ask questions about your research
        </p>
      </div>

      {!llmReady && (
        <Card className="border-amber-200 bg-amber-50/50">
          <CardContent className="pt-4 pb-4 flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium text-amber-800">Local LLM not available</p>
              <p className="text-xs text-amber-600 mt-0.5">
                Q&A requires a connected local LLM (LM Studio or Ollama).{" "}
                <NavLink to="/settings" className="underline font-medium">
                  Configure it in Settings
                </NavLink>
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <MessageSquare className="h-4 w-4" />
            Q&A
          </CardTitle>
        </CardHeader>
        <CardContent>
          <QAPanel disabled={!llmReady} />
        </CardContent>
      </Card>
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
