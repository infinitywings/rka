import { BrowserRouter, Routes, Route } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { Toaster } from "@/components/ui/sonner"
import { AppLayout } from "@/components/layout/AppLayout"

// Pages
import Dashboard from "@/pages/Dashboard"
import Journal from "@/pages/Journal"
import Decisions from "@/pages/Decisions"
import Literature from "@/pages/Literature"
import Missions from "@/pages/Missions"
import Timeline from "@/pages/Timeline"
import KnowledgeGraph from "@/pages/KnowledgeGraph"
import AuditLog from "@/pages/AuditLog"
import ContextInspector from "@/pages/ContextInspector"
import Settings from "@/pages/Settings"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="journal" element={<Journal />} />
            <Route path="decisions" element={<Decisions />} />
            <Route path="literature" element={<Literature />} />
            <Route path="missions" element={<Missions />} />
            <Route path="timeline" element={<Timeline />} />
            <Route path="graph" element={<KnowledgeGraph />} />
            <Route path="audit" element={<AuditLog />} />
            <Route path="context" element={<ContextInspector />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster position="bottom-right" richColors />
    </QueryClientProvider>
  )
}
