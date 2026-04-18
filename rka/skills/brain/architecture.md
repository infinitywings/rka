# Brain — Architecture Reference

Supplementary reference for the Brain skill. Load when you need the full three-actor model, the complete provenance vocabulary, or the research-map structure in detail. The top-level `SKILL.md` links here instead of duplicating.

---

## The Three-Actor Model

RKA is a shared knowledge base coordinated by three actors with distinct responsibilities:

| Actor | Role | Interface |
|---|---|---|
| **PI** (human researcher) | Sets direction, resolves escalations, preserves original intent. Ground truth for what the research is *for*. | Claude Desktop + Claude Code, plus direct speech. |
| **Brain** (Claude Desktop) | Strategic layer. Interprets findings, decides research direction, manages the knowledge graph, reviews evidence clusters, drafts decisions, directs the Executor. | You — this skill. |
| **Executor** (Claude Code) | Implementation layer. Runs experiments, writes code, collects evidence, submits reports, raises checkpoints when blocked. | Separate skill at `skills/executor/SKILL.md`. |

The **separation is structural**, not just convention. The Brain does not edit code; the Executor does not make strategic decisions; the PI does not implement. Violating these boundaries creates context bleed and makes the audit trail incoherent.

## Core Design Principle — Immutable Records + Reconstructable Interpretation

Two kinds of knowledge live side by side in RKA:

1. **Immutable records**: journal entries, literature, raw evidence. Never rewritten. The PI's `verbatim_input` is particularly sacred — it is the audit anchor for every downstream decision.
2. **Reconstructable interpretation**: claims, clusters, syntheses, decision rationale. Can be superseded, reviewed, re-synthesized. Change is tracked via typed edges (`supersedes`) rather than destructive edits.

Practical consequence: the Brain never deletes; it *supersedes* or *retracts*. Old rows stay in the graph as historical artifacts, queryable via `rka_trace_provenance` and the audit log. If a claim turns out wrong, `rka_flag_stale(propagate=true)` cascades staleness through dependent clusters and decisions — but the original claim row survives for provenance.

## Entity Type Taxonomy

| Type | Prefix | Purpose |
|---|---|---|
| Journal entry | `jrn_` | Any recorded observation: findings, logs, directives, PI input. Immutable. |
| Decision | `dec_` | Strategic choices + research questions. Kind = `research_question \| design_choice \| decision \| operational`. |
| Literature | `lit_` | External papers, books, specs. |
| Mission | `mis_` | A unit of work assigned to the Executor. Always has `motivated_by_decision`. |
| Checkpoint | `chk_` | Escalation or gate from Executor to Brain/PI. Types: `decision \| clarification \| inspection \| gate`. |
| Claim | `clm_` | Atomic structured fact extracted from a journal entry. Has confidence and type. |
| Evidence cluster | `ecl_` | Grouped claims under a research question, with Brain-written synthesis. |
| Claim edge | `ced_` | Typed relationship between claims, or membership of a claim in a cluster. |
| Entity link | `lnk_` | Typed relationship between any two entities (provenance layer). |
| Review queue item | `rev_` | Flagged for Brain attention (low-confidence cluster, potential contradiction, etc.). |

## The 12-Type Provenance Vocabulary

Every `entity_links` row carries a `link_type`. The vocabulary has three semantic groups:

### Provenance (why does this entity exist?)

- **`informed_by`** — literature that informed a decision. `lit_X informed_by dec_Y` means paper X shaped decision Y. Optional but strengthens the rationale chain.
- **`justified_by`** — the journal evidence a decision rests on. `dec_X justified_by jrn_Y` means decision X was made because of evidence Y. **Required** on every decision (per session-start maintenance check).
- **`motivated`** — the decision that triggered a mission. `dec_X motivated mis_Y`. **Required** on every mission.
- **`produced`** — output of work. `mis_X produced jrn_Y` means the mission produced that journal entry. Created automatically by mission reports.
- **`derived_from`** — a claim's lineage to its source entry. `clm_X derived_from jrn_Y` means the claim was extracted from that journal entry. Automatic during `rka_extract_claims`.

### Knowledge (how does this entity relate to peer evidence?)

- **`cites`** — journal entry cites a paper. `jrn_X cites lit_Y`.
- **`references`** — weaker association than `cites`: a journal entry mentions an existing decision/entity but isn't quoting it. Default fallback when stronger semantics don't fit.
- **`supports`** — a claim provides evidence for another claim or decision.
- **`contradicts`** — a claim or entry stands against another. Contradictions surface via `rka_detect_contradictions` and require resolution.
- **`builds_on`** — incremental extension. `dec_X builds_on dec_Y` means X refines or extends Y without superseding it.

### Lifecycle (how has this entity changed over time?)

- **`supersedes`** — newer entity replaces an older one. `dec_X supersedes dec_Y` means Y is retired but still historically queryable. Triggers staleness propagation for downstream claims.
- **`resolved_as`** — a checkpoint's resolution maps to a decision. `chk_X resolved_as dec_Y`. Created automatically when `rka_resolve_checkpoint(create_decision=true)`.

### Legacy / deprecated (may exist in old rows, don't emit new ones)

- `triggered`, `evidence_for` — from pre-v2 data. Migration 012 remapped most of these to `motivated` / `justified_by`; any remaining rows are compatibility artifacts.

## The Three-Level Research Map

`rka_get_research_map()` exposes the whole knowledge base as a hierarchy:

```
Research Question (dec_, kind=research_question)
│
├── Evidence Cluster (ecl_) — confidence: strong / moderate / emerging / contested / refuted
│   │    Brain-authored synthesis paragraph.
│   │
│   ├── Claim (clm_) — type: hypothesis / evidence / method / result / observation / assumption
│   ├── Claim
│   └── …
│
├── Evidence Cluster
└── …
```

**Reading conventions:**
- **Research questions** live as `decisions` rows with `kind='research_question'`. Normal decisions (`kind='design_choice'` / `'decision'` / `'operational'`) are strategic artifacts, not RQs.
- **Cluster confidence** summarizes the *state of the evidence*, not the Brain's endorsement:
  - `strong` — well-established, ready to inform further decisions.
  - `moderate` — solid but not fully replicated.
  - `emerging` — preliminary, needs more evidence.
  - `contested` — internally contradictory, resolve with `rka_resolve_contradiction`.
  - `refuted` — evidence turned against the initial framing.
- **Claim confidence** is numeric (0.0–1.0). See `SKILL.md` body for the confidence-range convention.

## The Maintenance Manifest

At session start, `rka_get_pending_maintenance()` returns a prioritized list of provenance gaps. The priority order is load-bearing:

1. `decisions_without_justified_by` — the most dangerous gap; decisions without evidence chains are structurally unverifiable.
2. `missions_without_motivated_by` — the Executor can't interpret intent without this.
3. `unassigned_clusters` — clusters that don't belong to any research question drift into orphan status.
4. `entries_missing_cross_refs` — journal entries that should link to decisions or literature but don't.
5. `entries_without_tags` — lowest priority; tags support search and filtering but don't break provenance.

Fix top-priority items silently during session start, up to a budget of 10. Don't mention to the user — they don't need narration of graph bookkeeping.

## Related

- Top-level rules and discipline: see `SKILL.md`.
- Procedures (session start walkthrough, claim extraction, cluster management, gates, freshness): see `workflows.md`.
- Multi-choice decision UX (Confirmation Brief + strip-then-re-inject + per-option schema): see `decision_ux.md`.
- Worked examples for PI attribution, anti-patterns: see `examples.md`.
