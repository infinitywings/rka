# Phase O — Project Onboarding (full design)

Status: **design only**. Implementation deferred. Supersedes
`phase-d-onboarding-design.md`'s scope by **wrapping** the existing
Phase D MVP — Phase D's tool-setup subgraph becomes Phase O's
sub-phase **O5**.

## Goal

Take a PI from "I have a research idea" to "the orchestrator can run
autonomously against a ratified plan" through a structured but
pause-able workflow. Phase O is the place to spend human attention
because everything downstream (mission execution) is autonomous.

## PI-ratified design choices (this session)

| # | Choice |
|---|---|
| Workspace root | `~/Research/{project-slug}/` — PI picks slug at idea-capture; orchestrator refuses if dir exists |
| Polished idea + plan structure | **Highly structured** — dataclasses with explicit fields, not freeform prose |
| Mission execution autonomy | **Per-phase acked** — orchestrator queues missions, PI Y/N before each phase boundary |
| Document/diagram ingestion | PI summarizes each source in chat; one `rka_add_note(source='pi', tags=[project_id, 'ingested-source'])` per source; orchestrator queries by tag |
| Tool setup placement | After plan synthesis (O5), not before — so Brain knows the RQ when recommending tools |
| Deep research feedback | Option (a) — PI ingests in-session via `rka_*` tools; orchestrator queries journals tagged with the project |

Carry-forward from Phase D (still valid):
| # | Choice |
|---|---|
| Manifest lifecycle | Hybrid: baseline frozen + per-mission extensions |
| Credential criticality | required / recommended / optional tiers |
| Curated tool registry | ~10-15 entries + SerpAPI augmentation (deferred D3b) |
| Auth patterns in MVP | API key only; OAuth/Keychain in Phase D2 |
| Audit entry | Summary journal entry with manifest hash + supersedes chain |

## Sub-phase decomposition

```
O1 — Idea Capture & Scope                          [3 nodes, 2 interrupts]
   capture_idea
     ↓                                  ┌─ doc-attached path:
   pi_idea_capture (free-form)          │  PI summarizes each source via rka_add_note
     ↓                                  │  before continuing
   idea_polish (Brain)                  │
     ↓                                  │
   pi_scope_ratify (TWO-TAP)            │
   ──────────────────────────────────────┘ END Phase O1 ─ PI may pause here

O2 — Workspace + Deep Research (async pause)       [2 nodes, 2 interrupts]
   workspace_setup
     ↓
   pi_deepresearch_prompt (long pause expected)
     ↓                ← PI works in Claude Desktop's Deep Research; ingests via rka_* tools
   pi_research_complete (PI signals back)
   ──────────────────────────────────────  END Phase O2

O3 — Hygiene + Claim Extraction                    [3 nodes, 1 interrupt]
   hygiene_pass (Brain: rka_check_integrity + rka_check_freshness)
     ↓
   claim_extraction (Brain: rka_extract_claims over project journals)
     ↓
   pi_claims_review (TWO-TAP — claims become provenance for the plan)
   ──────────────────────────────────────  END Phase O3

O4 — Plan Synthesis + Ratification                 [2 nodes, 1 interrupt]
   plan_synthesis (Brain: reads everything in RKA + produces ResearchPlan dataclass)
     ↓
   pi_plan_ratify (TWO-TAP — THE contract licensing autonomy)
   ──────────────────────────────────────  END Phase O4

O5 — Tool Setup (current Phase D, repositioned)    [6 nodes, 3 interrupts]
   research_toolkit (now reads ratified plan instead of pi_onboarding_topic)
     ↓
   pi_toolkit_ratify (TWO-TAP)
     ↓
   draft_manifest (writes ~/Research/{slug}/.rka/tools.json)
     ↓
   pi_credentials_ready (PI edits .env)
     ↓
   finalize (probe + audit journal)
   ──────────────────────────────────────  END Phase O5 — autonomy licensed

H  — Mission Queue Handoff                         [1 node, N interrupts]
   For each milestone in plan.milestones:
     pi_phase_entry_ack (per-phase Y/N — costs + ETA shown)
       ↓ on Y
     start_run(mission_id) ← spawns mission subgraph (Phase A)
       ↓ mission completes (terminal_state)
     loop to next milestone
   ──────────────────────────────────────  Project execution done
```

**6 sub-phases × natural pause points = each one is a separately
testable, independently replayable unit.** PI re-enters via
`orchestrator_continue_onboarding(project_id)` (new MCP tool) between
phases.

## Schemas (locked dataclasses)

### `ProjectSlug` — workspace identity

```python
@dataclass
class ProjectSlug:
    slug: str  # kebab-case, [a-z0-9-], 3-40 chars
    rka_project_id: str  # prj_…
    workspace_root: Path  # ~/Research/{slug}/

    @classmethod
    def derive_from_name(cls, rka_project_name: str) -> str:
        """Auto-generate slug from RKA project name. PI can override."""
        # "IoT Edge LLM Hosting (MLSys 2026)" → "iot-edge-llm-hosting-mlsys-2026"
        ...
```

### `IngestedSource` — what `pi_idea_capture` writes

```python
@dataclass
class IngestedSource:
    """One source the PI brought into the project at idea-capture time.
    The PI summarized it; orchestrator stored the summary.
    """
    rka_journal_id: str          # the jrn_… that holds the summary
    source_kind: Literal["text", "pdf", "diagram", "url", "doc"]
    title: Optional[str]
    summary: str                 # 2-3 sentences PI wrote
    extracted_claims: list[str]  # bullet-point claims PI extracted
    pi_attachment_ref: Optional[str]  # path to original if pasted to disk
```

### `PolishedIdea` — what `idea_polish` writes (output of O1)

```python
@dataclass
class PolishedIdea:
    research_question: str       # one-sentence RQ
    motivation: str              # 1-paragraph why this matters
    scope: str                   # what's in vs out
    target_venue: Optional[str]  # "MLSys 2026" etc.
    novelty_hypothesis: str      # what the project claims is new
    ingested_sources: list[str]  # journal IDs from pi_idea_capture
    open_assumptions: list[str]  # things PI should validate before O4
```

The polished idea lands as a structured journal entry
(`type=note, source=brain, tags=[project_id, 'polished-idea']`) for the
plan_synthesis step to read later.

### `ResearchPlan` — what `plan_synthesis` writes (output of O4; **THE contract**)

```python
@dataclass
class HypothesisSpec:
    statement: str
    falsifier: str   # what would refute it
    confidence: Literal["high", "medium", "low"]

@dataclass
class VariableSpec:
    name: str
    kind: Literal["independent", "dependent", "confound"]
    description: str
    measurement: Optional[str]   # how it's measured

@dataclass
class MissionMilestone:
    """One executable mission the orchestrator will dispatch in Phase H."""
    milestone_id: str            # m_01, m_02, … (auto-generated)
    phase: str                   # "literature" | "research_design" | "experiment_design" | …
    objective: str               # passed to rka_create_mission as objective
    acceptance_criteria: str
    scope_boundaries: str
    depends_on_milestone: Optional[str]
    estimated_llm_cost_usd: float
    estimated_wall_clock_min: int

@dataclass
class ResearchPlan:
    refined_research_question: str
    hypotheses: list[HypothesisSpec]
    variables: list[VariableSpec]
    experimental_matrix: str     # markdown table or structured description
    literature_gaps: list[str]
    milestones: list[MissionMilestone]
    open_risks: list[str]
    polished_idea_journal_id: str  # backlink to O1's output
```

The ratified plan lands as TWO RKA artifacts:
1. A journal entry (`type=note, source=brain, tags=[project_id, 'ratified-plan']`) containing the full structured plan as JSON.
2. A `rka_add_decision` recording that the PI ratified this plan (decision content = `f"Ratified plan v1 of project {project_id}"`, related_journal = [plan_journal_id]).

Each `MissionMilestone` will be materialized into an RKA mission via
`rka_create_mission` at Phase H startup — that's where the autonomy
hands off.

## Node specs

### O1: capture_idea

**Inputs (state):** `project_id` only (project must already exist; created
by `orchestrator_onboard_start` itself).
**Outputs (state):** nothing (this is just a pass-through that sets up
the interrupt payload).
**LLM call:** none.

The orchestrator pre-loads context: what's in the project today
(should be empty for a fresh project; surfaces any existing entries
if PI is onboarding a partially-populated project).

### O1: `pi_idea_capture` (interrupt)

**Payload:**
```jsonc
{
  "type": "pi_idea_capture",
  "title": "PI idea capture",
  "prompt": "Describe the research project — paste text, summarize attached docs, drop diagrams (you'll summarize them next).\n\nWhile in this session, for each document/diagram/URL you want to bring in:\n  1. Read or view it (in Claude Desktop's chat)\n  2. Summarize in 2-3 sentences\n  3. Extract concrete claims as bullets\n  4. Call rka_add_note(content=<summary+claims>, source='pi', type='note', tags=['<project_id>', 'ingested-source'])\n\nWhen all sources are ingested AND you've described the project, accept this interrupt.",
  "expected_response": "free-form text describing the project; orchestrator parses for the next node"
}
```

**Response semantics:** PI's `orchestrator_correct(interrupt_id, response_text=<idea>)` carries the project description. PI's `orchestrator_accept(interrupt_id)` alone means "I just used the chat to describe + ingest; no extra text". Either path proceeds.

**TWO-TAP:** no — capture is low-stakes; ratification happens at O1's `pi_scope_ratify`.

### O1: `idea_polish` (Brain node)

**Inputs:** PI's idea text from the interrupt response + all journals tagged `ingested-source` since project creation.
**Outputs:** `state["polished_idea"]` (PolishedIdea dataclass dict).
**LLM call:** Brain composes the polished idea per the dataclass schema; emits structured JSON the way `mission_execute` emits `proposed_actions`. Parse failures yield ErrorRecord + retry once.
**Writes to RKA:** one `rka_add_note(content=<json-of-polished-idea>, type='note', source='brain', tags=[project_id, 'polished-idea'])`.

### O1: `pi_scope_ratify` (interrupt, TWO-TAP)

**Payload:** the polished idea rendered as markdown sections (research_question / motivation / scope / venue / novelty / open_assumptions). The interrupt's `items` list carries the structured PolishedIdea.

**TWO-TAP:**
1. PI picks Accept | Reject | Correct.
2. If Accept: "Confirm the polished scope locks the project's framing? You can still extend in later phases but this is the foundation."

**On accept:** state["scope_ratified"] = True; advance to O2.
**On reject/correct:** loops back to capture_idea with the redirection text in state.

---

### O2: workspace_setup

**Inputs:** state.project_slug (from PI's response in O1 — Brain extracts it from the polished_idea + asks PI if ambiguous).
**Outputs:** state["workspace_path"] (absolute path).
**Side effects:**
- Creates `~/Research/{slug}/` with mode 0700
- Creates subdirs: `data/`, `code/`, `notebooks/`, `manuscripts/`, `results/`, `.rka/`
- Writes `.rka/project_id` (single line: the prj_… ID)
- Writes `.rka/workspace.json` (phase status, schema version)
- Refuses if `~/Research/{slug}/` already exists with mode-bits / non-empty — emits a checkpoint with a clear error.

### O2: `pi_deepresearch_prompt` (interrupt — **async pause**)

**Payload:**
```jsonc
{
  "type": "pi_deepresearch_prompt",
  "title": "Deep Research (async)",
  "prompt": "Time to bring in SOTA literature + related work. In Claude Desktop:\n  1. Use Deep Research / web search / arxiv to scan the literature.\n  2. For each useful paper, call rka_enrich_doi(doi=...) or rka_add_literature(title=..., source='deep-research') — tag with ['<project_id>', 'literature']. The orchestrator will discover what you added by querying tags.\n  3. For broader insights / framing, use rka_add_note with tag 'deep-research-finding'.\n\nWhen you're done (≥5 papers is a reasonable floor), accept this interrupt. Reject to abandon the project.",
  "minimum_paper_floor_suggestion": 5,
  "tag_to_query": [project_id, "literature"]
}
```

**Critical async pattern:** the orchestrator parks here indefinitely. PI can close Claude Desktop, come back hours/days later, accept. The runner doesn't care about elapsed time.

**On accept:** state["deepresearch_complete"] = True; orchestrator queries `rka_get_journal(tags=[project_id, 'literature'])` to get the count + IDs. If count < 3, surface a soft warning before O3 but proceed.

### O2: `pi_research_complete` 

Same node spec as `pi_deepresearch_prompt`'s `accept` handler — actually this is just the resume of `pi_deepresearch_prompt`. No separate interrupt; the resume IS the completion signal.

---

### O3: hygiene_pass (Brain node)

**LLM call:** Brain calls (via mcp client):
- `rka_check_integrity(project_id)` — flags orphan refs, missing provenance
- `rka_check_freshness(project_id)` — flags stale entries
- `rka_get_pending_maintenance(project_id)` — discovers any auto-flagged maintenance items

**Writes to state:** `state["hygiene_findings"]` (list of dicts: {kind, target_id, detail}).
**Writes to RKA:** if any required maintenance items, surfaces them via the existing checkpoint mechanism so PI can resolve before O4.

### O3: claim_extraction (Brain node)

**LLM call:** Brain reads all journals tagged `polished-idea`, `ingested-source`, `literature`, `deep-research-finding`, then calls `rka_extract_claims(...)` for each (which has a Phase 2.x existing implementation). Result: structured claims linked back to journal IDs.
**Writes to RKA:** uses existing `rka_extract_claims` (a WRITE_TOOL).
**State:** `state["claim_ids"]` (list of clm_… IDs).

### O3: pi_claims_review (interrupt, TWO-TAP)

**Payload:** structured rendering of every claim with provenance. PI can mark each as kept / rejected / needs-revision (via the orchestrator_correct freeform path).
**On accept:** Phase O3 closes; claims become the inputs to O4's plan synthesis.

---

### O4: plan_synthesis (Brain node)

**LLM call:** Brain reads:
- The polished idea (journal tagged `polished-idea`)
- All ingested sources
- All literature
- All extracted claims
- All deep-research findings

Brain produces a `ResearchPlan` dataclass instance as structured JSON. The prompt enforces the exact schema (with a regex-validated `milestone_id` pattern, valid `phase` enum, etc.). Parse failure → ErrorRecord, retry once with explicit correction guidance, then escalate.

**Writes to RKA:** the plan as a journal entry (`tags=[project_id, 'ratified-plan-draft']`).

### O4: pi_plan_ratify (interrupt, TWO-TAP — **THE contract gate**)

**Payload:** Brain's full ResearchPlan rendered as markdown:
```
## Refined RQ
{plan.refined_research_question}

## Hypotheses (3)
1. {h.statement} — falsifier: {h.falsifier}
2. ...

## Variables
| name | kind | description |
...

## Experimental matrix
{plan.experimental_matrix}

## Literature gaps
- {gap[0]}
- ...

## Mission queue (N milestones, total estimated cost $X, total ETA Y hours)
| milestone_id | phase | objective | depends_on | cost | wall-clock |
| m_01 | literature | … | — | $0.50 | 30m |
| m_02 | research_design | … | m_01 | $1.20 | 45m |
...

## Open risks
...
```

**TWO-TAP:** 
1. PI picks Accept | Reject | Correct.
2. If Accept: "**Authorize the orchestrator to dispatch this N-milestone mission queue with the listed cost + ETA estimates? Per-phase acknowledgment will still apply for each milestone.**" Yes / No.

**On accept:**
- The plan moves to the ratified state: journal entry retagged from `ratified-plan-draft` → `ratified-plan`.
- A `rka_add_decision` records the ratification with the plan journal as `related_journal`.
- Each milestone is materialized via `rka_create_mission(objective=..., motivated_by_decision=<ratification_decision_id>, depends_on=...)` — this creates the actual mission chain.
- `state["ratified_plan_decision_id"]` and `state["ratified_mission_ids"]` are populated.

---

### O5: Tool Setup (current Phase D, repositioned)

Same as today, with two changes:
1. `research_toolkit_node` reads `state["ratified_plan_decision_id"]` instead of `state["topic_metadata"]`. Loads the plan JSON, extracts the topic + literature gaps + experimental phases. Brain reasons about which tools the milestones need (e.g., a milestone mentioning "fine-tune a 1B model" → suggest huggingface-mcp + wandb-mcp).
2. Manifest path: `~/Research/{slug}/.rka/tools.json` (was `~/rka-projects/{id}/tools.json`).

---

### H: Mission Queue Handoff

**New node:** `pi_phase_entry_ack` — surfaces the next milestone:

```jsonc
{
  "type": "pi_phase_entry_ack",
  "title": "Ready to start next mission?",
  "milestone": {
    "milestone_id": "m_02",
    "phase": "research_design",
    "objective": "...",
    "estimated_cost_usd": 1.20,
    "estimated_wall_clock_min": 45,
    "depends_on_complete": true
  },
  "remaining_milestones": 6,
  "total_remaining_cost_usd": 8.50,
  "total_remaining_wall_clock_min": 320
}
```

**Response:**
- accept → `orchestrator_run_start(mission_id=<this milestone's mis_…>)`; mission runs through its 16-node Phase A subgraph; terminal output captured; loop back for next milestone.
- reject → pause the queue; PI can resume later via `orchestrator_continue_plan(project_id)`.
- correct → freeform redirect; e.g., "skip m_03 and m_04, go straight to m_05" — orchestrator re-orders queue.

## Repo boundary (critical)

**Project-specific content lives at `~/Research/{slug}/`, NEVER inside
the rka repo.** The orchestrator creates the workspace at runtime in
the PI's home dir; the rka repo only contains the *templates and
scaffolding* (the orchestrator code that knows how to create the
workspace, and the Writer skill's `workspace-template/` from v2.5.12).

What the rka repo holds re: this feature:
- `orchestrator/orchestrator/workspace.py` — module with ProjectSlug + slug-validation + workspace-creation helpers (code that runs against the user's `~/`, not data that lives in the repo)
- `orchestrator/orchestrator/manifest.py` — schema + IO for `.rka/tools.json` (code, not data)
- `orchestrator/orchestrator/nodes/onboarding.py` — graph nodes (code)
- `orchestrator/docs/phase-o-project-onboarding-design.md` — this design doc (no project data)
- `plugin/skills/orchestrator-pi/SKILL.md` — rendering rules (no project data)
- `plugin/skills/writer/workspace-template/` — Writer's scaffold (TEMPLATE, never specific to a project)

What the rka repo does NOT hold:
- ❌ `~/Research/{slug}/data/` — PI's research data
- ❌ `~/Research/{slug}/code/` — PI's research code
- ❌ `~/Research/{slug}/notebooks/` — PI's exploratory work
- ❌ `~/Research/{slug}/results/` — experiment outputs
- ❌ `~/Research/{slug}/manuscripts/` — PI's manuscript drafts (the Writer skill's *template* is in the repo; PI's actual drafts go in their workspace)
- ❌ `~/Research/{slug}/.rka/tools.json` — per-project tool manifest (template structure is in the repo; actual filled-in manifests are per-PI per-project)
- ❌ `~/Research/{slug}/.rka/.env` — credentials (file-mode 0600, gitignored at the workspace level; never in the rka repo regardless)

The `.rka/.gitignore` *inside the workspace* (auto-generated by
workspace_setup) keeps the PI from accidentally pushing their own
project's credentials to whatever git repo THEY make in
`~/Research/{slug}/`. That's separate from the rka repo's own
`.gitignore`, which doesn't need any new entries because the
workspace path is in the PI's home, not under the rka repo's tree.

## Workspace layout (canonical, locked)

```
~/Research/iot-edge-llm/
├── .rka/
│   ├── project_id           # one line: prj_…
│   ├── workspace.json       # phase status, hashes, last-onboard ts
│   ├── tools.json           # Phase D manifest (baseline)
│   ├── extension_*.json     # per-mission extensions (Q1 hybrid)
│   └── .env                 # mode 0600, gitignored
├── data/                    # research datasets (Executor mission outputs)
├── code/                    # implementation (PI-written; Executor can't write yet)
├── notebooks/               # exploratory analysis
├── manuscripts/{venue}/     # Writer skill workspace (per existing Phase v2.5.12)
├── results/                 # experiment outputs
├── README.md                # auto-generated; describes the project's plan
└── .gitignore               # auto: .rka/.env, results/, etc.
```

## State additions to ResearchWorkflowState

```python
# Phase O additions (TypedDict total=False; back-compat for pre-Phase-O states)
project_slug: str
workspace_path: str
ingested_source_ids: list[str]           # journal IDs from O1
polished_idea: dict                       # PolishedIdea as dict (from idea_polish)
scope_ratified: bool
deepresearch_complete: bool
hygiene_findings: list[dict]
claim_ids: list[str]
ratified_plan_decision_id: str           # the dec_… from O4 ratification
ratified_plan_journal_id: str            # the jrn_… with the plan content
ratified_mission_ids: list[str]          # mis_… for each milestone (auto-created)
current_milestone_index: int             # index into ratified_mission_ids during Phase H
```

## Migration from Phase D MVP

Phase D MVP's `pi_onboarding_topic` interrupt is **deleted** — it's
subsumed by `pi_idea_capture`. `research_toolkit_node` is **repositioned**
into O5 with the plan-reading change. `~/rka-projects/{id}/` is
**deprecated**; the orchestrator looks at `~/Research/{slug}/.rka/` and
falls back to `~/rka-projects/{id}/` only when a back-compat shim is
needed (PI's existing test projects from this session).

Migration helper:
```python
def migrate_phase_d_workspace_to_phase_o(project_id, new_slug):
    """One-shot helper to move ~/rka-projects/{id}/ → ~/Research/{slug}/.rka/.
    Called by an `orchestrator_migrate_workspace` MCP tool."""
```

## Build order (sub-tasks with effort estimates)

| Task | Effort | Notes |
|---|---|---|
| **O0** — State schema additions + workspace layout module (new `workspace.py`) | 0.75 day | Includes ProjectSlug dataclass + slug validation + migrate helper |
| **O1.1** — capture_idea + pi_idea_capture nodes | 0.5 day | Free-form interrupt + idea-text extraction from response |
| **O1.2** — idea_polish Brain node + structured JSON parsing | 1 day | Brain prompt + PolishedIdea dataclass + parse retry logic |
| **O1.3** — pi_scope_ratify interrupt + TWO-TAP routing | 0.5 day | Mirrors pi_decision_select's set-identity pattern |
| **O2.1** — workspace_setup node + dir creation + .rka/ scaffold | 0.5 day | Includes "refuse if exists" + checkpoint emit |
| **O2.2** — pi_deepresearch_prompt + pi_research_complete (async pause) | 1 day | New "async pause" pattern; orchestrator queries by tag on resume |
| **O3.1** — hygiene_pass (calls existing rka_check_*) | 0.5 day | Mostly orchestration; the actual checks exist in RKA |
| **O3.2** — claim_extraction (Brain over journals) | 0.75 day | Uses rka_extract_claims; new state field; pi_claims_review interrupt |
| **O4.1** — plan_synthesis Brain node + ResearchPlan dataclass | 1.5 days | Largest LLM work; structured prompt + dataclass parsing |
| **O4.2** — pi_plan_ratify TWO-TAP + auto-create missions | 1 day | The contract gate; auto-creates milestones via rka_create_mission |
| **O5** — Reposition existing Phase D (research_toolkit reads ratified plan) | 0.5 day | Refactor only; tests carry over |
| **H** — pi_phase_entry_ack + mission-queue runner extension | 1.5 days | Loop pattern; cost + ETA aggregation; orchestrator_continue_plan |
| **Workspace unification refactor** | 0.5 day | Move tools.json/.env from `~/rka-projects/{id}/` to `~/Research/{slug}/.rka/` |
| **Skill + slash command rewrite** | 0.75 day | orchestrator-pi skill picks up the 5+1 sub-phases; new /orchestrator-onboard-continue, /orchestrator-plan-status commands |
| **New MCP tools** | 0.5 day | orchestrator_continue_onboarding, orchestrator_get_plan_status, orchestrator_continue_plan, orchestrator_migrate_workspace |
| **Integration tests (E2E walks for each sub-phase)** | 1.5 days | Scripted-graph fakes per sub-phase + one full-chain walk |
| **CHANGELOG + release notes** | 0.25 day | |
| **Total** | **~13.5 days** | |

## Tests + invariants

- Every new node + interrupt gets a unit test for state shape, error
  modes, and (where applicable) prompt content.
- Every new PI interrupt joins `parked_store.InterruptType` literal
  + the schema CHECK constraint.
- Every new node name joins `ONBOARDING_NODE_NAMES` so audit-symmetry
  invariant holds.
- The **workspace unification migration** gets a test that walks the
  Phase D `~/rka-projects/{id}/tools.json` shape to the Phase O
  `~/Research/{slug}/.rka/tools.json` shape and verifies the result
  loads cleanly.
- The **async pause pattern** gets a regression test: start O2 → park
  → simulate hours-long gap (the runner doesn't actually need to sleep;
  the test just verifies the parked state survives a process restart
  via the SqliteSaver).
- **The Phase-2.4 v1 response-token regression** is verified for ALL
  new interrupt types in `_ACCEPT_TOKEN_BY_TYPE`. Currently 7 entries
  (Phase A + D); Phase O adds 6 more.

## Open design questions (3 — should be resolvable in passing)

1. **What does "Brain reads the polished idea + asks PI if slug ambiguous" actually do?**  
   In O2's workspace_setup, the slug needs to be derived. Options:
   (a) Brain proposes; PI confirms with single-tap; (b) PI provides
   slug as part of pi_idea_capture response (mixed with the idea text;
   Brain extracts); (c) Brain auto-generates without asking.
   I lean **(a) — Brain proposes, PI confirms** because the slug is
   a persistent filesystem path the PI will see often. Worth one
   small interrupt.

2. **What's the cost-estimation method for `MissionMilestone.estimated_llm_cost_usd`?**  
   Brain's a priori estimate during plan_synthesis is unreliable.
   We could use a simple heuristic (e.g., `tasks × 0.30` per mission)
   or have Brain provide a confidence interval. For Phase O MVP I'd
   ship the heuristic + display it as "estimated, actual will vary".

3. **What happens if the PI walks away mid-plan-synthesis?**  
   Brain's plan_synthesis call could take 2-5 min of LLM work. If the
   PI closes Claude Desktop, the orchestrator's runner is still busy.
   This already works for mission graph nodes (they complete in the
   background and the next interrupt parks). Same pattern applies
   here. No new design needed — but the orchestrator-pi skill should
   tell the PI "this step may take a few minutes; you can switch away
   and come back."

## Versioning

After Phase O ships: bump plugin version from `1.2.0` (current) →
`1.3.0` (Phase O onboarding wizard surfaces). RKA core stays on
whatever main is. Orchestrator package internal version stays at
`0.1.0` until we tag a release.

## Cross-cutting impact

Phase O affects:
- `state.py` — 11 new fields on ResearchWorkflowState
- `manifest.py` — manifest path now relative to workspace root, not `~/rka-projects/{id}/`
- `parked_store.py` — 6 new interrupt types in the CHECK constraint (already has migration helper from D1; extend)
- `graph.py` — ONBOARDING_NODE_NAMES expanded by 6+
- `runner.py` — `_ONBOARDING_INTERRUPT_TYPES` expanded; new `start_phase_h` entry point for mission queue
- `nodes/onboarding.py` — 9 new nodes
- `nodes/pi.py` — 7 new PI interrupt nodes (including pi_idea_capture, pi_scope_ratify, pi_deepresearch_prompt, pi_claims_review, pi_plan_ratify, pi_phase_entry_ack, pi_extend_toolkit from deferred D6)
- `onboarding_graph.py` — restructured into 5 sub-graph compose functions
- `server.py` — 4 new endpoints: `/onboard/continue`, `/plan/{id}/status`, `/plan/{id}/continue`, `/projects/{id}/migrate`
- `mcp_server.py` — 4 new MCP tools wrapping above
- `plugin/skills/orchestrator-pi/SKILL.md` — extensive update for 6 sub-phases
- `plugin/commands/` — `/orchestrator-onboard-continue`, `/orchestrator-plan-status` added

Phase O does NOT depend on:
- Phase D6 (pi_extend_toolkit) — orthogonal; could land before or after
- Phase D3b (SerpAPI augmentation) — orthogonal; could land before or after
- Phase E (capability categories) — natural next step AFTER Phase O lands

## Cross-link

See [`../../docs/archive/2026-q2/orchestrator/phase-d-onboarding-design.md`](../../docs/archive/2026-q2/orchestrator/phase-d-onboarding-design.md)
for the archived Phase D MVP design that becomes O5 (folded ratification
history inlined in the appendix below).
See [[project-branch-model]] for the agentic-vs-main relationship that
makes this all Phase O scope land on agentic only.

## Appendix: Phase D ratified-design-question history (folded from phase-d-onboarding-design.md, archived 2026-06-02)

The Phase D onboarding wizard was designed and PI-ratified before being
implemented as Phase D MVP (now O5 in this Phase O design). The five
design questions Q1-Q5 were resolved in a single session and bound the
implementation scope; their rationale is preserved here so Phase O can
build on them without re-litigating.

| Question | Choice |
|---|---|
| Q1 — Onboarding lifecycle | **Hybrid**: baseline manifest is frozen after initial onboarding; missions may request extension tools mid-stream via `pi_extend_toolkit` interrupt. Each ratified write records the active tool-set version (baseline hash + extensions) so reproduction can recreate the exact tool surface. |
| Q2 — Missing-credential handling | **Criticality-aware**. Each secret declares `criticality: required \| recommended \| optional`. `required` missing → escalate via checkpoint (PI must provide or downgrade); `recommended` → escalate once at session start; `optional` → skip with journal note. Brain proposes tier during `research_toolkit_node`; PI ratifies. |
| Q3 — Curated registry | **Yes, small (~10-15 entries)**. Ship `orchestrator/data/tool_registry.yaml` with canonical always-on (rka, context7, fs-mcp, git-mcp) + domain shortlists (finance: sec-edgar; bio: ncbi; legal: westlaw; ml-systems: hf, wandb). Brain consults registry FIRST (high-confidence priors), then web-searches for gaps. |
| Q4 — Auth patterns supported | **API key only in Phase D MVP** (~80% of MCP servers). Manifest schema designed extensibly (`auth_type: "api_key"` initially; `oauth_token`, `oauth_browser`, `keychain`, `service_account` added in Phase D2). |
| Q5 — Onboarding audit in RKA | **Yes — summary journal entry with manifest hash**. One-paragraph summary entry (`source=system`, `tags=[orchestrator, onboarding, baseline]`) referencing the manifest file path + sha256. Extensions trigger new entries with `supersedes` linkage. File remains the source of truth for execution; journal entry is the audit snapshot. |

### Concrete impact on the build (preserved verbatim from Phase D design)

**Q1 (hybrid lifecycle)** changes the manifest schema:

```jsonc
{
  "project_id": "prj_01...",
  "manifest_version": "baseline_v1",       // baseline | extension_v2 | ...
  "supersedes": null,                      // or a previous manifest hash for extensions
  "tools": [ ... ],
  // ...
}
```

And adds a new interrupt type `pi_extend_toolkit` (used by missions that
discover they need a new tool mid-stream).

**Q2 (criticality)** changes the per-secret schema:

```jsonc
"secrets": [
  {
    "name": "SEC_EDGAR_API_KEY",
    "auth_type": "api_key",
    "criticality": "required",           // required | recommended | optional
    "probe_url": "https://...",
    "probe_header": "X-API-Key"
  }
]
```

And adds dispatcher logic: at session start, check all required+recommended
secrets are present and probed; escalate accordingly.

**Q3 (small registry)** adds a new data file:

```
orchestrator/data/tool_registry.yaml
```

Seeded with ~10-15 entries. Loaded at `research_toolkit_node` startup;
results combine with SerpAPI results before being scored and presented
to PI.

**Q4 (api_key only MVP)** simplifies the credential UX to a single flow
(paste-into-`.env` + probe). The `auth_type` field is in the schema from
day one so future patterns can land without breaking changes.

**Q5 (audit entry)** adds one call at onboarding completion:

```python
mcp.rka_add_note(
    content=summary_text,
    source="system",
    type="note",
    tags=["orchestrator", "onboarding", "baseline"],
    related_decisions=[onboarding_decision_id],
)
```

For extensions, the new entry's `supersedes` field points to the previous
baseline's journal id.

### Phase D security invariants (carry forward into Phase O credential flows)

- Token values never appear in any RKA journal entry.
- Token values never appear in the orchestrator daemon's logs.
- Token values never appear in the Claude Code transcript (the PI's
  assistant only sees key names + validation results).
- The `.env` file is `chmod 600` on creation.
- The `~/rka-projects/{project_id}/` directory has perms `0700`.

Phase O re-locates these artifacts under `~/Research/{project-slug}/.rka/`
per the workspace consolidation in this design, but the file-permission
and never-log-secrets invariants carry through unchanged.

### Original Phase D build order (for reference; O5 collapses these into the Phase O timeline)

The Phase D design enumerated 8 sub-tasks (D1-D8) summing to ~7.25 days of
implementation. D1 (schema), D2 (workspace dir + manifest IO), D3 (research
toolkit node + SerpAPI augmentation), D4 (credential UX), D5 (subgraph
wiring + MCP tools), D6 (pi_extend_toolkit mid-stream extensions), D7
(audit-entry integration), D8 (skill update + integration tests). D3b
(SerpAPI augmentation) and D6 (pi_extend_toolkit) remain on the Deferred
follow-ups list in repo CLAUDE.md; the other D-stages shipped as Phase D
MVP and are now folded into Phase O as the O5 step.
