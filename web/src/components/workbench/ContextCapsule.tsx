import { AlertTriangle, ArrowRight, Database, FileText, GitCommitHorizontal, ShieldCheck } from "lucide-react"
import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import type { ManuscriptContext, ManuscriptReadiness, ResearchMapData } from "@/api/types"

export type WorkbenchQueueSummary =
  | { state: "loading" }
  | { state: "error"; message: string }
  | {
      state: "ready"
      shown: number
      attention: number
      ready: number
      limitReached: boolean
    }

function queueValue(
  summary: WorkbenchQueueSummary,
  attentionLabel: string,
  readyLabel: string,
) {
  if (summary.state === "loading") return "Loading review queue"
  if (summary.state === "error") return "Review queue unavailable"
  if (summary.shown === 0) return "No records in this view"
  const counts = `${summary.attention} ${attentionLabel} · ${summary.ready} ${readyLabel}`
  return summary.limitReached
    ? `${counts} · ${summary.shown} records shown; total unknown`
    : counts
}

function queueDetail(summary: WorkbenchQueueSummary, base: string) {
  if (summary.state === "error") return `${base} Error: ${summary.message}`
  if (summary.state === "ready" && summary.limitReached) {
    return `${base} The API limit was reached, so these counts must not be read as project totals.`
  }
  return base
}

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

function ReviewQueueFact({
  label,
  value,
  detail,
  source,
  to,
}: {
  label: string
  value: string
  detail: string
  source: string
  to: string
}) {
  return (
    <Link
      to={to}
      className="group rounded-md border bg-background/70 px-3 py-2 transition-colors hover:border-primary/40 hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className="mt-0.5 text-sm font-medium">{value}</p>
          <p className="mt-1 text-[10px] leading-4 text-muted-foreground">{detail}</p>
          <p className="mt-1 truncate text-[10px] text-muted-foreground" title={source}>Source: {source}</p>
        </div>
        <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
      </div>
    </Link>
  )
}

export function ContextCapsule({
  projectId,
  projectName,
  projectError,
  manuscriptRequested,
  contextLoading,
  context,
  readiness,
  readinessLoading,
  readinessError,
  map,
  mapLoading,
  mapError,
  impactCount,
  impactPartial,
  impactError,
  interpretationSummary,
  scopeSummary,
}: {
  projectId: string
  projectName: string
  projectError: Error | null
  manuscriptRequested: boolean
  contextLoading: boolean
  context?: ManuscriptContext
  readiness?: ManuscriptReadiness
  readinessLoading: boolean
  readinessError: Error | null
  map?: ResearchMapData
  mapLoading: boolean
  mapError: Error | null
  impactCount: number
  impactPartial: boolean
  impactError: Error | null
  interpretationSummary: WorkbenchQueueSummary
  scopeSummary: WorkbenchQueueSummary
}) {
  const manuscript = context?.manuscript
  const readinessLabel = readiness
    ? readiness.ready
      ? "Ready for drafting"
      : `${readiness.verdict}: ${readiness.findings.length} finding${readiness.findings.length === 1 ? "" : "s"}`
    : contextLoading
      ? "Waiting for manuscript context"
      : readinessError
        ? "Readiness unavailable"
    : manuscript
      ? readinessLoading
        ? "Readiness loading"
        : "Readiness unavailable"
      : manuscriptRequested
        ? "Manuscript unavailable"
        : "Pre-manuscript exploration"
  const manuscriptLabel = manuscript
    ? manuscript.title
    : contextLoading
      ? "Loading manuscript"
      : manuscriptRequested
        ? "Unavailable"
        : "Not selected"
  const manuscriptSource = manuscript
    ? `/api/manuscripts/${manuscript.id}/context`
    : manuscriptRequested
      ? "Canonical context request"
      : "No canonical man_ aggregate"
  const mapLabel = map
    ? `${map.summary.total_rqs} RQs · ${map.summary.total_clusters} clusters · ${map.summary.total_claims} claims`
    : mapError
      ? "Research map unavailable"
      : mapLoading
        ? "Loading"
        : "No research map returned"

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
          <CapsuleFact
            label="Project"
            value={projectName}
            source={projectError ? `Error: ${projectError.message}` : `/api/status · ${projectId}`}
          />
          <CapsuleFact
            label="Manuscript"
            value={manuscriptLabel}
            source={manuscriptSource}
          />
          <CapsuleFact
            label="Venue and phase"
            value={manuscript ? `${manuscript.venue ?? "Venue unset"} · ${manuscript.phase}` : "Planning not registered"}
            source={manuscript ? `man_ revision ${manuscript.revision}` : "Workbench stage contract"}
          />
          <CapsuleFact
            label="Research map"
            value={mapLabel}
            source={mapError ? `Error: ${mapError.message}` : "/api/research-map"}
          />
          <CapsuleFact
            label="Readiness"
            value={readinessLabel}
            source={readinessError ? `Error: ${readinessError.message}` : "/api/manuscripts/:id/readiness?target_phase=drafting"}
          />
        </div>

        <div className="grid gap-2 lg:grid-cols-2">
          <ReviewQueueFact
            label="Interpretation staging"
            value={queueValue(interpretationSummary, "awaiting review", "resolved")}
            detail={queueDetail(
              interpretationSummary,
              "Source-bounded candidates only; review does not establish scientific support.",
            )}
            source="/api/interpretation-candidates?limit=200"
            to="/interpretations?review_status=pending"
          />
          <ReviewQueueFact
            label="Canonical claim scope"
            value={queueValue(scopeSummary, "blocking scope", "ready")}
            detail={queueDetail(
              scopeSummary,
              "Applicability only; evidence support, contradictions, and source grounding remain independent.",
            )}
            source="/api/claims?limit=200"
            to="/claim-scopes?scope=missing"
          />
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

        {impactError && (
          <div role="alert" className="flex items-start gap-2 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="text-xs">
              <p className="font-medium">Semantic impact check unavailable.</p>
              <p className="mt-0.5 opacity-80">
                No clean-impact conclusion can be drawn. Error: {impactError.message}
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
