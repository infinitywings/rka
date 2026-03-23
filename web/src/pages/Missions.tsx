import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { TagList } from "@/components/shared/TagList"
import { Markdown } from "@/components/shared/Markdown"
import { useMissions } from "@/hooks/useMissions"
import { useCheckpoints } from "@/hooks/useCheckpoints"
import { formatDate } from "@/lib/utils"
import { Rocket, CheckCircle2, Circle, AlertTriangle, Clock, ChevronDown, ChevronUp } from "lucide-react"
import type { Mission, Checkpoint } from "@/api/types"

const taskIcons: Record<string, typeof Circle> = {
  complete: CheckCircle2,
  pending: Circle,
  in_progress: Clock,
  blocked: AlertTriangle,
  skipped: Circle,
}

export default function Missions() {
  const { data: missions, isLoading } = useMissions()
  const { data: checkpoints } = useCheckpoints()
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const active = missions?.filter((m) => m.status === "active") ?? []
  const others = missions?.filter((m) => m.status !== "active") ?? []

  if (isLoading) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold tracking-tight">Missions</h1>
        {[1, 2].map((i) => (
          <Card key={i}>
            <CardContent className="py-6">
              <div className="h-5 w-48 bg-muted rounded animate-pulse mb-2" />
              <div className="h-4 w-full bg-muted rounded animate-pulse" />
            </CardContent>
          </Card>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Missions</h1>
        <p className="text-muted-foreground text-sm">
          {active.length} active, {missions?.length ?? 0} total
        </p>
      </div>

      {/* Active Missions */}
      {active.map((mission) => (
        <MissionCard
          key={mission.id}
          mission={mission}
          checkpoints={checkpoints?.filter((c) => c.mission_id === mission.id) ?? []}
          expanded
          variant="active"
        />
      ))}

      {/* Historical Missions */}
      {others.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">History</h2>
          <div className="space-y-2">
            {others.map((mission) => (
              <MissionCard
                key={mission.id}
                mission={mission}
                checkpoints={checkpoints?.filter((c) => c.mission_id === mission.id) ?? []}
                expanded={expandedId === mission.id}
                onToggle={() => setExpandedId(expandedId === mission.id ? null : mission.id)}
                variant="history"
              />
            ))}
          </div>
        </div>
      )}

      {missions?.length === 0 && (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            No missions yet
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function MissionCard({
  mission,
  checkpoints,
  expanded,
  onToggle,
  variant,
}: {
  mission: Mission
  checkpoints: Checkpoint[]
  expanded: boolean
  onToggle?: () => void
  variant: "active" | "history"
}) {
  const tasks = mission.tasks ?? []
  const done = tasks.filter((t) => t.status === "complete").length
  const isClickable = variant === "history"

  return (
    <Card
      className={`${variant === "active" ? "border-green-200" : ""} ${isClickable ? "cursor-pointer transition-colors hover:bg-muted/50" : ""} ${expanded && variant === "history" ? "ring-1 ring-primary/20" : ""}`}
      onClick={isClickable ? onToggle : undefined}
    >
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            {variant === "active" && <Rocket className="h-4 w-4 text-green-600" />}
            <span className={variant === "history" && !expanded ? "truncate max-w-[500px]" : ""}>
              {mission.objective}
            </span>
          </CardTitle>
          <div className="flex items-center gap-2 shrink-0">
            <StatusBadge status={mission.status} />
            {isClickable && (
              expanded
                ? <ChevronUp className="h-4 w-4 text-muted-foreground" />
                : <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>{mission.phase}</span>
          <span>·</span>
          <span>{done}/{tasks.length} tasks</span>
          {mission.created_at && (
            <>
              <span>·</span>
              <span>Created {formatDate(mission.created_at)}</span>
            </>
          )}
          {mission.completed_at && (
            <>
              <span>·</span>
              <span>Completed {formatDate(mission.completed_at)}</span>
            </>
          )}
        </div>
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-4 pt-0">
          {/* Context */}
          {mission.context && (
            <div className="rounded-md border bg-muted/20 p-3">
              <h4 className="text-xs font-semibold mb-1 text-muted-foreground uppercase tracking-wide">Context</h4>
              <div className="text-muted-foreground">
                <Markdown>{mission.context}</Markdown>
              </div>
            </div>
          )}

          {/* Task Progress */}
          {tasks.length > 0 && (
            <div className="space-y-2">
              <div className="h-2 w-full rounded-full bg-secondary">
                <div
                  className="h-2 rounded-full bg-green-500 transition-all"
                  style={{ width: `${tasks.length > 0 ? (done / tasks.length) * 100 : 0}%` }}
                />
              </div>
              <div className="space-y-1">
                {tasks.map((task, i) => {
                  const Icon = taskIcons[task.status ?? "pending"] ?? Circle
                  return (
                    <div key={i} className="flex items-start gap-2 text-sm">
                      <Icon
                        className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${
                          task.status === "complete"
                            ? "text-green-500"
                            : task.status === "blocked"
                              ? "text-red-500"
                              : task.status === "in_progress"
                                ? "text-blue-500"
                                : "text-muted-foreground"
                        }`}
                      />
                      <span className={task.status === "complete" ? "line-through text-muted-foreground" : ""}>
                        {task.description}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Acceptance Criteria */}
          {mission.acceptance_criteria && (
            <div>
              <h4 className="text-xs font-semibold mb-1 text-muted-foreground uppercase tracking-wide">Acceptance Criteria</h4>
              <p className="text-sm text-muted-foreground">{mission.acceptance_criteria}</p>
            </div>
          )}

          {/* Checkpoints */}
          {checkpoints.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold mb-2 flex items-center gap-1">
                <AlertTriangle className="h-3.5 w-3.5" />
                Checkpoints
              </h4>
              <div className="space-y-1">
                {checkpoints.map((chk) => (
                  <div key={chk.id} className="flex items-center gap-2 text-sm p-2 rounded border">
                    <StatusBadge status={chk.status} />
                    <span className="truncate">{chk.description}</span>
                    {chk.blocking && (
                      <Badge variant="destructive" className="text-[10px] ml-auto shrink-0">
                        blocking
                      </Badge>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Report */}
          {mission.report && (
            <div className="rounded-md border bg-muted/30 p-3">
              <h4 className="text-sm font-semibold mb-2">Mission Report</h4>
              {mission.report.findings && mission.report.findings.length > 0 && (
                <div className="mb-2">
                  <span className="text-xs font-medium">Findings:</span>
                  <ul className="text-xs text-muted-foreground list-disc pl-4">
                    {mission.report.findings.map((f, i) => (
                      <li key={i}>{f}</li>
                    ))}
                  </ul>
                </div>
              )}
              {mission.report.recommended_next && (
                <p className="text-xs text-muted-foreground">
                  <span className="font-medium">Next: </span>
                  {mission.report.recommended_next}
                </p>
              )}
            </div>
          )}

          <TagList tags={mission.tags} />

          {/* Mission ID */}
          <p className="text-xs text-muted-foreground font-mono">{mission.id}</p>
        </CardContent>
      )}
    </Card>
  )
}
