import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { MissionCreate, MissionUpdate, MissionReportCreate } from "@/api/types"

export function useMissions(params?: { status?: string }) {
  return useQuery({
    queryKey: ["missions", params],
    queryFn: () => api.listMissions(params),
  })
}

export function useMission(id: string) {
  return useQuery({
    queryKey: ["missions", id],
    queryFn: () => api.getMission(id),
    enabled: !!id,
  })
}

export function useCreateMission() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: MissionCreate) => api.createMission(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["missions"] }),
  })
}

export function useUpdateMission() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: MissionUpdate }) =>
      api.updateMission(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["missions"] }),
  })
}

export function useSubmitReport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: MissionReportCreate }) =>
      api.submitReport(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["missions"] }),
  })
}
