import { useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { OutlineProposalRequest } from "@/api/types"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function useManuscriptOutline(manuscriptId: string) {
  const projectId = useActiveProjectId()
  const queryClient = useQueryClient()
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["manuscript-workbench", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["semantic-patches", projectId] }),
    ])
  }
  const prepare = useMutation({
    mutationFn: (data: OutlineProposalRequest) =>
      api.prepareManuscriptOutlineProposal(manuscriptId, data),
    onSuccess: refresh,
  })
  const createCheckpoint = useMutation({
    mutationFn: (data: {
      expected_revision: number
      supersedes_id?: string
    }) => api.createManuscriptCheckpoint(manuscriptId, {
      expected_revision: data.expected_revision,
      kind: "outline",
      ...(data.supersedes_id ? { supersedes_id: data.supersedes_id } : {}),
    }),
    onSuccess: refresh,
  })
  return { prepare, createCheckpoint }
}
