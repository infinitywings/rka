import { Badge } from "@/components/ui/badge"

export function TagList({ tags }: { tags: string[] }) {
  if (!tags.length) return null
  return (
    <div className="flex flex-wrap gap-1">
      {tags.map((tag) => (
        <Badge key={tag} variant="secondary" className="text-[10px] px-1.5 py-0">
          {tag}
        </Badge>
      ))}
    </div>
  )
}
