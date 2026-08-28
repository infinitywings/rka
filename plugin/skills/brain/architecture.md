# Brain — Architecture Reference

Supplementary reference for the Brain skill. Load when you need the full three-actor model, the complete provenance vocabulary, or the research-map structure in detail. The top-level `SKILL.md` links here instead of duplicating.

> **v2.7.0 dispatch translation.** Legacy tool names cited in this file (`rka_trace_provenance`, `rka_extract_claims`, `rka_detect_contradictions`, `rka_resolve_contradiction`, `rka_resolve_checkpoint`, `rka_get_research_map`, `rka_get_pending_maintenance`, `rka_flag_stale`) are synonyms for `rka_query` / `rka_execute` operations under the v2.7.0+ typed-arg surface. Architecture and provenance semantics are unchanged across the v2.6 → v2.7.0 arc — only the MCP call shape evolved.

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

## Entity-link and claim-edge vocabularies

RKA deliberately separates cross-entity provenance from claim semantics. Every
`entity_links` row carries one of the nine active `link_type` values enforced by
migration 021. Claim-to-claim scientific relations live in `claim_edges`; they
are not legal `entity_links` values.

### Provenance (why does this entity exist?)

- **`informed_by`** — literature that informed a decision. `lit_X informed_by dec_Y` means paper X shaped decision Y. Optional but strengthens the rationale chain.
- **`justified_by`** — the journal evidence a decision rests on. `dec_X justified_by jrn_Y` means decision X was made because of evidence Y. **Required** on every decision (per session-start maintenance check).
- **`motivated`** — the decision that triggered a mission. `dec_X motivated mis_Y`. **Required** on every mission.
- **`produced`** — output of work. `mis_X produced jrn_Y` means the mission produced that journal entry. Created automatically by mission reports.
- **`derived_from`** — staged interpretation and claim lineage. Candidate creation records `icd_X derived_from jrn_Y|lit_Y|art_Y`. `rka_extract_claims` stops at this candidate boundary. After exact grounding review, explicit promotion records `clm_X derived_from icd_X`; journal-backed claims also retain `clm_X derived_from jrn_Y` and exact offsets.

### Cross-entity association

- **`cites`** — journal entry cites a paper. `jrn_X cites lit_Y`.
- **`references`** — weaker association than `cites`: a journal entry mentions an existing decision/entity but isn't quoting it. Default fallback when stronger semantics don't fit.

### Lifecycle (how has this entity changed over time?)

- **`supersedes`** — newer entity replaces an older one. `dec_X supersedes dec_Y` means Y is retired but still historically queryable. Triggers staleness propagation for downstream claims.
- **`resolved_as`** — a checkpoint's resolution maps to a decision. `chk_X resolved_as dec_Y`. Created automatically when `rka_resolve_checkpoint(create_decision=true)`.

### Claim semantics (`claim_edges`, not `entity_links`)

- **`member_of`** — a claim belongs to an evidence cluster.
- **`supports`** — one claim supports another claim.
- **`contradicts`** — one claim stands against another claim.
- **`qualifies`** — one claim narrows or conditions another claim.
- **`supersedes`** — a newer claim replaces an older claim.

Downstream clients may consume these relations when checking support and
disagreement, but must not encode them as cross-entity provenance links.

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
- **Claim confidence** is numeric extraction/grounding confidence (0.0–1.0),
  not scientific evidence strength. See `SKILL.md` for the range convention;
  use `evidence_status` for scientific assessment.

## Evidence promotion funnel (noise control)

Journal entries are an intentionally inclusive research record; they may contain
failed attempts, transient observations, duplicated notes, or preliminary
interpretations. Do not make the journal less useful by pretending every entry
is reusable evidence. Promote information through explicit gates instead:

1. **Record.** Preserve the source `jrn_` with its exact conditions, mission,
   timestamps, and uncertainty. Raw records remain immutable evidence even when
   their interpretation changes.
2. **Extract.** Convert only atomic, falsifiable propositions into `clm_`
   records. New claims default to `evidence_status=unassessed`.
3. **Ground.** Review source offsets, numbers, direction, and wording.
   `verified=true` means only that the claim faithfully represents its source;
   it never means the result is scientifically supported.
4. **Assess.** Compare current positive evidence, qualifiers, and
   counterevidence. Set exactly one categorical `evidence_status` through
   `review_claims`: `supported`, `partially_supported`, `inconclusive`, or
   `contradicted`. Leave it `unassessed` until this review actually happens.
5. **Synthesize.** Add grounded claims to an `ecl_`, represent
   support/qualification/contradiction in `claim_edges`, and write a bounded
   cluster synthesis. Cluster confidence summarizes the collection; it cannot
   upgrade an unassessed member claim.
6. **Answer.** Bind the cluster to one explicit research-question `dec_` and
   advance the RQ only from current assessed claims. Mixed evidence produces a
   partial, reframed, or contested answer rather than a smoothed consensus.
7. **Serve.** Expose current claims, qualifiers, counterevidence, and their
   provenance through the public retrieval contract. Any downstream drafting
   or presentation layer remains responsible for its own explicit selection
   and author review.

This funnel is monotone in accountability, not in certainty: later evidence may
move a claim to `inconclusive` or `contradicted`, which must propagate to its
cluster and RQ conclusion instead of being averaged away.

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
