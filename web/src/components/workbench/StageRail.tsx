import { useRef } from "react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
  WORKBENCH_STAGES,
  type StageVerdict,
  type WorkbenchStageId,
} from "@/components/workbench/stages"

const verdictStyles: Record<StageVerdict, string> = {
  Ready: "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
  "Needs review": "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200",
  Blocked: "border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200",
  Exploratory: "border-blue-300 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-200",
}

export function StageRail({
  selected,
  verdicts,
  onSelect,
}: {
  selected: WorkbenchStageId
  verdicts: Record<WorkbenchStageId, StageVerdict>
  onSelect: (stage: WorkbenchStageId) => void
}) {
  const stageButtons = useRef<Array<HTMLButtonElement | null>>([])

  const moveFocus = (index: number, key: string) => {
    let nextIndex: number | null = null
    if (key === "ArrowDown" || key === "ArrowRight") {
      nextIndex = (index + 1) % WORKBENCH_STAGES.length
    } else if (key === "ArrowUp" || key === "ArrowLeft") {
      nextIndex = (index - 1 + WORKBENCH_STAGES.length) % WORKBENCH_STAGES.length
    } else if (key === "Home") {
      nextIndex = 0
    } else if (key === "End") {
      nextIndex = WORKBENCH_STAGES.length - 1
    }
    if (nextIndex === null) return
    stageButtons.current[nextIndex]?.focus()
  }

  return (
    <nav
      aria-label="Manuscript stages"
      aria-describedby="manuscript-stage-keyboard-help"
      className="space-y-1.5"
    >
      <p id="manuscript-stage-keyboard-help" className="sr-only">
        Use the arrow keys, Home, or End to move between stages. Press Enter or Space to select a stage.
      </p>
      {WORKBENCH_STAGES.map((stage, index) => {
        const Icon = stage.icon
        const verdict = verdicts[stage.id]
        return (
          <button
            key={stage.id}
            ref={(node) => { stageButtons.current[index] = node }}
            type="button"
            onClick={() => onSelect(stage.id)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault()
                onSelect(stage.id)
                return
              }
              if (["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) {
                event.preventDefault()
                moveFocus(index, event.key)
              }
            }}
            className={cn(
              "w-full rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2",
              selected === stage.id
                ? "border-primary bg-primary/5 shadow-sm"
                : "border-transparent hover:border-border hover:bg-muted/60",
            )}
            aria-current={selected === stage.id ? "step" : undefined}
          >
            <div className="flex items-start gap-2.5">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted text-xs font-semibold text-muted-foreground">
                {index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Icon className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate text-sm font-medium">{stage.label}</span>
                </div>
                <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">
                  {stage.question}
                </p>
                <Badge variant="outline" className={cn("mt-2 text-[10px]", verdictStyles[verdict])}>
                  {verdict}
                </Badge>
              </div>
            </div>
          </button>
        )
      })}
    </nav>
  )
}
