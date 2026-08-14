import { useMemo, useState } from "react"
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  ExternalLink,
  GitMerge,
  History,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import type {
  InterpretationCandidate,
  InterpretationCandidateDetail,
  InterpretationReviewStatus,
  InterpretationTriageAction,
} from "@/api/types"
import {
  useInterpretationCandidate,
  useInterpretationCandidates,
  useTriageInterpretationCandidate,
} from "@/hooks/useInterpretationStaging"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

type StatusFilter = "all" | InterpretationReviewStatus

const actionLabels: Record<InterpretationTriageAction, string> = {
  start_review: "Start review",
  promote: "Promote to canonical claim",
  merge: "Merge into another candidate",
  defer: "Defer",
  reject: "Reject",
  classify_decision: "Classify as decision",
  classify_plan: "Classify as plan",
  classify_author_intent: "Classify as author intent",
  request_evidence_mission: "Request evidence mission",
  reopen: "Reopen for review",
  revoke_promotion: "Revoke promotion",
}

function actionsFor(candidate: InterpretationCandidateDetail): InterpretationTriageAction[] {
  if (candidate.review_status === "resolved") {
    return candidate.disposition === "promoted"
      ? ["reopen", "revoke_promotion"]
      : ["reopen"]
  }
  return [
    ...(candidate.review_status === "pending" ? ["start_review" as const] : []),
    "promote",
    "merge",
    "defer",
    "reject",
    "classify_decision",
    "classify_plan",
    "classify_author_intent",
    "request_evidence_mission",
  ]
}

function formatDate(value: string | null) {
  if (!value) return "time unavailable"
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

function locatorLabel(candidate: InterpretationCandidate) {
  if (candidate.locator_kind === "text_offset") {
    return `characters ${candidate.locator_start}–${candidate.locator_end ?? "end"}`
  }
  if (candidate.locator_kind === "page") {
    return `page ${candidate.locator_start}${candidate.locator_end != null ? `–${candidate.locator_end}` : ""}`
  }
  if (candidate.locator_kind === "line_range") {
    return `lines ${candidate.locator_start}${candidate.locator_end != null ? `–${candidate.locator_end}` : ""}`
  }
  return `${candidate.locator_kind.replaceAll("_", " ")}: ${candidate.locator_value}`
}

function StatusBadge({ status }: { status: InterpretationReviewStatus }) {
  if (status === "resolved") {
    return <Badge className="bg-emerald-600 text-white">Resolved</Badge>
  }
  if (status === "in_review") {
    return <Badge className="bg-amber-500 text-black">In review</Badge>
  }
  return <Badge variant="secondary">Pending</Badge>
}

function CandidateButton({
  candidate,
  selected,
  onSelect,
}: {
  candidate: InterpretationCandidate
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "w-full rounded-lg border p-3 text-left transition-colors",
        selected ? "border-primary bg-muted" : "hover:bg-muted/50",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <Badge variant="outline" className="font-normal">
          {candidate.epistemic_kind.replaceAll("_", " ")}
        </Badge>
        <StatusBadge status={candidate.review_status} />
      </div>
      <p className="mt-2 line-clamp-3 text-sm font-medium leading-5">
        {candidate.statement}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
        <span>rev {candidate.revision}</span>
        <span>{candidate.source_type}</span>
        {candidate.conflict_hint_count > 0 && (
          <span className="text-red-600">{candidate.conflict_hint_count} conflict</span>
        )}
        {candidate.duplicate_hint_count > 0 && (
          <span>{candidate.duplicate_hint_count} duplicate</span>
        )}
      </div>
    </button>
  )
}

export default function InterpretationStaging() {
  const candidatesQuery = useInterpretationCandidates()
  const [filter, setFilter] = useState<StatusFilter>("pending")
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const candidates = useMemo(() => candidatesQuery.data ?? [], [candidatesQuery.data])
  const filtered = useMemo(
    () => candidates.filter((candidate) => filter === "all" || candidate.review_status === filter),
    [candidates, filter],
  )
  const activeId = selectedId && filtered.some((item) => item.id === selectedId)
    ? selectedId
    : filtered[0]?.id ?? null
  const detailQuery = useInterpretationCandidate(activeId)

  const counts = useMemo(
    () => ({
      all: candidates.length,
      pending: candidates.filter((item) => item.review_status === "pending").length,
      in_review: candidates.filter((item) => item.review_status === "in_review").length,
      resolved: candidates.filter((item) => item.review_status === "resolved").length,
    }),
    [candidates],
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">Interpretation Review</h1>
            <Badge variant="outline">M1 staging</Badge>
          </div>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Review source-grounded interpretations before they enter the canonical claim graph.
            Candidate status and uncertainty are visible; extraction never implies scientific support.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => void Promise.all([
            candidatesQuery.refetch(),
            activeId ? detailQuery.refetch() : Promise.resolve(),
          ])}
          disabled={candidatesQuery.isFetching || detailQuery.isFetching}
        >
          <RefreshCw className={cn(
            "mr-2 h-4 w-4",
            (candidatesQuery.isFetching || detailQuery.isFetching) && "animate-spin",
          )} />
          Refresh queue
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        {(["all", "pending", "in_review", "resolved"] as const).map((status) => (
          <button
            key={status}
            type="button"
            onClick={() => setFilter(status)}
            className={cn(
              "rounded-lg border px-4 py-3 text-left transition-colors",
              filter === status ? "border-primary bg-muted" : "hover:bg-muted/50",
            )}
          >
            <p className="text-xs capitalize text-muted-foreground">{status.replaceAll("_", " ")}</p>
            <p className="mt-1 text-2xl font-semibold">{counts[status]}</p>
          </button>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[23rem_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm">
              <span>Deterministic review queue</span>
              <span className="font-normal text-muted-foreground">{filtered.length}</span>
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              In-review first, then oldest pending records. Resolved history remains queryable.
            </p>
          </CardHeader>
          <CardContent className="max-h-[68vh] space-y-2 overflow-y-auto">
            {candidatesQuery.isLoading && (
              <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading candidates
              </div>
            )}
            {candidatesQuery.error && (
              <p className="rounded-md border border-red-300 p-3 text-sm text-red-700">
                {candidatesQuery.error.message}
              </p>
            )}
            {!candidatesQuery.isLoading && filtered.length === 0 && (
              <div className="py-12 text-center text-sm text-muted-foreground">
                No {filter === "all" ? "" : filter.replaceAll("_", " ")} candidates.
              </div>
            )}
            {filtered.map((candidate) => (
              <CandidateButton
                key={candidate.id}
                candidate={candidate}
                selected={candidate.id === activeId}
                onSelect={() => setSelectedId(candidate.id)}
              />
            ))}
          </CardContent>
        </Card>

        {detailQuery.isLoading && activeId && (
          <Card><CardContent className="flex h-48 items-center justify-center">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading review history
          </CardContent></Card>
        )}
        {detailQuery.error && (
          <Card><CardContent className="p-5 text-sm text-red-700">
            {detailQuery.error.message}
          </CardContent></Card>
        )}
        {detailQuery.data && <CandidateDetail candidate={detailQuery.data} />}
        {!activeId && !candidatesQuery.isLoading && (
          <Card><CardContent className="flex h-48 items-center justify-center text-sm text-muted-foreground">
            Select a status with candidates to inspect its provenance and review history.
          </CardContent></Card>
        )}
      </div>
    </div>
  )
}

function CandidateDetail({ candidate }: { candidate: InterpretationCandidateDetail }) {
  return (
    <div className="min-w-0 space-y-4">
      <Card>
        <CardHeader className="border-b pb-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={candidate.review_status} />
                <Badge variant="outline">{candidate.epistemic_kind.replaceAll("_", " ")}</Badge>
                {candidate.proposed_claim_type && (
                  <Badge variant="secondary">proposes {candidate.proposed_claim_type}</Badge>
                )}
              </div>
              <CardTitle className="mt-3 text-lg leading-7">{candidate.statement}</CardTitle>
            </div>
            <code className="rounded bg-muted px-2 py-1 text-xs">rev {candidate.revision}</code>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 p-4 lg:grid-cols-2">
          <section className="space-y-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <ExternalLink className="h-4 w-4" /> Exact source
            </h2>
            <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Source</dt>
              <dd><code className="break-all">{candidate.source_type}:{candidate.source_id}</code></dd>
              <dt className="text-muted-foreground">Locator</dt>
              <dd>{locatorLabel(candidate)}</dd>
              <dt className="text-muted-foreground">Extracted by</dt>
              <dd>{candidate.created_by} via {candidate.extraction_tool}</dd>
              <dt className="text-muted-foreground">Model</dt>
              <dd>{candidate.extraction_model ?? "not recorded"}</dd>
              <dt className="text-muted-foreground">Candidate id</dt>
              <dd><code className="break-all text-xs">{candidate.id}</code></dd>
            </dl>
          </section>

          <section className="space-y-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <AlertTriangle className="h-4 w-4" /> Scope and uncertainty
            </h2>
            <div className="space-y-2 text-sm">
              <p><span className="text-muted-foreground">Uncertainty:</span> {candidate.uncertainty}</p>
              <p>{candidate.uncertainty_note ?? "No uncertainty note was recorded."}</p>
              <p><span className="text-muted-foreground">Falsifier:</span> {candidate.falsifier ?? "Not recorded."}</p>
              <div className="flex flex-wrap gap-1">
                {candidate.scope_conditions.length > 0
                  ? candidate.scope_conditions.map((scope) => <Badge key={scope} variant="outline">{scope}</Badge>)
                  : <span className="text-muted-foreground">No scope conditions recorded.</span>}
              </div>
            </div>
          </section>
        </CardContent>
      </Card>

      {(candidate.conflict_hint_count > 0 || candidate.duplicate_hint_count > 0) && (
        <Card className="border-amber-300 dark:border-amber-800">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <GitMerge className="h-4 w-4" /> Review hints
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {candidate.hints.map((hint) => (
              <div key={hint.id} className="rounded-md bg-muted/50 p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <Badge variant={hint.kind === "conflict" ? "destructive" : "secondary"}>{hint.kind}</Badge>
                  <span className="text-xs text-muted-foreground">{Math.round(hint.confidence * 100)}%</span>
                </div>
                <p className="mt-2">{hint.rationale}</p>
                <code className="mt-1 block text-xs text-muted-foreground">related: {hint.related_candidate_id}</code>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <HistoryCard candidate={candidate} />
        <TriageCard key={candidate.id} candidate={candidate} />
      </div>
    </div>
  )
}

function HistoryCard({ candidate }: { candidate: InterpretationCandidateDetail }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <History className="h-4 w-4" /> Append-only review history
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {[...candidate.review_events].reverse().map((event) => (
          <div key={event.id} className="border-l-2 pl-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium">{actionLabels[event.action as InterpretationTriageAction] ?? event.action.replaceAll("_", " ")}</span>
              <Badge variant="outline">rev {event.candidate_revision}</Badge>
              <span className="text-xs text-muted-foreground">by {event.actor}</span>
            </div>
            {event.reason && <p className="mt-1 text-sm">{event.reason}</p>}
            {event.target_id && (
              <code className="mt-1 block break-all text-xs text-muted-foreground">
                {event.target_type}:{event.target_id}
              </code>
            )}
            <p className="mt-1 text-xs text-muted-foreground">{formatDate(event.created_at)}</p>
          </div>
        ))}
        {candidate.promotions.map((promotion) => (
          <div key={promotion.id} className="rounded-md border bg-muted/30 p-3 text-sm">
            <div className="flex items-center gap-2">
              {promotion.status === "active" ? <ShieldCheck className="h-4 w-4 text-emerald-600" /> : <AlertTriangle className="h-4 w-4 text-amber-600" />}
              <span className="font-medium">Promotion {promotion.status}</span>
            </div>
            <code className="mt-1 block text-xs">claim:{promotion.claim_id}</code>
            {promotion.revocation_reason && <p className="mt-2">{promotion.revocation_reason}</p>}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function TriageCard({ candidate }: { candidate: InterpretationCandidateDetail }) {
  const mutation = useTriageInterpretationCandidate()
  const actions = actionsFor(candidate)
  const [action, setAction] = useState<InterpretationTriageAction>(actions[0])
  const effectiveAction = actions.includes(action) ? action : actions[0]
  const [reason, setReason] = useState("")
  const [targetId, setTargetId] = useState("")
  const [groundingVerified, setGroundingVerified] = useState(false)
  const [claimConfidence, setClaimConfidence] = useState("0.5")

  const reasonRequired = effectiveAction !== "start_review"
  const targetRequired = effectiveAction === "merge"
  const promotionBlocked = effectiveAction === "promote" && (
    candidate.source_type !== "journal" || !candidate.proposed_claim_type
  )
  const canSubmit = !mutation.isPending
    && (!reasonRequired || Boolean(reason.trim()))
    && (!targetRequired || Boolean(targetId.trim()))
    && (!promotionBlocked)
    && (effectiveAction !== "promote" || groundingVerified)

  const submit = () => {
    mutation.mutate(
      {
        candidateId: candidate.id,
        data: {
          action: effectiveAction,
          expected_revision: candidate.revision,
          actor: "web_ui",
          reason: reason.trim() || undefined,
          target_candidate_id: effectiveAction === "merge" ? targetId.trim() : undefined,
          target_entity_id: ["classify_decision", "classify_plan", "classify_author_intent", "request_evidence_mission"].includes(effectiveAction)
            ? targetId.trim() || undefined
            : undefined,
          grounding_verified: effectiveAction === "promote" ? groundingVerified : undefined,
          claim_confidence: effectiveAction === "promote" ? Number(claimConfidence) : undefined,
        },
      },
      {
        onSuccess: (updated) => {
          toast.success(`${actionLabels[effectiveAction]} recorded at revision ${updated.revision}`)
          setReason("")
          setTargetId("")
          setGroundingVerified(false)
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 409) {
            toast.error("This candidate changed. Reload the queue before reviewing it again.")
          } else {
            toast.error(error instanceof Error ? error.message : "Review action failed")
          }
        },
      },
    )
  }

  return (
    <Card className="h-fit">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Sparkles className="h-4 w-4" /> Explicit triage
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          Every action is revision guarded and appended to history.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor={`triage-action-${candidate.id}`}>Action</Label>
          <Select value={effectiveAction} onValueChange={(value) => setAction(value as InterpretationTriageAction)}>
            <SelectTrigger id={`triage-action-${candidate.id}`} className="w-full">
              <SelectValue>{actionLabels[effectiveAction]}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {actions.map((item) => <SelectItem key={item} value={item}>{actionLabels[item]}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>

        {effectiveAction !== "start_review" && (
          <div className="space-y-2">
            <Label htmlFor={`triage-reason-${candidate.id}`}>Reason</Label>
            <Textarea
              id={`triage-reason-${candidate.id}`}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Record why this disposition is warranted."
              rows={4}
            />
          </div>
        )}

        {(targetRequired || ["classify_decision", "classify_plan", "classify_author_intent", "request_evidence_mission"].includes(effectiveAction)) && (
          <div className="space-y-2">
            <Label htmlFor={`triage-target-${candidate.id}`}>
              {targetRequired ? "Target candidate id" : "Related entity id (optional)"}
            </Label>
            <Input
              id={`triage-target-${candidate.id}`}
              value={targetId}
              onChange={(event) => setTargetId(event.target.value)}
              placeholder={targetRequired ? "icd_..." : "dec_, mis_, or external plan id"}
            />
          </div>
        )}

        {effectiveAction === "promote" && (
          <div className="space-y-3 rounded-md border p-3">
            <div className="flex items-start gap-2">
              <input
                id={`grounding-${candidate.id}`}
                type="checkbox"
                className="mt-1"
                checked={groundingVerified}
                onChange={(event) => setGroundingVerified(event.target.checked)}
              />
              <Label htmlFor={`grounding-${candidate.id}`} className="font-normal leading-5">
                I checked the exact journal locator and confirm that it supports this wording.
              </Label>
            </div>
            <div className="space-y-2">
              <Label htmlFor={`claim-confidence-${candidate.id}`}>Grounding confidence</Label>
              <Input
                id={`claim-confidence-${candidate.id}`}
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={claimConfidence}
                onChange={(event) => setClaimConfidence(event.target.value)}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              Promotion confirms source fidelity only. The new claim remains scientifically unassessed.
            </p>
            {promotionBlocked && (
              <p className="text-xs text-red-700 dark:text-red-300">
                M1 promotion requires a journal source and proposed claim kind. This candidate must remain staged.
              </p>
            )}
          </div>
        )}

        {effectiveAction === "revoke_promotion" && (
          <p className="rounded-md bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-100">
            Revocation preserves the claim and lineage, marks the claim stale, and reopens this candidate.
          </p>
        )}

        <Button className="w-full" onClick={submit} disabled={!canSubmit}>
          {mutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : effectiveAction === "start_review" ? <Clock3 className="mr-2 h-4 w-4" /> : effectiveAction === "promote" ? <ArrowUpRight className="mr-2 h-4 w-4" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
          {actionLabels[effectiveAction]}
        </Button>
      </CardContent>
    </Card>
  )
}
