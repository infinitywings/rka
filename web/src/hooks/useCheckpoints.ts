import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { CheckpointResolve } from "@/api/types"

export function useCheckpoints(params?: { status?: string; mission_id?: string }) {
  return useQuery({
    queryKey: ["checkpoints", params],
    queryFn: () => api.listCheckpoints(params),
  })
}

export function useResolveCheckpoint() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: CheckpointResolve }) =>
      api.resolveCheckpoint(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["checkpoints"] })
      qc.invalidateQueries({ queryKey: ["missions"] })
    },
  })
}
