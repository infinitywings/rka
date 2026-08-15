import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { PlanningBranchCreate, PlanningBranchTransition } from "@/api/types"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function usePlanningBranches(manuscriptId: string | null) {
  const projectId = useActiveProjectId()
  const queryClient = useQueryClient()
  const key = ["manuscript-planning", projectId, manuscriptId ?? "project"] as const

  const branches = useQuery({
    queryKey: [...key, "branches"],
    queryFn: () => api.listPlanningBranches(manuscriptId),
  })
  const resume = useQuery({
    queryKey: [...key, "resume"],
    queryFn: () => api.resumePlanningBranch(manuscriptId),
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: key })
  const create = useMutation({
    mutationFn: (data: PlanningBranchCreate) => api.createPlanningBranch(data),
    onSuccess: refresh,
  })
  const transition = useMutation({
    mutationFn: ({
      branchId,
      data,
    }: {
      branchId: string
      data: PlanningBranchTransition
    }) => api.transitionPlanningBranch(branchId, data),
    onSuccess: refresh,
  })

  return { branches, resume, create, transition, key }
}

export function usePlanningComparison(
  manuscriptId: string | null,
  baseBranchId: string | null,
  otherBranchId: string | null,
) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: [
      "manuscript-planning",
      projectId,
      manuscriptId ?? "project",
      "compare",
      baseBranchId,
      otherBranchId,
    ],
    queryFn: () => api.comparePlanningBranches(baseBranchId!, otherBranchId!),
    enabled: Boolean(baseBranchId && otherBranchId && baseBranchId !== otherBranchId),
  })
}
