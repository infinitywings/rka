import { ArrowRight, Eye, Fingerprint, SquareArrowOutUpRight } from "lucide-react"
import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export interface WorkbenchTraceItem {
  title: string
  summary: string
  kind: string
  origin: string
  derivation: string
  ids: string[]
  status?: string
  trace?: string[]
  links?: Array<{
    label: string
    to: string
  }>
}

export function EvidenceInspector({ item }: { item: WorkbenchTraceItem }) {
  return (
    <Card className="min-h-40">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Eye className="h-4 w-4" /> Evidence and derivation
          </CardTitle>
          <Badge variant="outline">{item.kind}</Badge>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="space-y-2">
          <div>
            <h3 className="text-sm font-semibold">{item.title}</h3>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.summary}</p>
          </div>
          <div className="rounded-md border bg-muted/30 p-2.5 text-xs">
            <p><span className="font-medium">Origin:</span> {item.origin}</p>
            <p className="mt-1"><span className="font-medium">Derivation:</span> {item.derivation}</p>
            {item.status && <p className="mt-1"><span className="font-medium">Status:</span> {item.status}</p>}
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-medium">
            <Fingerprint className="h-3.5 w-3.5" /> Record identifiers
          </div>
          {item.ids.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {item.ids.map((id) => (
                <code key={id} className="rounded bg-muted px-1.5 py-1 text-[10px]">{id}</code>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">No canonical record yet. This item is an interface-stage projection.</p>
          )}
          {item.trace && item.trace.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 text-[10px] text-muted-foreground">
              {item.trace.map((node, index) => (
                <span key={`${node}-${index}`} className="flex items-center gap-1">
                  {index > 0 && <ArrowRight className="h-3 w-3" />}
                  <span className="rounded border px-1.5 py-0.5">{node}</span>
                </span>
              ))}
            </div>
          )}
          {item.links && item.links.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {item.links.map((link) => (
                <Link
                  key={`${link.to}-${link.label}`}
                  to={link.to}
                  className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-medium transition-colors hover:border-primary/40 hover:bg-muted"
                >
                  {link.label}
                  <SquareArrowOutUpRight className="h-3 w-3" />
                </Link>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
