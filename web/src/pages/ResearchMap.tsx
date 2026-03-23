import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Markdown } from "@/components/shared/Markdown"
import { useResearchMap, useRQClusters, useClusterClaims } from "@/hooks/useResearchMap"
import { ArrowLeft, AlertTriangle, CheckCircle, HelpCircle, Loader2, X } from "lucide-react"

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

type StatFilter = "gaps" | "contradictions" | null

export default function ResearchMap() {
  const { data: map, isLoading } = useResearchMap()
  const [selectedRQ, setSelectedRQ] = useState<string | null>(null)
  const [selectedCluster, setSelectedCluster] = useState<string | null>(null)
  const [statFilter, setStatFilter] = useState<StatFilter>(null)
  const { data: clusters } = useRQClusters(selectedRQ)
  const { data: claims } = useClusterClaims(selectedCluster)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  const summary = map?.summary

  // Detail view: Claims in a cluster
  if (selectedCluster) {
    const cluster = clusters?.find((c) => c.id === selectedCluster)
    return (
      <div className="space-y-4 p-6">
        <Button variant="ghost" size="sm" onClick={() => setSelectedCluster(null)}>
          <ArrowLeft className="h-4 w-4 mr-2" /> Back to clusters
        </Button>
        {cluster && (
          <div className="space-y-2">
            <h2 className="text-lg font-semibold">{cluster.label}</h2>
            {cluster.synthesis && (
              <div className="rounded-md border bg-muted/20 p-3 text-muted-foreground">
                <Markdown>{cluster.synthesis}</Markdown>
              </div>
            )}
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <Badge className={confidenceColors[cluster.confidence] || ""}>{cluster.confidence}</Badge>
              <span>{cluster.claim_count} claims</span>
              {cluster.synthesized_by === "brain" && (
                <Badge variant="secondary" className="text-xs">Brain-verified</Badge>
              )}
            </div>
          </div>
        )}
        <h3 className="text-base font-semibold">Claims</h3>
        <div className="space-y-3">
          {claims?.map((claim) => (
            <Card key={claim.id} className={claim.stale ? "opacity-50" : ""}>
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge className={claimTypeColors[claim.claim_type] || ""}>{claim.claim_type}</Badge>
                      {claim.verified && <CheckCircle className="h-4 w-4 text-green-500" />}
                      {claim.stale && <Badge variant="destructive">stale</Badge>}
                      <span className="text-xs text-muted-foreground">
                        conf: {(claim.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <p className="text-sm">{claim.content}</p>
                    <p className="text-xs text-muted-foreground mt-1 font-mono">
                      Source: {claim.source_entry_id}
                      {claim.source_offset_start != null && ` [${claim.source_offset_start}:${claim.source_offset_end}]`}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
          {(!claims || claims.length === 0) && (
            <p className="text-sm text-muted-foreground">No claims in this cluster yet.</p>
          )}
        </div>
      </div>
    )
  }

  // Cluster view: clusters for a research question
  if (selectedRQ) {
    const rq = map?.research_questions?.find((r) => r.id === selectedRQ)
    return (
      <div className="space-y-4 p-6">
        <Button variant="ghost" size="sm" onClick={() => setSelectedRQ(null)}>
          <ArrowLeft className="h-4 w-4 mr-2" /> Back to research questions
        </Button>
        {rq && (
          <div className="space-y-1">
            <h2 className="text-lg font-semibold">{rq.question}</h2>
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <span>{rq.cluster_count} clusters</span>
              <span>{rq.total_claims} claims</span>
              {rq.gap_count > 0 && (
                <span className="flex items-center gap-1 text-amber-600">
                  <HelpCircle className="h-3 w-3" /> {rq.gap_count} gaps
                </span>
              )}
            </div>
          </div>
        )}
        <h3 className="text-base font-semibold">Evidence Clusters</h3>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {clusters?.map((cluster) => (
            <Card
              key={cluster.id}
              className="cursor-pointer hover:shadow-md transition-shadow"
              onClick={() => setSelectedCluster(cluster.id)}
            >
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-medium">{cluster.label}</CardTitle>
                  <Badge className={confidenceColors[cluster.confidence] || ""}>
                    {cluster.confidence}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-2">
                {cluster.synthesis && (
                  <p className="text-xs text-muted-foreground line-clamp-3">{cluster.synthesis}</p>
                )}
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span>{cluster.claim_count} claims</span>
                  {cluster.gap_count > 0 && (
                    <span className="flex items-center gap-1 text-amber-600">
                      <HelpCircle className="h-3 w-3" /> {cluster.gap_count} gaps
                    </span>
                  )}
                  {cluster.needs_reprocessing && (
                    <Badge variant="outline" className="text-xs">needs reprocessing</Badge>
                  )}
                  {cluster.synthesized_by === "brain" && (
                    <Badge variant="secondary" className="text-xs">Brain-verified</Badge>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
          {(!clusters || clusters.length === 0) && (
            <p className="text-sm text-muted-foreground col-span-full">
              No evidence clusters for this research question yet.
            </p>
          )}
        </div>
      </div>
    )
  }

  // Filter research questions based on active stat filter
  const allRQs = map?.research_questions ?? []
  const filteredRQs = statFilter === "gaps"
    ? allRQs.filter((rq) => rq.gap_count > 0)
    : statFilter === "contradictions"
      ? allRQs.filter((rq) => rq.contradiction_count > 0)
      : allRQs

  // Overview: Research questions
  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Research Map</h1>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid gap-4 md:grid-cols-5">
          <Card>
            <CardContent className="p-4 text-center">
              <div className="text-2xl font-bold">{summary.total_rqs}</div>
              <div className="text-xs text-muted-foreground">Research Questions</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4 text-center">
              <div className="text-2xl font-bold">{summary.total_clusters}</div>
              <div className="text-xs text-muted-foreground">Evidence Clusters</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4 text-center">
              <div className="text-2xl font-bold">{summary.total_claims}</div>
              <div className="text-xs text-muted-foreground">Claims</div>
            </CardContent>
          </Card>
          <Card
            className={`cursor-pointer transition-all hover:shadow-md ${statFilter === "gaps" ? "ring-2 ring-amber-500" : ""}`}
            onClick={() => setStatFilter(statFilter === "gaps" ? null : "gaps")}
          >
            <CardContent className="p-4 text-center">
              <div className="text-2xl font-bold text-amber-600">{summary.total_gaps}</div>
              <div className="text-xs text-muted-foreground">Evidence Gaps</div>
              {statFilter === "gaps" && <div className="text-[10px] text-amber-600 mt-1">click to clear filter</div>}
            </CardContent>
          </Card>
          <Card
            className={`cursor-pointer transition-all hover:shadow-md ${statFilter === "contradictions" ? "ring-2 ring-red-500" : ""}`}
            onClick={() => setStatFilter(statFilter === "contradictions" ? null : "contradictions")}
          >
            <CardContent className="p-4 text-center">
              <div className="text-2xl font-bold text-red-600">{summary.total_contradictions}</div>
              <div className="text-xs text-muted-foreground">Contradictions</div>
              {statFilter === "contradictions" && <div className="text-[10px] text-red-600 mt-1">click to clear filter</div>}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Research questions */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Research Questions</h2>
          {statFilter && (
            <Button variant="ghost" size="sm" onClick={() => setStatFilter(null)} className="text-xs gap-1">
              <X className="h-3 w-3" />
              Clear filter ({filteredRQs.length} of {allRQs.length})
            </Button>
          )}
        </div>
        {filteredRQs.map((rq) => (
          <Card
            key={rq.id}
            className="cursor-pointer hover:shadow-md transition-shadow"
            onClick={() => setSelectedRQ(rq.id)}
          >
            <CardContent className="p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <h3 className="font-medium">{rq.question}</h3>
                  <div className="flex items-center gap-4 mt-2 text-sm text-muted-foreground">
                    <span>{rq.cluster_count} clusters</span>
                    <span>{rq.total_claims} claims</span>
                    {rq.gap_count > 0 && (
                      <Badge variant="outline" className="text-amber-600 border-amber-300 gap-1">
                        <HelpCircle className="h-3 w-3" /> {rq.gap_count} gaps
                      </Badge>
                    )}
                    {rq.contradiction_count > 0 && (
                      <Badge variant="outline" className="text-red-600 border-red-300 gap-1">
                        <AlertTriangle className="h-3 w-3" /> {rq.contradiction_count} contradictions
                      </Badge>
                    )}
                  </div>
                </div>
                <Badge variant={rq.status === "active" ? "default" : "secondary"}>
                  {rq.status}
                </Badge>
              </div>
            </CardContent>
          </Card>
        ))}
        {filteredRQs.length === 0 && allRQs.length > 0 && (
          <Card>
            <CardContent className="p-8 text-center text-muted-foreground">
              <p>No research questions match the current filter.</p>
              <Button variant="ghost" size="sm" onClick={() => setStatFilter(null)} className="mt-2">
                Clear filter
              </Button>
            </CardContent>
          </Card>
        )}
        {allRQs.length === 0 && (
          <Card>
            <CardContent className="p-8 text-center text-muted-foreground">
              <p>No research questions yet.</p>
              <p className="text-sm mt-1">
                Create decisions with kind="research_question" to populate the research map.
              </p>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Unassigned clusters */}
      {map?.unassigned_clusters && map.unassigned_clusters.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold">Unassigned Clusters</h2>
          <div className="grid gap-3 md:grid-cols-3">
            {map.unassigned_clusters.map((c) => (
              <Card key={c.id}>
                <CardContent className="p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">{c.label}</span>
                    <Badge className={confidenceColors[c.confidence] || ""}>{c.confidence}</Badge>
                  </div>
                  <span className="text-xs text-muted-foreground">{c.claim_count} claims</span>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
