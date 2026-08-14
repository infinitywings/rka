import { AlertTriangle, Database, FileText, GitCommitHorizontal, ShieldCheck } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import type { ManuscriptContext, ManuscriptReadiness, ResearchMapData } from "@/api/types"

function CapsuleFact({
  label,
  value,
  source,
}: {
  label: string
  value: string
  source: string
}) {
  return (
    <div className="min-w-0 rounded-md border bg-background/70 px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5 truncate text-sm font-medium" title={value}>{value}</p>
      <p className="mt-1 truncate text-[10px] text-muted-foreground" title={source}>Source: {source}</p>
    </div>
  )
}

export function ContextCapsule({
  projectId,
  projectName,
  context,
  readiness,
  map,
  impactCount,
  impactPartial,
}: {
  projectId: string
  projectName: string
  context?: ManuscriptContext
  readiness?: ManuscriptReadiness
  map?: ResearchMapData
  impactCount: number
  impactPartial: boolean
}) {
  const manuscript = context?.manuscript
  const readinessLabel = readiness
    ? readiness.ready
      ? "Ready for drafting"
      : `${readiness.verdict}: ${readiness.findings.length} finding${readiness.findings.length === 1 ? "" : "s"}`
    : manuscript
      ? "Readiness loading"
      : "Pre-manuscript exploration"

  return (
    <Card className="border-primary/20 bg-gradient-to-r from-primary/[0.04] via-background to-background">
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-primary" />
            <div>
              <h2 className="text-sm font-semibold">Context Capsule</h2>
              <p className="text-xs text-muted-foreground">
                Compact, inspectable context only. No AI call is made by this view.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="outline"><Database className="mr-1 h-3 w-3" />RKA authoritative</Badge>
            <Badge variant="outline"><FileText className="mr-1 h-3 w-3" />Read-only prototype</Badge>
          </div>
        </div>

        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          <CapsuleFact label="Project" value={projectName} source={`/api/status · ${projectId}`} />
          <CapsuleFact
            label="Manuscript"
            value={manuscript ? manuscript.title : "Not selected"}
            source={manuscript ? `/api/manuscripts/${manuscript.id}/context` : "No canonical man_ aggregate"}
          />
          <CapsuleFact
            label="Venue and phase"
            value={manuscript ? `${manuscript.venue ?? "Venue unset"} · ${manuscript.phase}` : "Planning not registered"}
            source={manuscript ? `man_ revision ${manuscript.revision}` : "Workbench stage contract"}
          />
          <CapsuleFact
            label="Research map"
            value={map ? `${map.summary.total_rqs} RQs · ${map.summary.total_clusters} clusters · ${map.summary.total_claims} claims` : "Loading"}
            source="/api/research-map"
          />
          <CapsuleFact label="Readiness" value={readinessLabel} source="/api/manuscripts/:id/readiness?target_phase=drafting" />
        </div>

        {(impactCount > 0 || impactPartial) && (
          <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="text-xs">
              <p className="font-medium">
                {impactCount} relevant semantic change{impactCount === 1 ? "" : "s"} found since cursor 0.
              </p>
              <p className="mt-0.5 opacity-80">
                Derived from <code>/api/manuscripts/:id/impact</code>.
                {impactPartial ? " The first page is partial; this is not a clean impact result." : ""}
              </p>
            </div>
          </div>
        )}

        {manuscript && (
          <p className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <GitCommitHorizontal className="h-3 w-3" />
            Canonical identity {manuscript.id}; workspace {manuscript.workspace_ref ?? "not registered"}; state {manuscript.state}.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
