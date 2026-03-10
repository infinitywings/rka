import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { ConfidenceBadge } from "@/components/shared/ConfidenceBadge"
import { TagList } from "@/components/shared/TagList"
import { useProjectStatus } from "@/hooks/useProject"
import { useMissions } from "@/hooks/useMissions"
import { useCheckpoints } from "@/hooks/useCheckpoints"
import { useNotes } from "@/hooks/useNotes"
import { timeAgo } from "@/lib/utils"
import {
  Rocket,
  AlertTriangle,
  BookOpen,
  Target,
} from "lucide-react"

export default function Dashboard() {
  const { data: project, isLoading: projectLoading } = useProjectStatus()
  const { data: missions } = useMissions()
  const { data: checkpoints } = useCheckpoints({ status: "open" })
  const { data: notes } = useNotes({ limit: 10 })

  const activeMissions = missions?.filter((m) => m.status === "active") ?? []

  if (projectLoading) {
    return <DashboardSkeleton />
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground text-sm">
          Project overview and recent activity
        </p>
      </div>

      {/* Top Row: Project Status Cards */}
      <div className="grid gap-4 md:grid-cols-3">
        {/* Project Status */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Project</CardTitle>
            <Target className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">{project?.project_name ?? "—"}</div>
            {project?.current_phase && (
              <Badge variant="outline" className="mt-1">
                {project.current_phase}
              </Badge>
            )}
            {project?.summary && (
              <p className="text-xs text-muted-foreground mt-2 line-clamp-2">
                {project.summary}
              </p>
            )}
          </CardContent>
        </Card>

        {/* Active Missions */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Active Missions</CardTitle>
            <Rocket className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{activeMissions.length}</div>
            <p className="text-xs text-muted-foreground">
              {missions?.length ?? 0} total missions
            </p>
          </CardContent>
        </Card>

        {/* Open Checkpoints */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Open Checkpoints</CardTitle>
            <AlertTriangle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{checkpoints?.length ?? 0}</div>
            <p className="text-xs text-muted-foreground">
              {checkpoints?.filter((c) => c.blocking).length ?? 0} blocking
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Bottom Row: Active Mission + Recent Journal */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Active Mission Detail */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Rocket className="h-4 w-4" />
              Active Missions
            </CardTitle>
          </CardHeader>
          <CardContent>
            {activeMissions.length === 0 ? (
              <p className="text-sm text-muted-foreground">No active missions</p>
            ) : (
              <div className="space-y-3">
                {activeMissions.slice(0, 3).map((mission) => {
                  const tasks = mission.tasks ?? []
                  const done = tasks.filter((t) => t.status === "complete").length
                  const pct = tasks.length > 0 ? Math.round((done / tasks.length) * 100) : 0
                  return (
                    <div key={mission.id} className="space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium truncate max-w-[70%]">
                          {mission.objective}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {done}/{tasks.length}
                        </span>
                      </div>
                      <div className="h-1.5 w-full rounded-full bg-secondary">
                        <div
                          className="h-1.5 rounded-full bg-primary transition-all"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Recent Journal Entries */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <BookOpen className="h-4 w-4" />
              Recent Journal
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!notes?.length ? (
              <p className="text-sm text-muted-foreground">No entries yet</p>
            ) : (
              <div className="space-y-3">
                {notes.slice(0, 5).map((entry) => (
                  <div key={entry.id} className="space-y-1">
                    <div className="flex items-center gap-2">
                      <ConfidenceBadge confidence={entry.confidence} />
                      <StatusBadge status={entry.type} />
                      {entry.created_at && (
                        <span className="text-[10px] text-muted-foreground ml-auto">
                          {timeAgo(entry.created_at)}
                        </span>
                      )}
                    </div>
                    <p className="text-sm line-clamp-2">
                      {entry.summary ?? entry.content}
                    </p>
                    <TagList tags={entry.tags} />
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Open Checkpoints */}
      {checkpoints && checkpoints.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-orange-500" />
              Open Checkpoints
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {checkpoints.slice(0, 5).map((chk) => (
                <div key={chk.id} className="flex items-start gap-3 p-2 rounded-md border">
                  <div className="flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      <StatusBadge status={chk.type} />
                      {chk.blocking && (
                        <Badge variant="destructive" className="text-[10px]">
                          blocking
                        </Badge>
                      )}
                    </div>
                    <p className="text-sm">{chk.description}</p>
                    {chk.options && chk.options.length > 0 && (
                      <div className="flex gap-1 mt-1">
                        {chk.options.map((opt) => (
                          <Badge key={opt.label} variant="secondary" className="text-[10px]">
                            {opt.label}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <div>
        <div className="h-8 w-40 bg-muted rounded animate-pulse" />
        <div className="h-4 w-60 bg-muted rounded animate-pulse mt-2" />
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {[1, 2, 3].map((i) => (
          <Card key={i}>
            <CardContent className="pt-6">
              <div className="h-6 w-20 bg-muted rounded animate-pulse" />
              <div className="h-8 w-12 bg-muted rounded animate-pulse mt-2" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
