import { useMutation } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { ReportContextRequest } from "@/api/types"

export function useBuildReportContext() {
  return useMutation({
    mutationFn: (data: ReportContextRequest) => api.buildReportContext(data),
  })
}
