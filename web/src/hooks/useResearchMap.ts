import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function useResearchMap() {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["research-map", projectId],
    queryFn: () => api.getResearchMap(),
  })
}

export function useRQClusters(rqId: string | null) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["rq-clusters", projectId, rqId],
    queryFn: () => api.getRQClusters(rqId!),
    enabled: !!rqId,
  })
}

export function useClusterClaims(clusterId: string | null) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["cluster-claims", projectId, clusterId],
    queryFn: () => api.getClusterClaims(clusterId!),
    enabled: !!clusterId,
  })
}

export function useReviewQueue(status = "pending") {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["review-queue", projectId, status],
    queryFn: () => api.getReviewQueue({ status }),
  })
}
