import { useMemo } from "react"
import type { FormEvent } from "react"
import { ArrowUpRight, CheckCircle2, FilePenLine, Loader2, Route } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { usePlanningBranches } from "@/hooks/usePlanningBranches"
import type {
  ManuscriptContext,
  PlanningArtifact,
  PlanningPromotionEvent,
  PlanningWorkflowVerdict,
} from "@/api/types"

type Candidate = Record<string, unknown> & {
  local_key: string
  disposition?: string
  question?: string
  scope?: string
  exact_wording?: string
  contribution_type?: string
}

function candidates(value: unknown): Candidate[] {
  return Array.isArray(value)
    ? value.filter((item): item is Candidate => (
      Boolean(item)
      && typeof item === "object"
      && typeof (item as Record<string, unknown>).local_key === "string"
    ))
    : []
}

function verdictVariant(verdict: PlanningWorkflowVerdict) {
  if (verdict === "Ready") return "default" as const
  if (verdict === "Blocked") return "destructive" as const
  return "outline" as const
}

function latestEvent(
  events: PlanningPromotionEvent[],
  candidateKey: string,
  action: PlanningPromotionEvent["action"],
) {
  return [...events].reverse().find(
    (event) => event.candidate_key === candidateKey && event.action === action,
  )
}

export function ArgumentWorkflowPanel({
  manuscriptId,
  context,
}: {
  manuscriptId: string | null
  context?: ManuscriptContext
}) {
  const planning = usePlanningBranches(manuscriptId)
  const workflow = planning.workflow.data
  const promotionEvents = useMemo(
    () => planning.promotions.data ?? [],
    [planning.promotions.data],
  )
  const rqStage = workflow?.stages.find((stage) => stage.stage_type === "rq_contribution")
  const portfolio = rqStage?.current_artifact ?? null
  const payload = portfolio?.version.payload ?? {}
  const researchQuestions = candidates(payload.research_questions)
  const contributions = candidates(payload.contributions)

  const promoteResearchQuestion = async (candidate: Candidate) => {
    if (!workflow || !portfolio) return
    try {
      await planning.promoteResearchQuestion.mutateAsync({
        branchId: workflow.branch.id,
        data: {
          expected_branch_revision: workflow.branch.revision,
          artifact_id: portfolio.id,
          expected_artifact_version: portfolio.version.version,
          candidate_key: candidate.local_key,
          phase: "paper_framing",
          reason: "PI promoted the selected bounded research question in the manuscript workbench.",
        },
      })
      toast.success("Research question promoted to an auditable PI decision")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Research-question promotion failed")
    }
  }

  const prepareContribution = async (candidate: Candidate) => {
    if (!workflow || !portfolio || !manuscriptId || !context) return
    try {
      await planning.prepareContribution.mutateAsync({
        branchId: workflow.branch.id,
        data: {
          expected_branch_revision: workflow.branch.revision,
          artifact_id: portfolio.id,
          expected_artifact_version: portfolio.version.version,
          candidate_key: candidate.local_key,
          manuscript_id: manuscriptId,
          expected_manuscript_revision: context.manuscript.revision,
          reason: "Prepare the selected bounded contribution for explicit semantic review.",
          actor: "web_ui",
        },
      })
      toast.success("Contribution proposal prepared; the manuscript is unchanged")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Contribution proposal failed")
    }
  }

  const ratifyContribution = async (
    event: FormEvent<HTMLFormElement>,
    candidate: Candidate,
    applied: PlanningPromotionEvent,
  ) => {
    event.preventDefault()
    if (!workflow || !portfolio || !manuscriptId || !context || !applied.proposal_id) return
    const decisionId = String(new FormData(event.currentTarget).get("decision_id") ?? "").trim()
    if (!decisionId) return
    try {
      await planning.ratifyContribution.mutateAsync({
        branchId: workflow.branch.id,
        data: {
          expected_branch_revision: workflow.branch.revision,
          artifact_id: portfolio.id,
          expected_artifact_version: portfolio.version.version,
          candidate_key: candidate.local_key,
          manuscript_id: manuscriptId,
          claim_ref: applied.target_id,
          expected_manuscript_revision: context.manuscript.revision,
          proposal_id: applied.proposal_id,
          decision_id: decisionId,
          reason: "PI ratified the exact applied contribution wording in the manuscript workbench.",
        },
      })
      event.currentTarget.reset()
      toast.success("Exact contribution wording ratified")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Contribution ratification failed")
    }
  }

  const loading = planning.resume.isLoading || planning.workflow.isLoading
  const error = planning.workflow.error ?? planning.promotions.error

  return (
    <Card>
      <CardHeader className="gap-2 pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Route className="h-4 w-4" /> Seed-to-contribution workflow
          </CardTitle>
          <Badge variant="outline">deterministic</Badge>
          {workflow?.next_recommended_stage && (
            <Badge>next: {workflow.next_recommended_stage.replaceAll("_", " ")}</Badge>
          )}
        </div>
        <p className="max-w-4xl text-xs text-muted-foreground">
          Guidance reads the selected immutable branch head. Navigation remains non-linear; promotion and
          ratification are separate explicit actions, and this projection performs no model call.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading && (
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Reconstructing the selected argument…
          </p>
        )}
        {error && <p role="alert" className="text-sm text-red-700">{error.message}</p>}
        {!loading && !workflow && (
          <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            Select or create a planning branch to start the guided argument workflow.
          </div>
        )}

        {workflow && (
          <>
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
              {workflow.stages.map((stage) => (
                <div key={stage.stage_type} className="rounded-lg border p-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium">{stage.label}</p>
                    <Badge variant={verdictVariant(stage.verdict)}>{stage.verdict}</Badge>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{stage.next_action}</p>
                  {stage.current_artifact && (
                    <p className="mt-2 font-mono text-[10px] text-muted-foreground">
                      {stage.current_artifact.local_key} · v{stage.current_artifact.version.version}
                    </p>
                  )}
                  {[...stage.blockers, ...stage.warnings].slice(0, 2).map((finding) => (
                    <p key={finding} className="mt-1 text-[11px] text-amber-800 dark:text-amber-200">
                      {finding}
                    </p>
                  ))}
                </div>
              ))}
            </div>

            <div className="grid gap-3 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
              <div className="rounded-lg border p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-medium">Quick-reader spine</p>
                  <Badge variant="outline">provisional sources shown</Badge>
                </div>
                {workflow.quick_reader.slots.length ? (
                  <ol className="mt-3 space-y-2">
                    {workflow.quick_reader.slots.map((slot) => (
                      <li key={`${slot.slot}:${slot.source.version_id}`} className="rounded-md bg-muted/40 p-2 text-xs">
                        <span className="font-medium">{slot.slot.replaceAll("_", " ")}: </span>
                        {slot.text}
                        <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                          {slot.source.artifact_id} · v{slot.source.version}
                        </p>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Select stage artifacts to populate this source-linked projection.
                  </p>
                )}
                {workflow.quick_reader.discrepancies.length > 0 && (
                  <p className="mt-3 text-xs text-amber-800 dark:text-amber-200">
                    {workflow.quick_reader.discrepancies.length} paragraph/stage discrepancy
                    {workflow.quick_reader.discrepancies.length === 1 ? "" : "ies"} require review.
                  </p>
                )}
              </div>

              <CandidatePromotionPanel
                portfolio={portfolio}
                researchQuestions={researchQuestions}
                contributions={contributions}
                promotionEvents={promotionEvents}
                manuscriptReady={Boolean(manuscriptId && context)}
                pending={planning.promoteResearchQuestion.isPending
                  || planning.prepareContribution.isPending
                  || planning.ratifyContribution.isPending}
                onPromoteResearchQuestion={promoteResearchQuestion}
                onPrepareContribution={prepareContribution}
                onRatifyContribution={ratifyContribution}
              />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function CandidatePromotionPanel({
  portfolio,
  researchQuestions,
  contributions,
  promotionEvents,
  manuscriptReady,
  pending,
  onPromoteResearchQuestion,
  onPrepareContribution,
  onRatifyContribution,
}: {
  portfolio: PlanningArtifact | null
  researchQuestions: Candidate[]
  contributions: Candidate[]
  promotionEvents: PlanningPromotionEvent[]
  manuscriptReady: boolean
  pending: boolean
  onPromoteResearchQuestion: (candidate: Candidate) => Promise<void>
  onPrepareContribution: (candidate: Candidate) => Promise<void>
  onRatifyContribution: (
    event: FormEvent<HTMLFormElement>,
    candidate: Candidate,
    applied: PlanningPromotionEvent,
  ) => Promise<void>
}) {
  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div>
        <p className="text-sm font-medium">Candidate promotion</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Only candidates in a selected, ready portfolio can cross into canonical RKA state.
        </p>
      </div>
      {!portfolio && (
        <p className="text-xs text-muted-foreground">No selected RQ/contribution portfolio is ready.</p>
      )}
      {researchQuestions.map((candidate) => {
        const promoted = latestEvent(promotionEvents, candidate.local_key, "rq_promoted")
        return (
          <div key={candidate.local_key} className="rounded-md bg-muted/40 p-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">RQ</Badge>
              <span className="font-medium">{candidate.local_key}</span>
              {promoted && <Badge variant="secondary">decision {promoted.target_id}</Badge>}
            </div>
            <p className="mt-2">{candidate.question}</p>
            {candidate.scope && <p className="mt-1 text-muted-foreground">Scope: {candidate.scope}</p>}
            {candidate.disposition === "selected" && !promoted && (
              <Button size="xs" className="mt-2" disabled={pending} onClick={() => void onPromoteResearchQuestion(candidate)}>
                <ArrowUpRight className="mr-1 h-3.5 w-3.5" /> Promote to PI decision
              </Button>
            )}
          </div>
        )
      })}
      {contributions.map((candidate) => {
        const prepared = latestEvent(
          promotionEvents, candidate.local_key, "contribution_proposal_prepared",
        )
        const applied = latestEvent(
          promotionEvents, candidate.local_key, "contribution_proposal_applied",
        )
        const ratified = latestEvent(
          promotionEvents, candidate.local_key, "contribution_ratified",
        )
        return (
          <div key={candidate.local_key} className="rounded-md bg-muted/40 p-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">contribution</Badge>
              <span className="font-medium">{candidate.local_key}</span>
              {prepared && <Badge variant="secondary">proposal {prepared.proposal_status ?? "prepared"}</Badge>}
              {applied && <Badge variant="secondary">applied v{applied.target_version}</Badge>}
              {ratified && <Badge><CheckCircle2 className="mr-1 h-3 w-3" /> ratified</Badge>}
            </div>
            <p className="mt-2">{candidate.exact_wording}</p>
            {candidate.disposition === "selected" && !prepared && (
              <Button
                size="xs"
                variant="outline"
                className="mt-2"
                disabled={pending || !manuscriptReady}
                onClick={() => void onPrepareContribution(candidate)}
              >
                <FilePenLine className="mr-1 h-3.5 w-3.5" /> Prepare review proposal
              </Button>
            )}
            {applied && !ratified && (
              <form
                className="mt-2 flex flex-col gap-2 sm:flex-row"
                onSubmit={(event) => void onRatifyContribution(event, candidate, applied)}
              >
                <Input
                  name="decision_id"
                  required
                  pattern="dec_.+"
                  placeholder="Exact-wording PI decision (dec_...)"
                  aria-label={`PI decision for ${candidate.local_key}`}
                  className="h-8 text-xs"
                />
                <Button size="xs" type="submit" disabled={pending || !manuscriptReady}>
                  Ratify exact version
                </Button>
              </form>
            )}
          </div>
        )
      })}
      {promotionEvents.length > 0 && (
        <details className="rounded-md border p-2 text-xs">
          <summary className="cursor-pointer font-medium">Audit {promotionEvents.length} promotion events</summary>
          <ol className="mt-2 space-y-1 text-muted-foreground">
            {promotionEvents.map((event) => (
              <li key={event.id}>
                {event.action.replaceAll("_", " ")} · {event.candidate_key} · {event.target_id}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  )
}
