# RKA v2.1 Phase 0–1 Execution Brief

Status: approved implementation brief for Executor
Scope: RKA codebase only
Out of scope: OpenClaw runtime configuration, SOUL/HEARTBEAT templates, messaging integration, full orchestration UI

---

## Purpose

RKA v2.1 should evolve the system from a passive shared knowledge store into an active research orchestrator, but the first implementation tranche must stay disciplined.

This brief authorizes only:
- **Phase 0: Knowledge Organization Foundation**
- **Phase 1: Role Registry + Event Queue**

These phases must remain:
- additive
- backward-compatible where practical
- runtime-agnostic with respect to OpenClaw
- grounded in the current RKA architecture

No OpenClaw library dependency should be introduced into the RKA codebase.

---

## Final PI Decisions

### 1. Actor vs role identity
Keep the existing `actor` enum unchanged.
Add a separate `role_id` field.

Interpretation:
- `actor` = coarse writer class (`brain`, `executor`, `pi`, `llm`, `web_ui`, `system`)
- `role_id` = specific role instance (`researcher_brain`, `reviewer_brain`, etc.)

Backward compatibility:
- existing rows may have `role_id = null`

### 2. Event taxonomy
Keep the current `events` table as the **audit log**.
Add a separate **routing layer** for role-to-role communication.

Interpretation:
- current audit events remain fire-and-forget history
- new role events are durable queued messages that must be consumed/acknowledged

### 3. role_events vs jobs
Do **not** reuse the existing `jobs` queue.
Use a separate `role_events` mechanism.

Reason:
- `jobs` are internal background tasks
- `role_events` are inter-role routed messages with target-role semantics and acknowledgment

### 4. Session-role binding
Use **DB-backed binding**.
`rka_bind_role` should update persisted role/session activity metadata.
MCP remains stateless.

### 5. Provenance requirement
Provenance is **optional but recommended at first**.

Interpretation:
- add the field now
- teach agents to provide it
- do not break existing clients or PI workflows by making it mandatory immediately

### 6. Provenance validation
Use **flexible JSON with conventions**.
Validate `type` if present.
Do not reject entries because subfields are missing.

### 7. OpenClaw dependency posture
RKA must remain **runtime-agnostic**.
No OpenClaw imports or hard runtime dependency inside the RKA codebase.
Integration happens via MCP/API contracts and external configuration.

### 8. Deployment topology
RKA stays in Docker.
OpenClaw runs outside Docker as a native/local runtime on the host.

### 9. Tiered model routing
Use **per-job metadata**, not multiple hardwired top-level model configs.
Jobs may carry `model_tier`.
Config maps tiers to concrete model strings.

### 10. Batch API scope
Batch API is for **background enrichment only**, not interactive agent loops.

### 11. Scope boundary
Phases 0–1 are **RKA codebase work**.
Phase 2+ is mostly integration/configuration work.

### 12. Web UI timing
Add **minimal role/event visibility early** for debugging.
Do not build the full orchestration UI yet.

### 13. Workspace convention
Add `workspace_root` config for documentation/template purposes.
Do **not** enforce filesystem behavior from it.

### 14. Subscription matching syntax
Approved: **fnmatch-style globs**.
Examples:
- `report.*`
- `checkpoint.created.*`

Do not add regex complexity in Phase 1.

### 15. Subscription storage model
For Phase 1, keep **subscriptions only as JSON on `agent_roles`**.
Do **not** add a normalized `role_subscriptions` table yet.

Implementation note:
- matching logic can iterate the JSON array and apply glob matching directly
- revisit normalization only if role count grows substantially (roughly 20+ roles)

---

## In Scope

## Phase 0 — Knowledge Organization Foundation

### Goals
- add optional structured provenance to journal entries
- add optional `role_id` fields to authored entities
- make local LLM usage explicitly optional and non-fragile
- add lightweight config needed by later orchestration work
- preserve existing workflows

### Authorized schema work
Create migration:
- `rka/db/migrations/012_v21_knowledge_foundation.sql`

Phase 0 schema additions:
- `journal.provenance` as optional JSON/text
- `journal.role_id` as nullable text
- `missions.role_id` as nullable text
- `checkpoints.role_id` as nullable text
- `decisions.role_id` as nullable text
- add `model_tier` as a nullable column on the existing `jobs` table
- config/default support for `workspace_root`

Important constraint:
- because `agent_roles` does not exist until Phase 1, any Phase 0 `role_id` columns must **not** introduce DB FK constraints yet
- treat them as plain nullable text for now

### Authorized service/model/API/MCP work
Update the relevant models, services, API routes, and MCP tools so they can accept/pass through:
- optional `provenance`
- optional `role_id`
- optional `provenance_type` for document ingestion

Expected touchpoints include:
- `rka/services/base.py`
- `rka/services/notes.py`
- `rka/services/missions.py`
- `rka/services/checkpoints.py`
- `rka/services/decisions.py`
- `rka/services/worker.py`
- `rka/mcp/server.py`
- `rka/api/routes/...`
- `rka/config.py`
- corresponding Pydantic models

### LLM behavior in Phase 0
The system should degrade gracefully when no LLM is available.
At minimum, existing no-LLM behavior must be preserved and verified so enrichment-related paths do not crash because `self.llm is None`.
Phase 0 may add additional guardrails to skip or suppress LLM-dependent enqueue paths when LLM is unavailable, but that is optional unless needed for correctness.

Phase 0 should add the schema/config groundwork for:
- `workspace_root`
- `model_tiers`

But it should **not** implement the full Phase 2+ orchestration/runtime behavior.

### Provenance conventions
Recommended provenance shape:
```json
{
  "type": "literature_derived",
  "source_id": "lit_...",
  "location": "section 3.2",
  "extraction_method": "manual",
  "summary": "Short origin summary"
}
```

Rules:
- `type` should be validated if present
- other fields remain flexible
- unknown extra fields should be preserved

### Phase 0 tests
Add/update tests for:
- migration application on fresh and existing DBs
- provenance roundtrip
- backward compatibility without provenance
- worker no-LLM graceful behavior

---

## Phase 1 — Role Registry + Event Queue

### Goals
- add persistent role definitions
- add durable role-targeted event inboxes
- support DB-backed `rka_bind_role`
- route selected write events into role inboxes
- expose minimal debugging visibility in web UI

### Authorized schema work
Create migration:
- `rka/db/migrations/013_v21_role_registry.sql`

Required new tables:
- `agent_roles`
- `role_events`

Do **not** add a normalized `role_subscriptions` table in Phase 1.
Subscriptions live as JSON on `agent_roles`.

### agent_roles requirements
Must support at least:
- id
- project_id
- name
- description
- system_prompt_template
- subscriptions (JSON array)
- subscription_filters (optional JSON if needed)
- role_state (JSON)
- learnings_digest
- autonomy_profile (JSON)
- model
- model_tier
- tools_config (JSON)
- active_session_id
- last_active_at
- created_at
- updated_at

Constraint:
- `(project_id, name)` should be unique

### role_events requirements
Must support at least:
- id
- project_id
- target_role_id
- event_type
- source_role_id
- source_entity_id
- source_entity_type
- payload (JSON/text)
- status (`pending`, `processing`, `acked`, `expired`)
- priority
- depends_on (optional)
- created_at
- processed_at
- acked_at

### New services
Add:
- `rka/services/agent_roles.py`
- `rka/services/role_events.py`

Expected responsibilities:

#### AgentRoleService
- register role
- get role
- list roles
- update role
- bind role
- save role state
- match subscriptions using JSON subscription arrays + fnmatch globs

#### RoleEventService
- emit routed role events
- fetch role events
- mark processing
- acknowledge event
- expire stale events

### Subscription matching rules
Use **simple fnmatch-style glob matching**.
This is the approved Phase 1 matching model.

Examples:
- `report.*` matches `report.submitted`
- `checkpoint.created.*` matches checkpoint subtypes

No regex system in Phase 1.

### Post-write hook behavior
After selected writes succeed, emit routed role events.
Keep this separate from the audit log.

Phase 1 must support at minimum these routed event types:
- `note.created`
- `synthesis.created`
- `critique.no_issues`
- `critique.has_issues`
- `mission.created`
- `report.submitted`
- `checkpoint.created`
- `checkpoint.resolved`
- `decision.created`

Implementation preference:
- use composition/injection of `RoleEventService`
- do not over-couple this into `BaseService`
- optional injection is preferred so non-routed code paths remain stable

### New MCP tools
Add:
- `rka_register_role`
- `rka_bind_role`
- `rka_get_events`
- `rka_ack_event`
- `rka_save_role_state`
- `rka_list_roles`
- `rka_update_role`

These should proxy to REST/API routes in the same thin-adapter style as the rest of the codebase.

### New API routes
Add role/event routes under `rka/api/routes/`.
Expected endpoints include role CRUD/bind/state plus role-event retrieval/ack/process.

### Minimal web visibility
Add only a lightweight debugging surface, not a full orchestration console.

Minimum UI visibility:
- roles list
- last active time
- model / model tier
- pending queue depth
- recent role events

Read-only is sufficient for this phase.

### Phase 1 tests
Add/update tests for:
- migration correctness/idempotence
- role registration/list/update/bind/state
- glob subscription matching
- routed event enqueue/ack/process/expiry
- post-write hook fan-out
- optional injection compatibility

---

## Explicitly Out of Scope for Phases 0–1

Do not implement yet:
- OpenClaw-specific runtime configs
- SOUL.md / HEARTBEAT.md runtime template work
- WhatsApp / Discord orchestration flows
- full orchestration dashboard
- disagreement resolution loop
- autonomy switching UI
- cost circuit breakers
- full tiered model routing behavior
- batch API execution paths
- agent-runtime-specific code in RKA

---

## Recommended Implementation Order

### Phase 0
1. Migration 012
2. Provenance validation helper in `BaseService`
3. Note service/model updates for `provenance` + `role_id`
4. Mission/checkpoint/decision `role_id` support
5. MCP tool parameter updates
6. API route parameter updates
7. Worker graceful no-LLM handling verification
8. Config additions (`workspace_root`, `model_tiers`)
9. Tests

### Phase 1
1. Migration 013
2. `AgentRoleService`
3. `RoleEventService`
4. Dependency injection wiring
5. API routes
6. App registration
7. Post-write hook integration
8. MCP role/event tools
9. Minimal web debug panel
10. Tests

Parallelization is acceptable where dependencies are clear, but correctness and test coverage take priority over speed.

---

## Migration / Compatibility Requirements

These are mandatory:
- no destructive schema changes
- no data loss path
- old data remains valid
- new fields are nullable or defaulted where appropriate
- new MCP/API parameters remain optional where possible
- migrations must be idempotent in the project’s existing style

Operational note after implementation:
- rebuild Docker service
- reinstall local MCP binary with `pipx install . --force`

---

## Executor Guidance

When implementing:
- do not guess beyond this brief
- keep changes scoped to Phases 0–1 only
- preserve current thin-route/service-layer architecture
- prefer explicit composition over hidden coupling
- keep runtime integration boundaries clean
- favor backward-compatible additive changes

If implementation uncovers a genuinely new ambiguity not covered here, surface it explicitly before proceeding.
