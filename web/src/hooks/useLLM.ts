import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { LLMConfigUpdate } from "@/api/types"

export function useLLMStatus() {
  return useQuery({
    queryKey: ["llm-status"],
    queryFn: api.getLLMStatus,
    refetchInterval: 15_000,
  })
}

export function useUpdateLLMConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: LLMConfigUpdate) => api.updateLLMConfig(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm-status"] })
      qc.invalidateQueries({ queryKey: ["health"] })
    },
  })
}

export function useCheckLLM() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.checkLLM(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm-status"] })
      qc.invalidateQueries({ queryKey: ["health"] })
    },
  })
}

export function useLLMModels() {
  return useQuery({
    queryKey: ["llm-models"],
    queryFn: api.getLLMModels,
    staleTime: 30_000,
  })
}
