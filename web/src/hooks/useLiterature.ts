import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { LiteratureCreate, LiteratureUpdate } from "@/api/types"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function useLiterature(params?: { status?: string }) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["literature", projectId, params],
    queryFn: () => api.listLiterature(params),
  })
}

export function useLiteratureItem(id: string) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["literature", projectId, id],
    queryFn: () => api.getLiterature(id),
    enabled: !!id,
  })
}

export function useCreateLiterature() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: LiteratureCreate) => api.createLiterature(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["literature"] }),
  })
}

export function useUpdateLiterature() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: LiteratureUpdate }) =>
      api.updateLiterature(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["literature"] }),
  })
}
