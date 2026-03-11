import { useState, useCallback, useEffect } from "react"
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  MarkerType,
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import ELK from "elkjs/lib/elk.bundled.js"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Badge } from "@/components/ui/badge"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { TagList } from "@/components/shared/TagList"
import type { Decision, Mission, JournalEntry, Literature, GraphData } from "@/api/types"

const elk = new ELK()

// Node dimensions — ELK needs these upfront
const DIM = {
  decision: { w: 252, h: 88 },
  mission:  { w: 232, h: 70 },
  finding:  { w: 212, h: 60 },
  lit:      { w: 222, h: 68 },
}

// ── Custom node components ──────────────────────────────────────────────────

const decisionStatusCls: Record<string, string> = {
  active:    "border-green-500 bg-green-50",
  abandoned: "border-gray-300 bg-gray-100 border-dashed",
  superseded:"border-yellow-400 bg-yellow-50",
  merged:    "border-blue-400 bg-blue-50",
  revisit:   "border-orange-400 bg-orange-50",
}

function DecisionNode({ data }: NodeProps) {
  const d = data as {
    question: string; status: string; chosen: string | null
    phase: string; explored: boolean
  }
  const isAbandoned = d.status === "abandoned"
  return (
    <>
      <Handle type="target" position={Position.Left} />
      <div
        className={`rounded-lg border-2 px-3 py-2 shadow-sm cursor-pointer transition-shadow hover:shadow-md
          ${decisionStatusCls[d.status] ?? "border-gray-300 bg-white"}
          ${isAbandoned ? "opacity-50" : ""}`}
        style={{ width: DIM.decision.w }}
      >
        <div className="flex items-center gap-1 mb-1">
          <span className="text-[9px] font-bold text-blue-700 uppercase tracking-wide">Decision</span>
          <span className="text-[9px] text-muted-foreground">{d.phase}</span>
          {!d.explored && !isAbandoned && (
            <span className="ml-auto text-[8px] px-1 py-px rounded border border-amber-400 text-amber-600 bg-amber-50 shrink-0">
              unexplored
            </span>
          )}
        </div>
        <p
          className="text-[11px] font-medium leading-snug"
          style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}
        >
          {d.question}
        </p>
        {d.chosen && (
          <p className="text-[10px] text-muted-foreground mt-1 truncate">→ {d.chosen}</p>
        )}
      </div>
      <Handle type="source" position={Position.Right} />
    </>
  )
}

const missionStatusCls: Record<string, string> = {
  pending:   "border-amber-400 bg-amber-50",
  active:    "border-teal-500 bg-teal-50",
  complete:  "border-slate-400 bg-slate-50",
  partial:   "border-slate-400 bg-slate-50",
  blocked:   "border-red-400 bg-red-50",
  cancelled: "border-gray-200 bg-gray-50 opacity-40",
}

function MissionNode({ data }: NodeProps) {
  const d = data as { objective: string; status: string }
  return (
    <>
      <Handle type="target" position={Position.Left} />
      <div
        className={`rounded-md border-2 px-3 py-2 shadow-sm cursor-pointer transition-shadow hover:shadow-md
          ${missionStatusCls[d.status] ?? "border-gray-300 bg-white"}`}
        style={{ width: DIM.mission.w }}
      >
        <span className="text-[9px] font-bold text-teal-700 uppercase tracking-wide">
          Mission · {d.status}
        </span>
        <p
          className="text-[11px] leading-snug mt-0.5"
          style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}
        >
          {d.objective}
        </p>
      </div>
      <Handle type="source" position={Position.Right} />
    </>
  )
}

const findingBorderCls: Record<string, string> = {
  finding:     "border-l-green-500",
  hypothesis:  "border-l-purple-500",
  observation: "border-l-sky-500",
  insight:     "border-l-indigo-500",
  methodology: "border-l-cyan-500",
  exploration: "border-l-amber-500",
}

function FindingNode({ data }: NodeProps) {
  const d = data as { content: string; type: string }
  return (
    <>
      <Handle type="target" position={Position.Left} />
      <div
        className={`rounded border border-gray-200 border-l-4 bg-white px-2 py-1.5 shadow-sm cursor-pointer transition-shadow hover:shadow-md
          ${findingBorderCls[d.type] ?? "border-l-gray-400"}`}
        style={{ width: DIM.finding.w }}
      >
        <span className="text-[9px] font-bold uppercase tracking-wide text-gray-500">{d.type}</span>
        <p
          className="text-[10px] leading-snug mt-0.5"
          style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}
        >
          {d.content}
        </p>
      </div>
    </>
  )
}

function LitNode({ data }: NodeProps) {
  const d = data as { title: string }
  return (
    <>
      <div
        className="rounded border-2 border-indigo-400 bg-indigo-50 px-3 py-2 shadow-sm cursor-pointer transition-shadow hover:shadow-md"
        style={{ width: DIM.lit.w }}
      >
        <span className="text-[9px] font-bold text-indigo-700 uppercase tracking-wide">Literature</span>
        <p
          className="text-[11px] leading-snug mt-0.5"
          style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}
        >
          {d.title}
        </p>
      </div>
      <Handle type="source" position={Position.Right} />
    </>
  )
}

const nodeTypes = {
  decisionNode: DecisionNode,
  missionNode:  MissionNode,
  findingNode:  FindingNode,
  litNode:      LitNode,
}

// ── Main component ──────────────────────────────────────────────────────────

export default function KnowledgeGraph() {
  const [showMissions, setShowMissions] = useState(true)
  const [showFindings, setShowFindings] = useState(true)
  const [showOrphans, setShowOrphans] = useState(false)
  const [selected, setSelected] = useState<{ id: string; kind: string } | null>(null)

  // Fetch entity data for detail sheets
  const { data: decisions  = [] } = useQuery({ queryKey: ["decisions"],              queryFn: () => api.listDecisions() })
  const { data: missions   = [] } = useQuery({ queryKey: ["missions"],               queryFn: () => api.listMissions() })
  const { data: notes      = [] } = useQuery({ queryKey: ["notes", { limit: 200 }],  queryFn: () => api.listNotes({ limit: 200 }) })
  const { data: literature = [] } = useQuery({ queryKey: ["literature"],             queryFn: () => api.listLiterature() })

  // Fetch graph from entity_links (the source of truth for edges)
  const { data: graphData } = useQuery<GraphData>({
    queryKey: ["graph"],
    queryFn: () => api.getGraph({ limit: 500 }),
  })

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  useEffect(() => {
    if (!graphData || graphData.nodes.length === 0) return

    // ── Build ELK input from graph API data ────────────────────────────
    type ElkNode = { id: string; width: number; height: number }
    type ElkEdge = { id: string; sources: string[]; targets: string[] }
    const elkNodes: ElkNode[] = []
    const elkEdges: ElkEdge[] = []
    const nodeIds  = new Set<string>()
    const edgeKeys = new Set<string>()

    function getDim(type: string) {
      switch (type) {
        case "decision":   return DIM.decision
        case "mission":    return DIM.mission
        case "literature": return DIM.lit
        default:           return DIM.finding
      }
    }

    function addNode(id: string, type: string) {
      if (nodeIds.has(id)) return
      nodeIds.add(id)
      const dim = getDim(type)
      elkNodes.push({ id, width: dim.w, height: dim.h })
    }

    function addEdge(src: string, tgt: string) {
      if (!nodeIds.has(src) || !nodeIds.has(tgt)) return
      const key = `${src}→${tgt}`
      if (edgeKeys.has(key)) return
      edgeKeys.add(key)
      elkEdges.push({ id: key, sources: [src], targets: [tgt] })
    }

    // Build set of connected node IDs (nodes that have at least one edge)
    const connectedIds = new Set<string>()
    for (const ge of graphData.edges) {
      connectedIds.add(ge.source)
      connectedIds.add(ge.target)
    }

    // Add nodes, filtered by layer toggles and orphan toggle
    for (const gn of graphData.nodes) {
      if (gn.type === "mission" && !showMissions) continue
      if (gn.type === "journal" && !showFindings) continue
      if (gn.type === "literature" && !showFindings) continue
      if (!showOrphans && !connectedIds.has(gn.id)) continue
      addNode(gn.id, gn.type)
    }

    // Add all edges from entity_links
    for (const ge of graphData.edges) {
      addEdge(ge.source, ge.target)
    }

    if (elkNodes.length === 0) return

    // ── Run ELK layout ─────────────────────────────────────────────────────
    elk.layout({
      id: "root",
      children: elkNodes,
      edges: elkEdges,
      layoutOptions: {
        "elk.algorithm": "layered",
        "elk.direction": "RIGHT",
        "elk.spacing.nodeNode": "30",
        "elk.layered.spacing.nodeNodeBetweenLayers": "60",
        "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
        "elk.separateConnectedComponents": "true",
        "elk.spacing.componentComponent": "40",
        "elk.layered.compaction.connectedComponents": "true",
        "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
      },
    }).then(layout => {
      const posMap = new Map<string, { x: number; y: number }>()
      for (const n of layout.children ?? []) posMap.set(n.id, { x: n.x ?? 0, y: n.y ?? 0 })

      // ── Build React Flow nodes from graph data ───────────────────────────
      const flowNodes: Node[] = []
      const decMap = new Map(decisions.map(d => [d.id, d]))
      const misMap = new Map(missions.map(m => [m.id, m]))
      const noteMap = new Map(notes.map(n => [n.id, n]))
      const litMap = new Map(literature.map(l => [l.id, l]))

      for (const gn of graphData.nodes) {
        const pos = posMap.get(gn.id)
        if (!pos) continue

        if (gn.type === "decision") {
          const dec = decMap.get(gn.id)
          flowNodes.push({
            id: gn.id, type: "decisionNode", position: pos,
            data: {
              question: dec?.question ?? gn.label,
              status: gn.status ?? "active",
              chosen: dec?.chosen ?? null,
              phase: gn.phase,
              explored: true,
            },
          })
        } else if (gn.type === "mission" && showMissions) {
          const mis = misMap.get(gn.id)
          flowNodes.push({
            id: gn.id, type: "missionNode", position: pos,
            data: { objective: mis?.objective ?? gn.label, status: gn.status ?? "pending" },
          })
        } else if (gn.type === "journal" && showFindings) {
          const note = noteMap.get(gn.id)
          flowNodes.push({
            id: gn.id, type: "findingNode", position: pos,
            data: { content: note?.content ?? gn.label, type: note?.type ?? "finding" },
          })
        } else if (gn.type === "literature" && showFindings) {
          const lit = litMap.get(gn.id)
          flowNodes.push({
            id: gn.id, type: "litNode", position: pos,
            data: { title: lit?.title ?? gn.label },
          })
        }
      }

      // ── Build React Flow edges with semantic styling based on link_type ──
      const edgeTypeStyles: Record<string, { stroke: string; width: number; dash?: string }> = {
        triggered:    { stroke: "#3b82f6", width: 2 },
        produced:     { stroke: "#10b981", width: 1.5 },
        references:   { stroke: "#0d9488", width: 1.5 },
        cites:        { stroke: "#8b5cf6", width: 1, dash: "4,3" },
        supersedes:   { stroke: "#f59e0b", width: 1, dash: "6,4" },
        resolved_as:  { stroke: "#6366f1", width: 1.5 },
        evidence_for: { stroke: "#10b981", width: 1, dash: "4,3" },
      }

      const flowEdges: Edge[] = graphData.edges
        .map(ge => {
          if (!posMap.has(ge.source) || !posMap.has(ge.target)) return null!
          const key = `${ge.source}→${ge.target}`
          const es = edgeTypeStyles[ge.link_type] ?? { stroke: "#94a3b8", width: 1 }
          return {
            id: key,
            source: ge.source,
            target: ge.target,
            type: "smoothstep",
            animated: false,
            style: {
              strokeWidth: es.width,
              stroke: es.stroke,
              ...(es.dash ? { strokeDasharray: es.dash } : {}),
            },
            markerEnd: { type: MarkerType.ArrowClosed, width: 10, height: 10 },
          }
        })
        .filter(Boolean)

      setNodes(flowNodes)
      setEdges(flowEdges)
    }).catch(console.error)
  }, [graphData, decisions, missions, notes, literature, showMissions, showFindings, showOrphans, setNodes, setEdges])

  const handleNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    const kind =
      node.type === "missionNode"  ? "mission"     :
      node.type === "findingNode"  ? "finding"     :
      node.type === "litNode"      ? "literature"  : "decision"
    setSelected({ id: node.id, kind })
  }, [])

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Research Map</h1>
        <p className="text-sm text-muted-foreground">
          {nodes.length} nodes · {edges.length} connections
        </p>
      </div>

      <div className="h-[calc(100vh-190px)] rounded-lg border bg-background">
        {nodes.length === 0 ? (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            No data yet. The map appears once missions, decisions, or literature are created.
          </div>
        ) : (
          <ReactFlow
            nodes={nodes} edges={edges}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
            onNodeClick={handleNodeClick}
            nodeTypes={nodeTypes}
            fitView fitViewOptions={{ padding: 0.15 }}
            minZoom={0.08} maxZoom={2}
          >
            <Background gap={20} size={1} />
            <Controls />
            <MiniMap
              nodeColor={(n) => {
                if (n.type === "decisionNode") return "#3b82f6"
                if (n.type === "missionNode")  return "#0d9488"
                if (n.type === "findingNode")  return "#10b981"
                return "#94a3b8"
              }}
              style={{ height: 100, width: 160 }}
              zoomable pannable
            />

            {/* Filter + legend panel */}
            <Panel position="top-right">
              <div className="bg-background/95 backdrop-blur border rounded-lg p-3 shadow text-[11px] space-y-2 min-w-[160px]">
                <p className="text-xs font-semibold">Layers</p>
                {([
                  { label: "Missions",  color: "#0d9488", val: showMissions, set: setShowMissions },
                  { label: "Findings",  color: "#10b981", val: showFindings, set: setShowFindings },
                  { label: "Orphan nodes", color: "#94a3b8", val: showOrphans, set: setShowOrphans },
                ] as const).map(({ label, color, val, set }) => (
                  <label key={label} className="flex items-center gap-2 cursor-pointer select-none">
                    <input
                      type="checkbox" checked={val}
                      onChange={e => set(e.target.checked)}
                      className="accent-blue-500"
                    />
                    <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: color }} />
                    <span>{label}</span>
                  </label>
                ))}

                <div className="border-t pt-2 space-y-1 text-muted-foreground text-[10px]">
                  <div className="space-y-px">
                    <div>🟢 active · ⬜ abandoned</div>
                  </div>
                  <div className="border-t pt-1 space-y-px">
                    <div className="flex items-center gap-1"><span className="inline-block w-4 h-0 border-t-2" style={{borderColor:"#3b82f6"}} /> triggered</div>
                    <div className="flex items-center gap-1"><span className="inline-block w-4 h-0 border-t-2" style={{borderColor:"#10b981"}} /> produced</div>
                    <div className="flex items-center gap-1"><span className="inline-block w-4 h-0 border-t-2" style={{borderColor:"#0d9488"}} /> references</div>
                    <div className="flex items-center gap-1"><span className="inline-block w-4 h-0 border-t border-dashed" style={{borderColor:"#8b5cf6"}} /> cites</div>
                    <div className="flex items-center gap-1"><span className="inline-block w-4 h-0 border-t border-dashed" style={{borderColor:"#f59e0b"}} /> supersedes</div>
                  </div>
                  <p className="border-t pt-1 text-[9px]">Edges from entity_links table</p>
                </div>
              </div>
            </Panel>
          </ReactFlow>
        )}
      </div>

      <NodeDetailSheet
        node={selected} onClose={() => setSelected(null)}
        decisions={decisions} missions={missions} notes={notes} literature={literature}
      />
    </div>
  )
}

// ── Detail side panel ───────────────────────────────────────────────────────

function NodeDetailSheet({
  node, onClose, decisions, missions, notes, literature,
}: {
  node: { id: string; kind: string } | null
  onClose: () => void
  decisions: Decision[]
  missions: Mission[]
  notes: JournalEntry[]
  literature: Literature[]
}) {
  const decision = node?.kind === "decision"   ? decisions.find(d => d.id === node.id)  : null
  const mission  = node?.kind === "mission"    ? missions.find(m => m.id === node.id)   : null
  const note     = node?.kind === "finding"    ? notes.find(n => n.id === node.id)      : null
  const lit      = node?.kind === "literature" ? literature.find(l => l.id === node.id) : null

  return (
    <Sheet open={!!node} onOpenChange={open => !open && onClose()}>
      <SheetContent className="w-[420px] sm:w-[500px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="text-base capitalize">{node?.kind ?? ""} Detail</SheetTitle>
        </SheetHeader>
        <div className="space-y-4 mt-4 text-sm">
          {decision && <DecisionDetail dec={decision} />}
          {mission  && <MissionDetail  mis={mission} />}
          {note     && <FindingDetail  note={note} literature={literature} />}
          {lit      && <LitDetail      lit={lit} />}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">{label}</p>
      {children}
    </div>
  )
}

function DecisionDetail({ dec }: { dec: Decision }) {
  return (
    <>
      <div className="flex items-center gap-2 flex-wrap">
        <StatusBadge status={dec.status} />
        <Badge variant="outline" className="text-xs">{dec.phase}</Badge>
        <Badge variant="secondary" className="text-xs">{dec.decided_by}</Badge>
      </div>
      <Section label="Question"><p>{dec.question}</p></Section>
      {dec.chosen && <Section label="Chosen"><p>{dec.chosen}</p></Section>}
      {dec.rationale && <Section label="Rationale"><p className="text-muted-foreground">{dec.rationale}</p></Section>}
      {dec.abandonment_reason && <Section label="Abandonment Reason"><p className="text-muted-foreground">{dec.abandonment_reason}</p></Section>}
      {dec.options && dec.options.length > 0 && (
        <Section label="Options">
          <div className="space-y-1.5">
            {dec.options.map(opt => (
              <div
                key={opt.label}
                className={`p-2 rounded border text-xs ${opt.label === dec.chosen ? "border-green-400 bg-green-50" : "border-border"}`}
              >
                <span className="font-medium">{opt.label}</span>
                {opt.description && <p className="text-muted-foreground mt-0.5">{opt.description}</p>}
              </div>
            ))}
          </div>
        </Section>
      )}
      <TagList tags={dec.tags} />
      <p className="text-[10px] text-muted-foreground font-mono">{dec.id}</p>
    </>
  )
}

function MissionDetail({ mis }: { mis: Mission }) {
  return (
    <>
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant="outline">{mis.status}</Badge>
        <Badge variant="secondary" className="text-xs">{mis.phase}</Badge>
      </div>
      <Section label="Objective"><p>{mis.objective}</p></Section>
      {mis.context && <Section label="Context"><p className="text-muted-foreground">{mis.context}</p></Section>}
      {mis.acceptance_criteria && (
        <Section label="Acceptance Criteria">
          <p className="text-muted-foreground">{mis.acceptance_criteria}</p>
        </Section>
      )}
      {mis.tasks && mis.tasks.length > 0 && (
        <Section label="Tasks">
          <ul className="space-y-1">
            {mis.tasks.map((t, i) => (
              <li key={i} className={`text-xs flex gap-2 ${t.status === "complete" ? "text-muted-foreground" : ""}`}>
                <span className="shrink-0">{t.status === "complete" ? "✓" : "○"}</span>
                <span>{t.description}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {mis.report && (
        <>
          {(mis.report.findings ?? []).length > 0 && (
            <Section label="Findings">
              <ul className="space-y-0.5">
                {mis.report.findings!.map((f, i) => (
                  <li key={i} className="text-xs text-muted-foreground">· {f}</li>
                ))}
              </ul>
            </Section>
          )}
          {(mis.report.questions ?? []).length > 0 && (
            <Section label="Open Questions">
              <ul className="space-y-0.5">
                {mis.report.questions!.map((q, i) => (
                  <li key={i} className="text-xs text-muted-foreground">? {q}</li>
                ))}
              </ul>
            </Section>
          )}
        </>
      )}
      <p className="text-[10px] text-muted-foreground font-mono">{mis.id}</p>
    </>
  )
}

function FindingDetail({ note, literature }: { note: JournalEntry; literature: Literature[] }) {
  const relatedLit = (note.related_literature ?? [])
    .map(id => literature.find(l => l.id === id))
    .filter(Boolean) as Literature[]

  return (
    <>
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant="outline">{note.type}</Badge>
        <Badge variant="secondary" className="text-xs">{note.confidence}</Badge>
        {note.importance !== "normal" && (
          <Badge variant="outline" className="text-xs">{note.importance}</Badge>
        )}
      </div>
      <Section label="Content">
        <p className="whitespace-pre-wrap">{note.content}</p>
      </Section>
      {note.phase && <p className="text-xs text-muted-foreground">Phase: {note.phase}</p>}
      {relatedLit.length > 0 && (
        <Section label="Related Literature">
          <ul className="space-y-1">
            {relatedLit.map(lit => (
              <li key={lit.id} className="text-xs">
                <span className="font-medium">{lit.title}</span>
                {lit.year && <span className="text-muted-foreground ml-1">({lit.year})</span>}
                {lit.authors && lit.authors.length > 0 && (
                  <span className="text-muted-foreground block">{lit.authors.slice(0, 3).join(", ")}</span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}
      <TagList tags={note.tags} />
      <p className="text-[10px] text-muted-foreground font-mono">{note.id}</p>
    </>
  )
}

function LitDetail({ lit }: { lit: Literature }) {
  return (
    <>
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant="outline">{lit.status}</Badge>
        {lit.year && <Badge variant="secondary" className="text-xs">{lit.year}</Badge>}
      </div>
      <Section label="Title"><p className="font-medium">{lit.title}</p></Section>
      {lit.authors && lit.authors.length > 0 && (
        <p className="text-muted-foreground text-xs">{lit.authors.join(", ")}</p>
      )}
      {lit.abstract && (
        <Section label="Abstract">
          <p className="text-muted-foreground text-xs line-clamp-6">{lit.abstract}</p>
        </Section>
      )}
      {lit.relevance && (
        <Section label="Relevance"><p className="text-muted-foreground">{lit.relevance}</p></Section>
      )}
      {lit.key_findings && lit.key_findings.length > 0 && (
        <Section label="Key Findings">
          <ul className="space-y-0.5">
            {lit.key_findings.map((f, i) => <li key={i} className="text-xs text-muted-foreground">· {f}</li>)}
          </ul>
        </Section>
      )}
      <TagList tags={lit.tags} />
      <p className="text-[10px] text-muted-foreground font-mono">{lit.id}</p>
    </>
  )
}
