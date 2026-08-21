import { createContext } from "react"

export const PROJECT_SELECTION_STORAGE_KEY = "rka.activeProjectId"

export type ProjectSelectionValue = {
  projectId: string
  setProjectId: (projectId: string | null) => void
}

export const ProjectSelectionContext = createContext<ProjectSelectionValue | null>(null)
