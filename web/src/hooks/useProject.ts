import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { ProjectStateUpdate } from "@/api/types"

export function useProjectStatus() {
  return useQuery({
    queryKey: ["project"],
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

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 30_000,
  })
}
