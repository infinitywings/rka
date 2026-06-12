import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { TagList } from "@/components/shared/TagList"
import { useBuildReportContext } from "@/hooks/useReportContext"
import { FileSearch, Loader2 } from "lucide-react"
import type { ReportContextInclusion } from "@/api/types"

function formatInclusion(via: ReportContextInclusion): string {
  if (via.via === "search") return `search:${via.query}#${via.rank}`
  return `link:${via.link_type}<-${via.from}`
}

export default function ReportContext() {
  const buildContext = useBuildReportContext()
  const [description, setDescription] = useState("")
  const [angleQueries, setAngleQueries] = useState("")

  const handleBuild = () => {
    const angles = angleQueries
      .split(",")
      .map((q) => q.trim())
      .filter(Boolean)
    buildContext.mutate({
      description: description.trim(),
      angle_queries: angles.length > 0 ? angles : undefined,
    })
  }

  const result = buildContext.data

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Report Context</h1>
        <p className="text-muted-foreground text-sm">
          Assemble the knowledge-base node set relevant to a report described in prose
        </p>
      </div>

      {/* Input Form */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <FileSearch className="h-4 w-4" />
            Report Description
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label className="text-xs">Description</Label>
            <Textarea
              placeholder="Describe the report scope in prose, e.g. 'A methods section covering the embedding backend comparison and its evaluation protocol'"
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div>
            <Label className="text-xs">Angle queries (comma-separated, optional)</Label>
            <Input
              placeholder="e.g. embedding backends, evaluation protocol, fastembed"
              value={angleQueries}
              onChange={(e) => setAngleQueries(e.target.value)}
              className="h-8 text-xs"
            />
            <p className="text-[10px] text-muted-foreground mt-1">
              Short 1-4 word seed queries decomposing the description into search angles
            </p>
          </div>
          <Button
            size="sm"
            className="gap-2"
            onClick={handleBuild}
            disabled={buildContext.isPending || description.trim().length < 3}
          >
            {buildContext.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Building...
              </>
            ) : (
              <>
                <FileSearch className="h-4 w-4" />
                Build
              </>
            )}
          </Button>
        </CardContent>
      </Card>

      {/* Error */}
      {buildContext.isError && (
        <Card className="border-red-200">
          <CardContent className="py-4">
            <p className="text-sm text-red-600">
              Error:{" "}
              {buildContext.error instanceof Error
                ? buildContext.error.message
                : "Failed to build report context"}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Results */}
      {result && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <CardTitle className="text-sm font-medium">Context Nodes</CardTitle>
              <p className="text-xs text-muted-foreground">
                {result.seed_count} seed(s) + {result.expanded_count} expanded
                {result.truncated && " (truncated)"}
              </p>
            </div>
            {result.queries.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {result.queries.map((q) => (
                  <Badge key={q} variant="secondary" className="text-[10px]">
                    {q}
                  </Badge>
                ))}
              </div>
            )}
          </CardHeader>
          <CardContent>
            {result.nodes.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No matching nodes found for this description
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-right">Score</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>ID</TableHead>
                    <TableHead>Label</TableHead>
                    <TableHead>Included via</TableHead>
                    <TableHead>Tags</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.nodes.map((node) => (
                    <TableRow key={node.id}>
                      <TableCell className="text-right font-mono text-xs">
                        {node.score.toFixed(2)}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="text-[10px]">
                          {node.type}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <span
                          className="font-mono text-xs text-muted-foreground block max-w-[140px] truncate"
                          title={node.id}
                        >
                          {node.id}
                        </span>
                      </TableCell>
                      <TableCell className="whitespace-normal">
                        <span className="text-xs">{node.label}</span>
                      </TableCell>
                      <TableCell>
                        <span
                          className="font-mono text-[10px] text-muted-foreground block max-w-[220px] truncate"
                          title={formatInclusion(node.included_via)}
                        >
                          {formatInclusion(node.included_via)}
                        </span>
                      </TableCell>
                      <TableCell>
                        <TagList tags={node.tags} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      {/* Initial state */}
      {!result && !buildContext.isPending && (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            <FileSearch className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p>Describe the report above and click "Build"</p>
            <p className="text-xs mt-1">
              Seeds come from every angle query, then expand through provenance links
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
