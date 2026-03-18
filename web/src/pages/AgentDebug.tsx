import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import { useActiveProjectId } from "@/hooks/useProjectSelection"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { AgentRole, RoleEvent } from "@/api/types"

const statusColors: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  processing: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  acked: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  expired: "bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200",
}

export default function AgentDebug() {
  const projectId = useActiveProjectId()
  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null)

  const { data: roles, isLoading: rolesLoading } = useQuery({
    queryKey: ["agent-roles", projectId],
    queryFn: () => api.listAgentRoles(100),
  })

  const { data: events } = useQuery({
    queryKey: ["role-events", projectId, selectedRoleId],
    queryFn: () => api.listRoleEvents(selectedRoleId!, undefined, 50),
    enabled: !!selectedRoleId,
  })

  if (rolesLoading) {
    return (
      <div className="space-y-4 p-6">
        <h1 className="text-2xl font-bold">Agent Debug</h1>
        <div className="animate-pulse space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 rounded bg-muted" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-2xl font-bold">Agent Debug</h1>

      {/* Roles list */}
      <section>
        <h2 className="mb-3 text-lg font-semibold">Registered Roles ({roles?.length ?? 0})</h2>
        {!roles?.length ? (
          <p className="text-sm text-muted-foreground">No roles registered yet.</p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {roles.map((role: AgentRole) => (
              <Card
                key={role.id}
                className={`cursor-pointer transition-colors ${selectedRoleId === role.id ? "ring-2 ring-primary" : "hover:bg-muted/50"}`}
                onClick={() => setSelectedRoleId(role.id === selectedRoleId ? null : role.id)}
              >
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium">{role.name}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-1 text-xs text-muted-foreground">
                  {role.description && <p className="truncate">{role.description}</p>}
                  <div className="flex flex-wrap gap-1">
                    {role.model && <Badge variant="outline">{role.model}</Badge>}
                    {role.model_tier && <Badge variant="outline">tier: {role.model_tier}</Badge>}
                  </div>
                  <div className="flex justify-between pt-1">
                    <span>Subs: {role.subscriptions.length}</span>
                    <span>Last: {role.last_active_at ? new Date(role.last_active_at).toLocaleDateString() : "never"}</span>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      {/* Events for selected role */}
      {selectedRoleId && (
        <section>
          <h2 className="mb-3 text-lg font-semibold">
            Recent Events for {roles?.find((r) => r.id === selectedRoleId)?.name ?? selectedRoleId}
          </h2>
          {!events?.length ? (
            <p className="text-sm text-muted-foreground">No events.</p>
          ) : (
            <div className="space-y-2">
              {events.map((evt: RoleEvent) => (
                <div
                  key={evt.id}
                  className="flex items-center gap-3 rounded-md border px-4 py-2 text-sm"
                >
                  <Badge className={statusColors[evt.status] ?? ""}>{evt.status}</Badge>
                  <span className="font-mono text-xs">{evt.event_type}</span>
                  <span className="text-xs text-muted-foreground">pri={evt.priority}</span>
                  {evt.source_entity_type && (
                    <span className="text-xs text-muted-foreground">
                      {evt.source_entity_type}/{evt.source_entity_id?.slice(0, 12)}
                    </span>
                  )}
                  <span className="ml-auto text-xs text-muted-foreground">
                    {evt.created_at ? new Date(evt.created_at).toLocaleString() : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
