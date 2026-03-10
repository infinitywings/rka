import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { AuditEntry } from "@/api/types"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const ACTION_COLORS: Record<string, string> = {
  create: "bg-green-100 text-green-800",
  update: "bg-blue-100 text-blue-800",
  delete: "bg-red-100 text-red-800",
  resolve: "bg-teal-100 text-teal-800",
  abandon: "bg-orange-100 text-orange-800",
  submit_report: "bg-purple-100 text-purple-800",
  enrich: "bg-cyan-100 text-cyan-800",
  import: "bg-indigo-100 text-indigo-800",
}

function formatTime(ts: string | null): string {
  if (!ts) return "—"
  const d = new Date(ts)
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
}

function getActionColor(action: string): string {
  for (const [key, color] of Object.entries(ACTION_COLORS)) {
    if (action.includes(key)) return color
  }
  return "bg-gray-100 text-gray-800"
}

export default function AuditLog() {
  const [actionFilter, setActionFilter] = useState<string>("all")
  const [entityFilter, setEntityFilter] = useState<string>("all")
  const [actorFilter, setActorFilter] = useState<string>("all")

  const { data: entries = [], isLoading } = useQuery({
    queryKey: ["audit", { limit: 200, action: actionFilter, entity_type: entityFilter, actor: actorFilter }],
    queryFn: () =>
      api.listAudit({
        limit: 200,
        action: actionFilter !== "all" ? actionFilter : undefined,
        entity_type: entityFilter !== "all" ? entityFilter : undefined,
        actor: actorFilter !== "all" ? actorFilter : undefined,
      }),
  })

  const { data: counts = {} } = useQuery({
    queryKey: ["audit-counts"],
    queryFn: () => api.auditCounts(),
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Audit Log</h1>
          <p className="text-sm text-muted-foreground">
            System audit trail — {entries.length} entries
          </p>
        </div>
        <div className="flex gap-2">
          <Select value={actionFilter} onValueChange={(v) => setActionFilter(v ?? "all")}>
            <SelectTrigger className="w-[150px]">
              <SelectValue placeholder="Action" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All actions</SelectItem>
              <SelectItem value="create">Create</SelectItem>
              <SelectItem value="update">Update</SelectItem>
              <SelectItem value="delete">Delete</SelectItem>
              <SelectItem value="resolve">Resolve</SelectItem>
              <SelectItem value="submit_report">Report</SelectItem>
            </SelectContent>
          </Select>
          <Select value={entityFilter} onValueChange={(v) => setEntityFilter(v ?? "all")}>
            <SelectTrigger className="w-[150px]">
              <SelectValue placeholder="Entity" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All entities</SelectItem>
              <SelectItem value="note">Notes</SelectItem>
              <SelectItem value="decision">Decisions</SelectItem>
              <SelectItem value="literature">Literature</SelectItem>
              <SelectItem value="mission">Missions</SelectItem>
              <SelectItem value="checkpoint">Checkpoints</SelectItem>
            </SelectContent>
          </Select>
          <Select value={actorFilter} onValueChange={(v) => setActorFilter(v ?? "all")}>
            <SelectTrigger className="w-[130px]">
              <SelectValue placeholder="Actor" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All actors</SelectItem>
              <SelectItem value="brain">Brain</SelectItem>
              <SelectItem value="executor">Executor</SelectItem>
              <SelectItem value="pi">PI</SelectItem>
              <SelectItem value="web_ui">Web UI</SelectItem>
              <SelectItem value="system">System</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Counts summary */}
      {Object.keys(counts).length > 0 && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(counts).map(([action, count]) => (
            <Badge key={action} variant="secondary" className="text-xs">
              {action}: {count}
            </Badge>
          ))}
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-12 rounded bg-muted animate-pulse" />
          ))}
        </div>
      ) : entries.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            No audit entries recorded yet. All entity changes are logged here.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[180px]">Time</TableHead>
                <TableHead className="w-[120px]">Action</TableHead>
                <TableHead className="w-[100px]">Entity</TableHead>
                <TableHead className="w-[200px]">Entity ID</TableHead>
                <TableHead className="w-[80px]">Actor</TableHead>
                <TableHead>Details</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((entry: AuditEntry) => (
                <TableRow key={entry.id}>
                  <TableCell className="text-xs text-muted-foreground font-mono">
                    {formatTime(entry.created_at)}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={getActionColor(entry.action)}>
                      {entry.action}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="text-xs">
                      {entry.entity_type}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs font-mono truncate max-w-[200px]">
                    {entry.entity_id ?? "—"}
                  </TableCell>
                  <TableCell className="text-xs">
                    {entry.actor ?? "—"}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground max-w-[300px] truncate">
                    {entry.details ? JSON.stringify(entry.details) : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  )
}
