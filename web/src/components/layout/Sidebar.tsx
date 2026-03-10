import { NavLink } from "react-router-dom"
import {
  LayoutDashboard,
  BookOpen,
  GitBranch,
  Library,
  Rocket,
  Clock,
  Share2,
  Shield,
  Telescope,
  Settings,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useProjectStatus } from "@/hooks/useProject"

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/journal", icon: BookOpen, label: "Journal" },
  { to: "/decisions", icon: GitBranch, label: "Decisions" },
  { to: "/literature", icon: Library, label: "Literature" },
  { to: "/missions", icon: Rocket, label: "Missions" },
  { to: "/timeline", icon: Clock, label: "Timeline" },
  { to: "/graph", icon: Share2, label: "Graph" },
  { to: "/audit", icon: Shield, label: "Audit Log" },
  { to: "/context", icon: Telescope, label: "Context" },
  { to: "/settings", icon: Settings, label: "Settings" },
]

export function Sidebar() {
  const { data: project } = useProjectStatus()

  return (
    <aside className="flex h-screen w-56 flex-col border-r bg-sidebar">
      {/* Logo / Project Name */}
      <div className="flex h-14 items-center border-b px-4">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground text-xs font-bold">
            R
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-semibold truncate max-w-[140px]">
              {project?.project_name ?? "RKA"}
            </span>
            {project?.current_phase && (
              <span className="text-[10px] text-muted-foreground truncate">
                {project.current_phase}
              </span>
            )}
          </div>
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
