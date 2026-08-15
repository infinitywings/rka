import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { ClaimScopeWrite } from "@/api/types"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function useClaimScopeQueue() {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["claim-scope-queue", projectId],
    queryFn: () => api.listClaims({ limit: 200 }),
  })
}

export function useClaimScope(claimId: string | null) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["claim-scope", projectId, claimId],
    queryFn: () => api.getClaimScope(claimId!),
    enabled: Boolean(claimId),
  })
}

export function useAppendClaimScope() {
  const projectId = useActiveProjectId()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ claimId, data }: { claimId: string; data: ClaimScopeWrite }) =>
      api.appendClaimScope(claimId, data),
    onSuccess: (history) => {
      queryClient.setQueryData(
        ["claim-scope", projectId, history.claim_id],
        history,
      )
      void queryClient.invalidateQueries({ queryKey: ["claim-scope-queue", projectId] })
      void queryClient.invalidateQueries({ queryKey: ["research-map", projectId] })
      void queryClient.invalidateQueries({ queryKey: ["manuscript-workbench", projectId] })
    },
  })
}
