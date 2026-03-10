import { useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { ConfidenceBadge } from "@/components/shared/ConfidenceBadge"
import { TagList } from "@/components/shared/TagList"
import { useNotes, useCreateNote } from "@/hooks/useNotes"
import { timeAgo } from "@/lib/utils"
import { Plus, Filter } from "lucide-react"
import type { JournalEntryCreate, JournalType, Confidence, Source } from "@/api/types"

const TYPES: JournalType[] = [
  "finding", "insight", "pi_instruction", "exploration",
  "idea", "observation", "hypothesis", "methodology", "summary",
]
const CONFIDENCES: Confidence[] = ["hypothesis", "tested", "verified"]
const SOURCES: Source[] = ["pi", "brain", "executor", "web_ui"]

export default function Journal() {
  const [filterType, setFilterType] = useState<string>("")
  const [hideSuperseded, setHideSuperseded] = useState(true)
  const { data: notes, isLoading } = useNotes(
    filterType ? { type: filterType } : undefined,
  )

  const filtered = (notes ?? []).filter((entry) => {
    if (hideSuperseded && entry.superseded_by) return false
    return true
  })

  // Group by date
  const grouped = new Map<string, typeof filtered>()
  for (const entry of filtered) {
    const date = entry.created_at
      ? new Date(entry.created_at).toLocaleDateString("en-US", {
          weekday: "long",
          month: "long",
          day: "numeric",
          year: "numeric",
        })
      : "Unknown Date"
    if (!grouped.has(date)) grouped.set(date, [])
    grouped.get(date)!.push(entry)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Research Journal</h1>
          <p className="text-muted-foreground text-sm">
            {filtered.length} entries{filterType && ` (filtered: ${filterType})`}
          </p>
        </div>
        <CreateNoteDialog />
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <Filter className="h-4 w-4 text-muted-foreground" />
        <Select value={filterType} onValueChange={(v) => setFilterType(v ?? "")}>
          <SelectTrigger className="w-40 h-8 text-xs">
            <SelectValue placeholder="All types" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            {TYPES.map((t) => (
              <SelectItem key={t} value={t}>
                {t}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <label className="flex items-center gap-2 text-xs cursor-pointer">
          <input
            type="checkbox"
            checked={hideSuperseded}
            onChange={(e) => setHideSuperseded(e.target.checked)}
            className="rounded"
          />
          Hide superseded
        </label>
      </div>

      {/* Timeline */}
      {isLoading ? (
        <JournalSkeleton />
      ) : filtered.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            No journal entries found
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {Array.from(grouped.entries()).map(([date, entries]) => (
            <div key={date}>
              <h3 className="text-sm font-semibold text-muted-foreground mb-3 sticky top-0 bg-background py-1">
                {date}
              </h3>
              <div className="space-y-2 ml-4 border-l-2 border-border pl-4">
                {entries.map((entry) => (
                  <Card key={entry.id} className="relative">
                    {/* Timeline dot */}
                    <div className="absolute -left-[25px] top-4 h-2.5 w-2.5 rounded-full border-2 border-primary bg-background" />
                    <CardContent className="py-3 px-4">
                      <div className="flex items-center gap-2 mb-1.5">
                        <StatusBadge status={entry.type} />
                        <ConfidenceBadge confidence={entry.confidence} />
                        <span className="text-[10px] text-muted-foreground">
                          via {entry.source}
                        </span>
                        {entry.created_at && (
                          <span className="text-[10px] text-muted-foreground ml-auto">
                            {timeAgo(entry.created_at)}
                          </span>
                        )}
                      </div>
                      {entry.summary && (
                        <p className="text-sm font-medium mb-1">{entry.summary}</p>
                      )}
                      <p className="text-sm text-muted-foreground line-clamp-3">
                        {entry.content}
                      </p>
                      <TagList tags={entry.tags} />
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function CreateNoteDialog() {
  const [open, setOpen] = useState(false)
  const createNote = useCreateNote()
  const [form, setForm] = useState<JournalEntryCreate>({
    content: "",
    type: "finding",
    source: "web_ui",
    confidence: "hypothesis",
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.content.trim()) return
    await createNote.mutateAsync(form)
    setOpen(false)
    setForm({ content: "", type: "finding", source: "web_ui", confidence: "hypothesis" })
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={<Button size="sm" className="gap-1" />}
      >
        <Plus className="h-4 w-4" /> New Entry
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>New Journal Entry</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label className="text-xs">Type</Label>
              <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v as JournalType })}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TYPES.map((t) => (
                    <SelectItem key={t} value={t}>{t}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Confidence</Label>
              <Select value={form.confidence} onValueChange={(v) => setForm({ ...form, confidence: v as Confidence })}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CONFIDENCES.map((c) => (
                    <SelectItem key={c} value={c}>{c}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Source</Label>
              <Select value={form.source} onValueChange={(v) => setForm({ ...form, source: v as Source })}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SOURCES.map((s) => (
                    <SelectItem key={s} value={s}>{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div>
            <Label className="text-xs">Content</Label>
            <Textarea
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
              placeholder="Write your research note..."
              rows={5}
            />
          </div>
          <div>
            <Label className="text-xs">Tags (comma-separated)</Label>
            <Input
              placeholder="e.g., evaluation, statistical-test"
              onChange={(e) =>
                setForm({
                  ...form,
                  tags: e.target.value.split(",").map((t) => t.trim()).filter(Boolean),
                })
              }
              className="h-8 text-xs"
            />
          </div>
          <Button type="submit" disabled={createNote.isPending || !form.content.trim()}>
            {createNote.isPending ? "Creating..." : "Create Entry"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function JournalSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3].map((i) => (
        <Card key={i}>
          <CardContent className="py-4">
            <div className="h-4 w-32 bg-muted rounded animate-pulse mb-2" />
            <div className="h-3 w-full bg-muted rounded animate-pulse" />
            <div className="h-3 w-2/3 bg-muted rounded animate-pulse mt-1" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
