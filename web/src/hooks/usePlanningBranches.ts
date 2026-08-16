import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type {
  PlanningBranchCreate,
  PlanningBranchTransition,
  PlanningContributionProposalPrepare,
  PlanningContributionRatification,
  PlanningResearchQuestionPromotion,
} from "@/api/types"
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
  const selectedBranchId = resume.data?.branch.id ?? null
  const workflow = useQuery({
    queryKey: [...key, "workflow", selectedBranchId],
    queryFn: () => api.getPlanningArgumentWorkflow(selectedBranchId!),
    enabled: Boolean(selectedBranchId),
  })
  const promotions = useQuery({
    queryKey: [...key, "promotions", selectedBranchId],
    queryFn: () => api.listPlanningPromotions(selectedBranchId!),
    enabled: Boolean(selectedBranchId),
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: key })
  const refreshPromotionSurfaces = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: key }),
      queryClient.invalidateQueries({ queryKey: ["semantic-patches", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["manuscript-workbench", projectId] }),
    ])
  }
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
  const promoteResearchQuestion = useMutation({
    mutationFn: ({
      branchId,
      data,
    }: {
      branchId: string
      data: PlanningResearchQuestionPromotion
    }) => api.promotePlanningResearchQuestion(branchId, data),
    onSuccess: refreshPromotionSurfaces,
  })
  const prepareContribution = useMutation({
    mutationFn: ({
      branchId,
      data,
    }: {
      branchId: string
      data: PlanningContributionProposalPrepare
    }) => api.preparePlanningContribution(branchId, data),
    onSuccess: refreshPromotionSurfaces,
  })
  const ratifyContribution = useMutation({
    mutationFn: ({
      branchId,
      data,
    }: {
      branchId: string
      data: PlanningContributionRatification
    }) => api.ratifyPlanningContribution(branchId, data),
    onSuccess: refreshPromotionSurfaces,
  })

  return {
    branches,
    resume,
    workflow,
    promotions,
    create,
    transition,
    promoteResearchQuestion,
    prepareContribution,
    ratifyContribution,
    key,
  }
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
