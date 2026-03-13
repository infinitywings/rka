import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { ProjectCreate, ProjectStateUpdate } from "@/api/types"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function useProjectStatus() {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["project", projectId],
    queryFn: api.getStatus,
  })
}

export function useUpdateProjectStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: ProjectStateUpdate) => api.updateStatus(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["project"] }),
  })
}

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
  })
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: ProjectCreate) => api.createProject(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] })
    },
  })
}

export function useExportKnowledgePack() {
  return useMutation({
    mutationFn: api.exportKnowledgePack,
  })
}

export function useImportKnowledgePack() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      file,
      project_id,
      project_name,
    }: {
      file: File
      project_id?: string
      project_name?: string
    }) => api.importKnowledgePack(file, { project_id, project_name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] })
      qc.invalidateQueries({ queryKey: ["project"] })
    },
  })
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 30_000,
  })
}
