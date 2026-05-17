# Skill-prompt deltas (T10)

Diff-ready additions to the Brain + Executor skills based on the
mis_01KRKG9K1SSDZNDH90K2Z7ZM92 build and earlier rehearsal observations.

Status: **17 ratified additions** per Brain greenlight (jrn_01KRM1RVP8M49M7RXWX75SB5C2).
A candidate #18 (*service-up ≠ service-correct*) is **held** — only adopted if T9 hit
the corresponding failure mode. T9 landed clean (162/162 tests, no MCP-up-but-wrong
incidents), so #18 stays parked for Phase-2 polish.

**FOLDED 2026-05-17** — Phase 2.3 mission `mis_01KRV21Q6EMXFJY02GSRXQZPP4` folded
16 of 17 deltas into `/Users/ceron/Code/rka-test-plugin/skills/{brain,executor}/SKILL.md`
(plugin baseline `c5875d1` → brain fold `bef32d1` → executor fold `86c3d34`). Delta 10
is **CODE-ONLY** per resolved checkpoint `chk_01KRSTFD7203NWAR8MYD91KSFV` (paraphrasing
existing Rule + Why into a new skill-prompt section IS authoring per "no new rules"
scope rule). PI smoke-test (fresh Claude Code session) is the final acceptance gate.

Each addition lists:

- **rule** — the discipline to add
- **why** — the failure-mode or success-pattern that motivates it
- **target** — concrete file/section in this repo where the delta lands

---

## 1. Version-drift re-verification

**FOLDED 2026-05-17** → `skills/executor/SKILL.md` "Backbrief — Confirm Your Plan" (plugin commit `86c3d34`).

**Rule.** When a Backbrief assumption about a library version is more than 6 months
old, re-verify against PyPI's current `info.version` before pinning. Document the
re-verification result in the Backbrief.

**Why.** R13 in this mission: Backbrief pinned `langgraph>=0.3,<0.4` based on
rehearsal-era assumptions; PyPI showed the 0.3 line had no release for 14 months
and the version line had moved 0.3 → 0.5 → 0.6 → 1.0 → 1.1 → 1.2. Pinning to
abandoned majors is a worse failure mode than tracking current stable.

**Target.** `skills/executor/SKILL.md` — add to the "Backbrief — Confirm Your Plan"
section: *"For every library version pin in your Backbrief, capture the current
PyPI `info.version` and the last-release date for the pinned major. Flag any
pin where the line has been silent >6 months."*

---

## 2. Mid-mission Backbrief gate at structural milestones

**FOLDED 2026-05-17** → `skills/brain/SKILL.md` "Gate cadence" (### subsection under Validation Gates; plugin commit `bef32d1`).

**Rule.** When a mission spans more than ~5 tasks, designate a mid-mission
Backbrief gate at the task that locks the core foundation (state schema, data
model, API contract). The Brain re-ratifies before downstream tasks build on it.

**Why.** T2 gate caught the langgraph version drift before 15 nodes were built
on a wrong pin. Saved a wholesale re-pin across the topology.

**Target.** `skills/brain/SKILL.md` — add a "Gate cadence" subsection: *"For
missions >5 tasks: pick the foundation-locking task and gate-ratify before the
downstream work. Re-verify the upfront Backbrief's assumptions against any
empirical evidence the foundation work surfaced."*

---

## 3. Three-storage discipline

**FOLDED 2026-05-17** → `skills/brain/SKILL.md` "Project workflows" (new ## section; plugin commit `bef32d1`).

**Rule.** When building orchestration over RKA, partition state ownership:

- **RKA SQLite** — domain truth (decisions, missions, journals, claims)
- **LangGraph SqliteSaver** — workflow position (which node ran, with what input)
- **Claude SDK session** — transient prompt/response context per node

Never persist workflow position back to RKA; never use the SDK session as a state
bus across nodes.

**Why.** Mixing storages creates competing sources of truth. The orchestrator
nodes that write to RKA can be re-run idempotently because RKA writes are
journaled there, not in the LangGraph state.

**Target.** `orchestrator/state.py` docstring already documents this. Mirror in
`skills/brain/SKILL.md` under "Project workflows": *"Treat the three storage
layers as having distinct ownership. PI directives that affect domain truth
land in RKA; workflow-position decisions land in the checkpointer."*

---

## 4. workflow_thread_id auto-tagging

**FOLDED 2026-05-17** → `skills/executor/SKILL.md` "Repo-specific procedures" (bullet; plugin commit `86c3d34`).

**Rule.** Every RKA write during a workflow run carries a stable
`workflow_thread_id` tag. Use it to recover all artifacts a run produced:
`rka_get_journal(tags=[thread_id])`.

**Why.** Mirrors v2.3.5 Affordance F (motivated-by-explained tag suppression).
Lets the PI replay any workflow's artifact set without log-scraping.

**Target.** `orchestrator/mcp_client.py:RestMCPClient` does this. Document in
`skills/executor/SKILL.md` "Repo-specific procedures": *"Inside an orchestrator
workflow, every `rka_add_*` and `rka_submit_*` call MUST carry the
`workflow_thread_id` in `tags`. The `MCPClient` wrapper handles this; if you
bypass it, tag manually."*

---

## 5. Append-only reducers vs. last-write-wins scalars

**FOLDED 2026-05-17** → `skills/brain/SKILL.md` "LangGraph workflows" (new ## section; plugin commit `bef32d1`).

**Rule.** In LangGraph state schemas, partition fields:

- **Append-only collections** (artifacts, interrupts, checkpoints, errors,
  notifications) → `Annotated[list[T], operator.add]`
- **Scalars** (current_phase, usd_spent, loop_iterations) → LangGraph default
  (last-write-wins)

A guard test should assert each side of the partition matches the schema.

**Why.** Append-only ensures concurrent node writes (even in flat Phase 1
they're sequenced, but reducers also handle the resumed-from-checkpoint case)
concatenate instead of overwriting. Scalar last-write-wins is the obvious
default; a stray `Annotated[..., operator.add]` on a budget counter would
silently sum every write.

**Target.** `orchestrator/state.py` already separates these. Add to
`skills/brain/SKILL.md` "LangGraph workflows" subsection.

---

## 6. Protocol abstraction for SDK + MCP

**FOLDED 2026-05-17** → `skills/executor/SKILL.md` "Test method" (new ## section; plugin commit `86c3d34`).

**Rule.** Workflow nodes depend on `SDKClient` and `MCPClient` Protocol types
(typing.Protocol), not on concrete client classes. Tests inject Fake clients
that satisfy the Protocol; production binding happens in the graph constructor.

**Why.** Lets every node test offline. Also lets us swap (e.g., REST → stdio
MCP, or Anthropic SDK → another LLM) without touching node code.

**Target.** `orchestrator/llm_client.py` and `orchestrator/mcp_client.py`.
Add to `skills/executor/SKILL.md` "Test method" guidance: *"Node tests inject
Fake clients honoring the Protocol — no real HTTP, no real LLM."*

---

## 7. Conservative malformed-input defaults

**FOLDED 2026-05-17** → `skills/brain/SKILL.md` "Output parsing" (new ## section; plugin commit `bef32d1`).

**Rule.** When an LLM response is malformed (verdict not parseable, expected
key absent), default to the **conservative** outcome — for verdicts, that's
"redirect", not "approve".

**Why.** `gate1_validation` parses the first line for APPROVED/REDIRECTED.
A malformed reply ("hmm I'm not sure") should not be treated as approval.

**Target.** `orchestrator/nodes/brain.py:_parse_gate1_verdict`. Add to
`skills/brain/SKILL.md` "Output parsing": *"When parsing structured outputs
from your own LLM calls, default to the conservative branch if parsing fails."*

---

## 8. Defensive missing-required-field paths

**FOLDED 2026-05-17** → `skills/executor/SKILL.md` "Guardrails" (bullet; plugin commit `86c3d34`).

**Rule.** When a node requires a state field that should be present but might
not be (mission_id at report submission, executor_backbrief at gate1), record
an `ErrorRecord` and route to `escalation_router` rather than crashing.

**Why.** Crashes lose the workflow checkpointer's recovery affordance.
`submit_report` with missing mission_id appends an error and returns rather
than raising, so the PI can be notified via pi_acceptance with the partial state.

**Target.** `orchestrator/nodes/executor.py:submit_report` does this. Add to
`skills/executor/SKILL.md` "Guardrails": *"Inside an orchestrator workflow,
prefer appending an `ErrorRecord` over raising — the topology has a defined
escalation path; raising bypasses it."*

---

## 9. Telemetry-zero default

**FOLDED 2026-05-17** → `skills/executor/SKILL.md` "Repo-specific procedures" (bullet; plugin commit `86c3d34`).

**Rule.** Outbound notifications use **terminal bell + macOS osascript** only
by default. Webhook is **opt-in** and gated by an explicit `channels=["webhook"]`
plus a non-empty `webhook_url`.

**Why.** The user (PI) is the sole intended consumer of orchestrator
notifications. No third party should receive any data without explicit opt-in.

**Target.** `orchestrator/notifications.py:DEFAULT_CHANNELS = ("bell",
"osascript")`. Add to `skills/executor/SKILL.md` under "Repo-specific
procedures": *"Orchestrator notifications follow a telemetry-zero stance by
default."*

---

## 10. Webhook blocklist by substring match

**CODE-ONLY 2026-05-17** — rule lives in `orchestrator/notifications.py:_is_blocked_webhook` (already in-file pre-fold). NO plugin-side prose added per Brain's Option-C ratification on `chk_01KRVCWNKYBZ29RVTJZETKBKNG`: paraphrasing existing Rule + Why into a new skill-prompt section IS authoring for prompt-content purposes, violating the mission's binding "no new rules; just fold what's already ratified" scope rule.

**Rule.** Compare blocklist hosts as **substrings** of the URL, not exact-host
matches. This catches `us.api.posthog.com`, `staging.app.posthog.com`, etc.

**Why.** Telemetry vendors use rotating subdomains. Exact-match blocklists
silently let `us.api.segment.io/v1/track` through if only `api.segment.io`
is listed.

**Target.** `orchestrator/notifications.py:_is_blocked_webhook`. Reference
this in `skills/executor/SKILL.md` whenever adding new outbound channels.

---

## 11. functools.partial node binding

**FOLDED 2026-05-17** → `skills/executor/SKILL.md` "LangGraph wiring" (new ## section; plugin commit `86c3d34`).

**Rule.** When a LangGraph node needs dependencies beyond `state` (sdk, mcp,
interrupt_fn), bind them via `functools.partial` at graph-construction time so
the LangGraph engine sees a uniform `(state,)` callable.

**Why.** Mixing engine concerns with node concerns (subclassing, capturing
free variables) is brittle. `functools.partial` is the explicit idiom.

**Target.** `orchestrator/graph.py:_bind`. Add a code-pattern note to
`skills/executor/SKILL.md` "LangGraph wiring" subsection.

---

## 12. Conditional routing on next_node_override

**FOLDED 2026-05-17** → `skills/brain/SKILL.md` "Routing patterns" (new ## section; plugin commit `bef32d1`).

**Rule.** Utility nodes (budget_check, consensus_check) that need to escalate
do so by setting `state["next_node_override"] = "escalation_router"`. The
topology's conditional-edge mapping has an explicit `__continue__` key for
the no-override path.

**Why.** Embedding the routing decision inside the node's state output (rather
than in the topology) keeps the audit symmetric: every escalation is visible
in the state diff.

**Target.** `orchestrator/graph.py:_route_after_budget_or_consensus` +
`orchestrator/nodes/utility.py`. Document the pattern in
`skills/brain/SKILL.md` "Routing patterns".

---

## 13. NODE_NAMES canonical tuple

**FOLDED 2026-05-17** → `skills/executor/SKILL.md` "T11 audit checks" (new ## section; plugin commit `86c3d34`).

**Rule.** Maintain a single source of truth for the canonical node names
(`orchestrator/graph.py:NODE_NAMES`). T11 audit-symmetry asserts:

1. Every name in NODE_NAMES is registered in the compiled graph
2. Every `state["current_node"]` assignment in the codebase uses one of
   these names

**Why.** Typos in `current_node` strings are silent — they don't break
LangGraph, they just produce un-routable state. NODE_NAMES + audit gives
a compile-time-style guard.

**Target.** `orchestrator/graph.py:NODE_NAMES`. Add to
`skills/executor/SKILL.md` "T11 audit checks".

---

## 14. Metric divergence-as-headline

**FOLDED 2026-05-17** → `skills/brain/SKILL.md` "Status reporting" (new ## section; plugin commit `bef32d1`) AND `skills/executor/SKILL.md` "Report Submission" (new ## section; plugin commit `86c3d34`).

**Rule.** When the expected and observed values of a measured metric
diverge during a run, lead the next status update (report, journal note, or
PI notification) with the **divergence**, not the raw numbers. Use the form
*"expected X, observed Y — Z% off"* in the first sentence.

**Why.** Burying divergence inside a metrics table delays PI awareness. The
metric matters because the divergence matters.

**Target.** `skills/brain/SKILL.md` "Status reporting" section. Also flag in
`skills/executor/SKILL.md` "Report Submission".

---

## 15. PI batch-review affordance (obs #15 — adopted)

**FOLDED 2026-05-17** → `skills/brain/SKILL.md` "PI interactions" (new ## section; plugin commit `bef32d1`).

**Rule.** When a PI `interrupt()` payload exceeds `PI_BATCH_REVIEW_THRESHOLD`
items (default 10), emit `batched=True`, `page_size=THRESHOLD`,
`total_items=N` metadata so the renderer can paginate. Record
`batch_review_used=True` on the resulting `InterruptRecord`.

**Why.** Labeler-UX-scaling friction surfaces when a PI is asked to review
N decisions at once; single-blob presentation produces fatigue + missed
items. Pagination + post-hoc retrievability via `batch_review_used` enables
analytics on whether the affordance fired correctly.

**Target.** `orchestrator/nodes/pi.py:_build_interrupt_payload` + every PI
node. Document in `skills/brain/SKILL.md` "PI interactions" section:
*"When queueing >10 decisions for a single PI interrupt, the orchestrator
auto-paginates. For lower-volume manual flows, you still benefit from
splitting into 3-5 item batches."*

---

## 16. Affordance F propagation (workflow_thread_id mirrors motivated-by tags)

**FOLDED 2026-05-17** → `skills/brain/SKILL.md` "Affordances" (new ## section; plugin commit `bef32d1`).

**Rule.** The `workflow_thread_id` tag is structurally identical to the
v2.3.5 `motivated-by-explained` suppression tag: a deterministic value
written on every artifact during a context, used to scope retrospective
queries. Treat it as the same affordance applied to workflows.

**Why.** The pattern is durable across many forms of contextual scoping —
mission membership, workflow membership, decision provenance. Naming this
similarity makes future generalizations cheap.

**Target.** `skills/brain/SKILL.md` "Affordances" section.

---

## 17. Affordance G surface re-exposed (KnowledgePackIntegrityError)

**FOLDED 2026-05-17** → `skills/executor/SKILL.md` "Repo-specific procedures" (bullet; plugin commit `86c3d34`).

**Rule.** When an MCP write returns HTTP 422 with knowledge-pack-integrity
detail, map it to `CheckpointError` and route via `escalation_router`. Do
not retry; the integrity violation is a strategic problem (orphaned
references, missing transitive provenance) that needs PI input, not a
network retry.

**Why.** v2.3.5 surfaced Affordance G as structured 422 responses; the
orchestrator must consume that structure rather than coercing to a generic
5xx-style retry.

**Target.** `orchestrator/mcp_client.py:RestMCPClient._request` does this.
Add to `skills/executor/SKILL.md` "Repo-specific procedures": *"422 from
the RKA REST API is an integrity error, not a transient failure. Treat it
as a checkpoint trigger."*

---

## Candidate #18 (HELD)

**Rule (held).** *Service-up ≠ service-correct.* A successful TCP connect or
HTTP 200 says the service is reachable; it does not say its semantics match
expectations. Always do a probe call returning meaningful data before
treating a service as ready.

**Status.** T9 did not surface this failure mode. Re-evaluate after T12
pilot or any future workflow run that exposes the gap. If it lands, file as
#18 in this document; otherwise close as Phase-2 polish in the T12 mission
report.

---

## Summary of fold-in surface

| File                              | Additions touching it |
|-----------------------------------|----------------------|
| `skills/brain/SKILL.md`           | 2, 3, 5, 7, 12, 14, 15, 16 |
| `skills/executor/SKILL.md`        | 1, 4, 6, 8, 9, 10, 11, 13, 17 |
| `orchestrator/state.py` (docstring) | 3, 5 (already in-file) |
| `orchestrator/notifications.py` (docstring) | 9, 10 (already in-file) |
| `orchestrator/graph.py` (docstring) | 11, 12, 13 (already in-file) |
| `orchestrator/mcp_client.py` (docstring) | 4, 17 (already in-file) |
