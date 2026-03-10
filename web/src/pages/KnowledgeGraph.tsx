import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  MarkerType,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { Card, CardContent } from "@/components/ui/card"

const ENTITY_COLORS: Record<string, { bg: string; border: string }> = {
  decision: { bg: "#dbeafe", border: "#3b82f6" },
  literature: { bg: "#e0e7ff", border: "#6366f1" },
  journal: { bg: "#d1fae5", border: "#10b981" },
  mission: { bg: "#fce7f3", border: "#ec4899" },
  checkpoint: { bg: "#fef3c7", border: "#f59e0b" },
}

export default function KnowledgeGraph() {
  // Fetch all entity types for building the graph
  const { data: decisions = [] } = useQuery({
    queryKey: ["decisions"],
    queryFn: () => api.listDecisions(),
  })

  const { data: literature = [] } = useQuery({
    queryKey: ["literature"],
    queryFn: () => api.listLiterature(),
  })

  const { data: notes = [] } = useQuery({
    queryKey: ["notes", { limit: 100 }],
    queryFn: () => api.listNotes({ limit: 100 }),
  })

  const { data: missions = [] } = useQuery({
    queryKey: ["missions"],
    queryFn: () => api.listMissions(),
  })

  // Build graph from entity relationships
  const { nodes, edges } = useMemo(() => {
    const nodeList: Node[] = []
    const edgeList: Edge[] = []
    const edgeSet = new Set<string>()

    function addEdge(source: string, target: string, label?: string) {
      const key = `${source}->${target}`
      if (edgeSet.has(key)) return
      edgeSet.add(key)
      edgeList.push({
        id: key,
        source,
        target,
        label,
        type: "default",
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 },
        style: { strokeWidth: 1.5, opacity: 0.6 },
        labelStyle: { fontSize: 10, fill: "#666" },
      })
    }

    // Layout: arrange entities in columns by type
    let decY = 0
    let litY = 0
    let noteY = 0
    let misY = 0

    const ROW_H = 80
    const COL_W = 320

    // Decisions column (x=0)
    for (const dec of decisions) {
      nodeList.push({
        id: dec.id,
        type: "default",
        position: { x: 0, y: decY },
        data: {
          label: `📊 ${dec.question.substring(0, 40)}${dec.question.length > 40 ? "..." : ""}`,
        },
        style: {
          background: ENTITY_COLORS.decision.bg,
          border: `2px solid ${ENTITY_COLORS.decision.border}`,
          borderRadius: "8px",
          padding: "8px 12px",
          fontSize: "11px",
          width: 260,
        },
      })
      decY += ROW_H

      // Parent edges
      if (dec.parent_id) {
        addEdge(dec.parent_id, dec.id, "child")
      }

      // Related literature edges
      for (const litId of dec.related_literature ?? []) {
        addEdge(litId, dec.id, "informs")
      }

      // Related mission edges
      for (const misId of dec.related_missions ?? []) {
        addEdge(dec.id, misId, "guides")
      }
    }

    // Literature column (x=1)
    for (const lit of literature) {
      nodeList.push({
        id: lit.id,
        type: "default",
        position: { x: COL_W, y: litY },
        data: {
          label: `📄 ${lit.title.substring(0, 40)}${lit.title.length > 40 ? "..." : ""}`,
        },
        style: {
          background: ENTITY_COLORS.literature.bg,
          border: `2px solid ${ENTITY_COLORS.literature.border}`,
          borderRadius: "8px",
          padding: "8px 12px",
          fontSize: "11px",
          width: 260,
        },
      })
      litY += ROW_H

      // Related decision edges
      for (const decId of lit.related_decisions ?? []) {
        addEdge(lit.id, decId, "informs")
      }
    }

    // Journal column (x=2)
    for (const note of notes) {
      nodeList.push({
        id: note.id,
        type: "default",
        position: { x: COL_W * 2, y: noteY },
        data: {
          label: `📝 ${note.content.substring(0, 40)}${note.content.length > 40 ? "..." : ""}`,
        },
        style: {
          background: ENTITY_COLORS.journal.bg,
          border: `2px solid ${ENTITY_COLORS.journal.border}`,
          borderRadius: "8px",
          padding: "8px 12px",
          fontSize: "11px",
          width: 260,
        },
      })
      noteY += ROW_H

      // Related decision edges
      for (const decId of note.related_decisions ?? []) {
        addEdge(note.id, decId, "relates to")
      }
      // Related literature edges
      for (const litId of note.related_literature ?? []) {
        addEdge(note.id, litId, "cites")
      }
      // Supersedes edges
      if (note.supersedes) {
        addEdge(note.id, note.supersedes, "supersedes")
      }
      // Related mission edges
      if (note.related_mission) {
        addEdge(note.id, note.related_mission, "from mission")
      }
    }

    // Missions column (x=3)
    for (const mis of missions) {
      nodeList.push({
        id: mis.id,
        type: "default",
        position: { x: COL_W * 3, y: misY },
        data: {
          label: `🚀 ${mis.objective.substring(0, 40)}${mis.objective.length > 40 ? "..." : ""}`,
        },
        style: {
          background: ENTITY_COLORS.mission.bg,
          border: `2px solid ${ENTITY_COLORS.mission.border}`,
          borderRadius: "8px",
          padding: "8px 12px",
          fontSize: "11px",
          width: 260,
        },
      })
      misY += ROW_H

      // Depends on edges
      if (mis.depends_on) {
        addEdge(mis.depends_on, mis.id, "depends on")
      }
    }

    return { nodes: nodeList, edges: edgeList }
  }, [decisions, literature, notes, missions])

  const totalEntities = decisions.length + literature.length + notes.length + missions.length

  if (totalEntities === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold">Knowledge Graph</h1>
          <p className="text-sm text-muted-foreground">
            Entity relationship visualization
          </p>
        </div>
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            No entities to display. Add notes, decisions, literature, or missions to see the graph.
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Knowledge Graph</h1>
          <p className="text-sm text-muted-foreground">
            {totalEntities} entities, {edges.length} relationships
          </p>
        </div>
        <div className="flex gap-3 text-xs">
          {Object.entries(ENTITY_COLORS).map(([type, colors]) => (
            <div key={type} className="flex items-center gap-1.5">
              <div
                className="h-3 w-3 rounded"
                style={{ backgroundColor: colors.border }}
              />
              <span className="capitalize">{type}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="h-[calc(100vh-200px)] rounded-lg border bg-background">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.1}
          maxZoom={2}
          defaultEdgeOptions={{
            animated: false,
          }}
        >
          <Background gap={20} size={1} />
          <Controls />
          <MiniMap
            nodeColor={(node) => {
              const id = node.id
              if (id.startsWith("dec")) return ENTITY_COLORS.decision.border
              if (id.startsWith("lit")) return ENTITY_COLORS.literature.border
              if (id.startsWith("jrn") || id.startsWith("journal")) return ENTITY_COLORS.journal.border
              if (id.startsWith("mis")) return ENTITY_COLORS.mission.border
              return "#999"
            }}
            style={{ height: 100, width: 160 }}
          />
        </ReactFlow>
      </div>
    </div>
  )
}
