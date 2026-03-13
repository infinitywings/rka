# RKA Web Dashboard

The web dashboard for the Research Knowledge Agent. It provides a project-aware interface for inspecting project state, managing entities, exporting/importing project packs, visualizing relationships, and debugging the context engine without raw API calls.

## Quick Start

### Development Mode

```bash
# Terminal 1: Start the API server
cd /path/to/rka-project
rka serve

# Terminal 2: Start the Vite dev server with HMR
cd web
npm install
npm run dev
```

The Vite dev server runs at `http://localhost:5173` and proxies `/api` requests to `localhost:9712`.

### Production Build

```bash
cd web
npm run build
```

The build output goes to `web/dist/`. When `rka serve` starts, it automatically detects and serves this directory at `http://localhost:9712`.

## Tech Stack

| Library | Version | Purpose |
|---------|---------|---------|
| React | 19 | UI framework |
| TypeScript | 5.9 | Type safety |
| Vite | 7 | Build tool + HMR |
| Tailwind CSS | 4 | Utility-first styling |
| shadcn/ui | v5 | Accessible component library |
| TanStack Query | 5 | Server state management, caching, optimistic updates |
| React Router | 7 | Client-side routing |
| @xyflow/react | 12 | Decision tree + knowledge graph visualization |
| elkjs | — | Layered graph layout for decision trees |
| Lucide React | — | Icon library |

## Pages (11)

| Page | Route | Description |
|------|-------|-------------|
| **Dashboard** | `/` | Project overview, project selector, knowledge-pack export/import, active missions, open checkpoints, recent entries |
| **Journal** | `/journal` | Timeline of journal entries grouped by date with type/confidence/source filters |
| **Decisions** | `/decisions` | Interactive decision tree (React Flow + elkjs) with side panel details |
| **Literature** | `/literature` | Table view with reading pipeline status tabs (to_read → cited) |
| **Missions** | `/missions` | Active missions with task checklists, checkpoints, and report viewer |
| **Timeline** | `/timeline` | Event stream with causal chain visualization, entity/actor filters |
| **Knowledge Graph** | `/graph` | Entity relationship graph — nodes colored by type, edges by relationship |
| **Notebook** | `/notebook` | Grounded Q&A and summary generation across the active project |
| **Audit Log** | `/audit` | Audit trail table with action/entity/actor filters and action counts |
| **Context Inspector** | `/context` | Generate context packages with temperature badges and token budgets |
| **Settings** | `/settings` | API health, DB stats, LLM status, project configuration, quick links to `/docs` |

## Project Structure

```
web/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
├── components.json              # shadcn/ui configuration
├── src/
│   ├── main.tsx                 # Entry point
│   ├── App.tsx                  # Router + QueryClientProvider + layout
│   ├── api/
│   │   ├── client.ts            # Typed fetch wrapper (base URL, error handling, X-RKA-Project injection)
│   │   └── types.ts             # TypeScript interfaces matching Pydantic models
│   ├── hooks/
│   │   ├── useNotes.ts          # TanStack Query hooks for journal entries
│   │   ├── useDecisions.ts      # Decision CRUD + tree queries
│   │   ├── useLiterature.ts     # Literature CRUD queries
│   │   ├── useMissions.ts       # Mission lifecycle queries
│   │   ├── useCheckpoints.ts    # Checkpoint queries
│   │   ├── useEvents.ts         # Event stream queries
│   │   ├── useProject.ts        # Project status, list, and knowledge-pack queries
│   │   ├── useProjectSelection.tsx # Active-project state and persistence
│   │   ├── useSearch.ts         # Search queries
│   │   └── useContext.ts        # Context engine queries
│   ├── components/
│   │   ├── ui/                  # shadcn/ui components (button, card, badge, table, dialog, etc.)
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx      # Navigation sidebar with project name + phase
│   │   │   ├── Header.tsx       # Header with search bar
│   │   │   └── AppLayout.tsx    # Sidebar + header + content outlet
│   │   ├── shared/              # Reusable: TagBadge, ConfidenceBadge, StatusBadge
│   │   └── decisions/           # Decision tree custom nodes
│   │       ├── DecisionNode.tsx
│   │       └── DecisionSidePanel.tsx
│   ├── pages/
│   │   ├── Dashboard.tsx
│   │   ├── Journal.tsx
│   │   ├── Decisions.tsx
│   │   ├── Literature.tsx
│   │   ├── Missions.tsx
│   │   ├── Timeline.tsx         # Phase 4
│   │   ├── KnowledgeGraph.tsx   # Phase 4
│   │   ├── Notebook.tsx
│   │   ├── AuditLog.tsx         # Phase 5
│   │   ├── ContextInspector.tsx
│   │   └── Settings.tsx
│   ├── lib/
│   │   └── utils.ts             # cn() helper, date formatting
│   └── styles/
│       └── globals.css          # Tailwind directives + custom styles
└── dist/                        # Production build output (served by FastAPI)
```

## API Client

The API client (`src/api/client.ts`) provides typed methods for all backend endpoints and automatically injects the active project as `X-RKA-Project`:

```typescript
import { api } from "@/api/client"
import { setApiProjectId } from "@/api/client"

setApiProjectId("proj_alpha")

// Entity CRUD
const notes = await api.listNotes({ phase: "experiment", limit: 50 })
const lit = await api.createLiterature({ title: "Paper X", authors: ["A"], year: 2024 })

// Projects
const projects = await api.listProjects()
const pack = await api.exportKnowledgePack()

// Search
const results = await api.search("anomaly detection", ["literature", "decision"])

// Context
const ctx = await api.getContext({ topic: "evaluation", max_tokens: 2000 })

// Academic import
const result = await api.importBibtex("@article{...}", true)
await api.enrichDoi("lit_01ABC...")

// Audit
const entries = await api.listAudit({ action: "create", limit: 100 })
const counts = await api.auditCounts()

// Mermaid export
const { mermaid } = await api.getMermaid("literature_review")
```

## Configuration

### Vite Proxy

In development, Vite proxies all `/api` requests to the RKA backend. This is configured in `vite.config.ts`:

```typescript
server: {
  proxy: {
    "/api": {
      target: "http://127.0.0.1:9712",
      changeOrigin: true,
    },
  },
}
```

### TanStack Query

Default configuration in `App.tsx`:

```typescript
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,        // 30s before refetch
      refetchOnWindowFocus: true, // Refetch when tab regains focus
      retry: 1,                  // Retry failed queries once
    },
  },
})
```

## Adding a New Page

1. Create the page component in `src/pages/NewPage.tsx`
2. Add the route in `src/App.tsx`
3. Add a nav item in `src/components/layout/Sidebar.tsx`
4. Add any new API types in `src/api/types.ts`
5. Add API methods in `src/api/client.ts`
6. (Optional) Create a TanStack Query hook in `src/hooks/useNewThing.ts`
