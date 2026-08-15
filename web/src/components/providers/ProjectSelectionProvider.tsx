import { useEffect, useState, type ReactNode } from "react"
import { setApiProjectId } from "@/api/client"
import {
  PROJECT_SELECTION_STORAGE_KEY,
  ProjectSelectionContext,
} from "@/contexts/projectSelection"

export function ProjectSelectionProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectIdState] = useState(() => {
    if (typeof window === "undefined") return "proj_default"
    return window.localStorage.getItem(PROJECT_SELECTION_STORAGE_KEY) || "proj_default"
  })

  useEffect(() => {
    setApiProjectId(projectId)
    if (typeof window !== "undefined") {
      window.localStorage.setItem(PROJECT_SELECTION_STORAGE_KEY, projectId)
    }
  }, [projectId])

  return (
    <ProjectSelectionContext.Provider
      value={{
        projectId,
        setProjectId: (nextProjectId: string | null) => {
          const normalizedProjectId = nextProjectId?.trim() || "proj_default"

          // Publish the request boundary before React publishes new query
          // keys. Otherwise the first refetch can cache the previous
          // project's response under the newly selected project id.
          setApiProjectId(normalizedProjectId)
          setProjectIdState(normalizedProjectId)
        },
      }}
    >
      {children}
    </ProjectSelectionContext.Provider>
  )
}
