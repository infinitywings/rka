import { Outlet } from "react-router-dom"
import { Sidebar } from "./Sidebar"
import { Header } from "./Header"
import { FirstRunBanner } from "./FirstRunBanner"

export function AppLayout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <a
        href="#main-content"
        className="fixed left-3 top-3 z-[100] -translate-y-24 rounded-md bg-background px-3 py-2 text-sm font-medium shadow-md ring-2 ring-primary transition-transform focus:translate-y-0"
      >
        Skip to main content
      </a>
      <Sidebar className="hidden md:flex" />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Header />
        <FirstRunBanner />
        <main id="main-content" tabIndex={-1} className="flex-1 overflow-auto p-3 outline-none sm:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
