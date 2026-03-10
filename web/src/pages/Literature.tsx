import { useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { TagList } from "@/components/shared/TagList"
import { useLiterature, useCreateLiterature } from "@/hooks/useLiterature"
import { Plus, ExternalLink, FileText, Calendar, User } from "lucide-react"
import type { Literature as LiteratureType, LiteratureCreate } from "@/api/types"

const STATUSES: { value: string; label: string }[] = [
  { value: "all", label: "All" },
  { value: "to_read", label: "To Read" },
  { value: "reading", label: "Reading" },
  { value: "read", label: "Read" },
  { value: "cited", label: "Cited" },
  { value: "excluded", label: "Excluded" },
]

export default function Literature() {
  const [statusFilter, setStatusFilter] = useState("all")
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data: literature, isLoading } = useLiterature(
    statusFilter !== "all" ? { status: statusFilter } : undefined,
  )
  const selected = literature?.find((l) => l.id === selectedId)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Literature</h1>
          <p className="text-muted-foreground text-sm">
            {literature?.length ?? 0} papers
          </p>
        </div>
        <AddLiteratureDialog />
      </div>

      {/* Status Tabs */}
      <Tabs value={statusFilter} onValueChange={setStatusFilter}>
        <TabsList>
          {STATUSES.map(({ value, label }) => (
            <TabsTrigger key={value} value={value} className="text-xs">
              {label}
              {value !== "all" && literature && (
                <span className="ml-1 text-muted-foreground">
                  ({literature.filter((l) => value === "all" || l.status === value).length})
                </span>
              )}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {/* Table */}
      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-12 bg-muted rounded animate-pulse" />
          ))}
        </div>
      ) : !literature?.length ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            No literature entries found
          </CardContent>
        </Card>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[40%]">Title</TableHead>
                <TableHead>Authors</TableHead>
                <TableHead>Year</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Tags</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {literature.map((lit) => (
                <TableRow
                  key={lit.id}
                  className="cursor-pointer hover:bg-muted/50"
                  onClick={() => setSelectedId(lit.id)}
                >
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm truncate max-w-[300px]">
                        {lit.title}
                      </span>
                      {lit.doi && (
                        <ExternalLink className="h-3 w-3 text-muted-foreground shrink-0" />
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground truncate max-w-[200px]">
                    {lit.authors?.join(", ") ?? "—"}
                  </TableCell>
                  <TableCell className="text-sm">{lit.year ?? "—"}</TableCell>
                  <TableCell>
                    <StatusBadge status={lit.status} />
                  </TableCell>
                  <TableCell>
                    <TagList tags={lit.tags} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Detail Sheet */}
      <Sheet open={!!selectedId} onOpenChange={(open) => !open && setSelectedId(null)}>
        <SheetContent className="w-[450px] sm:w-[550px] overflow-y-auto">
          <SheetHeader>
            <SheetTitle className="text-lg">Paper Detail</SheetTitle>
          </SheetHeader>
          {selected && <LiteratureDetail lit={selected} />}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function DetailSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">{label}</h4>
      {children}
    </div>
  )
}

function LiteratureDetail({ lit }: { lit: LiteratureType }) {
  const pdfFilename = lit.pdf_path?.split("/").pop()

  return (
    <div className="space-y-5 mt-4">
      {/* Header */}
      <div>
        <h3 className="text-base font-semibold leading-tight">{lit.title}</h3>
        {(lit.authors || lit.year || lit.venue) && (
          <p className="text-sm text-muted-foreground mt-1">
            {lit.authors?.join(", ")}
            {lit.year && ` (${lit.year})`}
            {lit.venue && ` — ${lit.venue}`}
          </p>
        )}
      </div>

      {/* Status + Score row */}
      <div className="flex items-center gap-3">
        <StatusBadge status={lit.status} />
        {lit.relevance_score != null && (
          <span className="text-xs text-muted-foreground">
            Relevance: {lit.relevance_score}/10
          </span>
        )}
      </div>

      {/* PDF path */}
      {lit.pdf_path && (
        <DetailSection label="PDF File">
          <div className="flex items-center gap-2 text-sm">
            <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
            <span className="text-muted-foreground break-all" title={lit.pdf_path}>
              {pdfFilename}
            </span>
          </div>
        </DetailSection>
      )}

      {/* Abstract */}
      {lit.abstract && (
        <DetailSection label="Abstract">
          <p className="text-sm text-muted-foreground whitespace-pre-wrap">{lit.abstract}</p>
        </DetailSection>
      )}

      {/* Key Findings */}
      {lit.key_findings && lit.key_findings.length > 0 && (
        <DetailSection label="Key Findings">
          <ul className="text-sm text-muted-foreground list-disc pl-4 space-y-1">
            {lit.key_findings.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </DetailSection>
      )}

      {/* Methodology Notes */}
      {lit.methodology_notes && (
        <DetailSection label="Methodology Notes">
          <p className="text-sm text-muted-foreground whitespace-pre-wrap">{lit.methodology_notes}</p>
        </DetailSection>
      )}

      {/* Relevance */}
      {lit.relevance && (
        <DetailSection label="Relevance">
          <p className="text-sm text-muted-foreground">{lit.relevance}</p>
        </DetailSection>
      )}

      {/* Notes */}
      {lit.notes && (
        <DetailSection label="Notes">
          <p className="text-sm text-muted-foreground whitespace-pre-wrap">{lit.notes}</p>
        </DetailSection>
      )}

      {/* Links: DOI / URL */}
      {(lit.doi || lit.url) && (
        <DetailSection label="Links">
          <div className="space-y-1">
            {lit.doi && (
              <a
                href={`https://doi.org/${lit.doi}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-blue-600 hover:underline flex items-center gap-1"
              >
                DOI: {lit.doi} <ExternalLink className="h-3 w-3" />
              </a>
            )}
            {lit.url && (
              <a
                href={lit.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-blue-600 hover:underline flex items-center gap-1"
              >
                {lit.url} <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        </DetailSection>
      )}

      {/* Related Decisions */}
      {lit.related_decisions && lit.related_decisions.length > 0 && (
        <DetailSection label="Related Decisions">
          <div className="flex flex-wrap gap-1">
            {lit.related_decisions.map((d) => (
              <span key={d} className="text-xs bg-muted px-2 py-0.5 rounded font-mono">{d}</span>
            ))}
          </div>
        </DetailSection>
      )}

      {/* Tags */}
      {lit.tags.length > 0 && (
        <DetailSection label="Tags">
          <TagList tags={lit.tags} />
        </DetailSection>
      )}

      {/* Metadata footer */}
      <div className="pt-3 border-t space-y-1">
        {lit.added_by && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <User className="h-3 w-3" />
            Added by: {lit.added_by}
          </div>
        )}
        {lit.created_at && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Calendar className="h-3 w-3" />
            Created: {new Date(lit.created_at).toLocaleDateString("en-US", {
              year: "numeric", month: "short", day: "numeric",
              hour: "2-digit", minute: "2-digit",
            })}
          </div>
        )}
        {lit.updated_at && lit.updated_at !== lit.created_at && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Calendar className="h-3 w-3" />
            Updated: {new Date(lit.updated_at).toLocaleDateString("en-US", {
              year: "numeric", month: "short", day: "numeric",
              hour: "2-digit", minute: "2-digit",
            })}
          </div>
        )}
        <div className="text-xs text-muted-foreground/50 font-mono pt-1">{lit.id}</div>
      </div>
    </div>
  )
}

function AddLiteratureDialog() {
  const [open, setOpen] = useState(false)
  const createLit = useCreateLiterature()
  const [form, setForm] = useState<LiteratureCreate>({
    title: "",
    added_by: "web_ui",
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.title.trim()) return
    await createLit.mutateAsync(form)
    setOpen(false)
    setForm({ title: "", added_by: "web_ui" })
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={<Button size="sm" className="gap-1" />}
      >
        <Plus className="h-4 w-4" /> Add Paper
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Add Literature</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label className="text-xs">Title *</Label>
            <Input
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="Paper title"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Authors (comma-separated)</Label>
              <Input
                placeholder="Author 1, Author 2"
                onChange={(e) =>
                  setForm({
                    ...form,
                    authors: e.target.value.split(",").map((a) => a.trim()).filter(Boolean),
                  })
                }
                className="h-8 text-xs"
              />
            </div>
            <div>
              <Label className="text-xs">Year</Label>
              <Input
                type="number"
                placeholder="2024"
                onChange={(e) => setForm({ ...form, year: parseInt(e.target.value) || undefined })}
                className="h-8 text-xs"
              />
            </div>
          </div>
          <div>
            <Label className="text-xs">DOI</Label>
            <Input
              placeholder="10.1234/example"
              onChange={(e) => setForm({ ...form, doi: e.target.value || undefined })}
              className="h-8 text-xs"
            />
          </div>
          <div>
            <Label className="text-xs">Abstract</Label>
            <Textarea
              onChange={(e) => setForm({ ...form, abstract: e.target.value || undefined })}
              placeholder="Paper abstract..."
              rows={3}
            />
          </div>
          <div>
            <Label className="text-xs">Tags (comma-separated)</Label>
            <Input
              placeholder="e.g., iot-security, firmware"
              onChange={(e) =>
                setForm({
                  ...form,
                  tags: e.target.value.split(",").map((t) => t.trim()).filter(Boolean),
                })
              }
              className="h-8 text-xs"
            />
          </div>
          <Button type="submit" disabled={createLit.isPending || !form.title.trim()}>
            {createLit.isPending ? "Adding..." : "Add Paper"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
