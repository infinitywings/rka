import { useMemo, useState } from "react"
import type { DragEvent, FormEvent } from "react"
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  ChevronRight,
  GitCompareArrows,
  ListTree,
  Merge,
  PencilLine,
  Split,
} from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useManuscriptOutline } from "@/hooks/useManuscriptOutline"
import type { ManuscriptOutline, ManuscriptOutlineUnit } from "@/api/types"
import type { WorkbenchTraceItem } from "@/components/workbench/EvidenceInspector"

function lines(value: FormDataEntryValue | null): string[] {
  return String(value ?? "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean)
}

function checkpointStatus(outline: ManuscriptOutline): string {
  return String(outline.outline_checkpoint?.status ?? "not created")
}

const UNIT_ROLES = [
  "unspecified", "section", "argument_block", "paragraph_plan", "result",
  "caption", "appendix", "other",
] as const

const RHETORICAL_MOVES = [
  "unspecified", "frame_problem", "establish_gap", "state_insight",
  "explain_mechanism", "address_challenge", "present_innovation",
  "pose_research_question", "state_contribution", "describe_method",
  "present_result", "interpret_result", "compare_prior_work",
  "state_limitation", "transition", "summarize", "other",
] as const

function humanize(value: string): string {
  return value.replaceAll("_", " ")
}

const selectClassName = "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-sm"

export function OutlineEditor({
  outline,
  onInspect,
}: {
  outline: ManuscriptOutline
  onInspect: (item: WorkbenchTraceItem) => void
}) {
  const mutations = useManuscriptOutline(outline.manuscript_id)
  const canonicalOrder = useMemo(
    () => [...outline.units]
      .sort((left, right) => left.sequence - right.sequence || left.local_key.localeCompare(right.local_key))
      .map((unit) => unit.local_key),
    [outline.units],
  )
  const canonicalOrderKey = `${outline.manuscript_id}:${outline.manuscript_revision}:${canonicalOrder.join("\u0000")}`
  const [draftState, setDraftState] = useState({
    canonicalOrderKey,
    order: canonicalOrder,
  })
  const draftOrder = draftState.canonicalOrderKey === canonicalOrderKey
    ? draftState.order
    : canonicalOrder
  const setDraftOrder = (update: string[] | ((current: string[]) => string[])) => {
    setDraftState((current) => {
      const base = current.canonicalOrderKey === canonicalOrderKey
        ? current.order
        : canonicalOrder
      return {
        canonicalOrderKey,
        order: typeof update === "function" ? update(base) : update,
      }
    })
  }
  const [draggedKey, setDraggedKey] = useState<string | null>(null)
  const [editKey, setEditKey] = useState<string | null>(null)
  const [expandKey, setExpandKey] = useState<string | null>(null)
  const [condenseKey, setCondenseKey] = useState<string | null>(null)
  const [reorderReason, setReorderReason] = useState("")
  const byKey = useMemo(
    () => new Map(outline.units.map((unit) => [unit.local_key, unit])),
    [outline.units],
  )
  const ordered = draftOrder.map((key) => byKey.get(key)).filter(Boolean) as ManuscriptOutlineUnit[]
  const orderChanged = draftOrder.some((key, index) => canonicalOrder[index] !== key)
  const readinessFindings = outline.academic_readiness.dimensions.flatMap((dimension) =>
    dimension.findings.map((finding) => ({ ...finding, dimension: dimension.name })),
  )
  const nextReadinessFinding = readinessFindings.find((finding) => finding.blocking)
    ?? readinessFindings[0]

  const prepare = async (request: Parameters<typeof mutations.prepare.mutateAsync>[0]) => {
    try {
      const result = await mutations.prepare.mutateAsync(request)
      const affected = result.impact.affected_unit_keys.length
      toast.success(`Review proposal prepared for ${affected} outline unit${affected === 1 ? "" : "s"}`)
      setEditKey(null)
      setExpandKey(null)
      setCondenseKey(null)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not prepare outline proposal")
    }
  }

  const move = (key: string, delta: number) => {
    setDraftOrder((current) => {
      const index = current.indexOf(key)
      const target = index + delta
      if (index < 0 || target < 0 || target >= current.length) return current
      const next = [...current]
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  const drop = (event: DragEvent<HTMLDivElement>, targetKey: string) => {
    event.preventDefault()
    if (!draggedKey || draggedKey === targetKey) return
    setDraftOrder((current) => {
      const next = current.filter((key) => key !== draggedKey)
      next.splice(next.indexOf(targetKey), 0, draggedKey)
      return next
    })
    setDraggedKey(null)
  }

  const descendants = (rootKey: string): string[] => {
    const result: string[] = []
    const visit = (key: string) => {
      for (const unit of outline.units) {
        if (unit.parent_unit_key === key) {
          result.push(unit.local_key)
          visit(unit.local_key)
        }
      }
    }
    visit(rootKey)
    return result
  }

  const createCheckpoint = async () => {
    const latest = outline.outline_checkpoint
    try {
      await mutations.createCheckpoint.mutateAsync({
        expected_revision: outline.manuscript_revision,
        ...(latest && ["rejected", "superseded"].includes(String(latest.status))
          ? { supersedes_id: String(latest.id) }
          : {}),
      })
      toast.success("Outline checkpoint created; PI resolution remains explicit")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not create Outline checkpoint")
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 rounded-lg border bg-muted/20 p-3 sm:grid-cols-2 xl:grid-cols-4">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Outline units</p>
          <p className="mt-1 text-lg font-semibold">{outline.summary.active_units}</p>
        </div>
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Rationale complete</p>
          <p className="mt-1 text-lg font-semibold">{outline.summary.complete_units}/{outline.summary.active_units}</p>
        </div>
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Elaboration levels</p>
          <p className="mt-1 text-lg font-semibold">{outline.summary.levels.map((level) => `L${level}`).join(", ") || "None"}</p>
        </div>
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Outline checkpoint</p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Badge variant={checkpointStatus(outline) === "resolved" ? "default" : "outline"}>
              {checkpointStatus(outline)}
            </Badge>
            {Boolean(outline.outline_checkpoint?.id) && (
              <code className="text-[10px] text-muted-foreground">{String(outline.outline_checkpoint?.id)}</code>
            )}
          </div>
        </div>
      </div>

      <div className="rounded-lg border bg-card p-3 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium">Academic readiness</p>
          <Badge variant={outline.academic_readiness.ready ? "secondary" : "destructive"}>
            {outline.academic_readiness.ready ? "structurally ready" : "structural gap"}
          </Badge>
          {outline.academic_readiness.dimensions.map((dimension) => (
            <Badge key={dimension.name} variant={dimension.blocking ? "destructive" : "outline"}>
              {humanize(dimension.name)} · {humanize(dimension.verdict)}
            </Badge>
          ))}
        </div>
        <p className="mt-2 text-muted-foreground">
          {nextReadinessFinding
            ? `Next ${nextReadinessFinding.blocking ? "required" : "advisory"} gap: ${nextReadinessFinding.message}${nextReadinessFinding.unit_key ? ` (${nextReadinessFinding.unit_key})` : ""}.`
            : "All deterministic academic-structure checks pass. Rhetorical and venue judgment remain advisory."}
        </p>
        {readinessFindings.length > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer font-medium">Review all {readinessFindings.length} findings</summary>
            <ul className="mt-2 space-y-1 pl-4 text-muted-foreground">
              {readinessFindings.map((finding, index) => (
                <li key={`${finding.code}:${finding.unit_id ?? finding.claim_id ?? index}`}>
                  <strong className="text-foreground">{humanize(finding.dimension)}:</strong> {finding.message}
                  {finding.unit_key ? ` · ${finding.unit_key}` : finding.claim_key ? ` · ${finding.claim_key}` : ""}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs text-blue-950 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-100">
        <div className="max-w-3xl">
          <p className="font-medium">Proposal-first outline editing</p>
          <p className="mt-1 opacity-80">
            Edit, expand, condense, and reorder prepare a semantic diff. RKA changes only after separate explicit Apply in Edit proposals; manuscript files remain untouched.
          </p>
          <p className="mt-1 opacity-80">
            Apply or reject pending edit proposals before creating a checkpoint; checkpoint creation advances the manuscript revision and makes older proposals stale.
          </p>
        </div>
        {checkpointStatus(outline) !== "pending" && checkpointStatus(outline) !== "resolved" && (
          <Button
            size="sm"
            variant="outline"
            disabled={!outline.summary.rationale_complete || mutations.createCheckpoint.isPending}
            onClick={() => void createCheckpoint()}
          >
            <CheckCircle2 className="mr-1 h-4 w-4" /> Create Outline checkpoint
          </Button>
        )}
      </div>

      {ordered.map((unit, index) => {
        const unitDescendants = descendants(unit.local_key)
        const evidenceIds = unit.evidence.map((item) => item.evidence_claim_id)
        return (
          <div
            key={unit.id}
            draggable
            onDragStart={() => setDraggedKey(unit.local_key)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => drop(event, unit.local_key)}
            className="rounded-lg border bg-card p-3"
            style={{ marginLeft: `${Math.max(0, unit.outline_level - 2) * 0.75}rem` }}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <ListTree className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">{unit.local_key} · {unit.title ?? unit.kind}</h3>
                  <Badge variant="outline">L{unit.outline_level}</Badge>
                  <Badge variant="outline">{humanize(unit.unit_role)}</Badge>
                  <Badge variant="outline">{humanize(unit.rhetorical_move)}</Badge>
                  <Badge variant={unit.completeness === "complete" ? "secondary" : "destructive"}>
                    {unit.completeness.replaceAll("_", " ")}
                  </Badge>
                  {unit.parent_unit_key && <Badge variant="outline">parent {unit.parent_unit_key}</Badge>}
                </div>
                <p className="mt-2 text-xs"><strong>Job:</strong> {unit.communicative_job ?? "Missing"}</p>
                <p className="mt-1 text-xs"><strong>Reader takeaway:</strong> {unit.intended_takeaway ?? "Missing"}</p>
                <p className="mt-1 text-xs text-muted-foreground"><strong>Transition:</strong> {unit.transition_from_previous ?? "Not planned"}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {unit.claims.map((claim) => <Badge key={`${unit.id}:${claim.claim_id}`} variant="outline">{claim.claim_key} · {claim.relationship}</Badge>)}
                  <Badge variant="outline">{evidenceIds.length} evidence bindings</Badge>
                  <Badge variant="outline">{unit.citations.length} citation uses</Badge>
                  <Badge variant="outline">{unit.evidence_plan.length} evidence-plan items</Badge>
                  {unit.missing.map((missing) => (
                    <Badge key={missing} variant="destructive">
                      {missing === "declared_blocker"
                        ? `blocked: ${unit.blocker ?? "reason declared"}`
                        : `missing ${missing.replaceAll("_", " ")}`}
                    </Badge>
                  ))}
                </div>
                {(unit.evidence.length > 0 || unit.citations.length > 0) && (
                  <details className="mt-3 rounded-md border bg-muted/10 p-2 text-xs">
                    <summary className="cursor-pointer font-medium">Academic support</summary>
                    <div className="mt-2 space-y-3">
                      {unit.evidence.map((item) => (
                        <div key={`${item.role}:${item.evidence_claim_id}`} className="rounded border p-2">
                          <div className="flex flex-wrap gap-1">
                            <Badge variant="outline">{item.role}</Badge>
                            <code className="text-[10px]">{item.evidence_claim_id}</code>
                          </div>
                          <p className="mt-1"><strong>Supports:</strong> {item.supported_proposition ?? "Not explained"}</p>
                          <p className="mt-1 text-muted-foreground"><strong>Warrant:</strong> {item.warrant ?? "Not explained"}</p>
                        </div>
                      ))}
                      {unit.citations.map((citation) => (
                        <div key={`${citation.citation_key}:${citation.citation_role}:${citation.supported_proposition}`} className="rounded border p-2">
                          <div className="flex flex-wrap gap-1">
                            <Badge variant="outline">{citation.citation_key}</Badge>
                            <Badge variant="outline">{citation.citation_role}</Badge>
                            <Badge variant={citation.verification_state === "verified" ? "secondary" : "outline"}>{humanize(citation.verification_state)}</Badge>
                          </div>
                          <p className="mt-1"><strong>Supports:</strong> {citation.supported_proposition}</p>
                          {citation.comparison_axis && <p className="mt-1 text-muted-foreground"><strong>Comparison axis:</strong> {citation.comparison_axis}</p>}
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
              <div className="flex flex-wrap gap-1">
                <Button size="icon" variant="ghost" aria-label={`Move ${unit.local_key} up`} disabled={index === 0} onClick={() => move(unit.local_key, -1)}>
                  <ArrowUp className="h-4 w-4" />
                </Button>
                <Button size="icon" variant="ghost" aria-label={`Move ${unit.local_key} down`} disabled={index === ordered.length - 1} onClick={() => move(unit.local_key, 1)}>
                  <ArrowDown className="h-4 w-4" />
                </Button>
                <Button size="sm" variant="outline" onClick={() => setEditKey(editKey === unit.local_key ? null : unit.local_key)}>
                  <PencilLine className="mr-1 h-3.5 w-3.5" /> Edit
                </Button>
                {unit.outline_level < 5 && (
                  <Button size="sm" variant="outline" onClick={() => setExpandKey(expandKey === unit.local_key ? null : unit.local_key)}>
                    <Split className="mr-1 h-3.5 w-3.5" /> Expand
                  </Button>
                )}
                {unitDescendants.length > 0 && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={mutations.prepare.isPending}
                    onClick={() => setCondenseKey(
                      condenseKey === unit.local_key ? null : unit.local_key,
                    )}
                  >
                    <Merge className="mr-1 h-3.5 w-3.5" /> Condense {unitDescendants.length}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onInspect({
                    title: unit.title ?? unit.local_key,
                    summary: unit.communicative_job ?? "Outline rationale incomplete",
                    kind: `L${unit.outline_level} native manuscript unit`,
                    origin: "/api/manuscripts/:id/outline",
                    derivation: "Native mun_ plus its one-to-one outline profile and reverse claim/evidence bindings.",
                    ids: [unit.id, ...unit.claims.map((claim) => claim.claim_id), ...evidenceIds],
                    status: unit.completeness,
                    trace: [outline.manuscript_id, unit.parent_unit_key ?? "root", unit.id, ...evidenceIds],
                  })}
                >
                  Inspect <ChevronRight className="ml-1 h-3.5 w-3.5" />
                </Button>
              </div>
            </div>

            {editKey === unit.local_key && (
              <form
                className="mt-3 grid gap-3 rounded-md border bg-muted/20 p-3 lg:grid-cols-2"
                onSubmit={(event: FormEvent<HTMLFormElement>) => {
                  event.preventDefault()
                  const form = new FormData(event.currentTarget)
                  void prepare({
                    expected_revision: outline.manuscript_revision,
                    action: "edit",
                    reason: String(form.get("reason") ?? "").trim(),
                    unit_key: unit.local_key,
                    patch: {
                      unit_role: String(form.get("unit_role")) as ManuscriptOutlineUnit["unit_role"],
                      rhetorical_move: String(form.get("rhetorical_move")) as ManuscriptOutlineUnit["rhetorical_move"],
                      communicative_job: String(form.get("job") ?? "").trim(),
                      intended_takeaway: String(form.get("takeaway") ?? "").trim(),
                      transition_from_previous: String(form.get("transition") ?? "").trim() || null,
                      quick_reader_role: String(form.get("quick_reader") ?? "").trim() || null,
                      evidence_plan: lines(form.get("evidence_plan")),
                      figure_intentions: lines(form.get("figures")),
                      table_intentions: lines(form.get("tables")),
                      citation_intentions: lines(form.get("citations")),
                      blocker: String(form.get("blocker") ?? "").trim() || null,
                    },
                  })
                }}
              >
                <label className="space-y-1 text-xs font-medium">Unit role<select name="unit_role" defaultValue={unit.unit_role} className={selectClassName}>{UNIT_ROLES.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}</select></label>
                <label className="space-y-1 text-xs font-medium">Rhetorical move<select name="rhetorical_move" defaultValue={unit.rhetorical_move} className={selectClassName}>{RHETORICAL_MOVES.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}</select></label>
                <label className="space-y-1 text-xs font-medium">Communicative job<Textarea name="job" required defaultValue={unit.communicative_job ?? ""} /></label>
                <label className="space-y-1 text-xs font-medium">Intended reader takeaway<Textarea name="takeaway" required defaultValue={unit.intended_takeaway ?? ""} /></label>
                <label className="space-y-1 text-xs font-medium">Transition from prior unit<Textarea name="transition" defaultValue={unit.transition_from_previous ?? ""} /></label>
                <label className="space-y-1 text-xs font-medium">Quick-reader role<Textarea name="quick_reader" defaultValue={unit.quick_reader_role ?? ""} /></label>
                <label className="space-y-1 text-xs font-medium">Evidence plan, one per line<Textarea name="evidence_plan" required defaultValue={unit.evidence_plan.join("\n")} /></label>
                <label className="space-y-1 text-xs font-medium">Citation intentions, one per line<Textarea name="citations" defaultValue={unit.citation_intentions.join("\n")} /></label>
                <label className="space-y-1 text-xs font-medium">Figure intentions, one per line<Textarea name="figures" defaultValue={unit.figure_intentions.join("\n")} /></label>
                <label className="space-y-1 text-xs font-medium">Table intentions, one per line<Textarea name="tables" defaultValue={unit.table_intentions.join("\n")} /></label>
                <label className="space-y-1 text-xs font-medium">Current blocker<Textarea name="blocker" defaultValue={unit.blocker ?? ""} /></label>
                <label className="space-y-1 text-xs font-medium">Reason for this proposal<Input name="reason" required placeholder="Why does this improve the argument?" /></label>
                <Button type="submit" className="lg:col-span-2" disabled={mutations.prepare.isPending}>Prepare edit proposal</Button>
              </form>
            )}

            {expandKey === unit.local_key && (
              <form
                className="mt-3 grid gap-3 rounded-md border bg-muted/20 p-3 lg:grid-cols-2"
                onSubmit={(event: FormEvent<HTMLFormElement>) => {
                  event.preventDefault()
                  const form = new FormData(event.currentTarget)
                  void prepare({
                    expected_revision: outline.manuscript_revision,
                    action: "expand",
                    reason: String(form.get("reason") ?? "").trim(),
                    unit_key: unit.local_key,
                    children: [{
                      local_key: String(form.get("local_key") ?? "").trim(),
                      title: String(form.get("title") ?? "").trim(),
                      location: String(form.get("location") ?? "").trim(),
                      unit_role: String(form.get("unit_role")) as ManuscriptOutlineUnit["unit_role"],
                      rhetorical_move: String(form.get("rhetorical_move")) as ManuscriptOutlineUnit["rhetorical_move"],
                      communicative_job: String(form.get("job") ?? "").trim(),
                      intended_takeaway: String(form.get("takeaway") ?? "").trim(),
                      evidence_plan: lines(form.get("evidence_plan")),
                    }],
                  })
                }}
              >
                <label className="space-y-1 text-xs font-medium">Unit role<select name="unit_role" defaultValue="paragraph_plan" className={selectClassName}>{UNIT_ROLES.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}</select></label>
                <label className="space-y-1 text-xs font-medium">Rhetorical move<select name="rhetorical_move" defaultValue="unspecified" className={selectClassName}>{RHETORICAL_MOVES.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}</select></label>
                <label className="space-y-1 text-xs font-medium">Stable child key<Input name="local_key" required placeholder={`${unit.local_key}.DETAIL`} /></label>
                <label className="space-y-1 text-xs font-medium">Child title<Input name="title" required /></label>
                <label className="space-y-1 text-xs font-medium">Planned location<Input name="location" required defaultValue={`${unit.location}#detail`} /></label>
                <label className="space-y-1 text-xs font-medium">Communicative job<Textarea name="job" required /></label>
                <label className="space-y-1 text-xs font-medium">Intended takeaway<Textarea name="takeaway" required /></label>
                <label className="space-y-1 text-xs font-medium">Evidence plan, one per line<Textarea name="evidence_plan" required /></label>
                <label className="space-y-1 text-xs font-medium">Reason for expansion<Input name="reason" required /></label>
                <Button type="submit" className="self-end" disabled={mutations.prepare.isPending}>Prepare expansion proposal</Button>
                <p className="lg:col-span-2 text-[11px] text-muted-foreground">The parent remains. This form inherits the parent&apos;s disclosed claim and typed evidence bindings by default; typed API callers may narrow them explicitly.</p>
              </form>
            )}

            {condenseKey === unit.local_key && (
              <form
                className="mt-3 grid gap-3 rounded-md border bg-muted/20 p-3 lg:grid-cols-[minmax(0,1fr)_auto]"
                onSubmit={(event: FormEvent<HTMLFormElement>) => {
                  event.preventDefault()
                  const form = new FormData(event.currentTarget)
                  void prepare({
                    expected_revision: outline.manuscript_revision,
                    action: "condense",
                    reason: String(form.get("reason") ?? "").trim(),
                    unit_key: unit.local_key,
                    descendant_keys: unitDescendants,
                  })
                }}
              >
                <div className="text-xs text-muted-foreground">
                  <p className="font-medium text-foreground">Review the descendants and their bindings in the proposal diff before applying.</p>
                  <p className="mt-1">This proposal will retire: {unitDescendants.join(", ")}</p>
                </div>
                <Button type="button" size="sm" variant="ghost" onClick={() => setCondenseKey(null)}>Cancel</Button>
                <label className="space-y-1 text-xs font-medium">
                  Reason for condensation
                  <Input name="reason" required placeholder="Why should these units become one argument block?" />
                </label>
                <Button type="submit" className="self-end" disabled={mutations.prepare.isPending}>Prepare condensation proposal</Button>
              </form>
            )}
          </div>
        )
      })}

      {orderChanged && (
        <div className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
          <div className="flex items-start gap-2 text-xs">
            <GitCompareArrows className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-medium">Local order preview only</p>
              <p className="mt-1 opacity-80">Preparing this proposal records changed predecessors and flags transitions for review. Claim, evidence, and unit content stay bound.</p>
            </div>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input value={reorderReason} onChange={(event) => setReorderReason(event.target.value)} placeholder="Why is this order easier to accept and verify?" />
            <Button
              disabled={!reorderReason.trim() || mutations.prepare.isPending}
              onClick={() => void prepare({
                expected_revision: outline.manuscript_revision,
                action: "reorder",
                reason: reorderReason.trim(),
                ordered_unit_keys: draftOrder,
              })}
            >
              Prepare reorder proposal
            </Button>
            <Button variant="outline" onClick={() => setDraftOrder(canonicalOrder)}>Reset</Button>
          </div>
        </div>
      )}
    </div>
  )
}
