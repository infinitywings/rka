import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

/**
 * Read-only manuscript workbench data.
 *
 * Context is the gate query: dependent projections are fetched only after the
 * manuscript is proven to belong to the active project. This avoids a burst of
 * redundant 404s for a mistyped or foreign manuscript id.
 */
export function useManuscriptWorkbench(manuscriptId: string | null) {
  const projectId = useActiveProjectId()
  const enabled = Boolean(manuscriptId)

  const context = useQuery({
    queryKey: ["manuscript-workbench", projectId, manuscriptId, "context"],
    queryFn: () => api.getManuscriptContext(manuscriptId!),
    enabled,
  })

  const aggregateReady = enabled && context.isSuccess

  const spine = useQuery({
    queryKey: ["manuscript-workbench", projectId, manuscriptId, "spine"],
    queryFn: () => api.getManuscriptSpine(manuscriptId!),
    enabled: aggregateReady,
  })

  const candidates = useQuery({
    queryKey: ["manuscript-workbench", projectId, manuscriptId, "candidates"],
    queryFn: () => api.getManuscriptWritingCandidates(manuscriptId!),
    enabled: aggregateReady,
  })

  const readiness = useQuery({
    queryKey: ["manuscript-workbench", projectId, manuscriptId, "readiness", "drafting"],
    queryFn: () => api.getManuscriptReadiness(manuscriptId!, "drafting"),
    enabled: aggregateReady,
  })

  const impact = useQuery({
    queryKey: ["manuscript-workbench", projectId, manuscriptId, "impact", 0],
    queryFn: () => api.getManuscriptImpact(manuscriptId!, 0, 100),
    enabled: aggregateReady,
  })

  return { context, spine, candidates, readiness, impact }
}
