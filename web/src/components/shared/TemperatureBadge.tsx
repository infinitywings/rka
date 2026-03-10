import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const tempColors: Record<string, string> = {
  HOT: "bg-red-100 text-red-800 border-red-200",
  WARM: "bg-orange-100 text-orange-800 border-orange-200",
  COLD: "bg-blue-100 text-blue-800 border-blue-200",
  ARCHIVE: "bg-gray-100 text-gray-500 border-gray-200",
}

export function TemperatureBadge({ temp, className }: { temp: string; className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "text-[10px] font-bold",
        tempColors[temp] ?? "bg-gray-100 text-gray-600",
        className,
      )}
    >
      {temp}
    </Badge>
  )
}
