import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { ManuscriptSourceProposalCreate } from "@/api/types"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function useManuscriptSources(manuscriptId: string, relativePath: string | null) {
  const projectId = useActiveProjectId()
  const queryClient = useQueryClient()
  const rootKey = ["manuscript-sources", projectId, manuscriptId] as const
  const overview = useQuery({
    queryKey: [...rootKey, "overview"],
    queryFn: () => api.getManuscriptSourceOverview(manuscriptId),
  })
  const effectiveRelativePath = relativePath ?? overview.data?.files[0]?.relative_path ?? null
  const file = useQuery({
    queryKey: [...rootKey, "file", effectiveRelativePath],
    queryFn: () => api.readManuscriptSource(manuscriptId, effectiveRelativePath!),
    enabled: Boolean(effectiveRelativePath),
  })
  const proposals = useQuery({
    queryKey: [...rootKey, "proposals"],
    queryFn: () => api.listManuscriptSourceProposals(manuscriptId),
  })
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: rootKey }),
      queryClient.invalidateQueries({ queryKey: ["manuscript-workbench", projectId] }),
    ])
  }
  const create = useMutation({
    mutationFn: (data: ManuscriptSourceProposalCreate) =>
      api.createManuscriptSourceProposal(manuscriptId, data),
    onSuccess: refresh,
  })
  const review = useMutation({
    mutationFn: (proposalId: string) => api.getManuscriptSourceProposal(proposalId),
  })
  const apply = useMutation({
    mutationFn: ({ proposalId, revision, reason }: {
      proposalId: string
      revision: number
      reason: string
    }) => api.applyManuscriptSourceProposal(proposalId, revision, reason),
    onSuccess: refresh,
  })
  const reject = useMutation({
    mutationFn: ({ proposalId, revision, reason }: {
      proposalId: string
      revision: number
      reason: string
    }) => api.rejectManuscriptSourceProposal(proposalId, revision, reason),
    onSuccess: refresh,
  })
  return {
    overview,
    file,
    proposals,
    create,
    review,
    apply,
    reject,
    rootKey,
    relativePath: effectiveRelativePath,
  }
}
