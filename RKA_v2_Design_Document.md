# RKA v2.0 Design Document

**Progressive Distillation, Research Map, Entity Redesign, and Internal RAG Architecture**

UNC Charlotte — CS/IoT/CPS Security Research
March 2026 | Status: Design Phase — Ready for Implementation

---

## 1. Executive Summary

RKA (Research Knowledge Agent) v2.0 is a major architectural evolution that transforms the system from a passive research bookkeeper into an active knowledge builder. The upgrade introduces five interconnected capabilities:

1. **Progressive distillation pipeline** — the local LLM continuously extracts structured claims from raw journal entries and organizes them into evidence clusters and research themes
2. **Three-layer navigable research map** — replaces the flat journal timeline with a drill-down view from research questions through evidence clusters to individual claims
3. **Entity type redesign** — simplifies journal types from 9 to 3, pushes fine-grained knowledge classification to the claims layer, and separates immutable records from mutable interpretation
4. **Decision overturning with knowledge graph restructuring** — raw data is immutable; derived structures (claims, clusters, themes) are re-generated when framing decisions change
5. **Formalized internal retrieval architecture** — four distinct retrieval modes instead of a generic RAG chatbot pattern

These changes are informed by a systematic literature review of 84+ papers and open-source projects. The design adopts specific architectural patterns from Elicit (task-graph DAG), CoALA (cognitive memory architecture), GraphRAG (community summaries), MLflow (run hierarchy), W3C PROV (provenance triad), MetaGPT (SOP-encoded role separation), and SPECTER2 (scientific embeddings).

### 1.1 Design Decisions Summary

| # | Decision | Chosen Option | Key Reference |
|---|----------|---------------|---------------|
| 1 | RKA's role | Bookkeeper and message transmitter | Core philosophy |
| 2 | Deployment | Docker Compose for server/worker, pipx for MCP | Operational simplicity |
| 3 | Project IDs | Always indexed by project ID | Multi-project isolation |
| 4 | Workspace scanning | No Docker folder mounting | Claude Code submits via MCP |
| 5 | RAG approach | Retrieval as internal service (4 modes) | Elicit task-graph DAG |
| 6 | Local LLM role | Progressive distillation pipeline (5+ new job types) | CoALA, GraphRAG |
| 7 | Knowledge organization | Three-level drill-down research map | MLflow hierarchy, W3C PROV |
| 8 | Elicit integration | Brain-side usage + optional thin search tool | Elicit API (March 2026) |
| 9 | Model stack | Keep qwen3.5 + nomic; add SPECTER2 via API | SPECTER2, Blended RAG |
| 10 | Knowledge graph restructuring | Immutable records + reconstructable interpretation layer | W3C PROV, ProvONE |
| 11 | Entity type redesign | 3 record types + fine typing on claims layer | Practical analysis of v1.6 data |
| 12 | Entity cross-references | Typed bidirectional links with full provenance chains | W3C PROV, MLflow lineage |
| 13 | Brain-augmented enrichment | Tiered: local LLM for routine, Brain for complex reasoning | Agent Laboratory, CoALA |

---

## 2. Current State (v1.6.0)

### 2.1 Architecture Overview

| Layer | Technology | Lines |
|-------|-----------|-------|
| MCP server | FastMCP, stdio, thin HTTP proxy to REST | 2,146 |
| REST API | FastAPI, 18 route modules under /api/ | ~1,700 |
| Services | All business logic, shared by MCP + REST | ~7,300 |
| Models | Pydantic models for all entities | ~700 |
| Database | SQLite + FTS5 + sqlite-vec | 351 |
| Infrastructure | LiteLLM + Instructor, FastEmbed, database | ~1,800 |
| Web UI | React 19 + TypeScript + Vite + shadcn/ui | ~7,550 |
| **Total** | | **~25,300** |

### 2.2 What Works Well

- 44 MCP tools covering the full Brain/Executor/PI workflow
- Hybrid search (FTS5 keyword + sqlite-vec vector + RRF fusion)
- Background enrichment worker with durable job queue (auto-tag, auto-link, auto-summarize, embed)
- Temperature-classified context engine (HOT/WARM/COLD)
- Multi-project isolation with project-scoped queries
- 11-page web dashboard with decision tree and knowledge graph visualization

### 2.3 What Needs Improvement

- Journal entries are a flat timeline — no higher-level organization into themes or research questions
- Knowledge graph is unstructured node soup — doesn't answer "where are we?"
- LLM is reactive (processes entries after creation) — not proactive (building higher-level knowledge)
- 9 journal types are overlapping and unused in practice — nobody picks consistently, nobody updates confidence
- No structured claim extraction from entries — findings are free-text blobs
- No mechanism to restructure derived knowledge when a framing decision is overturned
- No contradiction detection or evidence gap analysis
- No Elicit API integration for systematic literature search

---

## 3. Governing Principle: Immutable Data, Mutable Interpretation

This is the foundational architectural principle for v2.0 and must be understood before all other sections.

**Raw data is immutable. Interpretation is always reconstructable.**

### 3.1 Immutable Layer (append-only, never deleted)

| Entity | What it records | Lifecycle |
|--------|----------------|-----------|
| Journal entries | What was observed, done, or directed | `draft → active → superseded → retracted` |
| Literature | Papers discovered | Reading pipeline status |
| Events | What happened, when | Append-only audit log |
| Decision history | All decisions including superseded ones | `active → abandoned / superseded / merged / revisit` |
| Mission reports | What the Executor actually did | Mission lifecycle |

### 3.2 Mutable Layer (re-generated when framing changes)

| Entity | What it represents | Reconstruction trigger |
|--------|-------------------|----------------------|
| Claims | Structured knowledge extracted from entries | Entry re-distilled |
| Evidence clusters | Grouped claims with synthesis | Cluster membership changes |
| Themes | Cross-cluster synthesis | Cluster updated |
| Topic assignments | Hierarchical categorization | Re-distillation |
| Tags | Free-form labels | Re-distillation or manual edit |

### 3.3 Decision Overturning Mechanism

When the Brain supersedes a decision:

1. Mark old decision as `superseded` with `superseded_by` pointer to replacement decision
2. Increment `scope_version` on the new decision
3. Find all journal entries linked to the old decision via `related_decisions`
4. Find all claims extracted from those entries
5. Mark those claims as `stale` (not deleted — they may be re-extracted identically)
6. Mark all clusters containing stale claims as `needs_reprocessing`
7. Enqueue `re_distill` background jobs for each affected entry

The `re_distill` job re-runs claim extraction on the entry under the new framing. Some claims will be identical (the observation didn't change). Some will be reframed (the interpretation changed). New clusters form organically.

**New fields on decisions:**
- `superseded_by TEXT` — pointer to replacement decision
- `scope_version INTEGER DEFAULT 1` — incremented on overturning

---

## 4. Entity Type Redesign

### 4.1 Problem: The Current 9-Type System Fails in Practice

The current journal types (`finding`, `insight`, `pi_instruction`, `exploration`, `idea`, `observation`, `hypothesis`, `methodology`, `summary`) conflate four different concerns:

| Current types | What they try to capture | Problem |
|--------------|------------------------|---------|
| finding, observation, exploration | What was seen | Overlapping — no clear boundary |
| insight, idea, hypothesis | What was thought | "insight" vs "idea" is arbitrary |
| methodology | How something was done | Only clear type |
| pi_instruction | What to do next | Not knowledge — it's a directive |
| summary | Derived synthesis | System artifact, not primary record |

Evidence from the `rka_development` project (38 entries): 18 are "insight" and 11 are "observation" with no meaningful distinction. The `hypothesis` type conflicts with the `hypothesis` confidence level. Nobody updates confidence — 37 of 38 entries have the default value.

### 4.2 Solution: Three Record Types + Claims Layer

**Journal entry types simplified to 3:**

| New type | What it means | Maps from |
|----------|-------------|-----------|
| `note` | What was observed, thought, or analyzed | finding, insight, idea, observation, exploration, hypothesis |
| `log` | What was done, step by step | methodology |
| `directive` | Instructions from PI or Brain | pi_instruction |

The `summary` type is **removed** — summaries are system artifacts produced by the distillation pipeline, stored in `evidence_clusters.synthesis`. If the Brain writes a manual synthesis, it's a `note`.

**Fine-grained knowledge classification moves to the claims layer:**

| Claim type | What it captures | Example |
|-----------|-----------------|---------|
| `hypothesis` | A speculation or proposed explanation | "The broker needs horizontal scaling" |
| `evidence` | A measured or observed data point | "12% packet loss above 400 connections" |
| `method` | A procedure or technique used | "Tested MQTT with 500 concurrent devices" |
| `result` | An outcome of an experiment or analysis | "Average latency: 45ms under load" |
| `observation` | A raw, uninterpreted notice | "CPU spikes correlate with connection count" |
| `assumption` | An unstated premise being relied on | "Default Mosquitto config is representative" |

**Why this works:** Entry-level type answers "what kind of record is this?" (easy to pick, obvious boundaries). Claim-level type answers "what kind of knowledge does it contain?" (LLM picks this, no human burden). A single `note` can contain both a verified result and a speculative hypothesis — they get separate claims with separate confidence scores.

### 4.3 Confidence: Moves from Entries to Claims

**Current:** Categorical on journal entries (`hypothesis | tested | verified | superseded | retracted`). Nobody updates it.

**Proposed:**
- Journal entries get a simple lifecycle: `status = draft | active | superseded | retracted`
- Claims get continuous confidence: `0.0-1.0` assigned by factored verification, updated as supporting/contradicting claims emerge

### 4.4 Importance: Removed

Replaced by optional boolean `pinned` flag. Importance is inferred from the claim and cluster layer: an entry whose claims are all in strong-evidence clusters is de facto important.

### 4.5 Tags: Split into Topics + Free Tags

| Concept | Structure | Purpose | Assigned by |
|---------|----------|---------|------------|
| **Topics** | Hierarchical (`mqtt`, `mqtt/scalability`) | Drive the research map structure | LLM with consistency enforcement |
| **Tags** | Flat, free-form | Ad-hoc labeling | LLM or human |

Topics map to research questions: each research question is implicitly a topic, and entries/claims belong to topics.

### 4.6 Mission Updates

Add iteration support for repeated experiments:
- `iteration INTEGER DEFAULT 1`
- `parent_mission_id TEXT` (self-referencing FK)

The Brain creates "re-run mission Y with variations" as iteration 2 of the same lineage.

### 4.7 Migration Strategy

This is a breaking schema change for the journal table's type CHECK constraint:

1. Add new columns (`status`, `pinned`) without dropping old ones
2. Map existing types: finding/insight/idea/observation/exploration/hypothesis → `note`, methodology → `log`, pi_instruction → `directive`, summary → `note`
3. Update the CHECK constraint
4. Backfill: copy existing confidence to `legacy_confidence`, set all entries to `status=active`
5. The distillation pipeline extracts claims with proper confidence from all entries during initial run

Existing MCP tools (`rka_add_note`) keep working with a deprecation period: old type values are silently mapped to new types with a warning logged.

---

## 5. Progressive Distillation Pipeline

### 5.1 Pipeline Layers

**Layer 0: Raw Entries (existing)** — Journal entries, literature, decisions as written by Brain/Executor/PI. No change needed. This is the data lake.

**Layer 1: Structured Claims (new)** — Each entry is decomposed by the LLM into typed claims. Example: a journal entry saying "We tested MQTT with 500 concurrent devices and saw 12% packet loss above 400 connections, which suggests the broker needs horizontal scaling" produces three claims:

- `method` claim: "tested MQTT with 500 concurrent devices"
- `evidence` claim: "12% packet loss above 400 connections"
- `hypothesis` claim: "broker needs horizontal scaling"

Each claim links back to its source entry with character offsets. This is the SciEx REV (Retrieval-Extraction-Verification) pattern.

**Layer 2: Evidence Clusters (new)** — Claims are grouped by topic similarity. The LLM scores relationships: does claim A *support*, *contradict*, or *qualify* claim B? Clustering uses both embeddings (sqlite-vec cosine similarity) and the LLM for semantic judgment. This is the GraphRAG "community summary" pattern.

**Layer 3: Research Themes (new)** — The LLM reads each cluster and produces a research theme: what's known, what's contested, and what's missing. Auto-maintained by the background worker.

### 5.2 New Background Worker Jobs

All jobs fit the existing JobQueue with lease-based claiming, dedup keys, and retry logic. The existing job types remain. New jobs form a downstream DAG:

| Job Type | Trigger | What It Does | Priority |
|----------|---------|-------------|----------|
| `note_extract_claims` | New journal entry created | Decompose entry into typed claims with character offsets | 120 |
| `claim_verify` | New claim extracted | Run factored verification against source text | 122 |
| `cluster_update` | New claim verified | Re-evaluate cluster membership, score support/contradict edges | 130 |
| `theme_synthesize` | Cluster modified | Regenerate theme summary for affected clusters | 140 |
| `contradiction_check` | New claim in existing cluster | Flag when new evidence contradicts verified claims | 125 |
| `gap_analysis` | Periodic (weekly) | Scan full knowledge graph for thin evidence areas | 200 |
| `re_distill` | Decision superseded | Re-run claim extraction on affected entries under new framing | 115 |

### 5.3 Elicit-Inspired Task-Graph DAG Pattern

Elicit decomposes every research question into a dependency-aware pipeline where each step runs independently and can be retried. RKA's enrichment pipeline as a DAG:

```
[Entry created]
    ├── auto_tag ──→ auto_link ──→ auto_summarize ──→ embed
    │
    └── extract_claims ──→ claim_verify ──→ cluster_update ──→ theme_synthesize
                                               │
                                               └── contradiction_check
```

Implementation: each job's completion handler calls `queue.enqueue()` for its downstream successors. The existing priority system ensures ordering. Dedup keys prevent duplicate work.

### 5.4 Factored Verification

After extracting a claim, the LLM cross-checks it against the source text with three independent checks:

1. **Existence check:** Does the extracted claim text actually appear in or follow from the source entry?
2. **Number accuracy:** Are any quantities, percentages, or counts accurately extracted?
3. **Direction check:** Is the direction of the effect correct (increase vs decrease, positive vs negative)?

Claims that fail verification are flagged with `confidence=0.0` and `verified=false`, marked for human review rather than silently included in evidence clusters.

### 5.5 Source-Locking for Reproducibility

When the Brain requests context for a research question, store the exact set of entries returned as a context snapshot:

```sql
CREATE TABLE context_snapshots (
    id TEXT PRIMARY KEY,
    entry_ids TEXT NOT NULL,      -- JSON array of entry IDs
    query TEXT,                   -- The query that generated this snapshot
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
```

Decision provenance becomes complete: "I decided X based on context snapshot Y which contained entries Z1, Z2, Z3."

---

## 6. Three-Layer Navigable Research Map

### 6.1 Top Level: Research Questions

The big questions driving the project. Can be manually created by the PI (as decisions) or auto-detected by the LLM when multiple findings cluster around an implicit question. Each question shows:

- Evidence cluster count and total claim count
- Gap count (areas with insufficient evidence)
- Contradiction count (conflicting claims within clusters)
- Confidence color: **teal** = healthy evidence, **coral** = needs attention, **gray** = emerging/exploring

### 6.2 Middle Level: Evidence Clusters

Clicking into a research question reveals the evidence clusters. Each cluster displays:

- Short LLM-generated label and synthesis paragraph
- Confidence indicator: `strong | moderate | emerging | contested | refuted`
- Inter-cluster edges: green solid = supporting, red dashed = contradicting
- Claim count and source entry count

### 6.3 Bottom Level: Individual Claims

Drilling into a cluster reveals atomic claims with full W3C PROV provenance:

- `wasDerivedFrom`: which journal entry the claim was extracted from (with character offset)
- `wasGeneratedBy`: which activity (mission, session) produced the source entry
- `wasAssociatedWith`: which agent (Brain, Executor, PI) wrote the source entry

### 6.4 Web Dashboard Implementation

New page at `/research-map` built with @xyflow/react. Three interaction modes:

1. **Overview mode:** all research questions as large nodes with summary badges. Click to drill down.
2. **Cluster mode:** evidence clusters for one RQ as a force-directed graph with support/contradict edges. Click a cluster for the detail panel.
3. **Detail mode:** individual claims listed in a side panel when a cluster is selected, with links to source journal entries.

The existing `/graph` page remains as a low-level debugging view.

**New components:**
- `ResearchMapPage.tsx` — top-level page with mode switching
- `RQNode.tsx` — custom React Flow node for research questions
- `ClusterNode.tsx` — custom node for evidence clusters with confidence coloring
- `ClaimPanel.tsx` — side panel showing individual claims
- `useResearchMap.ts` — TanStack Query hook for `/api/research-map`

**Sidebar:** Add "Research Map" between "Dashboard" and "Journal" with a compass/map icon.

---

## 7. Internal Retrieval Architecture

RKA v2.0 does NOT implement a traditional RAG chatbot. Retrieval is an internal service powering four distinct modes.

### 7.1 Four Retrieval Modes

| Mode | Consumer | Strategy | Optimized for |
|------|----------|----------|--------------|
| Context assembly | Brain/Executor sessions | Temperature-based (HOT/WARM/COLD), token-budgeted | Recall |
| Enrichment linking | Background worker | Candidate entity matching, LLM-scored relevance | Precision |
| Grounded Q&A | Notebook page (PI) | Source-restricted with mandatory citations | Accuracy |
| Batch synthesis | Research map generation | Scope-based retrieval (all entries in a cluster/phase) | Completeness |

### 7.2 Hybrid Search Improvements

The current FTS5 + sqlite-vec + RRF pipeline is architecturally sound. v2.0 adds:

- **SPECTER2 embeddings** for literature entries pulled from Semantic Scholar API (no local model)
- **Dual embedding storage:** nomic-embed-text-v1.5 for internal entities, SPECTER2 for literature
- **Future (post-v2.0):** FastEmbed `TextCrossEncoder` reranker (~80MB) as a post-RRF step when entity count grows
- **Dynamic query-type detection** to adjust dense/sparse balance per query

### 7.3 Source-Grounded Generation

Following the NotebookLM pattern (~13% hallucination rate vs ~40% for ungrounded models):

1. Restrict LLM context to retrieved passages only — no reliance on parametric knowledge
2. Require citation links with source entity IDs and character offsets for every generated claim
3. Store citations in structured format for the research map to display
4. Support "show me the evidence" drill-down from any synthesized text to source claims

---

## 8. Database Schema Changes

One new migration (`009_add_claims_clusters_entity_redesign.sql`). All existing data preserved. Backward-compatible with deprecation mapping.

### 8.1 Journal Table Modifications

**Migration strategy:** The journal table has a real CHECK constraint on `type` (9 values) and `confidence` (5 values). SQLite cannot ALTER existing CHECK constraints. The approach is table recreation with an expanded CHECK that includes both old and new values, followed by data migration.

**Step 1: Table recreation with expanded type CHECK (9 old + 3 new = 12 values):**

```sql
-- Recreate journal table with expanded CHECK constraint
-- Includes both old types (for backward compat) and new types
CREATE TABLE journal_new (
    -- ... all existing columns ...
    type TEXT NOT NULL CHECK (type IN (
        'finding', 'insight', 'pi_instruction', 'exploration',
        'idea', 'observation', 'hypothesis', 'methodology', 'summary',
        'note', 'log', 'directive'
    )),
    -- ... rest of columns unchanged ...
    -- New columns:
    status TEXT DEFAULT 'active'
        CHECK (status IN ('draft', 'active', 'superseded', 'retracted')),
    pinned INTEGER DEFAULT 0
);
-- Copy data, drop old, rename new (standard SQLite table recreation)
```

**Step 2: Data migration (run immediately after table recreation):**

```sql
UPDATE journal SET type = 'note' WHERE type IN ('finding', 'insight', 'idea', 'observation', 'exploration', 'hypothesis', 'summary');
UPDATE journal SET type = 'log' WHERE type = 'methodology';
UPDATE journal SET type = 'directive' WHERE type = 'pi_instruction';
UPDATE journal SET status = 'active';  -- all existing entries are active
```

**Confidence column: kept as-is.** The existing `confidence` column (hypothesis/tested/verified/superseded/retracted) stays unchanged — it has meaningful historical data (150 hypothesis, 62 tested, 45 verified across all projects). No `legacy_confidence` column needed — the existing column IS the legacy. New system reads `claims.confidence` for decisions, not `journal.confidence`. MCP tools continue accepting `confidence` parameter for backward compatibility.

### 8.2 Decision Table Modifications

```sql
ALTER TABLE decisions ADD COLUMN superseded_by TEXT REFERENCES decisions(id);
ALTER TABLE decisions ADD COLUMN scope_version INTEGER DEFAULT 1;
ALTER TABLE decisions ADD COLUMN kind TEXT DEFAULT 'decision'
    CHECK (kind IN ('research_question', 'design_choice', 'operational'));
ALTER TABLE decisions ADD COLUMN related_journal TEXT;  -- JSON: ["jrn_01H...", ...]
```

The `kind` field explicitly marks which decisions are research questions (top level of the research map), design choices, or operational decisions. The research map API queries `kind = 'research_question'` for its top-level view. Default is `'decision'` — existing decisions keep working. Brain or LLM reclassifies as needed.

### 8.3 Mission Table Modifications

```sql
ALTER TABLE missions ADD COLUMN iteration INTEGER DEFAULT 1;
ALTER TABLE missions ADD COLUMN parent_mission_id TEXT REFERENCES missions(id);
```

### 8.4 New Table: claims

```sql
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,                    -- ULID with clm_ prefix
    source_entry_id TEXT NOT NULL REFERENCES journal(id),
    claim_type TEXT NOT NULL CHECK (claim_type IN (
        'hypothesis', 'evidence', 'method', 'result', 'observation', 'assumption'
    )),
    content TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,            -- 0.0 to 1.0
    verified INTEGER DEFAULT 0,            -- 1 = passed factored verification
    stale INTEGER DEFAULT 0,               -- 1 = source decision was superseded
    source_offset_start INTEGER,           -- character offset in source entry
    source_offset_end INTEGER,
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_claims_source ON claims(source_entry_id);
CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type);
CREATE INDEX IF NOT EXISTS idx_claims_stale ON claims(stale);
CREATE INDEX IF NOT EXISTS idx_claims_project ON claims(project_id);
```

### 8.5 New Table: evidence_clusters

```sql
CREATE TABLE IF NOT EXISTS evidence_clusters (
    id TEXT PRIMARY KEY,                    -- ULID with ecl_ prefix
    research_question_id TEXT,             -- FK to decisions(id) where kind = 'research_question'
    label TEXT NOT NULL,                   -- short name, e.g. "broker limits"
    synthesis TEXT,                        -- LLM-generated paragraph summary
    confidence TEXT DEFAULT 'emerging'
        CHECK (confidence IN ('strong', 'moderate', 'emerging', 'contested', 'refuted')),
    claim_count INTEGER DEFAULT 0,         -- denormalized
    gap_count INTEGER DEFAULT 0,
    needs_reprocessing INTEGER DEFAULT 0,  -- 1 = flagged for re-distillation
    synthesized_by TEXT DEFAULT 'llm'      -- llm | brain (attribution for quality indicator)
        CHECK (synthesized_by IN ('llm', 'brain')),
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_clusters_rq ON evidence_clusters(research_question_id);
CREATE INDEX IF NOT EXISTS idx_clusters_project ON evidence_clusters(project_id);
```

### 8.6 New Table: claim_edges

```sql
CREATE TABLE IF NOT EXISTS claim_edges (
    id TEXT PRIMARY KEY,
    source_claim_id TEXT NOT NULL REFERENCES claims(id),
    target_claim_id TEXT,                  -- null for cluster membership
    cluster_id TEXT REFERENCES evidence_clusters(id),
    relation TEXT NOT NULL CHECK (relation IN (
        'member_of', 'supports', 'contradicts', 'qualifies', 'supersedes'
    )),
    confidence REAL DEFAULT 0.5,
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_claim_edges_source ON claim_edges(source_claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_edges_cluster ON claim_edges(cluster_id);
CREATE INDEX IF NOT EXISTS idx_claim_edges_project ON claim_edges(project_id);
```

### 8.7 New Table: topics

```sql
CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,                    -- ULID with top_ prefix
    name TEXT NOT NULL,                    -- e.g. "mqtt/scalability"
    parent_id TEXT REFERENCES topics(id),  -- for hierarchy
    description TEXT,
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Junction: entity-to-topic membership
CREATE TABLE IF NOT EXISTS entity_topics (
    topic_id TEXT NOT NULL REFERENCES topics(id),
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    assigned_by TEXT DEFAULT 'llm',         -- llm | brain | pi
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (topic_id, entity_type, entity_id)
);
```

### 8.8 New Table: context_snapshots

```sql
CREATE TABLE IF NOT EXISTS context_snapshots (
    id TEXT PRIMARY KEY,
    entry_ids TEXT NOT NULL,               -- JSON array
    query TEXT,
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
```

### 8.9 New Table: review_queue (Brain-augmented enrichment)

```sql
CREATE TABLE IF NOT EXISTS review_queue (
    id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,              -- entity type needing review
    item_id TEXT NOT NULL,                -- entity ID
    flag TEXT NOT NULL CHECK (flag IN (
        'low_confidence_cluster', 'potential_contradiction',
        'complex_synthesis_needed', 're_distill_review',
        'cross_topic_link', 'stale_theme'
    )),
    context TEXT,                         -- JSON: what the local LLM noticed
    priority INTEGER DEFAULT 100,        -- lower = higher priority
    status TEXT DEFAULT 'pending'
        CHECK (status IN ('pending', 'acknowledged', 'resolved', 'dismissed')),
    raised_by TEXT DEFAULT 'llm',
    resolved_by TEXT,                    -- brain | pi
    resolution TEXT,
    project_id TEXT NOT NULL DEFAULT 'proj_default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status);
CREATE INDEX IF NOT EXISTS idx_review_queue_project ON review_queue(project_id);
```

### 8.10 FTS5 and Vector Extensions

```sql
-- New FTS5 table for claims
CREATE VIRTUAL TABLE IF NOT EXISTS fts_claims USING fts5(
    id UNINDEXED, content, tokenize='porter unicode61'
);

-- New vec0 table for claims
CREATE VIRTUAL TABLE IF NOT EXISTS vec_claims USING vec0(
    id TEXT PRIMARY KEY, embedding float[768]
);
```

---

## 9. Service Layer Changes

### 9.1 New Service Modules

| Module | Responsibility | Key Methods |
|--------|---------------|-------------|
| `ClaimService` | Extract claims from entries, verify them, CRUD | `extract_claims()`, `verify_claim()`, `get_claims_for_entry()`, `mark_stale()` |
| `ClusterService` | Manage evidence clusters, run LLM clustering, score edges | `update_clusters()`, `synthesize_theme()`, `detect_contradictions()`, `mark_needs_reprocessing()` |
| `ResearchMapService` | Compose the three-level view for API and dashboard | `get_research_questions()`, `get_clusters_for_rq()`, `get_claims_for_cluster()` |
| `TopicService` | Manage hierarchical topics, assign entities | `create_topic()`, `assign_entity()`, `get_topic_tree()` |
| `ReviewQueueService` | Manage Brain review queue, flag items, resolve reviews | `flag_for_review()`, `get_pending()`, `resolve()`, `get_stats()` |

### 9.2 Modified Services

- **NoteService:** After creating a journal entry, enqueue `note_extract_claims` as downstream job. Map old type values to new types silently.
- **DecisionService:** Add `supersede_decision()` method that atomically marks old decision as superseded, creates new decision, and triggers `re_distill` jobs.
- **SearchService:** Add claims and evidence_clusters as searchable entity types. Extend FTS and vector search to include new tables.
- **ContextEngine:** Include relevant evidence cluster syntheses alongside raw entries. Record context snapshots when assembling context.
- **Worker (`worker.py`):** Add handlers for 7 new job types, routing to ClaimService and ClusterService.
- **GraphService:** Extend full graph to include claim and cluster nodes with claim_edges.

### 9.3 New API Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/api/claims` | GET | List claims with filters (entry_id, cluster_id, claim_type, verified, stale) |
| `/api/claims/{id}` | GET | Get single claim with provenance |
| `/api/clusters` | GET | List evidence clusters with filters (rq_id, confidence, needs_reprocessing) |
| `/api/clusters/{id}` | GET | Get cluster detail with claims and edges |
| `/api/research-map` | GET | Composed three-level view for the dashboard |
| `/api/research-map/rq/{id}` | GET | Clusters for a specific research question |
| `/api/topics` | GET/POST | List or create topics |
| `/api/topics/{id}` | GET/PUT/DELETE | Topic CRUD |
| `/api/context-snapshots/{id}` | GET | Retrieve a stored context snapshot |

---

## 10. MCP Tool Changes

### 10.1 New Tool: rka_search_elicit

Optional thin wrapper alongside `rka_search_semantic_scholar` and `rka_search_arxiv`. Gated behind `ELICIT_API_KEY` environment variable — if not set, the tool is not registered.

**Parameters:**
- `query` (str): Research question for semantic paper search
- `limit` (int, default 10): Max results
- `add_to_library` (bool, default False): Auto-add results to RKA literature table

**Implementation:**
```
POST https://elicit.com/api/v1/search
Headers: Authorization: Bearer $ELICIT_API_KEY
Body: { "query": "...", "maxResults": 10 }
```

Returns structured JSON matching the format of `rka_search_semantic_scholar`. The Brain uses this for paper discovery. The Report endpoint (async, 5-15 min) remains a Brain-initiated workflow outside RKA.

### 10.2 New Tool: rka_get_research_map

Returns the three-level research map view in compact text format for Brain/Executor context loading. Shows research questions with cluster counts, confidence indicators, and gap/contradiction flags.

### 10.3 New Tool: rka_get_claims

Query claims with filters: by entry_id, cluster_id, claim_type, verified status, stale status. Returns claim content with source entry provenance.

### 10.4 New Tool: rka_supersede_decision

Atomically supersedes a decision and triggers re-distillation:
- `old_decision_id` (str): Decision to supersede
- `question` (str): New decision question
- `chosen` (str): New chosen option
- `rationale` (str): Why the old decision is being overturned

### 10.5 New Tool: rka_trace_provenance

Traces the full reasoning chain behind any entity:
- `entity_id` (str): The entity to trace from
- `direction` (str): `upstream` (what led to this) | `downstream` (what this led to) | `both`
- `max_depth` (int, default 4): Maximum hops to traverse

Returns a formatted provenance chain showing the reasoning path. Example output:
```
Upstream provenance for dec_01KK... (implement broker sharding):
  ← justified_by jrn_01KK... [note] "12% packet loss above 400 connections"
    ← produced msn_01KK... "MQTT stress test at scale"
      ← motivated dec_01KK... (test broker limits)
        ← informed_by lit_01KK... "MQTT Protocol Benchmarks for IoT"
```

### 10.6 Modified Tools — New Cross-Reference Parameters

- **rka_add_decision:** New `related_journal: list[str]` parameter — the Brain specifies which findings (executor output, analyses) justify this decision. Creates `justified_by` links.
- **rka_create_mission:** New `motivated_by_decision: str` parameter — links mission to the decision that triggered its creation. Creates `motivated` link.
- **rka_submit_report:** New `related_decisions: list[str]` parameter — Executor specifies which decisions the report's findings bear on. Creates `justified_by` links from findings to decisions.
- **rka_add_note:** Existing `related_decisions` creates `references` links. Existing `related_literature` creates `cites` links. Both unchanged.
- **rka_get_status:** Include research map summary (total RQs, clusters, claims, gaps, contradictions).
- **rka_get_context:** Include evidence cluster syntheses in context packages. Record context snapshots.
- **rka_search:** Extend to search claims and clusters as entity types.

---

## 11. LLM Prompt Engineering

All LLM interactions use the existing LiteLLM + Instructor pattern with JSON_SCHEMA mode.

### 11.1 New Pydantic Models

**ExtractedClaims** — output of claim extraction:
```python
class ExtractedClaim(BaseModel):
    claim_type: Literal["hypothesis", "evidence", "method", "result", "observation", "assumption"]
    content: str
    source_offset_start: int
    source_offset_end: int

class ExtractedClaims(BaseModel):
    claims: list[ExtractedClaim] = Field(min_length=1, max_length=20)
    reasoning: str
```

**ClaimVerification** — output of factored verification:
```python
class ClaimVerification(BaseModel):
    exists_in_source: bool
    number_accuracy: bool
    direction_correct: bool
    overall_confidence: float = Field(ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)
```

**ClusterAssignment** — output of cluster scoring:
```python
class ClusterAssignment(BaseModel):
    cluster_id: str | None  # existing cluster or None for new
    cluster_label: str      # for new clusters
    relations: list[ClaimRelation]

class ClaimRelation(BaseModel):
    target_claim_id: str
    relation: Literal["supports", "contradicts", "qualifies"]
    confidence: float = Field(ge=0.0, le=1.0)
```

**ThemeSynthesis** — output of cluster synthesis:
```python
class ThemeSynthesis(BaseModel):
    synthesis: str           # paragraph
    confidence: Literal["strong", "moderate", "emerging", "contested", "refuted"]
    gaps: list[str]          # what evidence is missing
    contradictions: list[str] # what evidence conflicts
```

### 11.2 Context-Window-Aware Prompting

Apply scaling to claim extraction:

| Context window | Entry text | Existing claims for dedup |
|---------------|-----------|--------------------------|
| 128k+ | Full text | Up to 50 existing claims |
| 32k | Full text | Up to 20 existing claims |
| 8k | Truncate to 3000 chars | Up to 10 existing claims |

---

## 12. Model Stack

Minimal additions. Principle: minimize operational complexity, add models only when measured need appears.

| Model | Purpose | Status | Location |
|-------|---------|--------|----------|
| qwen3.5-35b | All LLM reasoning (extraction, linking, synthesis, Q&A) | Keep (existing) | LM Studio |
| nomic-embed-text-v1.5 | Embeddings for internal entities (journal, decisions, missions, claims) | Keep (existing) | FastEmbed ONNX (~130MB) |
| SPECTER2 | Embeddings for literature (scientific paper similarity) | Add via API | Semantic Scholar API (free) |
| Cross-encoder reranker | Post-RRF reranking for search quality | Add post-v2.0 | FastEmbed ONNX (~80MB) |

### 12.1 SPECTER2 Integration

When enriching a literature entry with a DOI or Semantic Scholar paper ID:

1. Call Semantic Scholar API with `fields=embedding`
2. Store the 768-dim SPECTER2 vector in `vec_literature` (compatible dimensionality)
3. Fall back to nomic embedding if S2 API returns no embedding (paper not indexed)

---

## 13. Provenance Model (W3C PROV-Aligned)

### 13.1 Entity-Activity-Agent Triad

| PROV Concept | RKA Mapping | Implementation |
|-------------|-------------|----------------|
| Entity | Journal entry, claim, cluster, literature, decision | All have id, created_at, project_id |
| Activity | Mission, session, enrichment job | Tracked in events + job queue |
| Agent | Brain, Executor, PI, LLM, system | source/actor field on all entities |
| wasDerivedFrom | Claim → source journal entry | `claims.source_entry_id` + offsets |
| wasGeneratedBy | Entry → mission that produced it | `journal.related_mission` |
| wasAssociatedWith | Entry → actor who wrote it | `journal.source` |

### 13.2 Prospective vs Retrospective Provenance

Following ProvONE:

- **Prospective provenance (the plan):** Recorded in missions (objective, tasks, acceptance_criteria). What the Brain intended.
- **Retrospective provenance (what happened):** Recorded in events, journal entries, mission reports. What the Executor actually did.

The research map surfaces both: the planned research roadmap (decisions, missions) and the actual evidence landscape (claims, clusters). Divergences between plan and reality are visible as research questions with thin evidence or contradictions.

---

## 14. Elicit Integration

### 14.1 Architecture: Brain-Side, Not Server-Side

Elicit is used by the Brain (Claude Desktop/Code), not integrated into RKA's server. Rationale:

- Violates RKA's bookkeeper philosophy — knowledge discovery is the Brain's job
- Couples RKA to a paid SaaS ($49+/mo) — RKA should deliver value with zero external dependencies
- Report endpoint is async (5-15 min) — poor fit for MCP tool calls

### 14.2 Workflow

1. Brain identifies a research question needing systematic literature analysis
2. Brain calls Elicit API directly (via Python script or MCP tool)
3. Brain receives structured results — papers with metadata and synthesized report
4. Brain calls `rka_batch_import` to add papers to RKA's literature table
5. Brain calls `rka_ingest_document` to add report findings as journal entries
6. RKA's background worker enriches everything automatically

### 14.3 Adopted Patterns (Not the API)

| Elicit Pattern | RKA Implementation |
|---------------|-------------------|
| Task-graph DAG | Background worker job chaining via enqueue-on-completion |
| Typed extraction columns | Claim types (hypothesis, evidence, method, result, observation, assumption) |
| Factored verification | Independent LLM checks: existence, number accuracy, direction correctness |
| Source-locking | Context snapshots recording exact entry sets used for decisions |

---

## 15. Web Dashboard Changes

### 15.1 New Page: /research-map

Primary navigation page. Three modes: overview → cluster → detail.

Color coding:
- **Teal:** strong/moderate evidence (healthy)
- **Coral:** contested or has contradictions (needs attention)
- **Gray:** emerging or insufficient evidence (exploring)
- **Green edges:** supporting relationships
- **Red dashed edges:** contradicting relationships

### 15.2 Modified Pages

- **Dashboard (/):** Add research map summary card (total RQs, clusters, claims, gaps, contradictions)
- **Journal (/journal):** Add "claims extracted" badge on processed entries. Update type filter to show note/log/directive.
- **Settings (/settings):** Add Elicit API key configuration. Add distillation pipeline status (jobs pending/complete/failed). Add topic management.

---

## 16. Implementation Plan

### Phase 1: Schema + Entity Redesign (Week 1-2)

1. Create migration `009_add_claims_clusters_entity_redesign.sql`
   - Modify journal type CHECK (add note/log/directive, keep old for migration)
   - Add journal.status, journal.pinned, journal.legacy_confidence
   - Add decisions.superseded_by, decisions.scope_version
   - Add missions.iteration, missions.parent_mission_id
   - Create claims, evidence_clusters, claim_edges, topics, entity_topics, context_snapshots tables
   - Create FTS5 and vec0 tables for claims
2. Write backfill script for existing journal type migration
3. Update NoteService for type mapping
4. Write tests: test_migration.py, test_type_mapping.py

### Phase 2: Claim Extraction + Verification + Cross-References (Week 3-4)

1. Implement ClaimService with `extract_claims()` and `verify_claim()`
2. Add ExtractedClaims and ClaimVerification Pydantic models to llm.py
3. Add `note_extract_claims` and `claim_verify` job types to worker.py
4. Add `/api/claims` routes
5. Expand entity_links link_type vocabulary (informed_by, justified_by, motivated, derived_from, builds_on)
6. Add `related_journal` column to decisions table
7. Add `motivated_by_decision` column to missions table
8. Expand SemanticLinks Pydantic model for richer LLM-inferred cross-references
9. Write tests: test_claim_service.py, test_claim_worker.py, test_cross_references.py

### Phase 3: Clustering + Synthesis (Week 5-6)

1. Implement ClusterService with `update_clusters()`, `synthesize_theme()`, `detect_contradictions()`
2. Add ClusterAssignment and ThemeSynthesis Pydantic models
3. Add `cluster_update`, `theme_synthesize`, `contradiction_check` job types
4. Implement TopicService for hierarchical topic management
5. Add `/api/clusters`, `/api/topics`, `/api/research-map` routes
6. Implement ResearchMapService composing the three-level view
7. Write tests: test_cluster_service.py, test_research_map.py

### Phase 4: Decision Overturning + Re-distillation (Week 7)

1. Add `supersede_decision()` to DecisionService
2. Add `re_distill` job type to worker
3. Add `rka_supersede_decision` MCP tool
4. Implement stale claim detection and cluster reprocessing
5. Write tests: test_supersede.py, test_redistill.py

### Phase 5: Research Map UI (Week 8-9)

1. Create ResearchMapPage.tsx with @xyflow/react
2. Build RQNode, ClusterNode, ClaimPanel components
3. Add useResearchMap.ts TanStack Query hook
4. Update sidebar navigation, Dashboard, Journal, Settings pages
5. Update type filters on Journal page for note/log/directive

### Phase 6: MCP Tools + Elicit + Cross-References (Week 10-11)

1. Add `rka_search_elicit` tool (gated behind ELICIT_API_KEY)
2. Add `rka_get_research_map` and `rka_get_claims` tools
3. Add `rka_trace_provenance` tool for reasoning chain traversal
4. Add `related_journal` parameter to `rka_add_decision`
5. Add `motivated_by_decision` parameter to `rka_create_mission`
6. Add `related_decisions` parameter to `rka_submit_report`
7. Modify `rka_get_status`, `rka_get_context`, `rka_search` for claims/clusters
8. Add SPECTER2 embedding pull to literature enrichment job
9. Implement periodic `gap_analysis` job
10. Add context snapshot recording to ContextEngine

### Phase 7: Brain-Augmented Enrichment + Polish (Week 12)

1. Create `review_queue` table in migration
2. Add review queue flagging logic to local LLM enrichment jobs (flag low-confidence, potential contradictions, complex clusters)
3. Implement `rka_get_review_queue` MCP tool
4. Implement `rka_review_cluster` MCP tool (Brain writes back refined synthesis + confidence)
5. Implement `rka_review_claims` MCP tool (Brain corrects/approves extracted claims)
6. Implement `rka_synthesize_topic` MCP tool (Brain produces deep topic synthesis)
7. Implement `rka_evaluate_evidence` MCP tool (Brain assesses evidence state + priorities)
8. Implement `rka_resolve_contradiction` MCP tool (Brain resolves flagged conflicts)
9. Update Brain/Executor orientation prompts to include review queue in session protocol
10. Add Brain-enrichment attribution (`synthesized_by: brain` vs `synthesized_by: llm`)
11. Add review queue indicator badges to research map UI (shows which syntheses are Brain-verified)
12. Run full test suite, update documentation
13. Tag v2.0.0 release

---

## 17. Literature References

| Title | Authors/Org | Year | Key Contribution |
|-------|------------|------|-----------------|
| Agent Laboratory | Schmidgall et al. (Johns Hopkins) | 2025 | Human-in-the-loop research pipeline, 84% cost reduction |
| ResearchAgent | Baek et al. | 2024 | Iterative idea generation over literature graphs |
| Towards Scientific Intelligence | Ren et al. | 2025 | Taxonomy of AI-for-science automation levels |
| SPECTER2 | Singh et al. (Allen AI) | 2023 | State-of-the-art scientific paper embeddings |
| Quivr | QuivrHQ | 2024 | Per-project Brain abstraction for RAG |
| Onyx | Onyx Contributors | 2024 | Hybrid search: embeddings + BM25 + reranking |
| Semantic Scholar (S2AG) | Ammar et al. (Allen AI) | 2022 | 205M paper knowledge graph, SPECTER2 API |
| Elicit | Elicit Team | 2024 | Task-graph DAG, 99.4% extraction, sentence citations |
| MLflow | Zaharia et al. (Databricks) | 2018 | Project/Experiment/Run hierarchy pattern |
| W3C PROV | Groth & Moreau | 2013 | Entity-Activity-Agent provenance triad |

---

## 18. Entity Cross-References and Provenance Chains

### 18.1 Problem: Current Links Are Sparse and One-Directional

The current `entity_links` table defines 7 link types (`triggered`, `produced`, `references`, `resolved_as`, `cites`, `supersedes`, `evidence_for`) but in practice only 3 are used: `references` (journal→decision), `cites` (journal→literature), and `produced` (mission→journal). This means:

- **Decisions don't point to their justification.** You can't answer "why was this decision made?" by traversing the graph — you have to search for journal entries that happen to reference the decision.
- **Literature doesn't link to what motivated its discovery.** Papers exist in isolation from the research questions that prompted finding them.
- **Executor outputs don't feed back into design decisions.** Experiment results (journal entries from the Executor) don't have typed links to the decisions they justify or overturn.
- **The graph is missing the reasoning chain.** The full chain — literature informed a decision, which motivated a mission, which produced findings, which justified a new design — is implicit in timestamps and free text, not explicit in the graph.

### 18.2 Solution: Expanded Link Vocabulary with Bidirectional Provenance

The link vocabulary expands from 7 to 12 typed relationships, organized by the reasoning chain they capture:

| Link type | Source → Target | What it means | Example |
|-----------|----------------|---------------|---------|
| `informed_by` | decision → literature | This paper's findings shaped the decision | Decision "use MQTT" informed by paper on protocol comparison |
| `justified_by` | decision → journal | This finding provides evidence for the decision | Decision "horizontal scaling" justified by executor's load test results |
| `motivated` | decision → mission | This decision triggered this investigation | Decision "test broker limits" motivated mission "MQTT stress test" |
| `produced` | mission → journal | This mission generated this finding | Mission "MQTT stress test" produced journal entry with results |
| `cites` | journal → literature | This entry references this paper | Literature review entry cites specific papers |
| `references` | journal → decision | This entry relates to this decision | Finding mentions the scaling decision |
| `supports` | claim → claim | This evidence strengthens that hypothesis | (Within evidence clusters) |
| `contradicts` | claim → claim | This evidence conflicts with that claim | (Within evidence clusters) |
| `supersedes` | entity → entity | This replaces that (decisions, entries, claims) | New decision supersedes old one |
| `resolved_as` | checkpoint → decision | Checkpoint was resolved by creating a decision | Executor's question became a recorded decision |
| `derived_from` | claim → journal | Claim was extracted from this entry | Provenance chain for distillation pipeline |
| `builds_on` | literature → literature | This paper extends or responds to that paper | Citation-chain relationship |

### 18.3 The Full Reasoning Chain

The cross-references form a complete provenance chain that answers any "why?" question by graph traversal:

```
Literature (paper on MQTT benchmarks)
    │ informed_by
    ▼
Decision (use MQTT for IoT messaging)
    │ motivated
    ▼
Mission (stress test MQTT broker at scale)
    │ produced
    ▼
Journal entry [log] (executor ran 500-connection test)
Journal entry [note] (12% packet loss above 400 connections)
    │ derived_from
    ▼
Claim [evidence] (packet loss threshold at 400 connections)
Claim [hypothesis] (broker needs horizontal scaling)
    │ justified_by
    ▼
Decision (implement broker sharding)
    │ motivated
    ▼
Mission (design and test sharding strategy)
    ... cycle continues ...
```

Every link is traversable in both directions. "Why did we decide to shard?" → follow `justified_by` edges → find the executor's load test findings → follow `derived_from` → find the source journal entry → follow `produced` → find the mission → follow `motivated` → find the original decision to test broker limits → follow `informed_by` → find the literature.

### 18.4 Schema Changes for Cross-References

**entity_links: No schema change needed.** The live database has NO CHECK constraint on `link_type` — only a SQL comment. New link types can be inserted immediately. The valid set is documented here for reference:

```sql
-- entity_links.link_type valid values (enforced at service layer, not by CHECK):
-- Provenance: informed_by, justified_by, motivated, produced, derived_from
-- Knowledge:  cites, references, supports, contradicts, builds_on
-- Lifecycle:  supersedes, resolved_as
-- Legacy:     triggered, evidence_for (deprecated, may exist in old data)
```

**Add `related_journal` to decisions table:**

```sql
ALTER TABLE decisions ADD COLUMN related_journal TEXT;  -- JSON: ["jrn_01H...", ...]
```

This is the missing reverse link — decisions can now explicitly point to the journal entries (executor findings, brain analyses) that justify them. Symmetric with the existing `journal.related_decisions`.

**Add `motivated_by_decision` to missions table:**

```sql
ALTER TABLE missions ADD COLUMN motivated_by_decision TEXT REFERENCES decisions(id);
```

Missions can now point to the decision that triggered their creation. The Brain creates a decision ("we need to test X"), then creates a mission motivated by that decision.

### 18.5 How Cross-References Are Created

Cross-references come from three sources, in order of reliability:

**1. Explicit (caller-provided):** When the Brain or Executor calls MCP tools, they provide `related_decisions`, `related_literature`, `related_journal`, `related_mission`. These create entity_links immediately. This is the most reliable source.

**Tool parameter additions:**
- `rka_add_decision`: add `related_journal: list[str]` parameter — the Brain specifies which findings justify this decision
- `rka_create_mission`: add `motivated_by_decision: str` parameter — links mission to the decision that triggered it
- `rka_submit_report`: add `related_decisions: list[str]` parameter — Executor specifies which decisions the report's findings bear on

**2. LLM-inferred (enrichment worker):** The existing `rka_enrich` / `auto_link` job already infers links using the LLM. In v2.0, expand the SemanticLinks Pydantic model:

```python
class SemanticLinks(BaseModel):
    related_decision_ids: list[str] = []
    related_literature_ids: list[str] = []
    related_mission_id: str | None = None
    related_journal_ids: list[str] = []        # NEW: cross-ref to other entries
    justified_decisions: list[str] = []        # NEW: decisions this entry provides evidence for
    link_types: dict[str, str] = {}            # NEW: entity_id → link_type override
    reasoning: str
```

The LLM prompt for link inference expands to ask: "Does this finding provide justification for any existing decision? Does it contradict any existing decision?"

**3. Automatic (structural):** Some links are created automatically by the system without LLM involvement:
- When a mission is completed, `produced` links are created from mission → all journal entries with `related_mission` set to that mission
- When a decision is superseded, `supersedes` link is created automatically
- When a claim is extracted, `derived_from` link is created from claim → source entry
- When a checkpoint is resolved as a decision, `resolved_as` link is created

### 18.6 Cross-Reference Queries for the Research Map

The research map uses cross-references to build its three-layer view. Key queries:

**"Why was this decision made?"**
```sql
SELECT el.source_type, el.source_id, el.link_type
FROM entity_links el
WHERE el.target_type = 'decision' AND el.target_id = ?
  AND el.link_type IN ('justified_by', 'informed_by')
```

**"What did this mission produce and what did it affect?"**
```sql
-- What it produced
SELECT el.target_id FROM entity_links el
WHERE el.source_type = 'mission' AND el.source_id = ?
  AND el.link_type = 'produced';

-- What decisions its findings justified
SELECT el2.target_id FROM entity_links el1
JOIN entity_links el2 ON el1.target_id = el2.source_id
WHERE el1.source_type = 'mission' AND el1.source_id = ?
  AND el1.link_type = 'produced'
  AND el2.link_type = 'justified_by';
```

**"What's the full provenance chain for this claim?"**
```sql
-- Claim → source entry → source mission → motivating decision → informing literature
WITH RECURSIVE chain AS (
    SELECT source_type, source_id, link_type, target_type, target_id, 1 as depth
    FROM entity_links WHERE source_type = 'claim' AND source_id = ?
    UNION ALL
    SELECT el.source_type, el.source_id, el.link_type, el.target_type, el.target_id, c.depth + 1
    FROM entity_links el JOIN chain c ON el.source_id = c.target_id
    WHERE c.depth < 5
)
SELECT * FROM chain;
```

### 18.7 MCP Tool: rka_trace_provenance

New tool for the Brain to trace the full reasoning chain behind any entity:

```
rka_trace_provenance(entity_id: str, direction: "upstream" | "downstream" | "both", max_depth: int = 4)
```

- **upstream**: What led to this entity? (literature → decision → mission → finding)
- **downstream**: What did this entity lead to? (finding → claim → cluster → decision)
- **both**: Full bidirectional chain

Returns a formatted provenance chain that the Brain can use to understand the full context behind any piece of knowledge.

### 18.8 Cross-Reference Visualization in the Dashboard

The research map's detail panel (shown when clicking any entity) should display:

- **Justified by** section: findings and literature that support this decision
- **Motivated** section: missions and investigations triggered by this decision
- **Produced by** section: the mission and actor that generated this finding
- **Informs** section: decisions that this finding provides evidence for
- **Builds on** section: related literature in the citation chain

Each cross-reference is a clickable link that navigates to the referenced entity, enabling the PI to traverse the full reasoning chain visually.

---

## 19. Brain-Augmented Enrichment

### 19.1 The Intelligence Gap

The local LLM (qwen3.5-35b) and the Brain (Claude Opus/Sonnet) differ dramatically in reasoning capability. Tasks that are straightforward for the Brain — synthesizing conflicting evidence across 30 claims, detecting subtle contradictions between a new finding and a months-old hypothesis, judging whether a cluster of mixed evidence should be classified as "moderate" or "contested," re-framing an entire sub-graph of knowledge after a decision overturning — are where the local LLM produces mediocre results or fails outright.

Currently, RKA uses only the local LLM for all enrichment. This wastes the Brain's intelligence — the Brain only reads RKA data (via `rka_get_context`) and writes conclusions (via `rka_add_note`, `rka_add_decision`). It never directly improves the distilled knowledge layer.

### 19.2 Tiered Enrichment Architecture

Split enrichment into two tiers based on task complexity:

| Tier | Handled by | When it runs | Tasks |
|------|-----------|-------------|-------|
| **Tier 1: Routine** | Local LLM (qwen3.5-35b) | Always, background worker | Auto-tag, basic claim extraction, embedding, simple classification, FTS5 indexing |
| **Tier 2: Deep reasoning** | Brain (Claude) | During active sessions, on request | Cluster synthesis, contradiction resolution, gap analysis, evidence evaluation, knowledge restructuring, cross-entity reasoning |

Tier 1 runs 24/7 via the background worker — it's the always-on enrichment that keeps the knowledge base minimally organized. Tier 2 runs when the Brain is present and either the PI explicitly requests it or the Brain proactively processes the review queue during session start.

### 19.3 The Review Queue

RKA maintains a review queue of items that need Brain-level attention. The local LLM populates this queue when it encounters tasks beyond its capability:

| Flag | When raised | What needs Brain attention |
|------|-----------|--------------------------|
| `low_confidence_cluster` | Local LLM assigns cluster confidence < 0.4 | Brain should evaluate the cluster and set a definitive confidence |
| `potential_contradiction` | Local LLM detects possible conflict but isn't sure | Brain should determine whether the contradiction is real or a misinterpretation |
| `complex_synthesis_needed` | Cluster has 10+ claims from 5+ sources | Brain should write a proper synthesis — too complex for local LLM |
| `re_distill_review` | Decision was overturned, claims re-extracted | Brain should verify the re-extraction quality and approve new clustering |
| `cross_topic_link` | Local LLM suspects two topics are related but can't articulate how | Brain should evaluate and create explicit cross-references |
| `stale_theme` | Theme synthesis hasn't been updated despite new claims | Brain should re-synthesize with full reasoning |

The queue is stored as a table:

```sql
CREATE TABLE IF NOT EXISTS review_queue (
    id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,          -- entity type needing review
    item_id TEXT NOT NULL,            -- entity ID
    flag TEXT NOT NULL,               -- one of the flags above
    context TEXT,                     -- JSON: what the local LLM noticed
    priority INTEGER DEFAULT 100,    -- lower = higher priority
    status TEXT DEFAULT 'pending'
        CHECK (status IN ('pending', 'acknowledged', 'resolved', 'dismissed')),
    raised_by TEXT DEFAULT 'llm',    -- who flagged this
    resolved_by TEXT,                -- brain | pi
    resolution TEXT,                 -- what was decided
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    resolved_at TEXT
);
```

### 19.4 New MCP Tools for Brain Enrichment

**rka_get_review_queue** — Brain calls this at session start (or PI requests it) to see what needs attention:

```
rka_get_review_queue(status: str = "pending", limit: int = 20) → list of flagged items
```

Returns items sorted by priority with enough context for the Brain to act.

**rka_review_cluster** — Brain evaluates a cluster and writes back its assessment:

```
rka_review_cluster(
    cluster_id: str,
    confidence: str,            -- Brain's assessed confidence
    synthesis: str,             -- Brain's written synthesis (replaces local LLM's)
    gaps: list[str],            -- Brain-identified evidence gaps
    contradictions: list[str],  -- Brain-confirmed contradictions
    resolve_queue_items: list[str]  -- review queue item IDs to mark resolved
)
```

**rka_review_claims** — Brain reviews extracted claims for an entry and corrects them:

```
rka_review_claims(
    entry_id: str,
    corrections: list[{claim_id, action, new_content?, new_type?, new_confidence?}]
    # action: "approve" | "edit" | "delete" | "split" | "merge"
)
```

**rka_synthesize_topic** — Brain produces a deep synthesis of a topic or research question, far better than local LLM:

```
rka_synthesize_topic(
    topic_or_rq_id: str,
    depth: str = "comprehensive",   -- "brief" | "comprehensive"
    include_recommendations: bool = True
) → stores synthesis in cluster/theme, returns to Brain
```

**rka_evaluate_evidence** — Brain evaluates the overall evidence state and identifies the most important gaps:

```
rka_evaluate_evidence(
    scope: str = "project",    -- "project" | "topic" | "cluster"
    scope_id: str | None = None
) → structured assessment with prioritized next steps
```

**rka_resolve_contradiction** — Brain resolves a flagged contradiction by determining which claim is correct, or whether both are valid under different conditions:

```
rka_resolve_contradiction(
    claim_ids: list[str],       -- the conflicting claims
    resolution: str,            -- Brain's analysis
    outcome: str,               -- "claim_a_correct" | "claim_b_correct" | "both_valid_conditional" | "insufficient_evidence"
    update_confidences: dict    -- {claim_id: new_confidence}
)
```

### 19.5 Brain Session Protocol Update

The Brain and Executor orientation prompts should be updated to include the review queue in the session start protocol:

**Brain session start (updated):**
1. `rka_get_status()` — project state
2. `rka_get_context()` — active knowledge
3. `rka_get_checkpoints(status="open")` — Executor blockers
4. **`rka_get_review_queue()` — items flagged for Brain attention** ← NEW

The Brain should process high-priority review queue items before starting new work. This is the "deep enrichment pass" that happens every session — the Brain reviews what the local LLM flagged, corrects cluster syntheses, resolves contradictions, and approves re-distilled knowledge.

### 19.6 PI-Triggered Brain Enrichment

The PI can explicitly request Brain-level enrichment through the web UI or by asking the Brain directly:

- "Brain, please review the evidence clusters for RQ1 and tell me what we're missing"
- "Brain, the Executor's latest findings seem to contradict our earlier decision — please evaluate"
- "Brain, synthesize everything we know about MQTT scalability into a coherent narrative"

These map to the MCP tools above. The PI doesn't need to know the tool names — they describe what they want and the Brain translates it into the appropriate tool calls.

### 19.7 What the Brain Does Better Than the Local LLM

| Task | Local LLM quality | Brain quality | Why |
|------|-------------------|---------------|-----|
| Auto-tagging | Good (80%+ accuracy) | Overkill | Well-defined, pattern-based |
| Basic claim extraction | Good for simple entries | Better for complex methods sections | Brain understands nuanced methodology |
| Embedding | N/A (nomic handles this) | N/A | Not an LLM task |
| Cluster synthesis | Mediocre (generic paragraphs) | Excellent (nuanced, identifies subtlety) | Requires cross-document reasoning |
| Contradiction detection | High false-positive rate | Low false-positive rate | Requires understanding context and conditions |
| Gap analysis | Finds obvious gaps | Finds subtle gaps + suggests what to investigate | Requires domain understanding |
| Re-framing after decision change | Mechanical re-extraction | Understands how the new framing changes interpretation | Requires reasoning about implications |
| Cross-topic connections | Misses most connections | Identifies non-obvious relationships | Requires broad pattern matching |
| Evidence evaluation | Binary (strong/weak) | Nuanced (strong for X, weak for Y, need Z to confirm) | Requires judgment |

### 19.8 Design Principles for Brain-Augmented Enrichment

1. **Local LLM is the floor, Brain is the ceiling.** The knowledge base should be useful even if the Brain never does an enrichment pass. Local LLM keeps everything minimally organized. Brain elevates it to high quality.

2. **Brain enrichment is additive, not destructive.** The Brain refines cluster syntheses, adjusts confidences, and resolves contradictions — it doesn't delete or restructure the raw data layer.

3. **Every Brain enrichment is attributed.** When the Brain writes a cluster synthesis, it's marked `synthesized_by: brain` (vs `synthesized_by: llm`). The research map can show which syntheses are Brain-verified and which are local-LLM-generated.

4. **The review queue is a priority system, not a blocker.** Pending review items don't prevent the research map from displaying. They're visual flags — the map shows local-LLM-quality content with an indicator that Brain review is available.

5. **The PI controls when Brain enrichment happens.** The Brain doesn't autonomously start reviewing clusters. It either processes the queue when the PI starts a session, or the PI explicitly asks for review. This keeps the human in the loop.

---

## 20. Conclusion

RKA v2.0 transforms the system from a passive research bookkeeper into an active knowledge builder through four fundamental shifts:

**Shift 1: The LLM's job changes.** It no longer just tags entries after creation. It continuously builds a higher-level representation — extracting claims, grouping them into evidence clusters, synthesizing themes, and detecting contradictions and gaps. Raw journal entries are the data lake. Claims, clusters, and themes are the warehouse. The research map reads the warehouse.

**Shift 2: Data and interpretation are cleanly separated.** Raw records are immutable and survive any reinterpretation. Derived structures (claims, clusters, themes, topics) are mutable views that rebuild when the framing changes. This means the Brain can overturn any decision and the knowledge graph restructures automatically, while no raw evidence is ever lost.

**Shift 3: Every entity knows why it exists.** Cross-references form complete provenance chains: literature informs decisions, decisions motivate missions, missions produce findings, findings justify new decisions. The Brain can trace any claim back to its origins and any decision forward to its consequences. This transforms the knowledge graph from a collection of loosely tagged artifacts into a navigable reasoning chain.

**Shift 4: Intelligence is applied where it matters most.** The local LLM handles the 80% of routine enrichment work — always on, always running, keeping the knowledge base organized. But the hard 20% — nuanced synthesis, contradiction resolution, evidence evaluation, knowledge restructuring — waits for the Brain's superior reasoning. The review queue bridges the gap: the local LLM flags what it can't handle, and the Brain processes the queue during sessions. This gives the best of both: continuous background enrichment plus periodic deep reasoning passes.

The entity type simplification (9 types → 3 record types + 6 claim types) is the bridge between these shifts: it acknowledges that humans should classify *records* (note, log, directive — obvious, mutually exclusive), while the LLM should classify *knowledge* (hypothesis, evidence, method, result — semantic, potentially overlapping within a single record).

All changes are incremental and backward-compatible. The implementation spans 10 weeks across 6 phases. The architecture maintains RKA's core philosophy: the system is a bookkeeper and message transmitter that makes the Brain/Executor/PI workflow more effective, not an autonomous agent that replaces human judgment.
