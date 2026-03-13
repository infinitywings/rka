import { useMutation } from "@tanstack/react-query"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function useSearch() {
  return useMutation({
    mutationFn: ({ query, entityTypes, limit }: {
      query: string
      entityTypes?: string[]
      limit?: number
    }) => api.search(query, entityTypes, limit),
  })
}

export function useTags() {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["tags", projectId],
    queryFn: api.listTags,
  })
}
