import { useContext } from "react"
import { ProjectSelectionContext } from "@/contexts/projectSelection"

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
