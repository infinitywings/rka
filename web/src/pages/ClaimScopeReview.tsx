import { useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"
import {
  AlertTriangle,
  CheckCircle2,
  History,
  Loader2,
  Plus,
  RefreshCw,
  Scale,
  ShieldCheck,
  Trash2,
} from "lucide-react"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import type {
  Claim,
  ClaimConditionKind,
  ClaimConditionOperator,
  ClaimScopeCondition,
  ClaimScopeExtensionPolicy,
  ClaimScopeUncertainty,
  ClaimFalsifierStatus,
  ClaimScopeHistory,
  ClaimScopeReadiness,
  ClaimScopeReviewStatus,
} from "@/api/types"
import {
  useAppendClaimScope,
  useClaimScope,
  useClaimScopeQueue,
} from "@/hooks/useClaimScopes"
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

type ReadinessFilter = "all" | ClaimScopeReadiness

const readinessOrder: ClaimScopeReadiness[] = [
  "missing",
  "stale",
  "incomplete",
  "needs_review",
  "ready",
]

const conditionKinds: ClaimConditionKind[] = [
  "dataset",
  "population",
  "platform",
  "environment",
  "threat_model",
  "baseline",
  "workload",
  "metric",
  "parameter",
  "assumption",
  "time_window",
  "other",
]

const conditionOperators: ClaimConditionOperator[] = [
  "equals",
  "one_of",
  "range",
  "at_least",
  "at_most",
  "present",
  "absent",
  "described_by",
]

function readinessBadge(readiness: ClaimScopeReadiness) {
  if (readiness === "ready") return <Badge className="bg-emerald-600 text-white">ready</Badge>
  if (readiness === "stale") return <Badge variant="destructive">stale</Badge>
  if (readiness === "needs_review") return <Badge className="bg-amber-500 text-black">needs review</Badge>
  return <Badge variant="secondary">{readiness.replaceAll("_", " ")}</Badge>
}

function formatDate(value: string | null) {
  if (!value) return "time unavailable"
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

export default function ClaimScopeReview() {
  const queue = useClaimScopeQueue()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedFilter = searchParams.get("scope")
  const claims = useMemo(() => queue.data ?? [], [queue.data])
  const requestedClaimId = searchParams.get("claim_id")
  const requestedClaim = claims.find((claim) => claim.id === requestedClaimId)
  const filter: ReadinessFilter = requestedClaim?.scope_readiness
    ?? (readinessOrder.includes(requestedFilter as ClaimScopeReadiness)
      ? requestedFilter as ClaimScopeReadiness
      : requestedFilter === "all" ? "all" : "missing")
  const filtered = useMemo(
    () => claims.filter((claim) => filter === "all" || claim.scope_readiness === filter),
    [claims, filter],
  )
  const activeId = requestedClaimId
    ? requestedClaim?.id ?? null
    : filtered[0]?.id ?? null
  const requestedClaimMissing = Boolean(requestedClaimId && !queue.isLoading && !requestedClaim)
  const history = useClaimScope(activeId)
  const activeClaim = claims.find((claim) => claim.id === activeId) ?? null
  const counts = useMemo(
    () => Object.fromEntries([
      ["all", claims.length],
      ...readinessOrder.map((state) => [
        state,
        claims.filter((claim) => claim.scope_readiness === state).length,
      ]),
    ]) as Record<ReadinessFilter, number>,
    [claims],
  )

  const selectFilter = (next: ReadinessFilter) => {
    const params = new URLSearchParams(searchParams)
    if (next === "missing") params.delete("scope")
    else params.set("scope", next)
    params.delete("claim_id")
    setSearchParams(params)
  }

  const selectClaim = (claim: Claim) => {
    const params = new URLSearchParams(searchParams)
    params.set("claim_id", claim.id)
    params.set("scope", claim.scope_readiness)
    setSearchParams(params)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">Claim Scope Review</h1>
            <Badge variant="outline">M2 contract</Badge>
          </div>
          <p className="mt-1 max-w-4xl text-sm text-muted-foreground">
            Bound canonical research claims before the writer uses them. Scope readiness,
            scientific support, contradictions, and source grounding remain separate signals.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => void Promise.all([
            queue.refetch(),
            activeId ? history.refetch() : Promise.resolve(),
          ])}
          disabled={queue.isFetching || history.isFetching}
        >
          <RefreshCw className={cn("mr-2 h-4 w-4", (queue.isFetching || history.isFetching) && "animate-spin")} />
          Refresh queue
        </Button>
      </div>

      <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-6">
        {(["all", ...readinessOrder] as ReadinessFilter[]).map((state) => (
          <button
            key={state}
            type="button"
            onClick={() => selectFilter(state)}
            className={cn(
              "rounded-lg border px-3 py-2 text-left transition-colors",
              filter === state ? "border-primary bg-muted" : "hover:bg-muted/50",
            )}
          >
            <p className="text-xs text-muted-foreground">{state.replaceAll("_", " ")}</p>
            <p className="mt-1 text-xl font-semibold">{counts[state]}</p>
          </button>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[23rem_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm">
              <span>Canonical claims</span>
              <span className="font-normal text-muted-foreground">{filtered.length}</span>
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Missing and stale contracts are workbench blockers, not hidden defaults.
            </p>
          </CardHeader>
          <CardContent className="max-h-[70vh] space-y-2 overflow-y-auto">
            {queue.isLoading && <Loading label="Loading claims" />}
            {queue.error && <ErrorMessage error={queue.error} />}
            {!queue.isLoading && filtered.length === 0 && (
              <p className="py-10 text-center text-sm text-muted-foreground">No claims in this state.</p>
            )}
            {filtered.map((claim) => (
              <ClaimButton
                key={claim.id}
                claim={claim}
                selected={claim.id === activeId}
                onSelect={() => selectClaim(claim)}
              />
            ))}
          </CardContent>
        </Card>

        {history.isLoading && activeId && <Card><CardContent><Loading label="Loading scope history" /></CardContent></Card>}
        {history.error && <Card><CardContent className="p-5"><ErrorMessage error={history.error} /></CardContent></Card>}
        {activeClaim && history.data && (
          <ClaimScopeDetail
            key={`${activeClaim.id}:${history.data.current_revision}`}
            claim={activeClaim}
            history={history.data}
          />
        )}
        {requestedClaimMissing && (
          <Card><CardContent className="flex h-48 items-center justify-center p-5 text-sm text-muted-foreground">
            Claim <code className="mx-1">{requestedClaimId}</code> is unavailable in the active project. No fallback claim was selected.
          </CardContent></Card>
        )}
        {!activeId && !queue.isLoading && !requestedClaimMissing && (
          <Card><CardContent className="flex h-48 items-center justify-center text-sm text-muted-foreground">
            Select a scope state with claims to review.
          </CardContent></Card>
        )}
      </div>
    </div>
  )
}

function Loading({ label }: { label: string }) {
  return <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> {label}
  </div>
}

function ErrorMessage({ error }: { error: Error }) {
  return <p className="rounded-md border border-red-300 p-3 text-sm text-red-700">{error.message}</p>
}

function ClaimButton({ claim, selected, onSelect }: { claim: Claim; selected: boolean; onSelect: () => void }) {
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
      <div className="flex items-center justify-between gap-2">
        <Badge variant="outline">{claim.claim_type}</Badge>
        {readinessBadge(claim.scope_readiness)}
      </div>
      <p className="mt-2 line-clamp-3 text-sm font-medium leading-5">{claim.content}</p>
      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
        <span>scope rev {claim.scope_revision}</span>
        <span>evidence {claim.evidence_status}</span>
        {claim.contradicted && <span className="text-red-600">contradicted</span>}
      </div>
    </button>
  )
}

function ClaimScopeDetail({ claim, history }: { claim: Claim; history: ClaimScopeHistory }) {
  return (
    <div className="min-w-0 space-y-4">
      <Card>
        <CardHeader className="border-b pb-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                {readinessBadge(history.scope_readiness)}
                <Badge variant="outline">{claim.claim_type}</Badge>
                <Badge variant={claim.verified ? "default" : "secondary"}>
                  source {claim.verified ? "grounded" : "unverified"}
                </Badge>
                <Badge variant="outline">evidence {claim.evidence_status}</Badge>
                {claim.contradicted && <Badge variant="destructive">contradicted</Badge>}
              </div>
              <CardTitle className="mt-3 text-lg leading-7">{claim.content}</CardTitle>
              <code className="mt-2 block break-all text-xs text-muted-foreground">
                {claim.id} ← {claim.source_entry_id}
              </code>
            </div>
            <code className="rounded bg-muted px-2 py-1 text-xs">scope rev {history.current_revision}</code>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 p-4 lg:grid-cols-2">
          <section className="space-y-2">
            <h2 className="flex items-center gap-2 text-sm font-semibold"><Scale className="h-4 w-4" /> Derived readiness</h2>
            {history.findings.length === 0
              ? <p className="text-sm text-muted-foreground">No scope findings.</p>
              : history.findings.map((finding) => (
                <div key={`${finding.code}:${finding.message}`} className="rounded-md border p-2 text-sm">
                  <div className="flex items-center gap-2">
                    {finding.severity === "block" ? <AlertTriangle className="h-4 w-4 text-red-600" /> : <ShieldCheck className="h-4 w-4 text-amber-600" />}
                    <code className="text-xs">{finding.code}</code>
                  </div>
                  <p className="mt-1 text-muted-foreground">{finding.message}</p>
                </div>
              ))}
          </section>
          <section className="space-y-2">
            <h2 className="text-sm font-semibold">Current applicability boundary</h2>
            {!history.current && <p className="text-sm text-muted-foreground">No contract exists. Review must supply the boundary; RKA will not infer one.</p>}
            {history.current && (
              <div className="space-y-2 text-sm">
                <p>{history.current.conditions.length} typed condition(s) · {history.current.uncertainty} uncertainty</p>
                <p>Extension policy: {history.current.extension_policy ?? "unresolved"}</p>
                <p>Falsifier: {history.current.falsifier_status}</p>
                <div className="flex flex-wrap gap-1">
                  {history.current.conditions.map((condition) => (
                    <Badge key={`${condition.kind}:${condition.key}`} variant="outline">
                      {condition.kind}:{condition.key} {condition.operator} {String(condition.value)}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </section>
        </CardContent>
      </Card>

      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ScopeEditor claim={claim} history={history} />
        <ScopeHistory history={history} />
      </div>
    </div>
  )
}

interface EditableCondition {
  kind: ClaimConditionKind
  key: string
  operator: ClaimConditionOperator
  value: string
  unit: string
}

function lines(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean)
}

function conditionValue(condition: EditableCondition): ClaimScopeCondition["value"] {
  if (condition.operator === "one_of" || condition.operator === "range") {
    return condition.value.split(",").map((value) => value.trim()).filter(Boolean)
  }
  if (condition.operator === "present" || condition.operator === "absent") return true
  return condition.value.trim()
}

function ScopeEditor({ claim, history }: { claim: Claim; history: ClaimScopeHistory }) {
  const current = history.current
  const mutation = useAppendClaimScope()
  const [reviewStatus, setReviewStatus] = useState<ClaimScopeReviewStatus>(current?.review_status ?? "draft")
  const [reason, setReason] = useState("")
  const [uncertainty, setUncertainty] = useState<ClaimScopeUncertainty>(current?.uncertainty ?? "unknown")
  const [uncertaintyNote, setUncertaintyNote] = useState(current?.uncertainty_note ?? "")
  const [extensionPolicy, setExtensionPolicy] = useState<ClaimScopeExtensionPolicy | "unresolved">(current?.extension_policy ?? "unresolved")
  const [allowed, setAllowed] = useState((current?.allowed_extensions ?? []).join("\n"))
  const [prohibited, setProhibited] = useState((current?.prohibited_extensions ?? []).join("\n"))
  const [falsifierStatus, setFalsifierStatus] = useState<ClaimFalsifierStatus>(current?.falsifier_status ?? "unknown")
  const [falsifier, setFalsifier] = useState(current?.falsifier ?? "")
  const [falsifierRationale, setFalsifierRationale] = useState(current?.falsifier_rationale ?? "")
  const [disconfirming, setDisconfirming] = useState((current?.disconfirming_claim_ids ?? []).join("\n"))
  const [conditions, setConditions] = useState<EditableCondition[]>(
    current?.conditions.map((condition) => ({
      kind: condition.kind,
      key: condition.key,
      operator: condition.operator,
      value: Array.isArray(condition.value) ? condition.value.join(", ") : String(condition.value),
      unit: condition.unit ?? "",
    })) ?? [{ kind: "dataset", key: "", operator: "equals", value: "", unit: "" }],
  )

  const submit = () => {
    mutation.mutate(
      {
        claimId: claim.id,
        data: {
          expected_revision: history.current_revision,
          actor: "web_ui",
          reason: reason.trim(),
          conditions: conditions
            .filter((condition) => condition.key.trim() && (condition.value.trim() || ["present", "absent"].includes(condition.operator)))
            .map((condition) => ({
              kind: condition.kind,
              key: condition.key.trim(),
              operator: condition.operator,
              value: conditionValue(condition),
              unit: condition.unit.trim() || undefined,
            })),
          uncertainty,
          uncertainty_note: uncertaintyNote.trim() || undefined,
          extension_policy: extensionPolicy === "unresolved" ? undefined : extensionPolicy,
          allowed_extensions: lines(allowed),
          prohibited_extensions: lines(prohibited),
          falsifier_status: falsifierStatus,
          falsifier: falsifier.trim() || undefined,
          falsifier_rationale: falsifierRationale.trim() || undefined,
          disconfirming_claim_ids: lines(disconfirming),
          review_status: reviewStatus,
        },
      },
      {
        onSuccess: (updated) => {
          toast.success(`Scope revision ${updated.current_revision} appended (${updated.scope_readiness})`)
          setReason("")
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 409) {
            toast.error("This scope changed. Reload before appending another revision.")
          } else {
            toast.error(error instanceof Error ? error.message : "Scope update failed")
          }
        },
      },
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm"><ShieldCheck className="h-4 w-4" /> Append scope revision</CardTitle>
        <p className="text-xs text-muted-foreground">Edits create immutable history; they never overwrite prior PI-visible boundaries.</p>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-4 md:grid-cols-3">
          <FieldSelect label="Review state" value={reviewStatus} values={["draft", "reviewed"]} onChange={(value) => setReviewStatus(value as ClaimScopeReviewStatus)} />
          <FieldSelect label="Uncertainty" value={uncertainty} values={["unknown", "none", "low", "medium", "high"]} onChange={(value) => setUncertainty(value as ClaimScopeUncertainty)} />
          <FieldSelect label="Extension policy" value={extensionPolicy} values={["unresolved", "exact_only", "bounded"]} onChange={(value) => setExtensionPolicy(value as ClaimScopeExtensionPolicy | "unresolved")} />
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>Typed applicability conditions</Label>
            <Button type="button" size="sm" variant="outline" onClick={() => setConditions([...conditions, { kind: "other", key: "", operator: "described_by", value: "", unit: "" }])}>
              <Plus className="mr-1 h-3.5 w-3.5" /> Add condition
            </Button>
          </div>
          {conditions.map((condition, index) => (
            <div key={index} className="grid gap-2 rounded-md border p-3 lg:grid-cols-[9rem_1fr_9rem_1fr_6rem_auto]">
              <CompactSelect value={condition.kind} values={conditionKinds} onChange={(value) => updateCondition(index, { kind: value as ClaimConditionKind })} />
              <Input aria-label={`Condition ${index + 1} key`} placeholder="key, e.g. evaluation_dataset" value={condition.key} onChange={(event) => updateCondition(index, { key: event.target.value })} />
              <CompactSelect value={condition.operator} values={conditionOperators} onChange={(value) => updateCondition(index, { operator: value as ClaimConditionOperator })} />
              <Input aria-label={`Condition ${index + 1} value`} disabled={["present", "absent"].includes(condition.operator)} placeholder={condition.operator === "range" ? "min, max" : "value"} value={condition.value} onChange={(event) => updateCondition(index, { value: event.target.value })} />
              <Input aria-label={`Condition ${index + 1} unit`} placeholder="unit" value={condition.unit} onChange={(event) => updateCondition(index, { unit: event.target.value })} />
              <Button type="button" size="icon" variant="ghost" aria-label={`Remove condition ${index + 1}`} onClick={() => setConditions(conditions.filter((_, itemIndex) => itemIndex !== index))}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <TextAreaField label="Allowed extensions (one per line)" value={allowed} onChange={setAllowed} />
          <TextAreaField label="Prohibited extensions (one per line)" value={prohibited} onChange={setProhibited} />
          <TextAreaField label="Uncertainty note" value={uncertaintyNote} onChange={setUncertaintyNote} />
          <TextAreaField label="Disconfirming clm_ ids (one per line)" value={disconfirming} onChange={setDisconfirming} />
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <FieldSelect label="Falsifier applicability" value={falsifierStatus} values={["unknown", "applicable", "not_applicable"]} onChange={(value) => setFalsifierStatus(value as ClaimFalsifierStatus)} />
          <TextAreaField label="Falsifier" value={falsifier} onChange={setFalsifier} />
          <TextAreaField label="Falsifier rationale" value={falsifierRationale} onChange={setFalsifierRationale} />
        </div>

        <div className="space-y-2">
          <Label htmlFor={`scope-reason-${claim.id}`}>Revision reason</Label>
          <Textarea id={`scope-reason-${claim.id}`} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="What source, evaluation, or PI judgment supports this boundary?" />
        </div>
        <Button className="w-full" disabled={!reason.trim() || mutation.isPending} onClick={submit}>
          {mutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
          Append {reviewStatus} revision
        </Button>
      </CardContent>
    </Card>
  )

  function updateCondition(index: number, patch: Partial<EditableCondition>) {
    setConditions(conditions.map((condition, itemIndex) => itemIndex === index ? { ...condition, ...patch } : condition))
  }
}

function ScopeHistory({ history }: { history: ClaimScopeHistory }) {
  return (
    <Card className="h-fit">
      <CardHeader><CardTitle className="flex items-center gap-2 text-sm"><History className="h-4 w-4" /> Immutable history</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {history.versions.length === 0 && <p className="text-sm text-muted-foreground">No scope revisions.</p>}
        {history.versions.map((version) => (
          <div key={version.id} className="border-l-2 pl-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">revision {version.revision}</span>
              <Badge variant="outline">{version.review_status}</Badge>
              <span className="text-xs text-muted-foreground">by {version.created_by}</span>
            </div>
            <p className="mt-1">{version.reason}</p>
            <p className="mt-1 text-xs text-muted-foreground">{formatDate(version.created_at)}</p>
            <code className="mt-1 block break-all text-[10px] text-muted-foreground">{version.id}</code>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function FieldSelect({ label, value, values, onChange }: { label: string; value: string; values: string[]; onChange: (value: string) => void }) {
  return <div className="space-y-2"><Label>{label}</Label><CompactSelect value={value} values={values} onChange={onChange} /></div>
}

function CompactSelect({ value, values, onChange }: { value: string; values: readonly string[]; onChange: (value: string) => void }) {
  return <Select value={value} onValueChange={(next) => next != null && onChange(next)}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent>{values.map((item) => <SelectItem key={item} value={item}>{item.replaceAll("_", " ")}</SelectItem>)}</SelectContent></Select>
}

function TextAreaField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <div className="space-y-2"><Label>{label}</Label><Textarea rows={3} value={value} onChange={(event) => onChange(event.target.value)} /></div>
}
