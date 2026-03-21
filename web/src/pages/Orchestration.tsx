import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import { useActiveProjectId } from "@/hooks/useProjectSelection"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { toast } from "sonner"
import type {
  OrchestrationStatus,
  OrchestrationRoleStatus,
  AutonomyMode,
  RoleCostSummary,
} from "@/api/types"

const autonomyColors: Record<AutonomyMode, string> = {
  manual: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200",
  supervised: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  autonomous: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  paused: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
}

export default function Orchestration() {
  const projectId = useActiveProjectId()
  const queryClient = useQueryClient()
  const [overrideOpen, setOverrideOpen] = useState(false)
  const [overrideDirective, setOverrideDirective] = useState("")
  const [overrideTarget, setOverrideTarget] = useState<string>("")
  const [overrideHalt, setOverrideHalt] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [costLimit, setCostLimit] = useState("")
  const [windowHours, setWindowHours] = useState("")

  const { data: status, isLoading } = useQuery({
    queryKey: ["orchestration-status", projectId],
    queryFn: () => api.getOrchestrationStatus(),
    refetchInterval: 10_000,
  })

  const setModeMutation = useMutation({
    mutationFn: (mode: string) => api.setAutonomyMode(mode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["orchestration-status"] })
      toast.success("Autonomy mode updated")
    },
    onError: (e) => toast.error(`Failed: ${e.message}`),
  })

  const resetBreakerMutation = useMutation({
    mutationFn: () => api.resetCircuitBreaker(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["orchestration-status"] })
      toast.success("Circuit breaker reset")
    },
    onError: (e) => toast.error(`Failed: ${e.message}`),
  })

  const overrideMutation = useMutation({
    mutationFn: () =>
      api.piOverride({
        directive: overrideDirective,
        target_role_name: overrideTarget || undefined,
        halt_current: overrideHalt,
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["orchestration-status"] })
      setOverrideOpen(false)
      setOverrideDirective("")
      setOverrideTarget("")
      setOverrideHalt(false)
      toast.success(`Override sent to ${data.events_created} role(s)`)
    },
    onError: (e) => toast.error(`Failed: ${e.message}`),
  })

  const retryMutation = useMutation({
    mutationFn: (eventId: string) => api.retryStuckEvent(eventId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["orchestration-status"] })
      toast.success("Event retried")
    },
    onError: (e) => toast.error(`Failed: ${e.message}`),
  })

  const updateConfigMutation = useMutation({
    mutationFn: (data: { cost_limit_usd?: number; cost_window_hours?: number }) =>
      api.updateOrchestrationConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["orchestration-status"] })
      setSettingsOpen(false)
      toast.success("Settings updated")
    },
    onError: (e) => toast.error(`Failed: ${e.message}`),
  })

  if (isLoading || !status) {
    return (
      <div className="space-y-4 p-6">
        <h1 className="text-2xl font-bold">Orchestration</h1>
        <div className="animate-pulse space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 rounded bg-muted" />
          ))}
        </div>
      </div>
    )
  }

  const cfg = status.config
  const roles = status.roles as OrchestrationRoleStatus[]
  const costByRole = status.cost_by_role as RoleCostSummary[]
  const stuckEvents = status.stuck_events as Array<Record<string, unknown>>
  const recentOverrides = status.recent_overrides as Array<Record<string, unknown>>

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Orchestration</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => {
            setCostLimit(String(cfg.cost_limit_usd))
            setWindowHours(String(cfg.cost_window_hours))
            setSettingsOpen(true)
          }}>
            Settings
          </Button>
          <Button size="sm" onClick={() => setOverrideOpen(true)}>
            PI Override
          </Button>
        </div>
      </div>

      {/* Top status cards */}
      <div className="grid gap-4 md:grid-cols-4">
        {/* Autonomy Mode */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Autonomy Mode</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <Badge className={`text-sm ${autonomyColors[cfg.autonomy_mode]}`}>
                {cfg.autonomy_mode.toUpperCase()}
              </Badge>
              <Select
                value={cfg.autonomy_mode}
                onValueChange={(v) => setModeMutation.mutate(v)}
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="manual">Manual</SelectItem>
                  <SelectItem value="supervised">Supervised</SelectItem>
                  <SelectItem value="autonomous">Autonomous</SelectItem>
                  <SelectItem value="paused">Paused</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* Circuit Breaker */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Circuit Breaker</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <Badge className={cfg.circuit_breaker_tripped
                ? "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200 text-sm"
                : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200 text-sm"
              }>
                {cfg.circuit_breaker_tripped ? "TRIPPED" : "OK"}
              </Badge>
              <p className="text-xs text-muted-foreground">
                Limit: ${cfg.cost_limit_usd.toFixed(2)} / {cfg.cost_window_hours}h
              </p>
              {cfg.circuit_breaker_tripped && (
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => resetBreakerMutation.mutate()}
                  disabled={resetBreakerMutation.isPending}
                >
                  Reset
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Cost Window */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Cost (Window)</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">
              ${status.cost_summary.total_cost_usd.toFixed(4)}
            </p>
            <p className="text-xs text-muted-foreground">
              {status.cost_summary.total_input_tokens.toLocaleString()} in /{" "}
              {status.cost_summary.total_output_tokens.toLocaleString()} out
            </p>
            <p className="text-xs text-muted-foreground">
              {status.cost_summary.entry_count} entries
            </p>
          </CardContent>
        </Card>

        {/* Stuck Events */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Stuck Events</CardTitle>
          </CardHeader>
          <CardContent>
            <p className={`text-2xl font-bold ${stuckEvents.length > 0 ? "text-amber-600" : ""}`}>
              {stuckEvents.length}
            </p>
            <p className="text-xs text-muted-foreground">
              events needing attention
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Roles with queue depth */}
      <section>
        <h2 className="mb-3 text-lg font-semibold">Roles ({roles.length})</h2>
        {!roles.length ? (
          <p className="text-sm text-muted-foreground">No roles registered.</p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {roles.map((role) => (
              <Card key={role.id}>
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center justify-between text-sm font-medium">
                    <span>{role.name}</span>
                    <Badge variant={role.active_session_id ? "default" : "outline"} className="text-xs">
                      {role.active_session_id ? "active" : "idle"}
                    </Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-1 text-xs text-muted-foreground">
                  {role.description && <p className="truncate">{role.description}</p>}
                  <div className="flex gap-3 pt-1">
                    <span>Pending: <span className="font-medium text-foreground">{role.pending_events}</span></span>
                    <span>Processing: <span className="font-medium text-foreground">{role.processing_events}</span></span>
                  </div>
                  <div className="flex flex-wrap gap-1 pt-1">
                    {role.model && <Badge variant="outline">{role.model}</Badge>}
                    {role.model_tier && <Badge variant="outline">tier: {role.model_tier}</Badge>}
                  </div>
                  <div className="pt-1">
                    Last active: {role.last_active_at ? new Date(role.last_active_at).toLocaleString() : "never"}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      {/* Cost by Role */}
      {costByRole.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-semibold">Cost by Role</h2>
          <div className="rounded-md border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="px-4 py-2 text-left font-medium">Role</th>
                  <th className="px-4 py-2 text-right font-medium">Input Tokens</th>
                  <th className="px-4 py-2 text-right font-medium">Output Tokens</th>
                  <th className="px-4 py-2 text-right font-medium">Cost (USD)</th>
                  <th className="px-4 py-2 text-right font-medium">Entries</th>
                </tr>
              </thead>
              <tbody>
                {costByRole.map((r) => (
                  <tr key={r.role_id} className="border-b">
                    <td className="px-4 py-2">{r.role_name ?? r.role_id}</td>
                    <td className="px-4 py-2 text-right font-mono">{r.total_input_tokens.toLocaleString()}</td>
                    <td className="px-4 py-2 text-right font-mono">{r.total_output_tokens.toLocaleString()}</td>
                    <td className="px-4 py-2 text-right font-mono">${r.total_cost_usd.toFixed(4)}</td>
                    <td className="px-4 py-2 text-right">{r.entry_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Stuck Events */}
      {stuckEvents.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-semibold">Stuck Events ({stuckEvents.length})</h2>
          <div className="space-y-2">
            {stuckEvents.map((evt) => (
              <div
                key={String(evt.id)}
                className="flex items-center gap-3 rounded-md border px-4 py-2 text-sm"
              >
                <Badge variant="outline">{String(evt.status)}</Badge>
                <span className="font-mono text-xs">{String(evt.event_type)}</span>
                <span className="text-xs text-muted-foreground">
                  role: {String(evt.role_name ?? evt.target_role_id)}
                </span>
                <span className="text-xs text-muted-foreground">
                  created: {evt.created_at ? new Date(String(evt.created_at)).toLocaleString() : "?"}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  className="ml-auto"
                  onClick={() => retryMutation.mutate(String(evt.id))}
                  disabled={retryMutation.isPending}
                >
                  Retry
                </Button>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Recent Overrides */}
      {recentOverrides.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-semibold">Recent PI Overrides</h2>
          <div className="space-y-2">
            {recentOverrides.map((o) => {
              let payload = o.payload
              if (typeof payload === "string") {
                try { payload = JSON.parse(payload) } catch { /* keep string */ }
              }
              const directive = (payload as Record<string, unknown>)?.directive ?? "?"
              return (
                <div
                  key={String(o.id)}
                  className="rounded-md border px-4 py-2 text-sm"
                >
                  <div className="flex items-center gap-2">
                    <Badge className="bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200">
                      PI Override
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {String(o.target_role_name ?? o.target_role_id ?? "broadcast")}
                    </span>
                    <span className="ml-auto text-xs text-muted-foreground">
                      {o.created_at ? new Date(String(o.created_at)).toLocaleString() : ""}
                    </span>
                  </div>
                  <p className="mt-1 text-xs">{String(directive).slice(0, 200)}</p>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* PI Override Dialog */}
      <Dialog open={overrideOpen} onOpenChange={setOverrideOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>PI Override</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>Target Role (leave empty for broadcast)</Label>
              <Select value={overrideTarget} onValueChange={setOverrideTarget}>
                <SelectTrigger>
                  <SelectValue placeholder="All roles (broadcast)" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All roles</SelectItem>
                  {roles.map((r) => (
                    <SelectItem key={r.id} value={r.name}>{r.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Directive</Label>
              <Textarea
                placeholder="Enter the PI directive to inject..."
                rows={4}
                value={overrideDirective}
                onChange={(e) => setOverrideDirective(e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="halt-current"
                checked={overrideHalt}
                onChange={(e) => setOverrideHalt(e.target.checked)}
              />
              <Label htmlFor="halt-current" className="text-sm">
                Halt current work (expire pending/processing events)
              </Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOverrideOpen(false)}>Cancel</Button>
            <Button
              onClick={() => overrideMutation.mutate()}
              disabled={!overrideDirective.trim() || overrideMutation.isPending}
            >
              {overrideMutation.isPending ? "Sending..." : "Send Override"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Settings Dialog */}
      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Orchestration Settings</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>Cost Limit (USD)</Label>
              <Input
                type="number"
                step="0.01"
                value={costLimit}
                onChange={(e) => setCostLimit(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Cost Window (hours)</Label>
              <Input
                type="number"
                step="1"
                value={windowHours}
                onChange={(e) => setWindowHours(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSettingsOpen(false)}>Cancel</Button>
            <Button
              onClick={() =>
                updateConfigMutation.mutate({
                  cost_limit_usd: parseFloat(costLimit) || undefined,
                  cost_window_hours: parseInt(windowHours) || undefined,
                })
              }
              disabled={updateConfigMutation.isPending}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
