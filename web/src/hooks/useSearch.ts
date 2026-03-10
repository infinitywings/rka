import { useMutation } from "@tanstack/react-query"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"

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
  return useQuery({
    queryKey: ["tags"],
    queryFn: api.listTags,
  })
}
