import { useState, useCallback, useEffect } from "react"
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  Panel,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import ELK from "elkjs/lib/elk.bundled.js"
import { Badge } from "@/components/ui/badge"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { TagList } from "@/components/shared/TagList"
import { useDecisionTree, useDecision } from "@/hooks/useDecisions"
import type { DecisionTreeNode } from "@/api/types"

const elk = new ELK()

const statusStyles: Record<string, string> = {
  active: "border-green-500 bg-green-50",
  abandoned: "border-gray-300 bg-gray-50 border-dashed",
  superseded: "border-yellow-400 bg-yellow-50",
  merged: "border-blue-400 bg-blue-50",
  revisit: "border-orange-400 bg-orange-50",
}

function DecisionNodeComponent({ data }: { data: { label: string; status: string; chosen: string | null; phase: string } }) {
  return (
    <div
      className={`rounded-lg border-2 px-4 py-3 shadow-sm min-w-[200px] max-w-[280px] ${
        statusStyles[data.status] ?? "border-gray-300 bg-white"
      }`}
    >
      <div className="flex items-center gap-2 mb-1">
        <StatusBadge status={data.status} />
        <span className="text-[10px] text-muted-foreground">{data.phase}</span>
      </div>
      <p className="text-sm font-medium leading-tight">{data.label}</p>
      {data.chosen && (
        <p className="text-xs text-muted-foreground mt-1 truncate">
          → {data.chosen}
        </p>
      )}
    </div>
  )
}

const nodeTypes = { decision: DecisionNodeComponent }

function flattenTree(
  nodes: DecisionTreeNode[],
  parentId?: string,
): { elkNodes: { id: string; width: number; height: number }[]; elkEdges: { id: string; sources: string[]; targets: string[] }[]; dataMap: Map<string, DecisionTreeNode> } {
  const elkNodes: { id: string; width: number; height: number }[] = []
  const elkEdges: { id: string; sources: string[]; targets: string[] }[] = []
  const dataMap = new Map<string, DecisionTreeNode>()

  function walk(node: DecisionTreeNode, parent?: string) {
    elkNodes.push({ id: node.id, width: 260, height: 80 })
    dataMap.set(node.id, node)
    if (parent) {
      elkEdges.push({ id: `${parent}-${node.id}`, sources: [parent], targets: [node.id] })
    }
    for (const child of node.children) {
      walk(child, node.id)
    }
  }

  for (const root of nodes) {
    walk(root, parentId)
  }
  return { elkNodes, elkEdges, dataMap }
}

export default function Decisions() {
  const { data: tree, isLoading } = useDecisionTree()
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const layoutTree = useCallback(async (treeData: DecisionTreeNode[]) => {
    const { elkNodes, elkEdges, dataMap } = flattenTree(treeData)

    if (elkNodes.length === 0) return

    const layout = await elk.layout({
      id: "root",
      children: elkNodes,
      edges: elkEdges,
      layoutOptions: {
        "elk.algorithm": "layered",
        "elk.direction": "DOWN",
        "elk.spacing.nodeNode": "60",
        "elk.layered.spacing.nodeNodeBetweenLayers": "80",
      },
    })

    const flowNodes: Node[] = (layout.children ?? []).map((n) => {
      const d = dataMap.get(n.id)!
      return {
        id: n.id,
        type: "decision",
        position: { x: n.x ?? 0, y: n.y ?? 0 },
        data: {
          label: d.question,
          status: d.status,
          chosen: d.chosen,
          phase: d.phase,
        },
      }
    })

    const flowEdges: Edge[] = elkEdges.map((e) => ({
      id: e.id,
      source: e.sources[0],
      target: e.targets[0],
      type: "smoothstep",
      animated: false,
      style: { stroke: "#94a3b8", strokeWidth: 1.5 },
    }))

    setNodes(flowNodes)
    setEdges(flowEdges)
  }, [setNodes, setEdges])

  useEffect(() => {
    if (tree && tree.length > 0) {
      layoutTree(tree)
    }
  }, [tree, layoutTree])

  const handleNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedId(node.id)
  }, [])

  if (isLoading) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold tracking-tight">Decision Tree</h1>
        <div className="h-[600px] bg-muted rounded-lg animate-pulse" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Decision Tree</h1>
        <p className="text-muted-foreground text-sm">
          {tree?.length ?? 0} root decisions
        </p>
      </div>

      <div className="h-[calc(100vh-200px)] rounded-lg border bg-background">
        {nodes.length === 0 ? (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            No decisions yet. Create one to get started.
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={handleNodeClick}
            nodeTypes={nodeTypes}
            fitView
            minZoom={0.3}
            maxZoom={2}
          >
            <Background gap={20} size={1} />
            <Controls />
            <MiniMap
              nodeStrokeWidth={3}
              zoomable
              pannable
              className="!bg-background"
            />
            <Panel position="top-right">
              <div className="flex gap-1">
                {["active", "abandoned", "revisit"].map((s) => (
                  <Badge key={s} variant="outline" className="text-[10px]">
                    {s}
                  </Badge>
                ))}
              </div>
            </Panel>
          </ReactFlow>
        )}
      </div>

      {/* Side Panel */}
      <DecisionDetailSheet
        decisionId={selectedId}
        onClose={() => setSelectedId(null)}
      />
    </div>
  )
}

function DecisionDetailSheet({
  decisionId,
  onClose,
}: {
  decisionId: string | null
  onClose: () => void
}) {
  const { data: decision } = useDecision(decisionId ?? "")

  return (
    <Sheet open={!!decisionId} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-[400px] sm:w-[500px]">
        <SheetHeader>
          <SheetTitle className="text-lg">Decision Detail</SheetTitle>
        </SheetHeader>
        {decision && (
          <div className="space-y-4 mt-4">
            <div>
              <StatusBadge status={decision.status} />
              <Badge variant="outline" className="ml-2 text-xs">
                {decision.phase}
              </Badge>
            </div>
            <div>
              <h3 className="text-sm font-semibold mb-1">Question</h3>
              <p className="text-sm">{decision.question}</p>
            </div>
            {decision.chosen && (
              <div>
                <h3 className="text-sm font-semibold mb-1">Chosen</h3>
                <p className="text-sm">{decision.chosen}</p>
              </div>
            )}
            {decision.rationale && (
              <div>
                <h3 className="text-sm font-semibold mb-1">Rationale</h3>
                <p className="text-sm text-muted-foreground">{decision.rationale}</p>
              </div>
            )}
            {decision.options && decision.options.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold mb-1">Options</h3>
                <div className="space-y-2">
                  {decision.options.map((opt) => (
                    <div
                      key={opt.label}
                      className={`text-sm p-2 rounded border ${
                        opt.label === decision.chosen
                          ? "border-green-300 bg-green-50"
                          : "border-border"
                      }`}
                    >
                      <span className="font-medium">{opt.label}</span>
                      {opt.description && (
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {opt.description}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div>
              <h3 className="text-sm font-semibold mb-1">Decided by</h3>
              <Badge variant="secondary">{decision.decided_by}</Badge>
            </div>
            <TagList tags={decision.tags} />
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
