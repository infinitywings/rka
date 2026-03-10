import { useMutation } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { ContextRequest } from "@/api/types"

export function useGetContext() {
  return useMutation({
    mutationFn: (data: ContextRequest) => api.getContext(data),
  })
}

export function useSummarize() {
  return useMutation({
    mutationFn: (data: { topic?: string; phase?: string; entity_ids?: string[] }) =>
      api.summarize(data),
  })
}
