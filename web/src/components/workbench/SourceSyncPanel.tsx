import { useMemo, useState } from "react"
import { AlertTriangle, CheckCircle2, FileCode2, RefreshCw, Save, ShieldAlert, XCircle } from "lucide-react"
import { toast } from "sonner"

import { Markdown } from "@/components/shared/Markdown"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { useManuscriptSources } from "@/hooks/useManuscriptSources"
import type { ManuscriptSourceFile, ManuscriptSourceProposal } from "@/api/types"


export function SourceSyncPanel({ manuscriptId }: { manuscriptId: string }) {
  const [relativePath, setRelativePath] = useState<string | null>(null)
  const sources = useManuscriptSources(manuscriptId, relativePath)

  const pending = useMemo(
    () => (sources.proposals.data ?? []).filter(
      (proposal) => proposal.status === "proposed" && proposal.relative_path === sources.relativePath,
    ),
    [sources.proposals.data, sources.relativePath],
  )

  if (sources.overview.isLoading) {
    return <div className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">Loading local manuscript sources…</div>
  }
  if (sources.overview.error) {
    return (
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100">
        <p className="font-medium">Local source synchronization is unavailable</p>
        <p className="mt-1 text-xs opacity-80">{sources.overview.error.message}</p>
        <p className="mt-2 text-xs opacity-80">
          Set an existing manuscript workspace and explicitly allow its server-side root with <code>RKA_MANUSCRIPT_WORKSPACE_ROOTS</code>. Workspace metadata alone never grants file access.
        </p>
      </div>
    )
  }

  const overview = sources.overview.data
  if (!overview) return null

  return (
    <section className="min-w-0 space-y-3 rounded-lg border bg-card p-4" aria-labelledby="source-sync-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <FileCode2 className="h-4 w-4" />
            <h3 id="source-sync-heading" className="font-semibold">Draft source synchronization</h3>
            <Badge variant="outline">local web only</Badge>
          </div>
          <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
            Markdown/LaTeX owns public prose; RKA owns claims, evidence, citations, and unit semantics. Preparing a change never writes the file. Apply is explicit, expected-hash guarded, recoverable, and performs no Git operation.
          </p>
        </div>
        <code className="max-w-full truncate rounded bg-muted px-2 py-1 text-[10px]" title={overview.workspace_ref}>
          {overview.workspace_ref}
        </code>
      </div>

      <Tabs defaultValue="source" className="min-w-0">
        <TabsList className="h-auto w-full flex-wrap justify-start">
          <TabsTrigger value="source">Draft source</TabsTrigger>
          <TabsTrigger value="quick">Quick reader</TabsTrigger>
          <TabsTrigger value="risk">Reviewer risk (private)</TabsTrigger>
        </TabsList>

        <TabsContent value="source" className="space-y-3 pt-3">
          {overview.files.length === 0 ? (
            <div className="rounded border border-dashed p-4 text-sm text-muted-foreground">
              No visible `.md`, `.markdown`, or `.tex` file exists in this workspace. Create one with your normal editor, then refresh this view.
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <label htmlFor="manuscript-source-file" className="text-xs font-medium">Source file</label>
                <select
                  id="manuscript-source-file"
                  className="w-full min-w-0 rounded-md border bg-background px-2 py-1.5 text-sm sm:w-auto sm:min-w-64"
                  value={sources.relativePath ?? ""}
                  onChange={(event) => {
                    setRelativePath(event.target.value)
                  }}
                >
                  {overview.files.map((file) => (
                    <option key={file.relative_path} value={file.relative_path}>{file.relative_path}</option>
                  ))}
                </select>
                {sources.file.data && (
                  <>
                    <Badge variant="outline">{sources.file.data.source_format}</Badge>
                    <code className="text-[10px] text-muted-foreground">sha256:{sources.file.data.content_hash.slice(0, 12)}</code>
                    <Badge variant={sources.file.data.findings.some((item) => item.severity === "error") ? "destructive" : "secondary"}>
                      {sources.file.data.anchors.length} unit anchor{sources.file.data.anchors.length === 1 ? "" : "s"}
                    </Badge>
                  </>
                )}
              </div>

              {sources.file.isLoading ? (
                <p className="text-sm text-muted-foreground">Reading source…</p>
              ) : sources.file.error ? (
                <p className="rounded border border-red-300 bg-red-50 p-3 text-xs text-red-900">{sources.file.error.message}</p>
              ) : sources.file.data ? (
                <SourceFileWorkspace
                  key={sources.file.data.relative_path}
                  snapshot={sources.file.data}
                  pending={pending}
                  sources={sources}
                />
              ) : null}
            </>
          )}
        </TabsContent>

        <TabsContent value="quick" className="space-y-2 pt-3">
          <p className="text-xs text-muted-foreground">This scan shows the fast-reader argument path and whether each stable `mun_` unit has a public source range.</p>
          {overview.quick_reader.map((unit, index) => (
            <div key={unit.unit_id} className="rounded-md border p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{index + 1}</Badge>
                <strong>{unit.local_key}</strong>
                <code className="break-all text-[10px] text-muted-foreground">{unit.unit_id}</code>
                <Badge variant={unit.anchor_state === "linked" ? "secondary" : "destructive"}>{unit.anchor_state}</Badge>
              </div>
              <p className="mt-2"><strong>Job:</strong> {unit.communicative_job || "Not specified"}</p>
              <p className="mt-1"><strong>Takeaway:</strong> {unit.intended_takeaway || "Not specified"}</p>
              <p className="mt-1 text-xs text-muted-foreground"><strong>Quick-reader role:</strong> {unit.quick_reader_role || "Not specified"}</p>
              {unit.anchors.map((anchor) => (
                <p key={`${anchor.relative_path}:${anchor.start_line}`} className="mt-1 font-mono text-[10px] text-muted-foreground">
                  {anchor.relative_path}:{anchor.start_line}-{anchor.end_line} · sha256:{anchor.content_hash.slice(0, 12)}
                </p>
              ))}
            </div>
          ))}
        </TabsContent>

        <TabsContent value="risk" className="space-y-3 pt-3">
          <div className="rounded-md border border-purple-300 bg-purple-50 p-3 text-xs text-purple-950 dark:border-purple-900 dark:bg-purple-950 dark:text-purple-100">
            <div className="flex items-center gap-2 font-medium"><ShieldAlert className="h-4 w-4" /> Private reviewer-risk workspace</div>
            <p className="mt-1 opacity-80">These boundaries, qualifiers, counterevidence, and citation warnings inform strategy. This projection cannot insert them into public source automatically.</p>
          </div>
          {overview.private_reviewer_risks.length === 0 ? (
            <p className="rounded border border-dashed p-4 text-sm text-muted-foreground">No typed private risks are currently projected. This is not proof that the manuscript has no weaknesses.</p>
          ) : overview.private_reviewer_risks.map((risk, index) => (
            <div key={`${risk.kind}:${risk.unit_id}:${risk.claim_id ?? risk.evidence_claim_id ?? risk.citation_key ?? index}`} className="rounded-md border p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{risk.kind.replaceAll("_", " ")}</Badge>
                <code className="break-all text-[10px] text-muted-foreground">{risk.unit_id}</code>
              </div>
              <p className="mt-2">{risk.message}</p>
              {risk.content && <p className="mt-1 text-xs text-muted-foreground">{risk.content}</p>}
              {risk.items?.map((item) => <p key={item} className="mt-1 text-xs text-muted-foreground">• {item}</p>)}
            </div>
          ))}
        </TabsContent>
      </Tabs>
    </section>
  )
}


function SourceFileWorkspace({
  snapshot,
  pending,
  sources,
}: {
  snapshot: ManuscriptSourceFile
  pending: ManuscriptSourceProposal[]
  sources: ReturnType<typeof useManuscriptSources>
}) {
  const [draft, setDraft] = useState(snapshot.content)
  const [loadedContent, setLoadedContent] = useState(snapshot.content)
  const [loadedHash, setLoadedHash] = useState(snapshot.content_hash)
  const [dirty, setDirty] = useState(false)
  const [reason, setReason] = useState("Revise the public source while preserving the reviewed manuscript-unit boundary.")
  const [reviewedProposal, setReviewedProposal] = useState<ManuscriptSourceProposal | null>(null)
  const externalConflict = dirty && snapshot.content_hash !== loadedHash

  const checkExternal = async () => {
    const result = await sources.file.refetch()
    const current = result.data
    if (!current || current.content_hash === loadedHash) {
      toast.success("No external source change detected")
      return
    }
    if (dirty) {
      toast.warning("External edit detected; your unsent draft was preserved")
      return
    }
    setDraft(current.content)
    setLoadedContent(current.content)
    setLoadedHash(current.content_hash)
    toast.success("Reloaded the external source change")
  }

  const reloadCurrent = () => {
    const current = sources.file.data
    if (!current) return
    setDraft(current.content)
    setLoadedContent(current.content)
    setLoadedHash(current.content_hash)
    setDirty(false)
  }

  const prepare = async () => {
    if (!dirty || externalConflict) return
    try {
      const proposal = await sources.create.mutateAsync({
        origin: "human",
        relative_path: snapshot.relative_path,
        expected_content_hash: loadedHash,
        content: draft,
        created_by: "web_ui",
        reason,
      })
      setReviewedProposal(proposal)
      toast.success("Source proposal prepared; the file is still unchanged")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not prepare source proposal")
    }
  }

  const apply = async (proposal: ManuscriptSourceProposal) => {
    try {
      const applied = await sources.apply.mutateAsync({
        proposalId: proposal.id,
        revision: proposal.revision,
        reason: "PI applied the reviewed source diff in the manuscript workbench.",
      })
      const appliedContent = applied.proposed_content ?? draft
      setDraft(appliedContent)
      setLoadedContent(appliedContent)
      setLoadedHash(applied.proposed_content_hash)
      setDirty(false)
      setReviewedProposal(null)
      toast.success("Source file replaced atomically; recovery metadata was retained")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not apply source proposal")
    }
  }

  const reject = async (proposal: ManuscriptSourceProposal) => {
    try {
      await sources.reject.mutateAsync({
        proposalId: proposal.id,
        revision: proposal.revision,
        reason: "PI rejected the proposed source wording after review.",
      })
      setReviewedProposal(null)
      toast.success("Source proposal rejected; the file was not changed")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not reject source proposal")
    }
  }

  const review = async (proposal: ManuscriptSourceProposal) => {
    try {
      setReviewedProposal(await sources.review.mutateAsync(proposal.id))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not load source proposal")
    }
  }

  return (
    <>
      <div className="flex justify-end">
        <Button size="sm" variant="outline" onClick={() => void checkExternal()} disabled={sources.file.isFetching}>
          <RefreshCw className="mr-1 h-3.5 w-3.5" /> Check external edits
        </Button>
      </div>
      {externalConflict && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-red-300 bg-red-50 p-3 text-xs text-red-950 dark:border-red-900 dark:bg-red-950 dark:text-red-100">
          <div>
            <p className="font-medium">The file changed outside this editor</p>
            <p className="mt-1 opacity-80">Your unsent draft is preserved. Reload the current file, compare manually, then prepare a new proposal.</p>
          </div>
          <Button size="sm" variant="outline" onClick={reloadCurrent}>Reload current file</Button>
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="space-y-1">
          <label htmlFor="manuscript-source-editor" className="text-xs font-medium">Editable public source</label>
          <Textarea
            id="manuscript-source-editor"
            className="min-h-[28rem] font-mono text-xs"
            spellCheck={false}
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value)
              setDirty(event.target.value !== loadedContent)
            }}
          />
        </div>
        <div className="space-y-1">
          <p className="text-xs font-medium">Non-authoritative preview</p>
          <div className="min-h-[28rem] overflow-auto rounded-md border bg-background p-3">
            {snapshot.source_format === "markdown" ? (
              <Markdown>{draft}</Markdown>
            ) : (
              <pre className="whitespace-pre-wrap font-mono text-xs">{draft}</pre>
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-[1fr_auto]">
        <label className="space-y-1 text-xs font-medium">
          Proposal reason
          <Textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={2} />
        </label>
        <Button
          className="self-end"
          disabled={!dirty || externalConflict || !reason.trim() || sources.create.isPending}
          onClick={() => void prepare()}
        >
          <Save className="mr-1 h-4 w-4" /> Prepare change
        </Button>
      </div>

      {snapshot.findings.length > 0 && (
        <details className="rounded-md border p-3 text-xs" open={snapshot.findings.some((item) => item.severity === "error")}>
          <summary className="cursor-pointer font-medium">Current anchor and provenance diagnostics ({snapshot.findings.length})</summary>
          <ul className="mt-2 space-y-1">
            {snapshot.findings.map((finding, index) => (
              <li key={`${finding.code}:${finding.line ?? index}`} className="flex items-start gap-2">
                {finding.severity === "error" ? <XCircle className="mt-0.5 h-3.5 w-3.5 text-red-600" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 text-amber-600" />}
                <span><strong>{finding.code}</strong>: {finding.message}{finding.line ? ` · line ${finding.line}` : ""}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {pending.length > 0 && (
        <div className="space-y-2 rounded-md border border-blue-200 bg-blue-50 p-3 text-xs text-blue-950 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-100">
          <p className="font-medium">Pending reviewed source changes</p>
          {pending.map((proposal) => (
            <div key={proposal.id} className="rounded border border-blue-200/70 bg-background/60 p-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <code>{proposal.id}</code>
                  <p className="mt-1 opacity-80">{proposal.reason}</p>
                  <p className="mt-1 font-mono text-[10px] opacity-70">{proposal.base_content_hash?.slice(0, 12)} → {proposal.proposed_content_hash.slice(0, 12)}</p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void review(proposal)}
                  disabled={sources.review.isPending}
                >
                  Review source diff
                </Button>
              </div>
            </div>
          ))}
          {reviewedProposal?.status === "proposed" && reviewedProposal.proposed_content !== undefined && (
            <div className="space-y-3 rounded border border-blue-300 bg-background p-3" aria-live="polite">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="font-medium">Review before apply</p>
                  <p className="mt-1 opacity-80">
                    {reviewedProposal.origin.replaceAll("_", " ")} proposal · revision {reviewedProposal.revision}
                  </p>
                </div>
                <code className="text-[10px]">{reviewedProposal.id}</code>
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                <div>
                  <p className="mb-1 font-medium">Current file</p>
                  <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded border bg-muted/40 p-2 font-mono text-[11px]">{snapshot.content}</pre>
                </div>
                <div>
                  <p className="mb-1 font-medium">Proposed file</p>
                  <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded border bg-muted/40 p-2 font-mono text-[11px]">{reviewedProposal.proposed_content}</pre>
                </div>
              </div>
              {reviewedProposal.validation_findings.length > 0 && (
                <ul className="space-y-1">
                  {reviewedProposal.validation_findings.map((finding, index) => (
                    <li key={`${finding.code}:${finding.line ?? index}`}>
                      <strong>{finding.code}</strong>: {finding.message}
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void reject(reviewedProposal)}
                  disabled={sources.reject.isPending}
                >
                  Reject
                </Button>
                <Button
                  size="sm"
                  onClick={() => void apply(reviewedProposal)}
                  disabled={sources.apply.isPending}
                >
                  <CheckCircle2 className="mr-1 h-3.5 w-3.5" /> Apply reviewed change
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  )
}
