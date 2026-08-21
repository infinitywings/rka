import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type {
  LMStudioSemanticPatchRequest,
  SemanticPatchProposalCreate,
  SemanticPatchTransition,
} from "@/api/types"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function useSemanticPatches() {
  const projectId = useActiveProjectId()
  const queryClient = useQueryClient()
  const key = ["semantic-patches", projectId] as const
  const proposals = useQuery({
    queryKey: key,
    queryFn: () => api.listSemanticPatchProposals(),
  })
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: key }),
      queryClient.invalidateQueries({ queryKey: ["manuscript-workbench", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["manuscript-planning", projectId] }),
    ])
  }
  const create = useMutation({
    mutationFn: (data: SemanticPatchProposalCreate) => api.createSemanticPatchProposal(data),
    onSuccess: refresh,
  })
  const apply = useMutation({
    mutationFn: ({ proposalId, data }: { proposalId: string; data: SemanticPatchTransition }) =>
      api.applySemanticPatchProposal(proposalId, data),
    onSuccess: refresh,
  })
  const reject = useMutation({
    mutationFn: ({ proposalId, data }: { proposalId: string; data: SemanticPatchTransition }) =>
      api.rejectSemanticPatchProposal(proposalId, data),
    onSuccess: refresh,
  })
  const generateLocal = useMutation({
    mutationFn: (data: LMStudioSemanticPatchRequest) => api.generateLMStudioSemanticPatch(data),
    onSuccess: refresh,
  })
  return { proposals, create, apply, reject, generateLocal, key }
}
