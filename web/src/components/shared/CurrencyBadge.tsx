import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

/**
 * Currency badge — flags knowledge that is no longer current.
 *
 * superseded / abandoned → amber "superseded"; retracted → red "retracted";
 * any other status renders nothing.
 */
export function CurrencyBadge({
  status,
  className,
}: {
  status: string | null | undefined
  className?: string
}) {
  if (status !== "superseded" && status !== "abandoned" && status !== "retracted") {
    return null
  }
  const retracted = status === "retracted"
  return (
    <Badge
      variant="outline"
      className={cn(
        "text-[10px] font-medium",
        retracted
          ? "bg-red-100 text-red-800 border-red-200"
          : "bg-amber-100 text-amber-800 border-amber-200",
        className,
      )}
    >
      {retracted ? "retracted" : "superseded"}
    </Badge>
  )
}
