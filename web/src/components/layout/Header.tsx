import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Search, Circle } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { useHealth } from "@/hooks/useProject"

export function Header() {
  const [query, setQuery] = useState("")
  const navigate = useNavigate()
  const { data: health } = useHealth()

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim()) {
      navigate(`/journal?search=${encodeURIComponent(query.trim())}`)
      setQuery("")
    }
  }

  return (
    <header className="flex h-14 items-center justify-between border-b bg-background px-6">
      {/* Search */}
      <form onSubmit={handleSearch} className="flex items-center gap-2 w-full max-w-md">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            type="search"
            placeholder="Search entries..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-9 h-9"
          />
        </div>
      </form>

      {/* Status Indicators */}
      <div className="flex items-center gap-3">
        {health && (
          <>
            <Badge variant="outline" className="gap-1.5 text-xs">
              <Circle
                className={`h-2 w-2 fill-current ${
                  health.status === "ok" ? "text-green-500" : "text-red-500"
                }`}
              />
              {health.status === "ok" ? "Online" : "Error"}
            </Badge>
            {health.vec_available && (
              <Badge variant="secondary" className="text-xs">
                Vector
              </Badge>
            )}
            <span className="text-xs text-muted-foreground">v{health.version}</span>
          </>
        )}
      </div>
    </header>
  )
}
