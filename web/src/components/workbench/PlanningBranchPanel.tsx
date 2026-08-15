import { useMemo, useState } from "react"
import type { FormEvent } from "react"
import {
  Archive,
  CheckCircle2,
  GitBranch,
  GitCompareArrows,
  Loader2,
  ParkingCircle,
  Plus,
  RotateCcw,
} from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { usePlanningBranches, usePlanningComparison } from "@/hooks/usePlanningBranches"
import type { PlanningBranch, PlanningBranchState } from "@/api/types"

export function PlanningBranchPanel({ manuscriptId }: { manuscriptId: string | null }) {
  const planning = usePlanningBranches(manuscriptId)
  const branches = useMemo(() => planning.branches.data ?? [], [planning.branches.data])
  const resumed = planning.resume.data
  const selected = resumed?.branch ?? branches.find((branch) => branch.state === "selected") ?? null
  const [showCreate, setShowCreate] = useState(false)
  const [forkSelected, setForkSelected] = useState(true)
  const alternatives = useMemo(
    () => branches.filter((branch) => branch.id !== selected?.id),
    [branches, selected?.id],
  )
  const [compareId, setCompareId] = useState<string>("")
  const validCompareId = alternatives.some((branch) => branch.id === compareId)
    ? compareId
    : ""

  const comparison = usePlanningComparison(manuscriptId, selected?.id ?? null, validCompareId || null)

  const createBranch = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    const name = String(form.get("name") ?? "").trim()
    const purpose = String(form.get("purpose") ?? "").trim()
    if (!name || !purpose) return
    try {
      await planning.create.mutateAsync({
        ...(manuscriptId ? { manuscript_id: manuscriptId } : {}),
        ...(forkSelected && selected ? { parent_branch_id: selected.id } : {}),
        name,
        purpose,
        created_by: "web_ui",
        reason: forkSelected && selected
          ? `Fork ${selected.name} for a recoverable alternative.`
          : "Create a recoverable planning branch.",
      })
      formElement.reset()
      setShowCreate(false)
      toast.success(`Planning branch ${name} created`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Planning branch creation failed")
    }
  }

  const transition = async (
    branch: PlanningBranch,
    targetState: PlanningBranchState,
  ) => {
    try {
      await planning.transition.mutateAsync({
        branchId: branch.id,
        data: {
          expected_revision: branch.revision,
          target_state: targetState,
          actor: "web_ui",
          reason: targetState === "selected"
            ? `Select ${branch.name} as the resumable planning branch.`
            : targetState === "archived"
              ? `Archive ${branch.name} without deleting its history.`
              : `Reactivate ${branch.name} as a planning alternative.`,
        },
      })
      toast.success(`${branch.name} is now ${targetState}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Planning branch update failed")
    }
  }

  const isLoading = planning.branches.isLoading || planning.resume.isLoading
  const error = planning.branches.error ?? planning.resume.error

  return (
    <Card>
      <CardHeader className="gap-3 pb-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <GitBranch className="h-4 w-4" /> Planning branches
            </CardTitle>
            <Badge variant="outline">provisional</Badge>
            {selected && <Badge>{selected.name}</Badge>}
          </div>
          <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
            Recoverable argument alternatives. These versions can cite RKA records, but they do not ratify claims,
            promote evidence, or edit manuscript files.
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={() => setShowCreate((value) => !value)}>
          <Plus className="mr-1 h-4 w-4" /> {showCreate ? "Cancel" : "New branch"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <p role="alert" className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100">
            {error.message}
          </p>
        )}
        {isLoading && (
          <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Restoring the selected planning branch…
          </div>
        )}

        {showCreate && (
          <form onSubmit={createBranch} className="grid gap-3 rounded-lg border bg-muted/20 p-3 lg:grid-cols-[13rem_minmax(0,1fr)_auto]">
            <label className="space-y-1 text-xs font-medium">
              Branch name
              <Input name="name" required maxLength={500} placeholder="reviewer-resilient" />
            </label>
            <label className="space-y-1 text-xs font-medium">
              Purpose
              <Textarea name="purpose" required maxLength={20000} rows={2} placeholder="What alternative should this branch preserve?" />
            </label>
            <div className="flex flex-col justify-end gap-2">
              {selected && (
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={forkSelected}
                    onChange={(event) => setForkSelected(event.target.checked)}
                  />
                  Fork selected r{selected.revision}
                </label>
              )}
              <Button type="submit" size="sm" disabled={planning.create.isPending}>
                {planning.create.isPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
                Create
              </Button>
            </div>
          </form>
        )}

        {!isLoading && branches.length === 0 && (
          <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            No planning branch exists for this {manuscriptId ? "manuscript" : "project"}. Create one to persist a
            seed, alternatives, and later-stage planning artifacts without changing canonical evidence.
          </div>
        )}

        {branches.length > 0 && (
          <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
            {branches.map((branch) => (
              <div key={branch.id} className="rounded-lg border p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{branch.name}</p>
                    <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{branch.purpose}</p>
                  </div>
                  <Badge variant={branch.state === "selected" ? "default" : "outline"}>{branch.state}</Badge>
                </div>
                <div className="mt-2 flex flex-wrap gap-1 text-[11px] text-muted-foreground">
                  <span>revision {branch.revision}</span>
                  {branch.parent_branch_id && (
                    <span>· fork frozen at parent r{branch.parent_branch_revision}</span>
                  )}
                  {branch.base_manuscript_revision && (
                    <span>· manuscript base r{branch.base_manuscript_revision}</span>
                  )}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {branch.state !== "selected" && branch.state !== "superseded" && (
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={planning.transition.isPending}
                      onClick={() => void transition(branch, "selected")}
                    >
                      <CheckCircle2 className="mr-1 h-3.5 w-3.5" /> Select
                    </Button>
                  )}
                  {branch.state === "active" && (
                    <Button
                      size="xs"
                      variant="ghost"
                      disabled={planning.transition.isPending}
                      onClick={() => void transition(branch, "archived")}
                    >
                      <Archive className="mr-1 h-3.5 w-3.5" /> Archive
                    </Button>
                  )}
                  {branch.state === "archived" && (
                    <Button
                      size="xs"
                      variant="ghost"
                      disabled={planning.transition.isPending}
                      onClick={() => void transition(branch, "active")}
                    >
                      <RotateCcw className="mr-1 h-3.5 w-3.5" /> Reactivate
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {selected && (
          <div className="grid gap-3 border-t pt-4 lg:grid-cols-2">
            <div className="space-y-2 rounded-lg border p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium">Selected branch head</p>
                <Badge variant="outline">{resumed?.effective_artifacts.length ?? 0} artifacts</Badge>
              </div>
              {resumed?.effective_artifacts.length ? (
                <div className="space-y-2">
                  {resumed.effective_artifacts.map((artifact) => (
                    <div key={`${artifact.stage_type}:${artifact.local_key}`} className="rounded-md bg-muted/40 p-2 text-xs">
                      <div className="flex flex-wrap items-center gap-1">
                        <span className="font-medium">{artifact.stage_type.replaceAll("_", " ")}</span>
                        <span>· {artifact.local_key}</span>
                        <Badge variant="outline">{artifact.version.lifecycle}</Badge>
                        {artifact.is_inherited && <Badge variant="secondary">inherited</Badge>}
                      </div>
                      <p className="mt-1 text-muted-foreground">{artifact.version.summary}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">No stage artifacts have been captured on this branch yet.</p>
              )}
              {resumed?.parking_lot.length ? (
                <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
                  <ParkingCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{resumed.parking_lot.length} recoverable parked alternative{resumed.parking_lot.length === 1 ? "" : "s"}.</span>
                </div>
              ) : null}
            </div>

            <div className="space-y-3 rounded-lg border p-3">
              <p className="flex items-center gap-2 text-sm font-medium">
                <GitCompareArrows className="h-4 w-4" /> Compare with selected
              </p>
              {alternatives.length ? (
                <>
                  <label className="space-y-1 text-xs font-medium">
                    Alternative branch
                    <select
                      className="h-8 w-full rounded-lg border border-input bg-background px-2 text-sm"
                      value={validCompareId}
                      onChange={(event) => setCompareId(event.target.value)}
                    >
                      <option value="">Choose a branch…</option>
                      {alternatives.map((branch) => (
                        <option key={branch.id} value={branch.id}>{branch.name} ({branch.state})</option>
                      ))}
                    </select>
                  </label>
                  {comparison.isLoading && <p className="text-xs text-muted-foreground">Comparing frozen branch views…</p>}
                  {comparison.error && <p role="alert" className="text-xs text-red-700">{comparison.error.message}</p>}
                  {comparison.data && (
                    <div className="grid grid-cols-4 gap-2 text-center text-xs">
                      {(["added", "removed", "changed", "unchanged"] as const).map((status) => (
                        <div key={status} className="rounded-md bg-muted/50 p-2">
                          <p className="text-base font-semibold">{comparison.data.summary[status]}</p>
                          <p className="text-muted-foreground">{status}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <p className="text-xs text-muted-foreground">Create or reactivate an alternative to compare framing without overwriting this branch.</p>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
