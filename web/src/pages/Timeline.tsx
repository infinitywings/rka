import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { Event } from "@/api/types"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { ChevronDown, ChevronUp } from "lucide-react"

const EVENT_TYPE_COLORS: Record<string, string> = {
  decision_created: "bg-blue-100 text-blue-800",
  decision_updated: "bg-blue-50 text-blue-700",
  decision_abandoned: "bg-red-100 text-red-800",
  mission_created: "bg-purple-100 text-purple-800",
  mission_completed: "bg-green-100 text-green-800",
  mission_blocked: "bg-orange-100 text-orange-800",
  finding_recorded: "bg-emerald-100 text-emerald-800",
  insight_recorded: "bg-cyan-100 text-cyan-800",
  pi_instruction: "bg-yellow-100 text-yellow-800",
  checkpoint_created: "bg-amber-100 text-amber-800",
  checkpoint_resolved: "bg-teal-100 text-teal-800",
  literature_added: "bg-indigo-100 text-indigo-800",
  literature_cited: "bg-indigo-50 text-indigo-700",
  phase_changed: "bg-pink-100 text-pink-800",
  status_updated: "bg-gray-100 text-gray-800",
}

const ACTOR_ICONS: Record<string, string> = {
  brain: "🧠",
  executor: "⚡",
  pi: "👤",
  llm: "🤖",
  web_ui: "🌐",
  system: "⚙️",
}

function formatTime(ts: string | null): string {
  if (!ts) return ""
  const d = new Date(ts)
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function formatDate(ts: string | null): string {
  if (!ts) return ""
  const d = new Date(ts)
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  })
}

function groupByDate(events: Event[]): Map<string, Event[]> {
  const groups = new Map<string, Event[]>()
  for (const ev of events) {
    const dateKey = ev.timestamp?.substring(0, 10) ?? "unknown"
    if (!groups.has(dateKey)) groups.set(dateKey, [])
    groups.get(dateKey)!.push(ev)
  }
  return groups
}

export default function Timeline() {
  const [entityFilter, setEntityFilter] = useState<string>("all")
  const [actorFilter, setActorFilter] = useState<string>("all")

  const { data: events = [], isLoading } = useQuery({
    queryKey: ["events", { limit: 200 }],
    queryFn: () => api.listEvents({ limit: 200 }),
  })

  const filtered = events.filter((ev) => {
    if (entityFilter !== "all" && ev.entity_type !== entityFilter) return false
    if (actorFilter !== "all" && ev.actor !== actorFilter) return false
    return true
  })

  const grouped = groupByDate(filtered)

  // Compute causal chains: find events that are caused_by another event
  const causalMap = new Map<string, string[]>()
  for (const ev of events) {
    if (ev.caused_by_event) {
      if (!causalMap.has(ev.caused_by_event)) causalMap.set(ev.caused_by_event, [])
      causalMap.get(ev.caused_by_event)!.push(ev.id)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Timeline</h1>
          <p className="text-sm text-muted-foreground">
            Event stream with causal chains — {events.length} events
          </p>
        </div>
        <div className="flex gap-2">
          <Select value={entityFilter} onValueChange={(v) => setEntityFilter(v ?? "all")}>
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="Entity type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All entities</SelectItem>
              <SelectItem value="decision">Decisions</SelectItem>
              <SelectItem value="mission">Missions</SelectItem>
              <SelectItem value="journal">Journal</SelectItem>
              <SelectItem value="literature">Literature</SelectItem>
              <SelectItem value="checkpoint">Checkpoints</SelectItem>
            </SelectContent>
          </Select>
          <Select value={actorFilter} onValueChange={(v) => setActorFilter(v ?? "all")}>
            <SelectTrigger className="w-[140px]">
              <SelectValue placeholder="Actor" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All actors</SelectItem>
              <SelectItem value="brain">Brain</SelectItem>
              <SelectItem value="executor">Executor</SelectItem>
              <SelectItem value="pi">PI</SelectItem>
              <SelectItem value="system">System</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 rounded-lg bg-muted animate-pulse" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            No events recorded yet. Events are emitted when entities are created or modified.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {Array.from(grouped.entries()).map(([dateKey, dayEvents]) => (
            <div key={dateKey}>
              <h2 className="text-sm font-semibold text-muted-foreground mb-3 sticky top-0 bg-background py-1">
                {formatDate(dateKey + "T00:00:00Z")}
              </h2>
              <div className="relative ml-4 border-l-2 border-muted space-y-3 pl-6">
                {dayEvents.map((ev) => (
                  <TimelineCard key={ev.id} event={ev} causalMap={causalMap} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function TimelineCard({ event: ev, causalMap }: { event: Event; causalMap: Map<string, string[]> }) {
  const [expanded, setExpanded] = useState(false)
  const colorClass = EVENT_TYPE_COLORS[ev.event_type] ?? "bg-gray-100 text-gray-800"
  const actorIcon = ACTOR_ICONS[ev.actor] ?? "📌"
  const hasChildren = causalMap.has(ev.id)
  const hasCause = !!ev.caused_by_event
  const isLong = (ev.summary?.length ?? 0) > 100

  return (
    <div className="relative">
      {/* Timeline dot */}
      <div className="absolute -left-[31px] top-2 h-3 w-3 rounded-full border-2 border-background bg-primary" />

      <Card
        className={`cursor-pointer transition-colors hover:bg-muted/50 ${hasChildren ? "border-l-4 border-l-primary/30" : ""} ${expanded ? "ring-1 ring-primary/20" : ""}`}
        onClick={() => setExpanded(!expanded)}
      >
        <CardContent className="py-3 px-4">
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-lg" title={ev.actor}>
                  {actorIcon}
                </span>
                <Badge variant="outline" className={colorClass}>
                  {ev.event_type.replace(/_/g, " ")}
                </Badge>
                <Badge variant="secondary" className="text-xs">
                  {ev.entity_type}
                </Badge>
                {ev.phase && (
                  <Badge variant="outline" className="text-xs">
                    {ev.phase}
                  </Badge>
                )}
                {isLong && (
                  expanded
                    ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
                    : <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                )}
              </div>
              <p className={`mt-1 text-sm whitespace-pre-wrap ${expanded ? "" : "line-clamp-2"}`}>
                {ev.summary}
              </p>
              {expanded && (
                <>
                  {hasCause && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      ↳ Caused by: {ev.caused_by_entity || ev.caused_by_event}
                    </p>
                  )}
                  {hasChildren && (
                    <p className="mt-1 text-xs text-blue-600">
                      → Triggered {causalMap.get(ev.id)!.length} follow-up event(s)
                    </p>
                  )}
                  <p className="mt-2 text-xs text-muted-foreground font-mono">
                    {ev.entity_id}
                  </p>
                </>
              )}
            </div>
            <div className="text-xs text-muted-foreground whitespace-nowrap">
              {formatTime(ev.timestamp)}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
