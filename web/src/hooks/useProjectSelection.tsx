import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { setApiProjectId } from "@/api/client"

const STORAGE_KEY = "rka.activeProjectId"

type ProjectSelectionValue = {
  projectId: string
  setProjectId: (projectId: string | null) => void
}

const ProjectSelectionContext = createContext<ProjectSelectionValue | null>(null)

export function ProjectSelectionProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectIdState] = useState(() => {
    if (typeof window === "undefined") return "proj_default"
    return window.localStorage.getItem(STORAGE_KEY) || "proj_default"
  })

  useEffect(() => {
    setApiProjectId(projectId)
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, projectId)
    }
  }, [projectId])

  return (
    <ProjectSelectionContext.Provider
      value={{
        projectId,
        setProjectId: (nextProjectId: string | null) => {
          setProjectIdState(nextProjectId?.trim() || "proj_default")
        },
      }}
    >
      {children}
    </ProjectSelectionContext.Provider>
  )
}

export function useProjectSelection() {
  const context = useContext(ProjectSelectionContext)
  if (!context) {
    throw new Error("useProjectSelection must be used within ProjectSelectionProvider")
  }
  return context
}

export function useActiveProjectId() {
  return useProjectSelection().projectId
}
