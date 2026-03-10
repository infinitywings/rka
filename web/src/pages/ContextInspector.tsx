import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { TemperatureBadge } from "@/components/shared/TemperatureBadge"
import { useGetContext } from "@/hooks/useContext"
import { useProjectStatus } from "@/hooks/useProject"
import { Telescope, Copy, Check, Loader2 } from "lucide-react"
import type { ContextPackage, ContextRequest } from "@/api/types"

export default function ContextInspector() {
  const { data: project } = useProjectStatus()
  const getContext = useGetContext()

  const [form, setForm] = useState<ContextRequest>({
    topic: "",
    phase: "",
    depth: "summary",
    max_tokens: 4000,
  })
  const [result, setResult] = useState<ContextPackage | null>(null)
  const [copied, setCopied] = useState(false)

  const handleGenerate = async () => {
    const payload: ContextRequest = {
      ...form,
      topic: form.topic || undefined,
      phase: form.phase || undefined,
    }
    const data = await getContext.mutateAsync(payload)
    setResult(data)
  }

  const handleCopy = async () => {
    if (!result) return
    await navigator.clipboard.writeText(JSON.stringify(result, null, 2))
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const phases = project?.phases_config ?? []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Context Inspector</h1>
        <p className="text-muted-foreground text-sm">
          Generate and inspect context packages for LLM consumption
        </p>
      </div>

      {/* Input Form */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Telescope className="h-4 w-4" />
            Context Parameters
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <div>
              <Label className="text-xs">Topic</Label>
              <Input
                placeholder="e.g., firmware analysis"
                value={form.topic ?? ""}
                onChange={(e) => setForm({ ...form, topic: e.target.value })}
                className="h-8 text-xs"
              />
            </div>
            <div>
              <Label className="text-xs">Phase</Label>
              <Select
                value={form.phase ?? ""}
                onValueChange={(v) => setForm({ ...form, phase: (!v || v === "__all__") ? "" : v })}
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="All phases" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">All phases</SelectItem>
                  {phases.map((p) => (
                    <SelectItem key={p} value={p}>
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Depth</Label>
              <Select
                value={form.depth ?? "summary"}
                onValueChange={(v) =>
                  setForm({ ...form, depth: v as "summary" | "detailed" })
                }
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="summary">Summary</SelectItem>
                  <SelectItem value="detailed">Detailed</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Max Tokens</Label>
              <Input
                type="number"
                value={form.max_tokens ?? 4000}
                onChange={(e) =>
                  setForm({ ...form, max_tokens: parseInt(e.target.value) || 4000 })
                }
                min={500}
                max={32000}
                step={500}
                className="h-8 text-xs"
              />
            </div>
          </div>
          <Button
            onClick={handleGenerate}
            disabled={getContext.isPending}
            className="mt-4 gap-2"
            size="sm"
          >
            {getContext.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Generating...
              </>
            ) : (
              <>
                <Telescope className="h-4 w-4" />
                Generate Context
              </>
            )}
          </Button>
        </CardContent>
      </Card>

      {/* Error */}
      {getContext.isError && (
        <Card className="border-red-200">
          <CardContent className="py-4">
            <p className="text-sm text-red-600">
              Error: {getContext.error instanceof Error ? getContext.error.message : "Failed to generate context"}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Results */}
      {result && (
        <div className="grid gap-4 md:grid-cols-2">
          {/* Left: Entry List with Temperature */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium">
                  Context Entries
                </CardTitle>
                <Badge variant="outline" className="text-xs">
                  ~{result.token_estimate} tokens
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* HOT entries */}
              {result.hot_entries.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <TemperatureBadge temp="HOT" />
                    <span className="text-xs text-muted-foreground">
                      {result.hot_entries.length} entries
                    </span>
                  </div>
                  <div className="space-y-1">
                    {result.hot_entries.map((entry, i) => (
                      <div
                        key={i}
                        className="text-xs p-2 rounded border border-red-100 bg-red-50/50"
                      >
                        {entry}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* WARM entries */}
              {result.warm_entries.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <TemperatureBadge temp="WARM" />
                    <span className="text-xs text-muted-foreground">
                      {result.warm_entries.length} entries
                    </span>
                  </div>
                  <div className="space-y-1">
                    {result.warm_entries.map((entry, i) => (
                      <div
                        key={i}
                        className="text-xs p-2 rounded border border-orange-100 bg-orange-50/50"
                      >
                        {entry}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* COLD entries */}
              {result.cold_entries.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <TemperatureBadge temp="COLD" />
                    <span className="text-xs text-muted-foreground">
                      {result.cold_entries.length} entries
                    </span>
                  </div>
                  <div className="space-y-1">
                    {result.cold_entries.map((entry, i) => (
                      <div
                        key={i}
                        className="text-xs p-2 rounded border border-blue-100 bg-blue-50/50"
                      >
                        {entry}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {result.hot_entries.length === 0 &&
                result.warm_entries.length === 0 &&
                result.cold_entries.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    No entries found for this context query
                  </p>
                )}

              {/* Sources */}
              {result.sources.length > 0 && (
                <>
                  <Separator />
                  <div>
                    <span className="text-xs font-medium">Sources:</span>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {result.sources.map((s, i) => (
                        <Badge key={i} variant="secondary" className="text-[10px]">
                          {s}
                        </Badge>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          {/* Right: Narrative + Copy */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium">
                  Generated Narrative
                </CardTitle>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleCopy}
                  className="gap-1 h-7 text-xs"
                >
                  {copied ? (
                    <>
                      <Check className="h-3 w-3" />
                      Copied
                    </>
                  ) : (
                    <>
                      <Copy className="h-3 w-3" />
                      Copy JSON
                    </>
                  )}
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {result.narrative ? (
                <div className="prose prose-sm max-w-none">
                  <div className="text-sm whitespace-pre-wrap rounded-md border bg-muted/30 p-4">
                    {result.narrative}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No narrative generated. Try increasing max_tokens or using
                  "detailed" depth.
                </p>
              )}

              {result.note && (
                <div className="mt-4 text-xs text-muted-foreground italic border-l-2 pl-3">
                  {result.note}
                </div>
              )}

              {/* Meta info */}
              <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <div>
                  <span className="font-medium">Topic: </span>
                  {result.topic ?? "—"}
                </div>
                <div>
                  <span className="font-medium">Phase: </span>
                  {result.phase ?? "all"}
                </div>
                <div>
                  <span className="font-medium">Token estimate: </span>
                  {result.token_estimate}
                </div>
                <div>
                  <span className="font-medium">Total entries: </span>
                  {result.hot_entries.length +
                    result.warm_entries.length +
                    result.cold_entries.length}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Initial state */}
      {!result && !getContext.isPending && (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            <Telescope className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p>Configure parameters above and click "Generate Context"</p>
            <p className="text-xs mt-1">
              The context engine assembles HOT/WARM/COLD entries based on
              recency, relevance, and phase filtering
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
