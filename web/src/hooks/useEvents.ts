import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function useEvents(params?: { entity_type?: string; entity_id?: string; limit?: number }) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["events", projectId, params],
    queryFn: () => api.listEvents(params),
  })
}
