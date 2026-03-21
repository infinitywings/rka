import { useEffect, useState } from "react"
import { NavLink } from "react-router-dom"
import {
  LayoutDashboard,
  BookOpen,
  GitBranch,
  Library,
  Rocket,
  Clock,
  Share2,
  MessageSquare,
  Shield,
  Telescope,
  Map,
  Radio,
  Bot,
  Settings,
  Plus,
  Sun,
  Moon,
  Monitor,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useTheme } from "@/hooks/useTheme"
import { useProjectStatus, useProjects, useCreateProject } from "@/hooks/useProject"
import { useProjectSelection } from "@/hooks/useProjectSelection"
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
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/journal", icon: BookOpen, label: "Journal" },
  { to: "/decisions", icon: GitBranch, label: "Decisions" },
  { to: "/literature", icon: Library, label: "Literature" },
  { to: "/missions", icon: Rocket, label: "Missions" },
  { to: "/timeline", icon: Clock, label: "Timeline" },
  { to: "/graph", icon: Share2, label: "Knowledge Graph" },
  { to: "/research-map", icon: Map, label: "Research Map" },
  { to: "/notebook", icon: MessageSquare, label: "Notebook" },
  { to: "/audit", icon: Shield, label: "Audit Log" },
  { to: "/context", icon: Telescope, label: "Context" },
  { to: "/orchestration", icon: Radio, label: "Orchestration" },
  { to: "/agent-debug", icon: Bot, label: "Agent Debug" },
  { to: "/settings", icon: Settings, label: "Settings" },
]

export function Sidebar() {
  const { projectId, setProjectId } = useProjectSelection()
  const { data: project } = useProjectStatus()
  const { data: projects } = useProjects()
  const createProject = useCreateProject()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")

  useEffect(() => {
    if (!projects?.length) return
    if (!projects.some((item) => item.id === projectId)) {
      setProjectId(projects[0].id)
    }
  }, [projectId, projects, setProjectId])

  const handleCreate = () => {
    if (!name.trim()) return
    createProject.mutate(
      { name: name.trim(), description: description.trim() || undefined },
      {
        onSuccess: (newProject) => {
          setProjectId(newProject.id)
          setDialogOpen(false)
          setName("")
          setDescription("")
        },
      },
    )
  }

  return (
    <aside className="flex h-screen w-56 flex-col border-r bg-sidebar">
      {/* Logo / Project Name */}
      <div className="border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground text-xs font-bold">
            R
          </div>
          <div className="flex min-w-0 flex-col">
            <span className="max-w-[140px] truncate text-sm font-semibold">
              {project?.project_name ?? "RKA"}
            </span>
            {project?.current_phase && (
              <span className="text-[10px] text-muted-foreground truncate">
                {project.current_phase}
              </span>
            )}
          </div>
        </div>
        <div className="mt-3 flex gap-1">
          <Select value={projectId} onValueChange={setProjectId}>
            <SelectTrigger className="h-9 flex-1 text-xs">
              <SelectValue placeholder="Select project" />
            </SelectTrigger>
            <SelectContent>
              {projects?.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {item.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="icon"
            className="h-9 w-9 shrink-0"
            onClick={() => setDialogOpen(true)}
            title="New project"
          >
            <Plus className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Nav Links */}
      <nav className="flex-1 space-y-1 p-2">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground hover:bg-sidebar-accent/50",
              )
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t p-3 space-y-2">
        <ThemeToggle />
        <p className="text-[10px] text-muted-foreground text-center">
          Research Knowledge Agent
        </p>
      </div>

      {/* New Project Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>New Project</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="project-name">Project name</Label>
              <Input
                id="project-name"
                placeholder="e.g. Climate Policy Analysis"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-description">Description (optional)</Label>
              <Textarea
                id="project-description"
                placeholder="Brief description of the research project"
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={!name.trim() || createProject.isPending}
            >
              {createProject.isPending ? "Creating..." : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </aside>
  )
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const options = [
    { value: "light" as const, icon: Sun, label: "Light" },
    { value: "dark" as const, icon: Moon, label: "Dark" },
    { value: "system" as const, icon: Monitor, label: "System" },
  ]

  return (
    <div className="flex items-center justify-center gap-1 rounded-md bg-muted p-0.5">
      {options.map(({ value, icon: Icon, label }) => (
        <button
          key={value}
          onClick={() => setTheme(value)}
          title={label}
          className={cn(
            "flex-1 flex items-center justify-center gap-1 rounded px-2 py-1 text-[10px] transition-colors",
            theme === value
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Icon className="h-3 w-3" />
          {label}
        </button>
      ))}
    </div>
  )
}
