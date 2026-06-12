import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function useResearchHealth() {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["research-health", projectId],
    queryFn: () => api.getResearchHealth(),
  })
}

export function useFileStalenessReviews() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.fileStalenessReviews(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["research-health"] }),
  })
}

export function useLinkSupportAudit() {
  return useMutation({
    mutationFn: (limit?: number) => api.auditLinkSupport(limit),
  })
}
