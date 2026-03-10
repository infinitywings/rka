import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const confidenceColors: Record<string, string> = {
  hypothesis: "bg-yellow-100 text-yellow-800 border-yellow-200",
  tested: "bg-blue-100 text-blue-800 border-blue-200",
  verified: "bg-green-100 text-green-800 border-green-200",
  superseded: "bg-gray-100 text-gray-500 border-gray-200",
  retracted: "bg-red-100 text-red-800 border-red-200",
}

export function ConfidenceBadge({ confidence, className }: { confidence: string; className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "text-[10px] font-medium",
        confidenceColors[confidence] ?? "bg-gray-100 text-gray-600",
        className,
      )}
    >
      {confidence}
    </Badge>
  )
}
