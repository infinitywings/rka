import { useMemo, useState } from "react"
import type { FormEvent, ReactNode } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import {
  AlertCircle,
  ArrowRight,
  Database,
  FlaskConical,
  Info,
  Loader2,
  Search,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ContextCapsule } from "@/components/workbench/ContextCapsule"
import { ArgumentWorkflowPanel } from "@/components/workbench/ArgumentWorkflowPanel"
import { PlanningBranchPanel } from "@/components/workbench/PlanningBranchPanel"
import { SemanticPatchPanel } from "@/components/workbench/SemanticPatchPanel"
import { OutlineEditor } from "@/components/workbench/OutlineEditor"
import { SourceSyncPanel } from "@/components/workbench/SourceSyncPanel"
import {
  EvidenceInspector,
  type WorkbenchTraceItem,
} from "@/components/workbench/EvidenceInspector"
import {
  StageRail,
} from "@/components/workbench/StageRail"
import {
  WORKBENCH_STAGES,
  type StageVerdict,
  type WorkbenchStageId,
} from "@/components/workbench/stages"
import { useManuscriptWorkbench } from "@/hooks/useManuscriptWorkbench"
import { useClaimScopeQueue } from "@/hooks/useClaimScopes"
import { useInterpretationCandidates } from "@/hooks/useInterpretationStaging"
import { useProjectStatus } from "@/hooks/useProject"
import { useActiveProjectId } from "@/hooks/useProjectSelection"
import { useResearchMap } from "@/hooks/useResearchMap"
import type {
  ManuscriptClaimContext,
  ManuscriptContext,
  ManuscriptEvidenceBinding,
  ManuscriptOutline,
  ManuscriptReadiness,
  ManuscriptUnitContext,
  ManuscriptWritingCandidates,
  ResearchMapData,
  ResearchQuestion,
  WritingCandidateClaim,
  WritingCandidateCluster,
} from "@/api/types"

type WorkbenchParams = { manuscriptId?: string }

type ScopedTraceSelection = {
  scopeKey: string
  item: WorkbenchTraceItem
}

const stageDescriptions: Record<WorkbenchStageId, string> = {
  seed: "Author intent and candidate inspiration. A captured seed remains provisional planning and never becomes evidence by itself.",
  spine: "Current ratified claims first, then server-attested candidate claims. No prose is generated here.",
  scope: "Allowed and prohibited wording make the claim boundary visible before drafting.",
  landscape: "Research questions and their cluster coverage organize the evidence landscape.",
  gap: "Gaps and blocked clusters remain explicit; absence of support is never converted into novelty.",
  response: "Method and mechanism candidates are shown only with their review state and lineage.",
  rqs: "Active research questions are navigational structure, not empirical support.",
  contributions: "Contribution candidates remain provisional until native versioning and exact PI ratification.",
  evaluation: "Exact contracts classify experiment plans, observations, and locators against bounded manuscript claims.",
  outline: "L2-L5 native manuscript units carry writing rationale and evidence bindings; every structural change remains a separate review proposal.",
}

const WORKBENCH_QUEUE_LIMIT = 200

function statusForClaim(claim: ManuscriptClaimContext): string {
  const currentRatification = claim.ratifications.some(
    (item) =>
      item.claim_version === claim.version &&
      item.decision_status === "active" &&
      item.decided_by === "pi" &&
      !item.superseded_by &&
      item.chosen === claim.exact_wording,
  )
  return currentRatification ? "Ratified" : "Provisional or stale ratification"
}

function makeStageVerdicts(
  map: ResearchMapData | undefined,
  context: ManuscriptContext | undefined,
  candidates: ManuscriptWritingCandidates | undefined,
  readiness: ManuscriptReadiness | undefined,
  outline: ManuscriptOutline | undefined,
): Record<WorkbenchStageId, StageVerdict> {
  const activeClaims = context?.claims.filter((claim) => claim.state === "active") ?? []
  const candidateClaims = candidates?.candidate_spine.claims ?? []
  const units = context?.units.filter((unit) => unit.status !== "removed") ?? []
  const resultUnits = units.filter((unit) => unit.kind === "result")
  const rqs = map?.research_questions ?? []
  const hasBoundedScope = activeClaims.length > 0 && activeClaims.every(
    (claim) => claim.allowed_wording?.trim() && claim.prohibited_wording.length > 0,
  )

  return {
    seed: "Exploratory",
    spine: activeClaims.length > 0 ? "Ready" : candidateClaims.length > 0 ? "Needs review" : "Exploratory",
    scope: hasBoundedScope ? "Ready" : activeClaims.length > 0 || candidateClaims.length > 0 ? "Needs review" : "Blocked",
    landscape: rqs.length > 0 ? "Ready" : "Blocked",
    gap: (map?.summary.total_gaps ?? 0) > 0 ? "Needs review" : rqs.length > 0 ? "Exploratory" : "Blocked",
    response: (candidates?.summary.clusters_eligible ?? 0) > 0 || activeClaims.some((claim) => claim.kind === "methodological")
      ? "Needs review"
      : "Exploratory",
    rqs: rqs.length > 0 ? "Ready" : "Blocked",
    contributions: activeClaims.length > 0 ? (readiness?.ready ? "Ready" : "Needs review") : candidateClaims.length > 0 ? "Needs review" : "Blocked",
    evaluation: resultUnits.length > 0 ? "Needs review" : "Blocked",
    outline: outline?.summary.rationale_complete
      ? checkpointStatusForStage(outline) === "resolved" ? "Ready" : "Needs review"
      : units.length > 0 ? "Needs review" : "Blocked",
  }
}

function checkpointStatusForStage(outline: ManuscriptOutline): string {
  return String(outline.outline_checkpoint?.status ?? "not_created")
}

export default function ManuscriptWorkbench() {
  const { manuscriptId: routeManuscriptId } = useParams<WorkbenchParams>()
  const manuscriptId = routeManuscriptId?.trim() || null
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const projectId = useActiveProjectId()
  const [selectedTrace, setSelectedTrace] = useState<ScopedTraceSelection | null>(null)
  const requestedStage = searchParams.get("stage")
  const stage = WORKBENCH_STAGES.some((item) => item.id === requestedStage)
    ? requestedStage as WorkbenchStageId
    : "seed"

  const project = useProjectStatus()
  const researchMap = useResearchMap()
  const interpretations = useInterpretationCandidates()
  const claimScopes = useClaimScopeQueue()
  const workbench = useManuscriptWorkbench(manuscriptId)
  const traceScopeKey = `${projectId}:${manuscriptId ?? "project-only"}:${stage}`

  const context = workbench.context.data
  const outline = workbench.outline.data
  const candidates = workbench.candidates.data
  const readiness = workbench.readiness.data
  const impact = workbench.impact.data
  const verdicts = useMemo(
    () => makeStageVerdicts(researchMap.data, context, candidates, readiness, outline),
    [researchMap.data, context, candidates, readiness, outline],
  )

  const handleLoad = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const next = String(new FormData(event.currentTarget).get("manuscript_id") ?? "").trim()
    const stageQuery = stage === "seed" ? "" : `?stage=${encodeURIComponent(stage)}`
    navigate(next ? `/manuscripts/${encodeURIComponent(next)}/workbench${stageQuery}` : `/workbench${stageQuery}`)
  }

  const stageMeta = WORKBENCH_STAGES.find((item) => item.id === stage)!
  const defaultTrace: WorkbenchTraceItem = {
    title: stageMeta.label,
    summary: stageDescriptions[stage],
    kind: "stage contract",
    origin: "Workbench stage contract (ADR 0001 and ADR 0005)",
    derivation: "Stage guidance is a deterministic projection. Captured work is stored separately as provisional planning; this view performs no LLM call.",
    ids: manuscriptId ? [projectId, manuscriptId] : [projectId],
    status: verdicts[stage],
    trace: manuscriptId ? [projectId, manuscriptId, stage] : [projectId, stage],
  }

  const impactCount = impact?.relevant_changes?.length ?? 0
  const interpretationSummary = useMemo(() => {
    if (interpretations.isLoading) return { state: "loading" as const }
    if (interpretations.error) {
      return { state: "error" as const, message: interpretations.error.message }
    }
    if (!interpretations.data) return { state: "loading" as const }
    const attention = interpretations.data.filter((item) => item.review_status !== "resolved").length
    return {
      state: "ready" as const,
      shown: interpretations.data.length,
      attention,
      ready: interpretations.data.length - attention,
      limitReached: interpretations.data.length >= WORKBENCH_QUEUE_LIMIT,
    }
  }, [interpretations.data, interpretations.error, interpretations.isLoading])
  const scopeSummary = useMemo(() => {
    if (claimScopes.isLoading) return { state: "loading" as const }
    if (claimScopes.error) {
      return { state: "error" as const, message: claimScopes.error.message }
    }
    if (!claimScopes.data) return { state: "loading" as const }
    const ready = claimScopes.data.filter((claim) => claim.scope_readiness === "ready").length
    return {
      state: "ready" as const,
      shown: claimScopes.data.length,
      attention: claimScopes.data.length - ready,
      ready,
      limitReached: claimScopes.data.length >= WORKBENCH_QUEUE_LIMIT,
    }
  }, [claimScopes.data, claimScopes.error, claimScopes.isLoading])

  const stageQueries = (() => {
    if (!manuscriptId) return []
    if (["seed", "spine", "scope", "gap", "response"].includes(stage)) {
      return [workbench.context, workbench.candidates]
    }
    if (stage === "contributions") {
      return [workbench.context, workbench.candidates, workbench.readiness]
    }
    if (stage === "evaluation") return [workbench.context]
    if (stage === "outline") return [workbench.context, workbench.outline]
    return []
  })()
  const stageIsLoading = stageQueries.some((query) => query.isLoading)
    || (["seed", "landscape", "gap", "rqs"].includes(stage) && researchMap.isLoading)
  const stageError = stageQueries.map((query) => query.error).find(Boolean)
    ?? (["seed", "landscape", "gap", "rqs"].includes(stage) ? researchMap.error : null)

  const selectStage = (next: WorkbenchStageId) => {
    const params = new URLSearchParams(searchParams)
    if (next === "seed") params.delete("stage")
    else params.set("stage", next)
    setSearchParams(params)
    setSelectedTrace(null)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">Manuscript Workbench</h1>
            <Badge variant="outline">M5 outline workbench</Badge>
          </div>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Navigate the argument from seed to outline while preserving the distinction between RKA evidence,
            manuscript semantics, and provisional interface guidance.
          </p>
        </div>

        <form
          key={manuscriptId ?? "project-only"}
          onSubmit={handleLoad}
          className="flex w-full flex-col gap-2 sm:flex-row lg:w-[34rem]"
        >
          <Input
            name="manuscript_id"
            defaultValue={manuscriptId ?? ""}
            placeholder="Canonical manuscript id (man_...)"
            aria-label="Canonical manuscript id"
          />
          <Button type="submit" variant="outline">
            <Search className="mr-2 h-4 w-4" /> Load
          </Button>
          {manuscriptId && (
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                const stageQuery = stage === "seed" ? "" : `?stage=${encodeURIComponent(stage)}`
                navigate(`/workbench${stageQuery}`)
              }}
            >
              Project only
            </Button>
          )}
        </form>
      </div>

      {!manuscriptId && (
        <div role="status" className="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-950 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-100">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            Project-only exploration. Load a canonical <code>man_...</code> identifier to inspect manuscript claims,
            evidence, readiness, and outline units.
          </p>
        </div>
      )}

      {workbench.context.error && (
        <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">The manuscript could not be loaded in the selected project.</p>
            <p className="mt-1 text-xs opacity-80">{workbench.context.error.message}</p>
          </div>
        </div>
      )}

      <ContextCapsule
        projectId={projectId}
        projectName={project.data?.project_name ?? (project.error ? "Project unavailable" : "Loading project")}
        projectError={project.error instanceof Error ? project.error : null}
        manuscriptRequested={Boolean(manuscriptId)}
        contextLoading={workbench.context.isLoading}
        context={context}
        readiness={readiness}
        readinessLoading={workbench.readiness.isLoading}
        readinessError={workbench.readiness.error instanceof Error ? workbench.readiness.error : null}
        map={researchMap.data}
        mapLoading={researchMap.isLoading}
        mapError={researchMap.error instanceof Error ? researchMap.error : null}
        impactCount={impactCount}
        impactPartial={Boolean(impact?.has_more)}
        impactError={workbench.impact.error instanceof Error ? workbench.impact.error : null}
        interpretationSummary={interpretationSummary}
        scopeSummary={scopeSummary}
      />

      <PlanningBranchPanel manuscriptId={manuscriptId} />

      <ArgumentWorkflowPanel manuscriptId={manuscriptId} context={context} />

      <SemanticPatchPanel manuscriptId={manuscriptId} context={context} />

      <div className="grid gap-4 xl:grid-cols-[17rem_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Guided stage rail</CardTitle>
            <p className="text-xs text-muted-foreground">Freely navigable; status is categorical, never a score.</p>
          </CardHeader>
          <CardContent>
            <StageRail
              selected={stage}
              verdicts={verdicts}
              onSelect={selectStage}
            />
          </CardContent>
        </Card>

        <div className="min-w-0 space-y-4">
          <StageCanvas
            stage={stage}
            map={researchMap.data}
            context={context}
            outline={outline}
            candidates={candidates}
            readiness={readiness}
            isLoading={stageIsLoading}
            error={stageError instanceof Error ? stageError : null}
            onInspect={(item) => setSelectedTrace({ scopeKey: traceScopeKey, item })}
          />
          <EvidenceInspector
            item={selectedTrace?.scopeKey === traceScopeKey ? selectedTrace.item : defaultTrace}
          />
        </div>
      </div>
    </div>
  )
}

function StageCanvas({
  stage,
  map,
  context,
  outline,
  candidates,
  readiness,
  isLoading,
  error,
  onInspect,
}: {
  stage: WorkbenchStageId
  map?: ResearchMapData
  context?: ManuscriptContext
  outline?: ManuscriptOutline
  candidates?: ManuscriptWritingCandidates
  readiness?: ManuscriptReadiness
  isLoading: boolean
  error: Error | null
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  const stageMeta = WORKBENCH_STAGES.find((item) => item.id === stage)!
  const activeClaims = context?.claims.filter((claim) => claim.state === "active") ?? []
  const units = context?.units.filter((unit) => unit.status !== "removed") ?? []
  const candidateClaims = candidates?.candidate_spine.claims ?? []
  const candidateClusters = candidates?.clusters ?? []
  const rqs = map?.research_questions ?? []

  return (
    <Card>
      <CardHeader className="border-b pb-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle className="text-lg">{stageMeta.label}</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">{stageMeta.question}</p>
          </div>
          <Badge variant="secondary">Canonical projection</Badge>
        </div>
        <p className="rounded-md bg-muted/50 px-3 py-2 text-xs leading-5 text-muted-foreground">
          {stageDescriptions[stage]}
        </p>
      </CardHeader>
      <CardContent className="space-y-3 p-4">
        {isLoading && (
          <div role="status" aria-live="polite" className="flex min-h-32 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading {stageMeta.label.toLowerCase()} data
          </div>
        )}
        {!isLoading && error && (
          <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-medium">This stage could not load its authoritative data.</p>
              <p className="mt-1 text-xs opacity-80">{error.message}</p>
            </div>
          </div>
        )}
        {!isLoading && !error && <>
        {stage === "seed" && (
          <SeedView map={map} candidates={candidates} onInspect={onInspect} />
        )}
        {stage === "spine" && (
          <SpineView activeClaims={activeClaims} candidateClaims={candidateClaims} candidates={candidates} onInspect={onInspect} />
        )}
        {stage === "scope" && (
          <ScopeView activeClaims={activeClaims} candidateClaims={candidateClaims} onInspect={onInspect} />
        )}
        {stage === "landscape" && <ResearchQuestionsView rqs={rqs} mode="landscape" onInspect={onInspect} />}
        {stage === "gap" && (
          <GapView rqs={rqs} clusters={candidateClusters} onInspect={onInspect} />
        )}
        {stage === "response" && (
          <ResponseView activeClaims={activeClaims} clusters={candidateClusters} onInspect={onInspect} />
        )}
        {stage === "rqs" && <ResearchQuestionsView rqs={rqs} mode="rqs" onInspect={onInspect} />}
        {stage === "contributions" && (
          <ContributionView
            activeClaims={activeClaims}
            candidateClaims={candidateClaims}
            readiness={readiness}
            onInspect={onInspect}
          />
        )}
        {stage === "evaluation" && <EvaluationView units={units} onInspect={onInspect} />}
        {stage === "outline" && outline && outline.units.length > 0 && (
          <>
            <OutlineEditor key={`${outline.manuscript_id}:${outline.manuscript_revision}`} outline={outline} onInspect={onInspect} />
            <SourceSyncPanel manuscriptId={outline.manuscript_id} />
          </>
        )}
        {stage === "outline" && outline && outline.units.length === 0 && (
          <EmptyState title="No native manuscript units" detail="Create claim-sized units through a reviewed argument-spine proposal before elaborating the outline." />
        )}
        </>}
      </CardContent>
    </Card>
  )
}

function TraceCard({
  title,
  children,
  trace,
  onInspect,
}: {
  title: string
  children: ReactNode
  trace: WorkbenchTraceItem
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onInspect(trace)}
      aria-label={`Inspect evidence for ${title}`}
      className="group w-full rounded-lg border bg-card p-3 text-left transition-colors hover:border-primary/40 hover:bg-muted/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-semibold">{title}</h3>
        <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
      </div>
      <div className="mt-2 text-xs leading-5 text-muted-foreground">{children}</div>
      <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t pt-2 text-[10px] text-muted-foreground">
        <Database className="h-3 w-3" />
        <span>{trace.origin}</span>
        {trace.ids.slice(0, 3).map((id) => <code key={id} className="rounded bg-muted px-1 py-0.5">{id}</code>)}
      </div>
    </button>
  )
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-lg border border-dashed p-6 text-center">
      <Info className="mx-auto h-5 w-5 text-muted-foreground" />
      <h3 className="mt-2 text-sm font-medium">{title}</h3>
      <p className="mx-auto mt-1 max-w-xl text-xs leading-5 text-muted-foreground">{detail}</p>
    </div>
  )
}

function SeedView({
  map,
  candidates,
  onInspect,
}: {
  map?: ResearchMapData
  candidates?: ManuscriptWritingCandidates
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  const inspirations = (candidates?.clusters ?? []).slice(0, 4)
  if (inspirations.length === 0) {
    return (
      <>
        <EmptyState
          title="No canonical seed exists by design"
          detail="The seed is author intent. Capture it as a versioned planning artifact on the selected branch; it remains provisional and is never promoted automatically."
        />
        {map && (
          <TraceCard
            title="Research-map inspiration boundary"
            trace={{
              title: "Research-map inspiration boundary",
              summary: "The project map may inspire a seed, but neither an RQ nor a cluster becomes author intent automatically.",
              kind: "derived guidance",
              origin: "/api/research-map",
              derivation: "Counts only; no claim promotion and no LLM synthesis.",
              ids: map.research_questions.map((rq) => rq.id),
              trace: ["research map", "author review", "seed (not persisted)"],
            }}
            onInspect={onInspect}
          >
            {map.summary.total_rqs} research questions and {map.summary.total_clusters} clusters are available as inspectable inspiration.
          </TraceCard>
        )}
      </>
    )
  }
  return <>{inspirations.map((cluster) => <ClusterCard key={cluster.cluster_id} cluster={cluster} prefix="Possible seed inspiration" onInspect={onInspect} />)}</>
}

function SpineView({
  activeClaims,
  candidateClaims,
  candidates,
  onInspect,
}: {
  activeClaims: ManuscriptClaimContext[]
  candidateClaims: WritingCandidateClaim[]
  candidates?: ManuscriptWritingCandidates
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  if (activeClaims.length > 0) {
    return <>{activeClaims.map((claim) => <ClaimCard key={claim.id} claim={claim} label="Canonical spine claim" onInspect={onInspect} />)}</>
  }
  if (candidateClaims.length > 0) {
    return <>{candidateClaims.map((claim) => <CandidateClaimCard key={claim.claim_id} claim={claim} candidates={candidates} onInspect={onInspect} />)}</>
  }
  return <EmptyState title="No paper spine yet" detail="No active native claim or eligible server-attested candidate is available. Review clusters or narrow the manuscript scope before drafting." />
}

function ScopeView({
  activeClaims,
  candidateClaims,
  onInspect,
}: {
  activeClaims: ManuscriptClaimContext[]
  candidateClaims: WritingCandidateClaim[]
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  if (activeClaims.length === 0 && candidateClaims.length === 0) {
    return <EmptyState title="Scope cannot be inferred" detail="A project description or research question does not supply an allowed/prohibited claim boundary. Select a candidate claim first." />
  }
  return (
    <>
      {activeClaims.map((claim) => (
        <TraceCard
          key={claim.id}
          title={`${claim.local_key} · ${claim.kind}`}
          trace={{
            title: claim.exact_wording ?? claim.local_key,
            summary: claim.allowed_wording ?? "Allowed wording missing",
            kind: "native claim scope",
            origin: "/api/manuscripts/:id/context",
            derivation: "Latest immutable wording version on the active manuscript claim.",
            ids: [
              claim.id,
              ...claim.evidence.map((item) => item.evidence_claim_id),
              ...claim.evidence.flatMap((item) => item.scope_contract ? [item.scope_contract.id] : []),
            ],
            status: statusForClaim(claim),
            trace: ["mcl_ version", "scope boundary", "manuscript units"],
            links: claim.evidence.flatMap(evidenceTraceLinks),
          }}
          onInspect={onInspect}
        >
          <p><span className="font-medium text-foreground">Allowed:</span> {claim.allowed_wording ?? "Missing"}</p>
          <p className="mt-1"><span className="font-medium text-foreground">Prohibited:</span> {claim.prohibited_wording.length > 0 ? claim.prohibited_wording.join(" · ") : "Missing, so scope is not ready"}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {claim.evidence.map((evidence) => (
              <Badge key={evidence.evidence_claim_id} variant={evidence.scope_readiness === "ready" ? "default" : "secondary"}>
                {evidence.evidence_claim_id}: scope {evidence.scope_readiness ?? "missing"}
              </Badge>
            ))}
          </div>
        </TraceCard>
      ))}
      {activeClaims.length === 0 && candidateClaims.map((claim) => (
        <TraceCard
          key={claim.claim_id}
          title={`${claim.claim_id} · provisional scope`}
          trace={{
            title: claim.text,
            summary: claim.allowed_wording,
            kind: "candidate scope",
            origin: "/api/manuscripts/:id/writing-candidates",
            derivation: "Brain-reviewed cluster synthesis; not a native claim or PI ratification.",
            ids: [...claim.evidence_ids, ...claim.scope_contract_ids],
            status: claim.prohibited_wording.length ? "Bounded candidate" : "Needs prohibited wording",
            links: claim.evidence_ids.map((claimId) => ({
              label: `Review ${claimId}`,
              to: `/claim-scopes?claim_id=${encodeURIComponent(claimId)}`,
            })),
          }}
          onInspect={onInspect}
        >
          <p><span className="font-medium text-foreground">Allowed:</span> {claim.allowed_wording}</p>
          <p className="mt-1"><span className="font-medium text-foreground">Prohibited:</span> {claim.prohibited_wording.length ? claim.prohibited_wording.join(" · ") : "Not yet bounded"}</p>
          <p className="mt-1 text-xs text-muted-foreground">{claim.scope_contract_ids.length} canonical scope contract(s)</p>
        </TraceCard>
      ))}
    </>
  )
}

function evidenceTraceLinks(evidence: ManuscriptEvidenceBinding) {
  const links = [{
    label: `Review ${evidence.evidence_claim_id}`,
    to: `/claim-scopes?claim_id=${encodeURIComponent(evidence.evidence_claim_id)}`,
  }]
  if (evidence.source_entry_id) {
    links.push({
      label: `Open source ${evidence.source_entry_id}`,
      to: `/journal?search=${encodeURIComponent(evidence.source_entry_id)}`,
    })
  }
  if (evidence.scope_contract?.source_candidate_id) {
    links.push({
      label: `Open interpretation ${evidence.scope_contract.source_candidate_id}`,
      to: `/interpretations?candidate_id=${encodeURIComponent(evidence.scope_contract.source_candidate_id)}`,
    })
  }
  return links
}

function ResearchQuestionsView({
  rqs,
  mode,
  onInspect,
}: {
  rqs: ResearchQuestion[]
  mode: "landscape" | "rqs"
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  if (rqs.length === 0) return <EmptyState title="No active research questions" detail="Create and review research-question decisions before treating the project map as a paper landscape." />
  return (
    <>{rqs.map((rq) => (
      <TraceCard
        key={rq.id}
        title={rq.question}
        trace={{
          title: rq.question,
          summary: `${rq.cluster_count} clusters, ${rq.total_claims} claims, ${rq.gap_count} gaps, ${rq.contradiction_count} contradictions.`,
          kind: mode === "rqs" ? "research question" : "landscape axis",
          origin: "/api/research-map",
          derivation: mode === "rqs" ? "Active RKA research-question decision." : "Workbench groups current clusters under their RKA research question.",
          ids: [rq.id, ...(rq.clusters ?? []).map((cluster) => cluster.id)],
          status: rq.status,
          trace: [rq.id, "ecl_ clusters", "clm_ claims"],
        }}
        onInspect={onInspect}
      >
        {rq.cluster_count} clusters · {rq.total_claims} claims · {rq.gap_count} gaps · {rq.contradiction_count} contradictions
      </TraceCard>
    ))}</>
  )
}

function GapView({
  rqs,
  clusters,
  onInspect,
}: {
  rqs: ResearchQuestion[]
  clusters: WritingCandidateCluster[]
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  const gapRqs = rqs.filter((rq) => rq.gap_count > 0 || rq.contradiction_count > 0)
  const blocked = clusters.filter((cluster) => cluster.blockers.length > 0)
  if (gapRqs.length === 0 && blocked.length === 0) {
    return <EmptyState title="No established gap is exposed" detail="This does not prove that the literature has no gap. It means current RKA reads do not expose a reviewed gap or blocker for this manuscript." />
  }
  return (
    <>
      {gapRqs.map((rq) => (
        <TraceCard
          key={rq.id}
          title={rq.question}
          trace={{
            title: rq.question,
            summary: `${rq.gap_count} gap signals and ${rq.contradiction_count} contradictions are recorded under this RQ.`,
            kind: "gap signal",
            origin: "/api/research-map",
            derivation: "Aggregated review-queue and contradiction counts; not an automatically established novelty claim.",
            ids: [rq.id],
            status: "Needs review",
          }}
          onInspect={onInspect}
        >
          {rq.gap_count} gap signals · {rq.contradiction_count} contradictions. Inspect sources before using this as motivation.
        </TraceCard>
      ))}
      {blocked.slice(0, 8).map((cluster) => <ClusterCard key={cluster.cluster_id} cluster={cluster} prefix="Blocked candidate" onInspect={onInspect} />)}
    </>
  )
}

function ResponseView({
  activeClaims,
  clusters,
  onInspect,
}: {
  activeClaims: ManuscriptClaimContext[]
  clusters: WritingCandidateCluster[]
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  const methods = activeClaims.filter((claim) => ["methodological", "theoretical"].includes(claim.kind))
  const eligible = clusters.filter((cluster) => cluster.disposition === "eligible")
  if (methods.length === 0 && eligible.length === 0) {
    return <EmptyState title="No reviewed response candidate" detail="Current clusters are missing review, current support, or a research-question binding. The interface does not invent a mechanism from raw journals." />
  }
  return (
    <>
      {methods.map((claim) => <ClaimCard key={claim.id} claim={claim} label="Canonical response claim" onInspect={onInspect} />)}
      {methods.length === 0 && eligible.map((cluster) => <ClusterCard key={cluster.cluster_id} cluster={cluster} prefix="Provisional response" onInspect={onInspect} />)}
    </>
  )
}

function ContributionView({
  activeClaims,
  candidateClaims,
  readiness,
  onInspect,
}: {
  activeClaims: ManuscriptClaimContext[]
  candidateClaims: WritingCandidateClaim[]
  readiness?: ManuscriptReadiness
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  return (
    <>
      {readiness && readiness.findings.length > 0 && (
        <TraceCard
          title={`${readiness.verdict}: drafting gate has ${readiness.findings.length} finding${readiness.findings.length === 1 ? "" : "s"}`}
          trace={{
            title: "Authoritative drafting readiness",
            summary: readiness.findings.map((item) => `${item.code}: ${item.message}`).join(" "),
            kind: "readiness gate",
            origin: "/api/manuscripts/:id/readiness?target_phase=drafting",
            derivation: "Deterministic RKA service findings over current claims, evidence, units, references, and checkpoints.",
            ids: readiness.findings.flatMap((item) => [item.claim_id, item.unit_id, item.literature_id].filter(Boolean) as string[]),
            status: readiness.verdict,
          }}
          onInspect={onInspect}
        >
          {readiness.findings.slice(0, 4).map((item) => <p key={`${item.code}-${item.claim_id ?? item.unit_id ?? "all"}`}>{item.code}: {item.message}</p>)}
        </TraceCard>
      )}
      {activeClaims.map((claim) => <ClaimCard key={claim.id} claim={claim} label="Native contribution" onInspect={onInspect} />)}
      {activeClaims.length === 0 && candidateClaims.map((claim) => <CandidateClaimCard key={claim.claim_id} claim={claim} onInspect={onInspect} />)}
      {activeClaims.length === 0 && candidateClaims.length === 0 && (
        <EmptyState title="No contribution candidate is admissible" detail="Review cluster blockers, resolve contradictions, or gather evidence. A fluent synthesis is not promoted automatically." />
      )}
    </>
  )
}

function EvaluationView({
  units,
  onInspect,
}: {
  units: ManuscriptUnitContext[]
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  const results = units.filter((unit) => unit.kind === "result")
  return (
    <>
      <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
        <FlaskConical className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <p className="font-medium">Evaluation authority stays explicit.</p>
          <p className="mt-1 opacity-80">
            The claim-centered matrix above resolves exact experiment plans, runs, observations, and locators. This drafting view shows only canonical result units that crossed the separate semantic-review boundary.
          </p>
          <p className="mt-1 opacity-70">A completed run is not evidence until an exact observation and locator are classified against the claim.</p>
        </div>
      </div>
      {results.map((unit) => <UnitCard key={unit.id} unit={unit} label="Result unit" onInspect={onInspect} />)}
      {results.length === 0 && (
        <EmptyState title="No canonical result units" detail="Use the evaluation contract to collect exact evidence and prepare a review proposal. Journal prose and repository execution are never promoted automatically." />
      )}
    </>
  )
}

function ClaimCard({
  claim,
  label,
  onInspect,
}: {
  claim: ManuscriptClaimContext
  label: string
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  const evidenceIds = claim.evidence.map((item) => item.evidence_claim_id)
  return (
    <TraceCard
      title={`${claim.local_key} · ${label}`}
      trace={{
        title: claim.exact_wording ?? claim.local_key,
        summary: claim.allowed_wording ?? "Allowed wording missing",
        kind: `native ${claim.kind} claim`,
        origin: "/api/manuscripts/:id/context",
        derivation: "Latest immutable mcl_ wording version with typed evidence and unit bindings.",
        ids: [claim.id, ...evidenceIds, ...claim.unit_links.map((link) => link.unit_id)],
        status: statusForClaim(claim),
        trace: ["terminal source", "clm_", claim.id, "mun_", "prose"],
      }}
      onInspect={onInspect}
    >
      <p className="text-foreground">{claim.exact_wording ?? "Wording missing"}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Badge variant="outline">{claim.kind}</Badge>
        <Badge variant="outline">{statusForClaim(claim)}</Badge>
        <Badge variant="outline">{evidenceIds.length} evidence bindings</Badge>
        <Badge variant="outline">{claim.unit_links.length} unit links</Badge>
      </div>
    </TraceCard>
  )
}

function CandidateClaimCard({
  claim,
  candidates,
  onInspect,
}: {
  claim: WritingCandidateClaim
  candidates?: ManuscriptWritingCandidates
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  const lineage = candidates?.candidate_lineage[claim.claim_id]
  const lineageIds = lineage
    ? [lineage.cluster_id, ...(lineage.research_question_id ? [lineage.research_question_id] : []), ...lineage.representative_claim_ids]
    : []
  return (
    <TraceCard
      title={`${claim.claim_id} · server-attested candidate`}
      trace={{
        title: claim.text,
        summary: "Eligible cluster synthesis proposed for manuscript scoping; not a native claim and not PI-ratified.",
        kind: "writing candidate",
        origin: "/api/manuscripts/:id/writing-candidates",
        derivation: "Current Brain-reviewed cluster bound to an active RQ, with duplicate grouping and admission checks.",
        ids: [...lineageIds, ...claim.evidence_ids, ...claim.scope_contract_ids],
        status: "Provisional",
        trace: ["jrn_", "clm_", lineage?.cluster_id ?? "ecl_", lineage?.research_question_id ?? "RQ", "candidate"],
      }}
      onInspect={onInspect}
    >
      <p className="text-foreground">{claim.text}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Badge variant="outline">{claim.claim_type}</Badge>
        <Badge variant="outline">{claim.evidence_ids.length} admitted claims</Badge>
        <Badge variant="outline">{claim.scope_contract_ids.length} scope contracts</Badge>
        <Badge variant="outline">not ratified</Badge>
      </div>
    </TraceCard>
  )
}

function ClusterCard({
  cluster,
  prefix,
  onInspect,
}: {
  cluster: WritingCandidateCluster
  prefix: string
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  return (
    <TraceCard
      title={`${prefix}: ${cluster.label}`}
      trace={{
        title: cluster.label,
        summary: cluster.synthesis ?? "Cluster synthesis missing",
        kind: "evidence cluster projection",
        origin: "/api/manuscripts/:id/writing-candidates",
        derivation: "Server evaluates RQ binding, Brain review, currency, support admission, duplicates, and contradictions.",
        ids: [cluster.cluster_id, ...(cluster.research_question_id ? [cluster.research_question_id] : []), ...cluster.support_claim_ids],
        status: cluster.blockers.length ? `Blocked: ${cluster.blockers.join(", ")}` : "Eligible, still provisional",
        trace: ["clm_ support", cluster.cluster_id, cluster.research_question_id ?? "RQ missing", "candidate"],
      }}
      onInspect={onInspect}
    >
      <p>{cluster.synthesis ?? "No reviewed synthesis"}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Badge variant="outline">{cluster.confidence}</Badge>
        <Badge variant="outline">{cluster.synthesized_by}</Badge>
        {cluster.blockers.map((blocker) => <Badge key={blocker} variant="destructive">{blocker}</Badge>)}
      </div>
    </TraceCard>
  )
}

function UnitCard({
  unit,
  label,
  onInspect,
}: {
  unit: ManuscriptUnitContext
  label: string
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  return (
    <TraceCard
      title={`${unit.local_key} · ${unit.title ?? unit.kind}`}
      trace={{
        title: unit.title ?? unit.local_key,
        summary: `${unit.kind} at ${unit.location}`,
        kind: "native manuscript unit",
        origin: "/api/manuscripts/:id/context",
        derivation: "Current mun_ record with evidence bindings and optional result interpretation boundary.",
        ids: [unit.id, ...unit.evidence.map((item) => item.evidence_claim_id), ...(unit.artifact_ref ? [unit.artifact_ref] : [])],
        status: unit.status,
        trace: ["mcl_", unit.id, unit.location],
      }}
      onInspect={onInspect}
    >
      <div className="flex flex-wrap gap-1.5">
        <Badge variant="outline">{label}</Badge>
        <Badge variant="outline">{unit.kind}</Badge>
        <Badge variant="outline">{unit.status}</Badge>
      </div>
      <p className="mt-2"><span className="font-medium text-foreground">Location:</span> {unit.location}</p>
      {unit.kind === "result" && (
        <>
          <p className="mt-1"><span className="font-medium text-foreground">Allowed:</span> {unit.allowed_interpretation ?? "Missing"}</p>
          <p className="mt-1"><span className="font-medium text-foreground">Prohibited:</span> {unit.prohibited_interpretation ?? "Missing"}</p>
        </>
      )}
    </TraceCard>
  )
}
