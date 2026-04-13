import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { ConfidenceBadge } from "@/components/shared/ConfidenceBadge"
import { TagList } from "@/components/shared/TagList"
import {
  useExportKnowledgePack,
  useImportKnowledgePack,
  useProjects,
  useProjectStatus,
} from "@/hooks/useProject"
import { useMissions } from "@/hooks/useMissions"
import { useCheckpoints } from "@/hooks/useCheckpoints"
import { useNotes } from "@/hooks/useNotes"
import { useProjectSelection } from "@/hooks/useProjectSelection"
import { timeAgo } from "@/lib/utils"
import { toast } from "sonner"
import {
  Rocket,
  AlertTriangle,
  BookOpen,
  Target,
  Layers3,
  Download,
  Loader2,
  PackageOpen,
  Upload,
  Copy,
} from "lucide-react"

export default function Dashboard() {
  const { projectId, setProjectId } = useProjectSelection()
  const [importOpen, setImportOpen] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importProjectId, setImportProjectId] = useState("")
  const [importProjectName, setImportProjectName] = useState("")
  const { data: project, isLoading: projectLoading } = useProjectStatus()
  const { data: projects } = useProjects()
  const { data: missions } = useMissions()
  const { data: checkpoints } = useCheckpoints({ status: "open" })
  const { data: notes } = useNotes({ limit: 10 })
  const exportPack = useExportKnowledgePack()
  const importPack = useImportKnowledgePack()

  const activeMissions = missions?.filter((m) => m.status === "active") ?? []

  const resetImportForm = () => {
    setImportFile(null)
    setImportProjectId("")
    setImportProjectName("")
  }

  const handleCopyProjectId = async (id: string) => {
    try {
      await navigator.clipboard.writeText(id)
      toast.success(`Copied ${id}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Copy failed")
    }
  }

  const handleExportPack = async () => {
    try {
      const { blob, filename } = await exportPack.mutateAsync()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = filename
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
      toast.success(`Exported ${project?.project_name ?? projectId}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Export failed")
    }
  }

  const handleImportPack = async () => {
    if (!importFile) {
      toast.error("Choose a knowledge-pack zip first")
      return
    }
    try {
      const result = await importPack.mutateAsync({
        file: importFile,
        project_id: importProjectId.trim() || undefined,
        project_name: importProjectName.trim() || undefined,
      })
      setProjectId(result.project_id)
      setImportOpen(false)
      resetImportForm()
      toast.success(`Imported ${result.project_name}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Import failed")
    }
  }

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

      <Card>
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Layers3 className="h-4 w-4" />
              Projects
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Export the active project as a portable pack or import one into a new project.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleExportPack}
              disabled={exportPack.isPending}
            >
              {exportPack.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Download className="mr-2 h-4 w-4" />
              )}
              Export Active
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setImportOpen(true)}
            >
              <Upload className="mr-2 h-4 w-4" />
              Import Pack
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {!projects?.length ? (
            <p className="text-sm text-muted-foreground">No projects found</p>
          ) : (
            <div className="grid gap-2 md:grid-cols-2">
              {projects.map((item) => {
                const active = item.id === projectId
                return (
                  <div
                    key={item.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setProjectId(item.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault()
                        setProjectId(item.id)
                      }
                    }}
                    className={`cursor-pointer rounded-md border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                      active
                        ? "border-primary bg-primary/5"
                        : "hover:bg-muted/50"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">{item.name}</div>
                        <div className="mt-1 flex items-center gap-1">
                          <code className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
                            {item.id}
                          </code>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-xs"
                            className="shrink-0"
                            onClick={(event) => {
                              event.stopPropagation()
                              handleCopyProjectId(item.id)
                            }}
                            title="Copy project ID"
                          >
                            <Copy className="h-3 w-3" />
                          </Button>
                        </div>
                      </div>
                      {active && <Badge variant="default">Active</Badge>}
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground line-clamp-2">
                      {item.description || "No description"}
                    </p>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={importOpen}
        onOpenChange={(open) => {
          setImportOpen(open)
          if (!open) resetImportForm()
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <PackageOpen className="h-4 w-4" />
              Import Knowledge Pack
            </DialogTitle>
            <DialogDescription>
              Import a previously exported project pack into a new project. Leave the optional ID and name blank to reuse the metadata from the pack.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="knowledge-pack-file">Pack file</Label>
              <Input
                id="knowledge-pack-file"
                type="file"
                accept=".zip,application/zip"
                onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="import-project-id">New project ID</Label>
                <Input
                  id="import-project-id"
                  value={importProjectId}
                  onChange={(event) => setImportProjectId(event.target.value)}
                  placeholder="Reuse pack ID"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="import-project-name">New project name</Label>
                <Input
                  id="import-project-name"
                  value={importProjectName}
                  onChange={(event) => setImportProjectName(event.target.value)}
                  placeholder="Reuse pack name"
                />
              </div>
            </div>

            <p className="text-xs text-muted-foreground">
              Import creates a separate project, remaps project-scoped entity IDs, and rewrites internal references. If the target project ID or project name already exists, the import is rejected instead of merging data.
            </p>
          </div>

          <DialogFooter showCloseButton>
            <Button
              type="button"
              onClick={handleImportPack}
              disabled={importPack.isPending}
            >
              {importPack.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Upload className="mr-2 h-4 w-4" />
              )}
              Import Pack
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
