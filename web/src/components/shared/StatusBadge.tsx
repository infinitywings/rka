import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const statusColors: Record<string, string> = {
  // Decision statuses
  active: "bg-green-100 text-green-800 border-green-200",
  abandoned: "bg-gray-100 text-gray-500 border-gray-200",
  superseded: "bg-yellow-100 text-yellow-800 border-yellow-200",
  merged: "bg-blue-100 text-blue-800 border-blue-200",
  revisit: "bg-orange-100 text-orange-800 border-orange-200",
  // Mission statuses
  pending: "bg-gray-100 text-gray-600 border-gray-200",
  complete: "bg-green-100 text-green-800 border-green-200",
  partial: "bg-yellow-100 text-yellow-800 border-yellow-200",
  blocked: "bg-red-100 text-red-800 border-red-200",
  cancelled: "bg-gray-100 text-gray-500 border-gray-200",
  // Literature statuses
  to_read: "bg-gray-100 text-gray-600 border-gray-200",
  reading: "bg-blue-100 text-blue-800 border-blue-200",
  read: "bg-green-100 text-green-800 border-green-200",
  cited: "bg-purple-100 text-purple-800 border-purple-200",
  excluded: "bg-gray-100 text-gray-500 border-gray-200",
  // Checkpoint
  open: "bg-orange-100 text-orange-800 border-orange-200",
  resolved: "bg-green-100 text-green-800 border-green-200",
  // Journal types (v2)
  note: "bg-blue-100 text-blue-800 border-blue-200",
  log: "bg-emerald-100 text-emerald-800 border-emerald-200",
  directive: "bg-purple-100 text-purple-800 border-purple-200",
  // Journal status (v2)
  draft: "bg-gray-100 text-gray-500 border-gray-200",
  retracted: "bg-red-100 text-red-800 border-red-200",
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "text-[10px] font-medium",
        statusColors[status] ?? "bg-gray-100 text-gray-600",
        className,
      )}
    >
      {status.replace(/_/g, " ")}
    </Badge>
  )
}
