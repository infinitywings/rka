import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Switch } from "@/components/ui/switch"
import { useProjectStatus } from "@/hooks/useProject"
import { useHealth } from "@/hooks/useProject"
import { useNotes } from "@/hooks/useNotes"
import { useDecisions } from "@/hooks/useDecisions"
import { useLiterature } from "@/hooks/useLiterature"
import { useMissions } from "@/hooks/useMissions"
import { useCheckpoints } from "@/hooks/useCheckpoints"
import { useTags } from "@/hooks/useSearch"
import { useLLMStatus, useUpdateLLMConfig, useCheckLLM, useLLMModels } from "@/hooks/useLLM"
import { toast } from "sonner"
import {
  Settings as SettingsIcon,
  Database,
  Activity,
  Server,
  Tag,
  CheckCircle2,
  XCircle,
  Brain,
  RefreshCw,
  Loader2,
} from "lucide-react"

export default function Settings() {
  const { data: project, isLoading: projectLoading } = useProjectStatus()
  const { data: health } = useHealth()
  const { data: notes } = useNotes()
  const { data: decisions } = useDecisions()
  const { data: literature } = useLiterature()
  const { data: missions } = useMissions()
  const { data: checkpoints } = useCheckpoints()
  const { data: tags } = useTags()

  const counts = [
    { label: "Journal Entries", count: notes?.length ?? 0, color: "text-blue-600" },
    { label: "Decisions", count: decisions?.length ?? 0, color: "text-purple-600" },
    { label: "Literature", count: literature?.length ?? 0, color: "text-green-600" },
    { label: "Missions", count: missions?.length ?? 0, color: "text-orange-600" },
    { label: "Checkpoints", count: checkpoints?.length ?? 0, color: "text-red-600" },
    { label: "Tags", count: tags?.length ?? 0, color: "text-cyan-600" },
  ]

  if (projectLoading) {
    return (
      <div className="space-y-6">
        <div>
          <div className="h-8 w-40 bg-muted rounded animate-pulse" />
          <div className="h-4 w-60 bg-muted rounded animate-pulse mt-2" />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {[1, 2, 3, 4].map((i) => (
            <Card key={i}>
              <CardContent className="pt-6">
                <div className="h-24 bg-muted rounded animate-pulse" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground text-sm">
          System configuration, health, and database statistics
        </p>
      </div>

      {/* LLM Configuration — full width, prominent */}
      <LLMConfigCard />

      <div className="grid gap-4 md:grid-cols-2">
        {/* API Health */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Activity className="h-4 w-4" />
              API Health
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm">Status</span>
              <div className="flex items-center gap-2">
                {health?.status === "ok" ? (
                  <CheckCircle2 className="h-4 w-4 text-green-500" />
                ) : (
                  <XCircle className="h-4 w-4 text-red-500" />
                )}
                <Badge
                  variant="outline"
                  className={
                    health?.status === "ok"
                      ? "bg-green-100 text-green-800 border-green-200"
                      : "bg-red-100 text-red-800 border-red-200"
                  }
                >
                  {health?.status ?? "unknown"}
                </Badge>
              </div>
            </div>
            <Separator />
            <div className="flex items-center justify-between">
              <span className="text-sm">Version</span>
              <Badge variant="secondary">{health?.version ?? "—"}</Badge>
            </div>
            <Separator />
            <div className="flex items-center justify-between">
              <span className="text-sm">Vector Search</span>
              <Badge
                variant="outline"
                className={
                  health?.vec_available
                    ? "bg-green-100 text-green-800 border-green-200"
                    : "bg-yellow-100 text-yellow-800 border-yellow-200"
                }
              >
                {health?.vec_available ? "available" : "unavailable"}
              </Badge>
            </div>
          </CardContent>
        </Card>

        {/* Project Configuration */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <SettingsIcon className="h-4 w-4" />
              Project Configuration
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm">Project Name</span>
              <span className="text-sm font-medium">{project?.project_name ?? "—"}</span>
            </div>
            <Separator />
            <div className="flex items-center justify-between">
              <span className="text-sm">Current Phase</span>
              <Badge variant="outline">{project?.current_phase ?? "—"}</Badge>
            </div>
            <Separator />
            <div>
              <span className="text-sm">Phases</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {project?.phases_config?.map((p) => (
                  <Badge
                    key={p}
                    variant={p === project.current_phase ? "default" : "secondary"}
                    className="text-[10px]"
                  >
                    {p}
                  </Badge>
                )) ?? <span className="text-xs text-muted-foreground">—</span>}
              </div>
            </div>
            {project?.project_description && (
              <>
                <Separator />
                <div>
                  <span className="text-sm">Description</span>
                  <p className="text-xs text-muted-foreground mt-1">
                    {project.project_description}
                  </p>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Database Statistics */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Database className="h-4 w-4" />
              Database Statistics
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3">
              {counts.map(({ label, count, color }) => (
                <div key={label} className="flex items-center justify-between p-2 rounded border">
                  <span className="text-xs">{label}</span>
                  <span className={`text-sm font-bold ${color}`}>{count}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Server Info */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Server className="h-4 w-4" />
              Server Info
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm">API Base URL</span>
              <code className="text-xs bg-muted px-2 py-0.5 rounded">
                http://localhost:9712/api
              </code>
            </div>
            <Separator />
            <div className="flex items-center justify-between">
              <span className="text-sm">Backend</span>
              <span className="text-xs text-muted-foreground">
                FastAPI + SQLite + FTS5
              </span>
            </div>
            <Separator />
            <div>
              <span className="text-sm">Quick Links</span>
              <div className="flex gap-2 mt-1">
                <a
                  href="/api/health"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-blue-600 hover:underline"
                >
                  /api/health
                </a>
                <a
                  href="/api/docs"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-blue-600 hover:underline"
                >
                  /api/docs (OpenAPI)
                </a>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Top Tags */}
      {tags && tags.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Tag className="h-4 w-4" />
              Top Tags
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {tags.slice(0, 30).map((t) => (
                <Badge key={t.tag} variant="secondary" className="text-xs gap-1">
                  {t.tag}
                  <span className="text-muted-foreground">({t.count})</span>
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Blockers */}
      {project?.blockers && (
        <Card className="border-orange-200">
          <CardHeader>
            <CardTitle className="text-sm font-medium text-orange-700">
              Current Blockers
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm">{project.blockers}</p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ── LLM Configuration Card ─────────────────────────────────────────────────

function LLMConfigCard() {
  const { data: llm, isLoading } = useLLMStatus()
  const { data: availableModels, refetch: refetchModels } = useLLMModels()
  const updateMutation = useUpdateLLMConfig()
  const checkMutation = useCheckLLM()

  const [editModel, setEditModel] = useState("")
  const [editApiBase, setEditApiBase] = useState("")
  const [editApiKey, setEditApiKey] = useState("")
  const [dirty, setDirty] = useState(false)

  // Initialize form from server data
  const initForm = () => {
    if (llm) {
      setEditModel(llm.model)
      setEditApiBase(llm.api_base ?? "")
      setEditApiKey("")
      setDirty(false)
    }
  }

  // Initialize on first load
  if (llm && !dirty && editModel === "" && editApiBase === "") {
    setEditModel(llm.model)
    setEditApiBase(llm.api_base ?? "")
  }

  const handleSave = () => {
    updateMutation.mutate(
      {
        enabled: true,
        model: editModel,
        api_base: editApiBase || undefined,
        api_key: editApiKey || undefined,
      },
      {
        onSuccess: (data) => {
          setDirty(false)
          refetchModels()
          if (data.available) {
            toast.success("LLM connected successfully")
          } else {
            toast.error("LLM config saved but connection failed. Check that your LLM server is running.")
          }
        },
        onError: () => toast.error("Failed to update LLM config"),
      }
    )
  }

  const handleDisable = () => {
    updateMutation.mutate(
      { enabled: false },
      {
        onSuccess: () => {
          toast.success("LLM disabled")
        },
      }
    )
  }

  const handleCheck = () => {
    checkMutation.mutate(undefined, {
      onSuccess: (data) => {
        if (data.available) {
          toast.success("LLM is reachable")
        } else {
          toast.error("LLM is not reachable. Check that your LLM server is running.")
        }
      },
    })
  }

  if (isLoading) {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="h-24 bg-muted rounded animate-pulse" />
        </CardContent>
      </Card>
    )
  }

  const isAvailable = llm?.enabled && llm?.available

  return (
    <Card className={!isAvailable ? "border-amber-200" : "border-green-200"}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Brain className="h-4 w-4" />
            Local LLM
          </CardTitle>
          <div className="flex items-center gap-3">
            {llm?.enabled && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCheck}
                disabled={checkMutation.isPending}
                className="h-7 text-xs gap-1"
              >
                {checkMutation.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RefreshCw className="h-3 w-3" />
                )}
                Test
              </Button>
            )}
            <Badge
              variant="outline"
              className={
                isAvailable
                  ? "bg-green-100 text-green-800 border-green-200"
                  : llm?.enabled
                  ? "bg-red-100 text-red-800 border-red-200"
                  : "bg-gray-100 text-gray-600 border-gray-200"
              }
            >
              {isAvailable ? "connected" : llm?.enabled ? "disconnected" : "disabled"}
            </Badge>
          </div>
        </div>
        {!isAvailable && (
          <p className="text-xs text-amber-600 mt-1">
            Q&A, summaries, and smart classification require a local LLM.
            {!llm?.enabled
              ? " Enable it below and point to your LM Studio or Ollama server."
              : " Check that your LLM server is running."}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-sm font-medium">Enabled</span>
            <p className="text-[11px] text-muted-foreground">Required for AI-powered features</p>
          </div>
          <Switch
            checked={llm?.enabled ?? false}
            onCheckedChange={(checked) => {
              if (checked) {
                updateMutation.mutate({ enabled: true })
              } else {
                handleDisable()
              }
            }}
          />
        </div>

        {llm?.enabled && (
          <>
            <Separator />
            <div className="space-y-3">
              <div className="space-y-1">
                <label className="text-xs font-medium">API Base URL</label>
                <Input
                  value={editApiBase}
                  onChange={(e) => { setEditApiBase(e.target.value); setDirty(true) }}
                  placeholder="http://localhost:1234/v1"
                  className="text-xs h-8"
                />
                <p className="text-[10px] text-muted-foreground">
                  LM Studio: http://localhost:1234/v1 — Ollama: leave empty
                </p>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium">Model</label>
                {availableModels && availableModels.length > 0 ? (
                  <Select
                    value={editModel}
                    onValueChange={(v) => { if (v) { setEditModel(v); setDirty(true) } }}
                  >
                    <SelectTrigger className="text-xs h-8">
                      <SelectValue placeholder="Select a model…" />
                    </SelectTrigger>
                    <SelectContent>
                      {availableModels.map((m) => {
                        const value = m.id.startsWith("openai/") ? m.id : `openai/${m.id}`
                        return (
                          <SelectItem key={m.id} value={value} className="text-xs">
                            {m.id}
                          </SelectItem>
                        )
                      })}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    value={editModel}
                    onChange={(e) => { setEditModel(e.target.value); setDirty(true) }}
                    placeholder="openai/qwen3-32b"
                    className="text-xs h-8"
                  />
                )}
                <p className="text-[10px] text-muted-foreground">
                  {availableModels && availableModels.length > 0
                    ? `${availableModels.length} models available from LM Studio`
                    : "LM Studio: openai/model-name — Ollama: ollama/model:tag"}
                </p>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium">API Key</label>
                <Input
                  value={editApiKey}
                  onChange={(e) => { setEditApiKey(e.target.value); setDirty(true) }}
                  placeholder={llm?.api_key_set ? "••••••••  (key is set)" : "Not required for local LM Studio / Ollama"}
                  type="password"
                  className="text-xs h-8"
                />
                <p className="text-[10px] text-muted-foreground">
                  Only needed for remote APIs (OpenAI, Together, etc.). Leave blank for local LM Studio / Ollama.
                </p>
              </div>
              {dirty && (
                <div className="flex gap-2">
                  <Button size="sm" onClick={handleSave} disabled={updateMutation.isPending} className="h-7 text-xs">
                    {updateMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
                    Save & Connect
                  </Button>
                  <Button size="sm" variant="ghost" onClick={initForm} className="h-7 text-xs">
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
