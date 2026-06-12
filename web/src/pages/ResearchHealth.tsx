import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  useResearchHealth,
  useFileStalenessReviews,
  useLinkSupportAudit,
} from "@/hooks/useResearchHealth"
import { toast } from "sonner"
import {
  Activity,
  AlertTriangle,
  ClipboardCheck,
  FileWarning,
  Loader2,
  Rocket,
  ScrollText,
} from "lucide-react"
import type { CoverageCounts } from "@/api/types"

export default function ResearchHealth() {
  const { data: health, isLoading } = useResearchHealth()

  if (isLoading) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold tracking-tight">Research Health</h1>
        <div className="grid gap-4 md:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-40 rounded-lg bg-muted animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Research Health</h1>
        <p className="text-muted-foreground text-sm">
          Provenance coverage, research-debt trajectory, and verification actions
        </p>
      </div>

      {health && (
        <>
          <div className="grid gap-4 md:grid-cols-3">
            {/* Provenance Coverage */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <Activity className="h-4 w-4" />
                  Provenance Coverage
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <CoverageRow
                  label="Decisions with evidence"
                  pct={health.provenance_coverage.decisions_with_evidence_pct}
                  counts={health.provenance_coverage.decisions}
                />
                <CoverageRow
                  label="Missions with motivation"
                  pct={health.provenance_coverage.missions_with_motivation_pct}
                  counts={health.provenance_coverage.missions}
                />
                <CoverageRow
                  label="Claims with source"
                  pct={health.provenance_coverage.claims_with_source_pct}
                  counts={health.provenance_coverage.claims}
                />
                <div className="border-t pt-2 text-xs text-muted-foreground space-y-1">
                  <div className="flex items-center justify-between">
                    <span>Superseded decisions</span>
                    <span className="font-mono">
                      {health.provenance_coverage.supersede_chain_integrity.superseded_decisions}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Orphaned pointers</span>
                    {health.provenance_coverage.supersede_chain_integrity.orphaned_pointers > 0 ? (
                      <Badge
                        variant="outline"
                        className="text-[10px] font-medium bg-amber-100 text-amber-800 border-amber-200 gap-1"
                      >
                        <AlertTriangle className="h-3 w-3" />
                        {health.provenance_coverage.supersede_chain_integrity.orphaned_pointers}
                      </Badge>
                    ) : (
                      <span className="font-mono">0</span>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Mission Cycle */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <Rocket className="h-4 w-4" />
                  Mission Cycle
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <StatRow label="Completed missions" value={health.mission_cycle.completed} />
                <StatRow
                  label="Avg days to complete"
                  value={health.mission_cycle.avg_days_to_complete ?? "—"}
                />
                <StatRow
                  label="Max days to complete"
                  value={health.mission_cycle.max_days_to_complete ?? "—"}
                />
                <StatRow label="Checkpoints total" value={health.mission_cycle.checkpoints_total} />
                <StatRow label="Checkpoints open" value={health.mission_cycle.checkpoints_open} />
              </CardContent>
            </Card>

            {/* Bookkeeping Overhead */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <ScrollText className="h-4 w-4" />
                  Bookkeeping Overhead
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="text-2xl font-bold">
                  {health.bookkeeping_overhead.write_share_pct}%
                </div>
                <p className="text-xs text-muted-foreground">
                  write share of recorded actions
                </p>
                <div className="border-t pt-2 space-y-1 text-xs text-muted-foreground">
                  {Object.entries(health.bookkeeping_overhead.recorded_actions)
                    .sort(([, a], [, b]) => b - a)
                    .map(([action, count]) => (
                      <div key={action} className="flex items-center justify-between">
                        <span>{action}</span>
                        <span className="font-mono">{count.toLocaleString()}</span>
                      </div>
                    ))}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Weekly debt trajectory */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">
                Research Debt Trajectory (weekly)
              </CardTitle>
            </CardHeader>
            <CardContent>
              {health.research_debt_trajectory_weekly.length === 0 ? (
                <p className="text-sm text-muted-foreground">No decisions recorded yet</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Week</TableHead>
                      <TableHead className="text-right">Created</TableHead>
                      <TableHead className="text-right">Covered</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {health.research_debt_trajectory_weekly.map((row) => (
                      <TableRow key={row.week}>
                        <TableCell className="font-mono text-xs">{row.week}</TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {row.created}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {row.covered}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </>
      )}

      <VerificationActions />
    </div>
  )
}

function CoverageRow({
  label,
  pct,
  counts,
}: {
  label: string
  pct: number
  counts: CoverageCounts
}) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span>
        <span className="font-bold">{pct}%</span>{" "}
        <span className="text-xs text-muted-foreground font-mono">
          ({counts.covered}/{counts.total})
        </span>
      </span>
    </div>
  )
}

function StatRow({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  )
}

function VerificationActions() {
  const fileReviews = useFileStalenessReviews()
  const linkAudit = useLinkSupportAudit()

  const handleFileReviews = async () => {
    try {
      const result = await fileReviews.mutateAsync()
      toast.success(
        `Filed ${result.filed} staleness review(s) across ${result.stale_roots} stale root(s)`,
      )
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to file staleness reviews")
    }
  }

  const handleLinkAudit = async () => {
    try {
      await linkAudit.mutateAsync(200)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Link-support audit failed")
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium">Verification Actions</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            className="gap-2"
            onClick={handleFileReviews}
            disabled={fileReviews.isPending}
          >
            {fileReviews.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FileWarning className="h-4 w-4" />
            )}
            File staleness reviews
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="gap-2"
            onClick={handleLinkAudit}
            disabled={linkAudit.isPending}
          >
            {linkAudit.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ClipboardCheck className="h-4 w-4" />
            )}
            Run link-support audit
          </Button>
        </div>

        {fileReviews.data && (
          <p className="text-xs text-muted-foreground">
            Last run: {fileReviews.data.filed} review(s) filed,{" "}
            {fileReviews.data.stale_roots} stale root(s) walked
          </p>
        )}

        {linkAudit.data && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Checked {linkAudit.data.checked_decisions} decision(s) and{" "}
              {linkAudit.data.checked_clusters} cluster(s) — method: {linkAudit.data.method}
            </p>
            {linkAudit.data.unsupported.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No unsupported provenance links found
              </p>
            ) : (
              <div className="space-y-1">
                {linkAudit.data.unsupported.map((item) => (
                  <div
                    key={`${item.item_type}-${item.item_id}`}
                    className="rounded border p-2 text-sm space-y-1"
                  >
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary" className="text-[10px]">
                        {item.item_type}
                      </Badge>
                      <span className="font-medium truncate">{item.label}</span>
                      <Badge
                        variant="outline"
                        className="text-[10px] font-medium bg-amber-100 text-amber-800 border-amber-200 ml-auto shrink-0"
                      >
                        support {item.support}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">{item.detail}</p>
                    <p className="text-[10px] text-muted-foreground font-mono">{item.item_id}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
