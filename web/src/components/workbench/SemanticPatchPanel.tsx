import { useMemo, useState } from "react"
import type { FormEvent } from "react"
import { AlertTriangle, Check, Loader2, PencilLine, Sparkles, X } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useSemanticPatches } from "@/hooks/useSemanticPatches"
import type { ManuscriptContext, SemanticPatchProposal } from "@/api/types"

export function SemanticPatchPanel({
  manuscriptId,
  context,
}: {
  manuscriptId: string | null
  context?: ManuscriptContext
}) {
  const patches = useSemanticPatches()
  const [showDirect, setShowDirect] = useState(false)
  const [showLocal, setShowLocal] = useState(false)
  const proposals = useMemo(() => {
    const all = patches.proposals.data ?? []
    if (!manuscriptId) return all
    return all.filter((proposal) => proposal.operations.some(
      (operation) => operation.manuscript_id === manuscriptId,
    ))
  }, [manuscriptId, patches.proposals.data])
  const pending = proposals.filter((proposal) => proposal.status === "proposed")

  const proposeTitle = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!manuscriptId || !context) return
    const form = new FormData(event.currentTarget)
    const title = String(form.get("title") ?? "").trim()
    const reason = String(form.get("reason") ?? "").trim()
    if (!title || !reason) return
    try {
      await patches.create.mutateAsync({
        origin: "human",
        intent: "Revise the manuscript title.",
        reason,
        created_by: "web_ui",
        operations: [{
          operation: "manuscript_metadata_update",
          manuscript_id: manuscriptId,
          expected_revision: context.manuscript.revision,
          title,
        }],
      })
      setShowDirect(false)
      toast.success("Title change saved as a proposal; the manuscript is unchanged")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not create proposal")
    }
  }

  const generateLocal = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!manuscriptId) return
    const form = new FormData(event.currentTarget)
    const instruction = String(form.get("instruction") ?? "").trim()
    if (!instruction) return
    try {
      await patches.generateLocal.mutateAsync({
        instruction,
        created_by: "web_ui",
        targets: [{ target_type: "manuscript", target_id: manuscriptId }],
        constraints: [
          "Preserve qualifiers and counterevidence.",
          "Do not claim PI ratification or application.",
        ],
      })
      setShowLocal(false)
      toast.success("LM Studio suggestion saved for review; nothing was applied")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "LM Studio suggestion failed")
    }
  }

  const transition = async (proposal: SemanticPatchProposal, action: "apply" | "reject") => {
    try {
      const mutation = action === "apply" ? patches.apply : patches.reject
      await mutation.mutateAsync({
        proposalId: proposal.id,
        data: {
          expected_revision: proposal.revision,
          actor: "web_ui",
          reason: action === "apply"
            ? "Approved in the manuscript workbench after semantic diff review."
            : "Rejected in the manuscript workbench after semantic diff review.",
        },
      })
      toast.success(action === "apply" ? "Proposal applied" : "Proposal rejected")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : `Could not ${action} proposal`)
    }
  }

  return (
    <Card>
      <CardHeader className="gap-3 pb-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <PencilLine className="h-4 w-4" /> Edit proposals
            </CardTitle>
            <Badge variant={pending.length ? "default" : "outline"}>{pending.length} awaiting review</Badge>
          </div>
          <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
            Human and AI edits use the same preview and validation path. Creating a proposal never changes RKA;
            Apply is the explicit canonical mutation.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" disabled={!manuscriptId || !context} onClick={() => setShowDirect((value) => !value)}>
            <PencilLine className="mr-1 h-4 w-4" /> Propose title
          </Button>
          <Button size="sm" variant="outline" disabled={!manuscriptId} onClick={() => setShowLocal((value) => !value)}>
            <Sparkles className="mr-1 h-4 w-4" /> Ask LM Studio
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {showDirect && context && (
          <form onSubmit={proposeTitle} className="grid gap-3 rounded-lg border bg-muted/20 p-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
            <label className="space-y-1 text-xs font-medium">
              Proposed title
              <Input name="title" required defaultValue={context.manuscript.title} />
            </label>
            <label className="space-y-1 text-xs font-medium">
              Reason
              <Input name="reason" required placeholder="Why is this clearer or more accurate?" />
            </label>
            <Button type="submit" className="self-end" size="sm" disabled={patches.create.isPending}>Save proposal</Button>
          </form>
        )}
        {showLocal && manuscriptId && (
          <form onSubmit={generateLocal} className="flex flex-col gap-3 rounded-lg border bg-muted/20 p-3 lg:flex-row lg:items-end">
            <label className="min-w-0 flex-1 space-y-1 text-xs font-medium">
              Instruction to the configured local model
              <Textarea name="instruction" required rows={2} placeholder="Suggest a clearer one-paragraph spine while preserving all claim boundaries." />
            </label>
            <Button type="submit" size="sm" disabled={patches.generateLocal.isPending}>
              {patches.generateLocal.isPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              Generate proposal
            </Button>
          </form>
        )}
        {patches.proposals.error && <p role="alert" className="text-sm text-red-700">{patches.proposals.error.message}</p>}
        {patches.proposals.isLoading && <p className="text-sm text-muted-foreground">Loading proposal ledger…</p>}
        {!patches.proposals.isLoading && proposals.length === 0 && (
          <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            No edit proposals for this context. Host agents can prepare an exact context manifest, load the
            proposal schema, and submit a candidate through RKA MCP.
          </div>
        )}
        {proposals.map((proposal) => {
          const changeCount = proposal.semantic_diff.reduce((sum, diff) => sum + diff.changes.length, 0)
          return (
            <div key={proposal.id} className="space-y-3 rounded-lg border p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium">{proposal.intent}</p>
                    <Badge variant="outline">{proposal.origin.replaceAll("_", " ")}</Badge>
                    <Badge variant={proposal.status === "proposed" ? "default" : "secondary"}>{proposal.status}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{proposal.reason}</p>
                </div>
                <span className="font-mono text-[11px] text-muted-foreground">{proposal.id}</span>
              </div>
              <div className="flex flex-wrap gap-2 text-xs">
                <Badge variant="outline">{changeCount} semantic changes</Badge>
                <Badge variant={proposal.validation_findings.length ? "destructive" : "outline"}>
                  {proposal.validation_findings.length} warnings
                </Badge>
                {proposal.boundary !== "none" && <Badge variant="secondary">{proposal.boundary.replaceAll("_", " ")}</Badge>}
              </div>
              {proposal.validation_findings.map((finding) => (
                <div key={`${proposal.id}:${finding.code}`} className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span><strong>{finding.code}</strong>: {finding.message}</span>
                </div>
              ))}
              <details className="rounded-md bg-muted/40 p-2 text-xs">
                <summary className="cursor-pointer font-medium">Inspect before/after semantic diff</summary>
                <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify(proposal.semantic_diff, null, 2)}</pre>
              </details>
              {proposal.status === "proposed" && (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" disabled={patches.apply.isPending || patches.reject.isPending} onClick={() => void transition(proposal, "apply")}>
                    <Check className="mr-1 h-4 w-4" /> Apply explicitly
                  </Button>
                  <Button size="sm" variant="outline" disabled={patches.apply.isPending || patches.reject.isPending} onClick={() => void transition(proposal, "reject")}>
                    <X className="mr-1 h-4 w-4" /> Reject
                  </Button>
                </div>
              )}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
