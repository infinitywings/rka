import { useEffect } from "react"
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
  Settings,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useProjectStatus, useProjects } from "@/hooks/useProject"
import { useProjectSelection } from "@/hooks/useProjectSelection"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/journal", icon: BookOpen, label: "Journal" },
  { to: "/decisions", icon: GitBranch, label: "Decisions" },
  { to: "/literature", icon: Library, label: "Literature" },
  { to: "/missions", icon: Rocket, label: "Missions" },
  { to: "/timeline", icon: Clock, label: "Timeline" },
  { to: "/graph", icon: Share2, label: "Research Map" },
  { to: "/notebook", icon: MessageSquare, label: "Notebook" },
  { to: "/audit", icon: Shield, label: "Audit Log" },
  { to: "/context", icon: Telescope, label: "Context" },
  { to: "/settings", icon: Settings, label: "Settings" },
]

export function Sidebar() {
  const { projectId, setProjectId } = useProjectSelection()
  const { data: project } = useProjectStatus()
  const { data: projects } = useProjects()

  useEffect(() => {
    if (!projects?.length) return
    if (!projects.some((item) => item.id === projectId)) {
      setProjectId(projects[0].id)
    }
  }, [projectId, projects, setProjectId])

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
        <div className="mt-3">
          <Select value={projectId} onValueChange={setProjectId}>
            <SelectTrigger className="h-9 w-full text-xs">
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
      <div className="border-t p-3">
        <p className="text-[10px] text-muted-foreground text-center">
          Research Knowledge Agent
        </p>
      </div>
    </aside>
  )
}
