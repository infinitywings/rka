import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { JournalEntryCreate, JournalEntryUpdate } from "@/api/types"

export function useNotes(params?: { phase?: string; type?: string; since?: string; limit?: number }) {
  return useQuery({
    queryKey: ["notes", params],
    queryFn: () => api.listNotes(params),
  })
}

export function useNote(id: string) {
  return useQuery({
    queryKey: ["notes", id],
    queryFn: () => api.getNote(id),
    enabled: !!id,
  })
}

export function useCreateNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: JournalEntryCreate) => api.createNote(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notes"] }),
  })
}

export function useUpdateNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: JournalEntryUpdate }) =>
      api.updateNote(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notes"] }),
  })
}
