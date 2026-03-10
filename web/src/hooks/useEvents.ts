import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"

export function useEvents(params?: { entity_type?: string; entity_id?: string; limit?: number }) {
  return useQuery({
    queryKey: ["events", params],
    queryFn: () => api.listEvents(params),
  })
}
