import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { useProjectStatus } from "@/hooks/useProject"
import { useHealth } from "@/hooks/useProject"
import { useNotes } from "@/hooks/useNotes"
import { useDecisions } from "@/hooks/useDecisions"
import { useLiterature } from "@/hooks/useLiterature"
import { useMissions } from "@/hooks/useMissions"
import { useCheckpoints } from "@/hooks/useCheckpoints"
import { useTags } from "@/hooks/useSearch"
import {
  Settings as SettingsIcon,
  Database,
  Activity,
  Server,
  Tag,
  CheckCircle2,
  XCircle,
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
