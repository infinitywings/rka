import { useState, useEffect } from "react"
import { NavLink } from "react-router-dom"
import { X, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"

// Mission D / v2.4.0: dismissible first-run banner announcing the
// default-on semantic-search baseline. Dismissal persists in
// localStorage so the banner stays gone across reloads.
const LOCALSTORAGE_KEY = "rka_first_run_banner_dismissed_v2_4"

export function FirstRunBanner() {
  const [dismissed, setDismissed] = useState<boolean>(true)

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(LOCALSTORAGE_KEY)
      setDismissed(stored === "true")
    } catch {
      // localStorage unavailable (private mode); show banner once per session.
      setDismissed(false)
    }
  }, [])

  const onDismiss = () => {
    setDismissed(true)
    try {
      window.localStorage.setItem(LOCALSTORAGE_KEY, "true")
    } catch {
      // best-effort; banner will reappear next session if storage failed
    }
  }

  if (dismissed) return null

  return (
    <div className="border-b bg-blue-50/50 px-4 py-2 text-xs flex items-center gap-3">
      <Sparkles className="h-4 w-4 text-blue-600 shrink-0" />
      <div className="flex-1">
        <span className="font-medium text-blue-900">
          Semantic search is enabled
        </span>
        <span className="text-blue-700 ml-2">
          (FastEmbed nomic-768 baseline). Switch to LM Studio, Ollama, or any
          OpenAI-compatible HTTP backend in{" "}
          <NavLink to="/settings" className="underline font-medium">
            Settings → Embeddings
          </NavLink>
          .
        </span>
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={onDismiss}
        aria-label="Dismiss banner"
        className="h-6 w-6 p-0"
      >
        <X className="h-3 w-3" />
      </Button>
    </div>
  )
}
