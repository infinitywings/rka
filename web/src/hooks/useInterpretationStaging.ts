import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { InterpretationTriageRequest } from "@/api/types"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function useInterpretationCandidates() {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["interpretation-candidates", projectId],
    queryFn: () => api.listInterpretationCandidates({ limit: 200 }),
  })
}

export function useInterpretationCandidate(candidateId: string | null) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["interpretation-candidate", projectId, candidateId],
    queryFn: () => api.getInterpretationCandidate(candidateId!),
    enabled: Boolean(candidateId),
  })
}

export function useTriageInterpretationCandidate() {
  const projectId = useActiveProjectId()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      candidateId,
      data,
    }: {
      candidateId: string
      data: InterpretationTriageRequest
    }) => api.triageInterpretationCandidate(candidateId, data),
    onSuccess: (candidate) => {
      queryClient.setQueryData(
        ["interpretation-candidate", projectId, candidate.id],
        candidate,
      )
      void queryClient.invalidateQueries({
        queryKey: ["interpretation-candidates", projectId],
      })
    },
  })
}
