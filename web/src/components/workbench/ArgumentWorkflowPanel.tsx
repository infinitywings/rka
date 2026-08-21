import { useMemo, useState } from "react"
import type { FormEvent } from "react"
import { ArrowUpRight, CheckCircle2, FilePenLine, FlaskConical, Loader2, Route } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { usePlanningBranches } from "@/hooks/usePlanningBranches"
import { useSemanticPatches } from "@/hooks/useSemanticPatches"
import type {
  ManuscriptContext,
  PlanningArgumentWorkflow,
  PlanningArtifact,
  PlanningEvaluationCommitmentView,
  PlanningEvaluationRequirementView,
  PlanningEvaluationWorkflow,
  PlanningPromotionEvent,
  PlanningStage,
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

function lines(value: string) {
  return [...new Set(value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean))]
}

function planningEntityType(entityId: string) {
  const prefix = entityId.split("_", 1)[0]
  const types: Record<string, string> = {
    jrn: "journal",
    lit: "literature",
    dec: "decision",
    clm: "claim",
    csc: "claim_scope",
    ecl: "cluster",
    icd: "interpretation_candidate",
    exp: "experiment",
    epv: "experiment_plan_version",
    run: "experiment_run",
    obs: "experiment_observation",
    elc: "evidence_locator",
    art: "artifact",
    man: "manuscript",
    mcl: "manuscript_claim",
    mun: "manuscript_unit",
  }
  const entityType = types[prefix]
  if (!entityType) throw new Error(`Unsupported RKA evidence identifier: ${entityId}`)
  return entityType
}

const STAGE_TEMPLATES: Record<PlanningStage, Record<string, unknown>> = {
  seed: {
    insight: "State the one-sentence insight.",
    significance: "Explain why this changes the research conversation.",
    audience: [],
  },
  paragraph_spine: {
    problem: "What concrete problem matters?",
    gap: "What defensible gap remains?",
    insight: "What is the core insight?",
    response: "How does the work act on the insight?",
    payoff: "What can a quick reader now understand or do?",
  },
  problem_scope: {
    problem: "Define the problem precisely.",
    in_scope: ["Name one included setting."],
    out_of_scope: ["Name one material exclusion."],
    assumptions: [],
    key_terms: [],
  },
  landscape_gap: {
    state_of_the_art: ["Summarize one evidence-backed SOTA capability."],
    limitations: ["State a bounded limitation without caricaturing prior work."],
    gap: "State the exact gap this paper addresses.",
    motivation: "Explain why closing this gap matters.",
  },
  response_mechanism: {
    insight: "State the mechanism-level insight.",
    mechanism_steps: ["Describe the first causal or design step."],
    expected_effect: "State the expected bounded effect.",
    boundary_conditions: ["State where the mechanism is expected to hold."],
  },
  challenge_innovation: {
    pairs: [{
      local_key: "challenge-1",
      challenge: "State the challenge created by the gap and proposed response.",
      innovation: "State the corresponding innovation.",
      required_evidence: ["Name the evidence needed to support this innovation."],
    }],
  },
  rq_contribution: {
    research_questions: [{
      local_key: "rq-1",
      question: "State a bounded research question.",
      scope: "State the exact operating scope.",
      rationale: "Explain why answering it resolves the central uncertainty.",
      evidence_entity_ids: [],
      missing_evidence: [],
      disposition: "candidate",
    }],
    contributions: [{
      local_key: "contribution-1",
      exact_wording: "State the exact provisional contribution wording.",
      contribution_type: "empirical",
      research_question_refs: ["rq-1"],
      allowed_wording: "State the strongest wording currently allowed.",
      prohibited_wording: ["State one tempting but unsupported extension."],
      support_ids: [],
      missing_evidence: ["Name evidence still needed before selection."],
      disposition: "candidate",
    }],
  },
  evaluation: {
    commitments: [{
      local_key: "claim-primary-evaluation",
      claim_id: "mcl_REPLACE_WITH_EXACT_ID",
      claim_version: 1,
      research_question_refs: ["dec_REPLACE_WITH_RQ_ID"],
      method: "Describe the exact evaluation method.",
      requirements: [{
        local_key: "primary-effect",
        kind: "support",
        description: "State the evidence needed to support or falsify the claim.",
        required: true,
        acceptance_criteria: ["State the exact success criterion."],
        failure_criteria: ["State the exact falsification criterion."],
        observations: [],
        missing_evidence: "Describe the work needed to collect exact evidence.",
      }],
      baselines: ["Name the baseline or control."],
      metrics: ["Name the metric or observation."],
      conditions: ["State the tested condition."],
      success_criteria: ["State what would support the bounded claim."],
      failure_criteria: ["State what would fail to support it."],
      allowed_interpretation: "State the strongest interpretation currently allowed.",
      prohibited_interpretation: ["State one tempting unsupported extension."],
      disposition: "candidate",
    }],
    validity_checks: ["State one validity check."],
  },
  outline: { units: [{ local_key: "intro", title: "Introduction", purpose: "" }] },
  review: { focus: "", findings: [] },
}

export function ArgumentWorkflowPanel({
  manuscriptId,
  context,
}: {
  manuscriptId: string | null
  context?: ManuscriptContext
}) {
  const planning = usePlanningBranches(manuscriptId)
  const patches = useSemanticPatches()
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
  const evaluation = planning.evaluation.data

  const proposeStageDraft = async (
    stage: PlanningStage,
    form: FormData,
  ) => {
    if (!workflow) return
    const localKey = String(form.get("local_key") ?? "").trim()
    const summary = String(form.get("summary") ?? "").trim()
    const reason = String(form.get("reason") ?? "").trim()
    const lifecycle = String(form.get("lifecycle") ?? "candidate")
    const readinessState = String(form.get("readiness_state") ?? "in_progress")
    const stageView = workflow.stages.find((item) => item.stage_type === stage)
    const existing = stageView?.candidate_artifacts.find(
      (artifact) => artifact.local_key === localKey,
    )
    try {
      const parsedPayload = JSON.parse(
        String(form.get("payload") ?? "{}"),
      ) as Record<string, unknown>
      const upstreamVersions = (stageView?.prerequisites ?? []).flatMap((prerequisite) => {
        const head = workflow.stages.find(
          (item) => item.stage_type === prerequisite,
        )?.current_artifact
        return head ? [{
          stage_type: prerequisite,
          local_key: head.local_key,
          artifact_id: head.id,
          version_id: head.version.id,
          version: head.version.version,
        }] : []
      })
      if (upstreamVersions.length) parsedPayload.upstream_versions = upstreamVersions
      else delete parsedPayload.upstream_versions
      const evidenceIds = lines(String(form.get("evidence_ids") ?? ""))
      await patches.create.mutateAsync({
        origin: "human",
        intent: `${existing ? "Revise" : "Capture"} ${stage.replaceAll("_", " ")} option ${localKey}.`,
        reason,
        created_by: "web_ui",
        operations: [{
          operation: "planning_artifact_upsert",
          branch_id: workflow.branch.id,
          append: {
            expected_branch_revision: workflow.branch.revision,
            expected_previous_version: existing?.version.version ?? 0,
            local_key: localKey,
            stage_type: stage,
            lifecycle,
            summary,
            payload: parsedPayload,
            origin: existing ? "user_revised" : "user",
            unresolved_items: lines(String(form.get("unresolved_items") ?? "")),
            readiness_state: readinessState,
            readiness_missing: lines(String(form.get("readiness_missing") ?? "")),
            created_by: "web_ui",
            reason,
            evidence_bindings: evidenceIds.map((entityId, ordinal) => ({
              entity_type: planningEntityType(entityId),
              entity_id: entityId,
              role: "support",
              ordinal,
            })),
          },
        }],
      })
      toast.success("Stage draft saved as a semantic proposal; the branch is unchanged")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Stage proposal failed")
    }
  }

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

  const createEvaluationMission = async (
    commitment: PlanningEvaluationCommitmentView,
    requirement: PlanningEvaluationRequirementView,
  ) => {
    if (!evaluation?.artifact || !commitment.commitment.local_key) return
    try {
      await planning.createEvaluationMission.mutateAsync({
        branchId: evaluation.branch.id,
        data: {
          expected_branch_revision: evaluation.branch.revision,
          artifact_id: evaluation.artifact.id,
          expected_artifact_version: evaluation.artifact.version.version,
          commitment_key: commitment.commitment.local_key,
          requirement_key: requirement.requirement.local_key,
          reason: "Create executable work for this exact missing-evidence requirement.",
          actor: "web_ui",
        },
      })
      toast.success("Missing-evidence mission created with exact contract provenance")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Evaluation mission failed")
    }
  }

  const prepareEvaluationResult = async (
    event: FormEvent<HTMLFormElement>,
    commitment: PlanningEvaluationCommitmentView,
  ) => {
    event.preventDefault()
    if (!evaluation?.artifact || !commitment.commitment.local_key || !manuscriptId || !context) return
    const form = new FormData(event.currentTarget)
    try {
      await planning.prepareEvaluationResult.mutateAsync({
        branchId: evaluation.branch.id,
        data: {
          expected_branch_revision: evaluation.branch.revision,
          artifact_id: evaluation.artifact.id,
          expected_artifact_version: evaluation.artifact.version.version,
          commitment_key: commitment.commitment.local_key,
          manuscript_id: manuscriptId,
          expected_manuscript_revision: context.manuscript.revision,
          result_unit_local_key: String(form.get("result_unit_local_key") ?? "").trim(),
          location: String(form.get("location") ?? "").trim(),
          title: String(form.get("title") ?? "").trim(),
          artifact_ref: String(form.get("artifact_ref") ?? "").trim(),
          reason: "Prepare a bounded result unit from the exact located evidence.",
          actor: "web_ui",
        },
      })
      toast.success("Result-unit proposal prepared; the manuscript is unchanged")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Result proposal failed")
    }
  }

  const loading = planning.resume.isLoading || planning.workflow.isLoading
  const error = planning.workflow.error ?? planning.promotions.error ?? planning.evaluation.error

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

            <StageDraftEditor
              workflow={workflow}
              pending={patches.create.isPending}
              onPropose={proposeStageDraft}
            />

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

            <EvaluationContractMatrix
              workflow={evaluation}
              manuscriptReady={Boolean(manuscriptId && context)}
              pending={planning.createEvaluationMission.isPending
                || planning.prepareEvaluationResult.isPending}
              onCreateMission={createEvaluationMission}
              onPrepareResult={prepareEvaluationResult}
            />
          </>
        )}
      </CardContent>
    </Card>
  )
}

const EDITABLE_ARGUMENT_STAGES: PlanningStage[] = [
  "seed",
  "paragraph_spine",
  "problem_scope",
  "landscape_gap",
  "response_mechanism",
  "challenge_innovation",
  "rq_contribution",
  "evaluation",
]

function StageDraftEditor({
  workflow,
  pending,
  onPropose,
}: {
  workflow: PlanningArgumentWorkflow
  pending: boolean
  onPropose: (stage: PlanningStage, form: FormData) => Promise<void>
}) {
  const [stage, setStage] = useState<PlanningStage>(
    workflow.next_recommended_stage && EDITABLE_ARGUMENT_STAGES.includes(
      workflow.next_recommended_stage,
    ) ? workflow.next_recommended_stage : "seed",
  )
  const stageView = workflow.stages.find((item) => item.stage_type === stage)
  const current = stageView?.current_artifact ?? null
  const existingEvidence = current?.version.evidence_bindings.map(
    (binding) => binding.entity_id,
  ).join("\n") ?? ""
  const formKey = `${stage}:${current?.version.id ?? "new"}`

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await onPropose(stage, new FormData(event.currentTarget))
  }

  return (
    <div className="rounded-lg border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium">Draft or revise a stage option</p>
          <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
            Each save creates a reviewable ADR 0006 proposal. Apply it separately in Edit proposals;
            changing an existing local key appends a version, while a new key preserves an alternative.
          </p>
        </div>
        <label className="space-y-1 text-xs font-medium">
          Stage
          <select
            className="block h-8 rounded-lg border border-input bg-background px-2 text-sm"
            value={stage}
            onChange={(event) => setStage(event.target.value as PlanningStage)}
          >
            {EDITABLE_ARGUMENT_STAGES.map((item) => (
              <option key={item} value={item}>{item.replaceAll("_", " ")}</option>
            ))}
          </select>
        </label>
      </div>
      <form key={formKey} onSubmit={submit} className="mt-3 grid gap-3 lg:grid-cols-2">
        <label className="space-y-1 text-xs font-medium">
          Stable option key
          <Input
            name="local_key"
            required
            defaultValue={current?.local_key ?? `${stage}-primary`}
            placeholder={`${stage}-primary`}
          />
        </label>
        <label className="space-y-1 text-xs font-medium">
          Scan-friendly summary
          <Input
            name="summary"
            required
            defaultValue={current?.version.summary ?? ""}
            placeholder="What changed or what choice does this option preserve?"
          />
        </label>
        <label className="space-y-1 text-xs font-medium">
          Lifecycle
          <select
            name="lifecycle"
            defaultValue={current?.version.lifecycle ?? "candidate"}
            className="block h-9 w-full rounded-lg border border-input bg-background px-2 text-sm"
          >
            <option value="candidate">candidate</option>
            <option value="reviewed">reviewed</option>
            <option value="selected">selected</option>
            <option value="parked">parked</option>
          </select>
        </label>
        <label className="space-y-1 text-xs font-medium">
          Mechanical readiness
          <select
            name="readiness_state"
            defaultValue={current?.version.readiness_state ?? "in_progress"}
            className="block h-9 w-full rounded-lg border border-input bg-background px-2 text-sm"
          >
            <option value="in_progress">in progress</option>
            <option value="ready">ready</option>
            <option value="blocked">blocked</option>
          </select>
        </label>
        <label className="space-y-1 text-xs font-medium lg:col-span-2">
          Typed stage payload
          <Textarea
            name="payload"
            required
            rows={14}
            spellCheck={false}
            className="font-mono text-xs"
            defaultValue={JSON.stringify(
              current?.version.payload ?? STAGE_TEMPLATES[stage],
              null,
              2,
            )}
          />
          <span className="block font-normal text-muted-foreground">
            Exact prerequisite heads are pinned automatically when the proposal is created.
          </span>
        </label>
        <label className="space-y-1 text-xs font-medium">
          RKA evidence/context IDs
          <Textarea
            name="evidence_ids"
            rows={4}
            defaultValue={existingEvidence}
            placeholder={"One ID per line, for example:\nclm_...\nlit_..."}
          />
        </label>
        <div className="grid gap-3">
          <label className="space-y-1 text-xs font-medium">
            Unresolved items
            <Textarea
              name="unresolved_items"
              rows={2}
              defaultValue={current?.version.unresolved_items.join("\n") ?? ""}
              placeholder="One unresolved question per line"
            />
          </label>
          <label className="space-y-1 text-xs font-medium">
            Missing before ready
            <Textarea
              name="readiness_missing"
              rows={2}
              defaultValue={current?.version.readiness_missing.join("\n") ?? ""}
              placeholder="One missing dependency per line"
            />
          </label>
        </div>
        <label className="space-y-1 text-xs font-medium lg:col-span-2">
          Reason for this version
          <Input
            name="reason"
            required
            placeholder="Why should this option or revision be preserved?"
          />
        </label>
        <div className="flex flex-wrap items-center justify-between gap-2 lg:col-span-2">
          <p className="text-xs text-muted-foreground">
            Select, revise, combine under a new key, or park an option without erasing history.
          </p>
          <Button type="submit" size="sm" disabled={pending}>
            {pending && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
            Save review proposal
          </Button>
        </div>
      </form>
    </div>
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

function EvaluationContractMatrix({
  workflow,
  manuscriptReady,
  pending,
  onCreateMission,
  onPrepareResult,
}: {
  workflow?: PlanningEvaluationWorkflow
  manuscriptReady: boolean
  pending: boolean
  onCreateMission: (
    commitment: PlanningEvaluationCommitmentView,
    requirement: PlanningEvaluationRequirementView,
  ) => Promise<void>
  onPrepareResult: (
    event: FormEvent<HTMLFormElement>,
    commitment: PlanningEvaluationCommitmentView,
  ) => Promise<void>
}) {
  if (!workflow) {
    return (
      <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
        Add an evaluation-stage artifact to connect exact claims to experiments and results.
      </div>
    )
  }
  return (
    <div className="space-y-4 rounded-lg border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="flex items-center gap-2 text-sm font-medium">
            <FlaskConical className="h-4 w-4" /> Claim-centered evaluation matrix
          </p>
          <p className="mt-1 max-w-4xl text-xs text-muted-foreground">
            Exact canonical evidence is resolved server-side. Positive or negative metric direction is
            never treated as claim support unless the contract classifies the outcome explicitly.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant={verdictVariant(workflow.verdict)}>{workflow.verdict}</Badge>
          <Badge variant="outline">private evidence contract</Badge>
          <Badge variant="outline">no model call</Badge>
        </div>
      </div>
      {[...workflow.blockers, ...workflow.warnings].map((finding) => (
        <p key={finding} className="rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-100">
          {finding}
        </p>
      ))}
      {workflow.commitments.map((commitment, commitmentIndex) => {
        const key = commitment.commitment.local_key ?? `legacy-${commitmentIndex}`
        const prepared = commitment.events?.find(
          (event) => event.action === "result_unit_proposal_prepared",
        )
        const applied = commitment.events?.find(
          (event) => event.action === "result_unit_proposal_applied",
        )
        return (
          <section key={key} className="space-y-3 rounded-lg bg-muted/25 p-3" aria-labelledby={`evaluation-${key}`}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p id={`evaluation-${key}`} className="text-sm font-medium">
                  {key} · claim {String(commitment.commitment.claim_id ?? "legacy text")}
                  {commitment.commitment.claim_version ? ` v${commitment.commitment.claim_version}` : ""}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {String((commitment.claim as Record<string, unknown> | undefined)?.exact_wording
                    ?? commitment.commitment.method ?? "Structured revision required")}
                </p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Badge variant={verdictVariant(commitment.verdict)}>{commitment.verdict}</Badge>
                {prepared && <Badge variant="secondary">proposal {prepared.proposal_status ?? "prepared"}</Badge>}
                {applied && <Badge><CheckCircle2 className="mr-1 h-3 w-3" /> result applied</Badge>}
              </div>
            </div>
            {[...commitment.blockers, ...commitment.warnings].map((finding) => (
              <p key={finding} className="text-xs text-amber-800 dark:text-amber-200">{finding}</p>
            ))}
            {!commitment.legacy && (
              <div className="grid gap-2 text-xs lg:grid-cols-2">
                <div className="rounded-md border bg-background p-2">
                  <p className="font-medium">Allowed interpretation</p>
                  <p className="mt-1 text-muted-foreground">{commitment.commitment.allowed_interpretation}</p>
                </div>
                <div className="rounded-md border bg-background p-2">
                  <p className="font-medium">Prohibited interpretation</p>
                  <ul className="mt-1 list-disc pl-4 text-muted-foreground">
                    {(commitment.commitment.prohibited_interpretation ?? []).map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              </div>
            )}
            <div className="overflow-x-auto rounded-md border bg-background">
              <table className="min-w-[900px] w-full text-left text-xs">
                <thead className="border-b bg-muted/50">
                  <tr>
                    <th className="p-2 font-medium">Evidence requirement</th>
                    <th className="p-2 font-medium">Exact plan</th>
                    <th className="p-2 font-medium">Observed outcome</th>
                    <th className="p-2 font-medium">Run / locators</th>
                    <th className="p-2 font-medium">Readiness / action</th>
                  </tr>
                </thead>
                <tbody>
                  {commitment.requirements.map((requirement) => {
                    const mission = commitment.events?.find(
                      (event) => event.action === "missing_evidence_mission_created"
                        && event.requirement_key === requirement.requirement.local_key,
                    )
                    return (
                      <tr key={requirement.requirement.local_key} className="border-b last:border-0 align-top">
                        <td className="p-2">
                          <p className="font-medium">{requirement.requirement.local_key}</p>
                          <p className="mt-1 text-muted-foreground">{requirement.requirement.description}</p>
                          <Badge variant="outline" className="mt-1">{requirement.requirement.kind}</Badge>
                        </td>
                        <td className="p-2 font-mono text-[10px] text-muted-foreground">
                          <p>{requirement.requirement.experiment_id ?? "missing exp_"}</p>
                          <p>{requirement.requirement.plan_version_id ?? "missing epv_"}</p>
                          {requirement.requirement.plan_version && <p>plan v{requirement.requirement.plan_version}</p>}
                        </td>
                        <td className="space-y-2 p-2">
                          {requirement.observations.map((item) => (
                            <div key={item.binding.observation_id} className="rounded bg-muted/40 p-1.5">
                              <div className="flex flex-wrap gap-1">
                                <Badge variant={item.binding.outcome === "fails_to_support" ? "destructive" : "outline"}>
                                  {item.binding.outcome.replaceAll("_", " ")}
                                </Badge>
                                <Badge variant="outline">{item.binding.claim_effect.replaceAll("_", " ")}</Badge>
                              </div>
                              <p className="mt-1">{item.binding.interpretation}</p>
                              {item.observation && <p className="mt-1 text-muted-foreground">direction: {item.observation.direction}</p>}
                            </div>
                          ))}
                          {requirement.observations.length === 0 && <span className="text-muted-foreground">No observation bound</span>}
                        </td>
                        <td className="p-2 font-mono text-[10px] text-muted-foreground">
                          {requirement.observations.map((item) => (
                            <div key={item.binding.observation_id} className="mb-2">
                              <p>{item.binding.observation_id}</p>
                              {item.observation && <p>{item.observation.run_id} · {item.observation.run_status}</p>}
                              {item.locators.map((locator) => <p key={locator.id}>{locator.id}</p>)}
                            </div>
                          ))}
                        </td>
                        <td className="p-2">
                          <Badge variant={verdictVariant(requirement.verdict)}>{requirement.verdict}</Badge>
                          {[...requirement.blockers, ...requirement.warnings].slice(0, 3).map((finding) => (
                            <p key={finding} className="mt-1 text-[10px] text-amber-800 dark:text-amber-200">{finding}</p>
                          ))}
                          {mission ? (
                            <p className="mt-2 font-mono text-[10px] text-muted-foreground">
                              mission {mission.target_id} · {mission.mission_status ?? "created"}
                            </p>
                          ) : requirement.conclusive_observation_count === 0 && !commitment.legacy ? (
                            <Button
                              size="xs"
                              variant="outline"
                              className="mt-2"
                              disabled={pending || !workflow.artifact}
                              onClick={() => void onCreateMission(commitment, requirement)}
                            >
                              Create evidence mission
                            </Button>
                          ) : null}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            {!commitment.legacy && commitment.requirements.some(
              (requirement) => requirement.conclusive_observation_count > 0,
            ) && !prepared && (
              <form
                className="grid gap-2 rounded-md border bg-background p-2 md:grid-cols-2 xl:grid-cols-4"
                onSubmit={(event) => void onPrepareResult(event, commitment)}
              >
                <Input name="result_unit_local_key" required placeholder="result-primary-effect" aria-label={`Result unit key for ${key}`} />
                <Input name="location" required placeholder="sections/results.tex#primary" aria-label={`Result location for ${key}`} />
                <Input name="title" required placeholder="Primary effect" aria-label={`Result title for ${key}`} />
                <Input name="artifact_ref" required pattern="(art|fig)_.+" placeholder="art_... or fig_..." aria-label={`Result artifact for ${key}`} />
                <div className="flex items-center justify-between gap-2 md:col-span-2 xl:col-span-4">
                  <p className="text-[10px] text-muted-foreground">
                    Creates a review proposal only; explicit semantic-patch apply remains separate.
                  </p>
                  <Button size="xs" type="submit" disabled={pending || !manuscriptReady}>
                    <FilePenLine className="mr-1 h-3.5 w-3.5" /> Prepare result proposal
                  </Button>
                </div>
              </form>
            )}
          </section>
        )
      })}
      {workflow.events.length > 0 && (
        <details className="rounded-md border p-2 text-xs">
          <summary className="cursor-pointer font-medium">Audit {workflow.events.length} evaluation actions</summary>
          <ol className="mt-2 space-y-1 text-muted-foreground">
            {workflow.events.map((event) => (
              <li key={event.id}>{event.action.replaceAll("_", " ")} · {event.commitment_key} · {event.target_id}</li>
            ))}
          </ol>
        </details>
      )}
    </div>
  )
}
