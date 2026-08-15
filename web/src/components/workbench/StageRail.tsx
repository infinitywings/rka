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
  return (
    <nav aria-label="Manuscript stages" className="space-y-1.5">
      {WORKBENCH_STAGES.map((stage, index) => {
        const Icon = stage.icon
        const verdict = verdicts[stage.id]
        return (
          <button
            key={stage.id}
            type="button"
            onClick={() => onSelect(stage.id)}
            className={cn(
              "w-full rounded-lg border px-3 py-2.5 text-left transition-colors",
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
