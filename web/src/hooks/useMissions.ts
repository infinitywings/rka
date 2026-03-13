import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { MissionCreate, MissionUpdate, MissionReportCreate } from "@/api/types"
import { useActiveProjectId } from "@/hooks/useProjectSelection"

export function useMissions(params?: { status?: string }) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["missions", projectId, params],
    queryFn: () => api.listMissions(params),
  })
}

export function useMission(id: string) {
  const projectId = useActiveProjectId()
  return useQuery({
    queryKey: ["missions", projectId, id],
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
