import { useEffect, useMemo, useState } from "react"
import type { ReactNode } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Markdown } from "@/components/shared/Markdown"
import {
  useClusterDetail,
  useResearchMap,
  useRQClusters,
  useUpdateCluster,
} from "@/hooks/useResearchMap"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import type {
  Claim,
  ClusterConfidence,
  ClusterContradiction,
  ResearchMapClusterDetail,
  ReviewItem,
} from "@/api/types"
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle,
  HelpCircle,
  Loader2,
  Save,
  X,
} from "lucide-react"
import { Link } from "react-router-dom"
import { toast } from "sonner"

const confidenceColors: Record<string, string> = {
  strong: "bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-200",
  moderate: "bg-teal-50 text-teal-700 dark:bg-teal-950 dark:text-teal-300",
  emerging: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
  contested: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  refuted: "bg-red-200 text-red-900 dark:bg-red-950 dark:text-red-100",
}

const claimTypeColors: Record<string, string> = {
  hypothesis: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  evidence: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  method: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  result: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  observation: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200",
  assumption: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
}

const clusterConfidenceOptions: ClusterConfidence[] = [
  "strong",
  "moderate",
  "emerging",
  "contested",
  "refuted",
]

type StatFilter = "gaps" | "contradictions" | null

export default function ResearchMap() {
  const { data: map, isLoading } = useResearchMap()
  const [selectedRQ, setSelectedRQ] = useState<string | null>(null)
  const [selectedCluster, setSelectedCluster] = useState<string | null>(null)
  const [statFilter, setStatFilter] = useState<StatFilter>(null)
  const [draftConfidence, setDraftConfidence] = useState<ClusterConfidence>("emerging")
  const [draftSynthesis, setDraftSynthesis] = useState("")

  const { data: clusters } = useRQClusters(selectedRQ)
  const {
    data: clusterDetail,
    isLoading: isClusterLoading,
    error: clusterError,
  } = useClusterDetail(selectedCluster)
  const updateCluster = useUpdateCluster()

  useEffect(() => {
    if (!clusterDetail) return
    setDraftConfidence(clusterDetail.confidence as ClusterConfidence)
    setDraftSynthesis(clusterDetail.synthesis ?? "")
  }, [clusterDetail?.id, clusterDetail?.confidence, clusterDetail?.synthesis])

  const hasDraftChanges = useMemo(() => {
    if (!clusterDetail) return false
    return (
      normalizeText(draftSynthesis) !== normalizeText(clusterDetail.synthesis) ||
      draftConfidence !== clusterDetail.confidence
    )
  }, [clusterDetail, draftConfidence, draftSynthesis])

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  const summary = map?.summary
  const allRQs = map?.research_questions ?? []
  const filteredRQs = statFilter === "gaps"
    ? allRQs.filter((rq) => rq.gap_count > 0)
    : statFilter === "contradictions"
      ? allRQs.filter((rq) => rq.contradiction_count > 0)
      : allRQs

  const selectedRQData = map?.research_questions?.find((rq) => rq.id === selectedRQ) ?? null

  const handleClusterSave = () => {
    if (!selectedCluster) return
    const synthesis = normalizeText(draftSynthesis) || null
    updateCluster.mutate(
      {
        clusterId: selectedCluster,
        data: {
          confidence: draftConfidence,
          synthesis,
          synthesized_by: "brain",
        },
      },
      {
        onSuccess: () => {
          toast.success("Cluster review updated")
        },
        onError: (error: Error) => {
          toast.error(error.message)
        },
      },
    )
  }

  return (
    <>
      {selectedRQ ? (
        <ResearchQuestionView
          clusters={clusters ?? []}
          onBack={() => setSelectedRQ(null)}
          onOpenCluster={setSelectedCluster}
          researchQuestion={selectedRQData}
        />
      ) : (
        <ResearchMapOverview
          allRQs={allRQs}
          filteredRQs={filteredRQs}
          map={map}
          statFilter={statFilter}
          summary={summary}
          onClearFilter={() => setStatFilter(null)}
          onOpenCluster={setSelectedCluster}
          onSelectRQ={setSelectedRQ}
          onToggleFilter={(nextFilter) =>
            setStatFilter((current) => (current === nextFilter ? null : nextFilter))
          }
        />
      )}

      <Sheet
        open={!!selectedCluster}
        onOpenChange={(open) => {
          if (!open) setSelectedCluster(null)
        }}
      >
        <SheetContent className="w-full overflow-y-auto sm:max-w-2xl md:!max-w-3xl lg:!max-w-[60vw] xl:!max-w-[55vw] 2xl:!max-w-[50vw]">
          {isClusterLoading ? (
            <div className="flex h-full min-h-64 items-center justify-center">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : clusterError ? (
            <div className="space-y-3 p-6">
              <SheetHeader className="px-0 pt-0">
                <SheetTitle>Cluster Unavailable</SheetTitle>
                <SheetDescription>
                  The selected cluster could not be loaded.
                </SheetDescription>
              </SheetHeader>
              <p className="text-sm text-destructive">
                {clusterError instanceof Error ? clusterError.message : "Unknown error"}
              </p>
            </div>
          ) : clusterDetail ? (
            <ClusterDetailPanel
              cluster={clusterDetail}
              draftConfidence={draftConfidence}
              draftSynthesis={draftSynthesis}
              hasDraftChanges={hasDraftChanges}
              isSaving={updateCluster.isPending}
              onConfidenceChange={(value) => {
                if (!value) return
                setDraftConfidence(value as ClusterConfidence)
              }}
              onSave={handleClusterSave}
              onSynthesisChange={setDraftSynthesis}
            />
          ) : null}
        </SheetContent>
      </Sheet>
    </>
  )
}

function ResearchQuestionView({
  clusters,
  onBack,
  onOpenCluster,
  researchQuestion,
}: {
  clusters: Array<{
    id: string
    label: string
    synthesis?: string | null
    confidence: string
    claim_count: number
    gap_count: number
    needs_reprocessing: boolean
    synthesized_by: string
  }>
  onBack: () => void
  onOpenCluster: (clusterId: string) => void
  researchQuestion: {
    id: string
    question: string
    cluster_count: number
    total_claims: number
    gap_count: number
  } | null
}) {
  return (
    <div className="space-y-4 p-6">
      <Button variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeft className="mr-2 h-4 w-4" /> Back to research questions
      </Button>

      {researchQuestion && (
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">{researchQuestion.question}</h2>
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span>{researchQuestion.cluster_count} clusters</span>
            <span>{researchQuestion.total_claims} claims</span>
            {researchQuestion.gap_count > 0 && (
              <span className="flex items-center gap-1 text-amber-600">
                <HelpCircle className="h-3 w-3" /> {researchQuestion.gap_count} gaps
              </span>
            )}
          </div>
        </div>
      )}

      <div className="space-y-2">
        <h3 className="text-base font-semibold">Evidence Clusters</h3>
        <p className="text-sm text-muted-foreground">
          Open a cluster to inspect claims, contradictions, and inline synthesis review.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {clusters.map((cluster) => (
          <Card
            key={cluster.id}
            className="cursor-pointer transition-shadow hover:shadow-md"
            onClick={() => onOpenCluster(cluster.id)}
          >
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="text-sm font-medium">{cluster.label}</CardTitle>
                <Badge className={confidenceColors[cluster.confidence] || ""}>
                  {cluster.confidence}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              {cluster.synthesis && (
                <p className="line-clamp-3 text-xs text-muted-foreground">{cluster.synthesis}</p>
              )}
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span>{cluster.claim_count} claims</span>
                {cluster.gap_count > 0 && (
                  <span className="flex items-center gap-1 text-amber-600">
                    <HelpCircle className="h-3 w-3" /> {cluster.gap_count} gaps
                  </span>
                )}
                {cluster.needs_reprocessing && (
                  <Badge variant="outline" className="text-xs">
                    needs reprocessing
                  </Badge>
                )}
                {cluster.synthesized_by === "brain" && (
                  <Badge variant="secondary" className="text-xs">
                    Brain-verified
                  </Badge>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
        {clusters.length === 0 && (
          <p className="col-span-full text-sm text-muted-foreground">
            No evidence clusters for this research question yet.
          </p>
        )}
      </div>
    </div>
  )
}

function ResearchMapOverview({
  allRQs,
  filteredRQs,
  map,
  statFilter,
  summary,
  onClearFilter,
  onOpenCluster,
  onSelectRQ,
  onToggleFilter,
}: {
  allRQs: Array<{
    id: string
    question: string
    status: string
    cluster_count: number
    total_claims: number
    gap_count: number
    contradiction_count: number
  }>
  filteredRQs: Array<{
    id: string
    question: string
    status: string
    cluster_count: number
    total_claims: number
    gap_count: number
    contradiction_count: number
  }>
  map: {
    unassigned_clusters?: Array<{
      id: string
      label: string
      claim_count: number
      confidence: string
    }>
  } | undefined
  statFilter: StatFilter
  summary:
    | {
        total_rqs: number
        total_clusters: number
        total_claims: number
        total_gaps: number
        total_contradictions: number
        pending_review: number
      }
    | undefined
  onClearFilter: () => void
  onOpenCluster: (clusterId: string) => void
  onSelectRQ: (rqId: string) => void
  onToggleFilter: (filter: Exclude<StatFilter, null>) => void
}) {
  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Research Map</h1>
      </div>

      {summary && (
        <div className="grid gap-4 md:grid-cols-5">
          <SummaryCard label="Research Questions" value={summary.total_rqs} />
          <SummaryCard label="Evidence Clusters" value={summary.total_clusters} />
          <SummaryCard label="Claims" value={summary.total_claims} />
          <SummaryCard
            active={statFilter === "gaps"}
            colorClass="text-amber-600"
            label="Evidence Gaps"
            onClick={() => onToggleFilter("gaps")}
            value={summary.total_gaps}
          />
          <SummaryCard
            active={statFilter === "contradictions"}
            colorClass="text-red-600"
            label="Contradictions"
            onClick={() => onToggleFilter("contradictions")}
            value={summary.total_contradictions}
          />
        </div>
      )}

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Research Questions</h2>
          {statFilter && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onClearFilter}
              className="gap-1 text-xs"
            >
              <X className="h-3 w-3" />
              Clear filter ({filteredRQs.length} of {allRQs.length})
            </Button>
          )}
        </div>
        {filteredRQs.map((rq) => (
          <Card
            key={rq.id}
            className="cursor-pointer transition-shadow hover:shadow-md"
            onClick={() => onSelectRQ(rq.id)}
          >
            <CardContent className="p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <h3 className="font-medium">{rq.question}</h3>
                  <div className="mt-2 flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
                    <span>{rq.cluster_count} clusters</span>
                    <span>{rq.total_claims} claims</span>
                    {rq.gap_count > 0 && (
                      <Badge variant="outline" className="gap-1 border-amber-300 text-amber-600">
                        <HelpCircle className="h-3 w-3" /> {rq.gap_count} gaps
                      </Badge>
                    )}
                    {rq.contradiction_count > 0 && (
                      <Badge variant="outline" className="gap-1 border-red-300 text-red-600">
                        <AlertTriangle className="h-3 w-3" /> {rq.contradiction_count} contradictions
                      </Badge>
                    )}
                  </div>
                </div>
                <Badge variant={rq.status === "active" ? "default" : "secondary"}>{rq.status}</Badge>
              </div>
            </CardContent>
          </Card>
        ))}
        {filteredRQs.length === 0 && allRQs.length > 0 && (
          <Card>
            <CardContent className="p-8 text-center text-muted-foreground">
              <p>No research questions match the current filter.</p>
              <Button variant="ghost" size="sm" onClick={onClearFilter} className="mt-2">
                Clear filter
              </Button>
            </CardContent>
          </Card>
        )}
        {allRQs.length === 0 && (
          <Card>
            <CardContent className="p-8 text-center text-muted-foreground">
              <p>No research questions yet.</p>
              <p className="mt-1 text-sm">
                Create decisions with kind=&quot;research_question&quot; to populate the research map.
              </p>
            </CardContent>
          </Card>
        )}
      </div>

      {map?.unassigned_clusters && map.unassigned_clusters.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold">Unassigned Clusters</h2>
          <div className="grid gap-3 md:grid-cols-3">
            {map.unassigned_clusters.map((cluster) => (
              <Card
                key={cluster.id}
                className="cursor-pointer transition-shadow hover:shadow-md"
                onClick={() => onOpenCluster(cluster.id)}
              >
                <CardContent className="space-y-2 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{cluster.label}</span>
                    <Badge className={confidenceColors[cluster.confidence] || ""}>
                      {cluster.confidence}
                    </Badge>
                  </div>
                  <span className="text-xs text-muted-foreground">{cluster.claim_count} claims</span>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ClusterDetailPanel({
  cluster,
  draftConfidence,
  draftSynthesis,
  hasDraftChanges,
  isSaving,
  onConfidenceChange,
  onSave,
  onSynthesisChange,
}: {
  cluster: ResearchMapClusterDetail
  draftConfidence: ClusterConfidence
  draftSynthesis: string
  hasDraftChanges: boolean
  isSaving: boolean
  onConfidenceChange: (value: string | null) => void
  onSave: () => void
  onSynthesisChange: (value: string) => void
}) {
  return (
    <div className="space-y-6 p-6">
      <SheetHeader className="border-b px-0 pb-4 pt-0">
        <SheetTitle>{cluster.label}</SheetTitle>
        <SheetDescription className="space-y-1">
          <span className="block">
            {cluster.research_question
              ? `Research question: ${cluster.research_question.question}`
              : "Unassigned cluster"}
          </span>
          <span className="block">
            Inspect linked claims, pending review items, and contradictions before finalizing synthesis.
          </span>
        </SheetDescription>
      </SheetHeader>

      <div className="flex flex-wrap items-center gap-2">
        <Badge className={confidenceColors[cluster.confidence] || ""}>{cluster.confidence}</Badge>
        <Badge variant="outline">{cluster.claim_count} claims</Badge>
        {cluster.gap_count > 0 && (
          <Badge variant="outline" className="gap-1 border-amber-300 text-amber-600">
            <HelpCircle className="h-3 w-3" /> {cluster.gap_count} gaps
          </Badge>
        )}
        {cluster.contradictions.length > 0 && (
          <Badge variant="outline" className="gap-1 border-red-300 text-red-600">
            <AlertTriangle className="h-3 w-3" /> {cluster.contradictions.length} contradictions
          </Badge>
        )}
        {cluster.review_items.length > 0 && (
          <Badge variant="outline">{cluster.review_items.length} pending review items</Badge>
        )}
        {cluster.needs_reprocessing && (
          <Badge variant="outline">needs reprocessing</Badge>
        )}
        {cluster.synthesized_by === "brain" && (
          <Badge variant="secondary">Brain-verified</Badge>
        )}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Inline Review</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* `minmax(0,1fr)` allows the synthesis column to shrink past min-content
              so the textarea fills the available space rather than collapsing to
              the longest unbreakable token. Default `1fr` defers to min-content,
              which produced the ~10-char/line wrapping bug (Mission report). */}
          <div className="grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Confidence
              </p>
              <Select value={draftConfidence} onValueChange={onConfidenceChange}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {clusterConfidenceOptions.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Synthesis
                </p>
                <Button
                  size="sm"
                  onClick={onSave}
                  disabled={!hasDraftChanges || isSaving}
                  className="gap-2"
                >
                  {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  Save review
                </Button>
              </div>
              <Textarea
                value={draftSynthesis}
                onChange={(event) => onSynthesisChange(event.target.value)}
                placeholder="Write the definitive synthesis for this cluster..."
                className="min-h-36 resize-y"
              />
              <p className="text-xs text-muted-foreground">
                Saving marks this cluster as reviewed by the Brain-facing workflow.
              </p>
            </div>
          </div>

          <Separator />

          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Rendered Synthesis
            </p>
            {normalizeText(draftSynthesis) ? (
              <div className="rounded-md border bg-muted/20 p-3">
                <Markdown>{draftSynthesis}</Markdown>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No synthesis written yet.
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      <DetailSection
        description="Pending Brain-facing review items linked to this cluster."
        title="Pending Review"
      >
        {cluster.review_items.length > 0 ? (
          <div className="space-y-3">
            {cluster.review_items.map((item) => (
              <ReviewItemCard key={item.id} item={item} />
            ))}
          </div>
        ) : (
          <EmptyState text="No pending review items for this cluster." />
        )}
      </DetailSection>

      <DetailSection
        description="Claim-edge contradictions currently attached to this cluster."
        title="Contradictions"
      >
        {cluster.contradictions.length > 0 ? (
          <div className="space-y-3">
            {cluster.contradictions.map((contradiction) => (
              <ContradictionCard key={contradiction.id} contradiction={contradiction} />
            ))}
          </div>
        ) : (
          <EmptyState text="No contradiction edges recorded for this cluster." />
        )}
      </DetailSection>

      <DetailSection
        description="All claims currently assigned to this cluster, with direct links back to journal evidence."
        title="Claims"
      >
        {cluster.claims.length > 0 ? (
          <div className="space-y-3">
            {cluster.claims.map((claim) => (
              <ClaimCard key={claim.id} claim={claim} />
            ))}
          </div>
        ) : (
          <EmptyState text="No claims in this cluster yet." />
        )}
      </DetailSection>
    </div>
  )
}

function DetailSection({
  children,
  description,
  title,
}: {
  children: ReactNode
  description: string
  title: string
}) {
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <h3 className="text-base font-semibold">{title}</h3>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {children}
    </div>
  )
}

function SummaryCard({
  active = false,
  colorClass,
  label,
  onClick,
  value,
}: {
  active?: boolean
  colorClass?: string
  label: string
  onClick?: () => void
  value: number
}) {
  return (
    <Card
      className={onClick
        ? `cursor-pointer transition-all hover:shadow-md ${active ? "ring-2 ring-primary" : ""}`
        : undefined}
      onClick={onClick}
    >
      <CardContent className="p-4 text-center">
        <div className={`text-2xl font-bold ${colorClass ?? ""}`}>{value}</div>
        <div className="text-xs text-muted-foreground">{label}</div>
        {active && <div className="mt-1 text-[10px] text-muted-foreground">click to clear filter</div>}
      </CardContent>
    </Card>
  )
}

function ClaimCard({ claim }: { claim: Claim }) {
  return (
    <Card className={claim.stale ? "opacity-60" : undefined}>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge className={claimTypeColors[claim.claim_type] || ""}>{claim.claim_type}</Badge>
              {claim.verified && <CheckCircle className="h-4 w-4 text-green-500" />}
              {claim.stale && <Badge variant="destructive">stale</Badge>}
              <span className="text-xs text-muted-foreground">
                conf: {(claim.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <p className="text-sm">{claim.content}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>
            Source: <ClaimSourceLink entryId={claim.source_entry_id} />
          </span>
          {claim.source_offset_start != null && (
            <span>
              [{claim.source_offset_start}:{claim.source_offset_end}]
            </span>
          )}
          {claim.source_type && <Badge variant="secondary">{claim.source_type}</Badge>}
          {claim.source_actor && <Badge variant="outline">{claim.source_actor}</Badge>}
        </div>
      </CardContent>
    </Card>
  )
}

function ContradictionCard({ contradiction }: { contradiction: ClusterContradiction }) {
  return (
    <Card className="border-red-200">
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="border-red-300 text-red-600">
            contradicts
          </Badge>
          <span className="text-xs text-muted-foreground">
            confidence {(contradiction.confidence * 100).toFixed(0)}%
          </span>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-2 rounded-md border bg-muted/20 p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Source Claim
            </p>
            <p className="text-sm">{contradiction.source_claim_content}</p>
            <p className="text-xs text-muted-foreground">
              Claim {contradiction.source_claim_id}
              {contradiction.source_entry_id && (
                <>
                  {" · "}
                  <ClaimSourceLink entryId={contradiction.source_entry_id} />
                </>
              )}
            </p>
          </div>
          <div className="space-y-2 rounded-md border bg-muted/20 p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Target Claim
            </p>
            <p className="text-sm">
              {contradiction.target_claim_content ?? "Target claim not available."}
            </p>
            <p className="text-xs text-muted-foreground">
              {contradiction.target_claim_id ? `Claim ${contradiction.target_claim_id}` : "Missing target claim"}
              {contradiction.target_source_entry_id && (
                <>
                  {" · "}
                  <ClaimSourceLink entryId={contradiction.target_source_entry_id} />
                </>
              )}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function ReviewItemCard({ item }: { item: ReviewItem }) {
  const contextLines = formatReviewContext(item.context)

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{item.flag}</Badge>
          <Badge variant="secondary">priority {item.priority}</Badge>
          <span className="text-xs text-muted-foreground">raised by {item.raised_by}</span>
        </div>
        {contextLines.length > 0 && (
          <div className="space-y-1 text-sm text-muted-foreground">
            {contextLines.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function ClaimSourceLink({ entryId }: { entryId: string }) {
  return (
    <Link
      to={`/journal?entry=${encodeURIComponent(entryId)}`}
      className="font-mono text-primary underline-offset-4 hover:underline"
    >
      {entryId}
    </Link>
  )
}

function EmptyState({ text }: { text: string }) {
  return <p className="text-sm text-muted-foreground">{text}</p>
}

function normalizeText(value: string | null | undefined) {
  return value?.trim() ?? ""
}

function formatReviewContext(context: unknown): string[] {
  if (!context) return []
  if (typeof context === "string") return [context]
  if (Array.isArray(context)) return context.map((item) => String(item))
  if (typeof context === "object") {
    return Object.entries(context as Record<string, unknown>).map(([key, value]) => {
      const rendered = Array.isArray(value) ? value.join(", ") : String(value)
      return `${key}: ${rendered}`
    })
  }
  return [String(context)]
}
