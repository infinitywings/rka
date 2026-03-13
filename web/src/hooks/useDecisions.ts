import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { DecisionCreate, DecisionUpdate } from "@/api/types"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function useDecisions(params?: { phase?: string; status?: string }) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["decisions", projectId, params],
    queryFn: () => api.listDecisions(params),
  })
}

export function useDecision(id: string) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["decisions", projectId, id],
    queryFn: () => api.getDecision(id),
    enabled: !!id,
  })
}

export function useDecisionTree(phase?: string) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["decisions", projectId, "tree", phase],
    queryFn: () => api.getDecisionTree(phase),
  })
}

export function useCreateDecision() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: DecisionCreate) => api.createDecision(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["decisions"] })
    },
  })
}

export function useUpdateDecision() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: DecisionUpdate }) =>
      api.updateDecision(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["decisions"] })
    },
  })
}
