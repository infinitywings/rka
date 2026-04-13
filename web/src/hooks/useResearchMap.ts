import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import { useActiveProjectId } from "@/hooks/useProjectSelection"
import type { EvidenceClusterUpdateRequest } from "@/api/types"

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

export function useClusterDetail(clusterId: string | null) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["cluster-detail", projectId, clusterId],
    queryFn: () => api.getClusterDetail(clusterId!),
    enabled: !!clusterId,
  })
}

export function useUpdateCluster() {
  const qc = useQueryClient()
  const projectId = useActiveProjectId()

  return useMutation({
    mutationFn: ({
      clusterId,
      data,
    }: {
      clusterId: string
      data: EvidenceClusterUpdateRequest
    }) => api.updateCluster(clusterId, data),
    onSuccess: (_, variables) => {
      qc.invalidateQueries({ queryKey: ["research-map", projectId] })
      qc.invalidateQueries({ queryKey: ["rq-clusters", projectId] })
      qc.invalidateQueries({ queryKey: ["cluster-detail", projectId, variables.clusterId] })
      qc.invalidateQueries({ queryKey: ["cluster-claims", projectId, variables.clusterId] })
    },
  })
}

export function useReviewQueue(status = "pending") {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["review-queue", projectId, status],
    queryFn: () => api.getReviewQueue({ status }),
  })
}
