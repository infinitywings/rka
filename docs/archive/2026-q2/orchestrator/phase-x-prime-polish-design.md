# Phase-X²' Polish — Schema-Divergence Validation Chain

> **Status update (2026-06-02): the structural fix arrived as v2.7.0
> GA.** This design doc landed as `agentic` PR2 (2.6.0+agentic.2) +
> `main` PRs (v2.6.1 / v2.6.2) per
> [v2.6.x-roadmap.md](./v2.6.x-roadmap.md). It was an additive
> patch series targeting the field-NAME layer of the navigator
> architecture. The deeper investigation that followed surfaced
> that Claude Desktop's tool_search is unreliable (3 unfixed GitHub
> bugs) and that Anthropic's recommended pattern for the 91-tool
> surface is intent-grouping with a discriminated union. v2.7.0
> ships exactly that: 3 always-on dispatch tools (`rka_query` /
> `rka_execute` / `rka_describe`) with 87 typed Pydantic operation
> models enforcing per-branch enum + required-field constraints
> at the FastMCP inputSchema layer — so the field-NAME gap this
> doc closes via runtime ErrorRecord is now closed structurally
> at the schema layer (oneOf branch `required: [...]` array). The
> agentic-side ErrorRecord plumbing remains useful because the
> orchestrator subprocess still runs on the v2.7.0a2 verb surface
> via `RKA_LEGACY_TOOLS=1` to preserve TWO-TAP gate granularity.
> See [/docs/v2.6.x-v2.7.0-tool-surface-arc.md](../../docs/v2.6.x-v2.7.0-tool-surface-arc.md)
> for the full narrative.

> **See also: Phase-X² (In-Run Redraft Channel) — sibling fix at the
> field-VALUE layer.** Phase-X² (CLAUDE.md "Phase-X² polish —
> validation-chain hardening") closed the validator gap at the
> field-VALUE layer (catches `confidence='confirmed'` and analogous
> enum-mismatches before the network round-trip). Phase-X²' (this
> doc) closes the validator gap at the field-NAME layer (catches
> `rka_submit_checkpoint(content=...)` instead of `description=...`).
> The two are structural siblings: same dispatcher seam, same
> manual-mirror posture, same ErrorRecord integration, same
> skip-and-continue semantics. They share the `rka_enums.py` module
> and the EC8 partial-dispatch escalation behavior.

---

## 1. Executive Summary

- **The gap.** RKA's 9 WRITE_TOOLS use **five different vocabularies**
  for the same semantic role ("primary free-text body field"):
  `content` (3 tools: `rka_add_note`, `rka_update_note`,
  `rka_ingest_document`), `question` (`rka_add_decision`), `objective`
  (`rka_create_mission`), `description` (`rka_submit_checkpoint`),
  `summary` (`rka_submit_report`). Brain's only worked example in
  `EXECUTOR_SYSTEM` (`nodes/executor.py:156`) uses `content=` for
  `rka_add_note`, which generalizes incorrectly to every sibling. The
  Phase-X² polish enumerated field VALUES (enum sets) but did NOT
  enumerate field NAMES per tool — so `content=` on
  `rka_submit_checkpoint` sails past pre-dispatch validation and dies
  at the adapter (`mcp_client.py:574 ValueError`) or at FastAPI's
  Pydantic `extra='forbid'` (HTTP 422).
- **One-sentence right answer.** Add a `TOOL_REQUIRED_FIELDS` table to
  `rka_enums.py` (alias-set-of-sets shape so the validator can
  consult adapter aliases), a `check_required_fields(tool, args) ->
  list[str]` function, a new
  `ratified_action_arg_missing_required_field` ErrorRecord type
  wired into `execute_ratified_actions` immediately after the
  existing enum check, a `content`→`description` alias on
  `rka_submit_checkpoint` (sibling `rka_submit_report` already
  accepts it), and a canonical-field-name enumeration block in
  BRAIN/EXECUTOR_SYSTEM symmetric to the Phase-X² enum-value block.
  All three layers together; no single layer alone is sufficient.
- **The minimal patch (agentic-only).** ~150 LOC across 5 files,
  10 new tests. Closes the bug class for the active workflow without
  touching `rka/`. Bookkeeper invariant intact.
- **The structural fix (main v2.6.x).** Server-side additive aliases
  on the three execution-gates tools, `Annotated[Literal[...]]`
  promotion on enum-typed parameters, schema-lie fix on
  `rka_submit_report`, docstring convention sweep, and a cross-check
  test asserting MCP-surface field names match Pydantic-model field
  names. All backward-compatible — qualifies for the v2.6.x patch
  cadence the PI requested rather than v2.7.0.
- **What we explicitly reject.**
  - *Adapter-only alias fix without validator + prompt* — the
    treadmill. Next field-name attractor (`body`, `text`,
    `message_text`) on another tool repeats the pattern. Fail-loud
    pre-dispatch + prompt grounding break the treadmill.
  - *Removing the orchestrator's adapter aliasing* — premature. The
    orchestrator does not (yet) pin a minimum RKA MCP-binary version,
    so the adapter must continue to absorb old-shape emissions until
    that version-pinning is resolved.
  - *Renaming canonical RKA fields to be consistent* — a v3.0
    breaking change. The additive-alias path achieves 90% of the
    benefit with zero break.

---

## 2. Background — What Phase-X² Did, What It Left Open

### 2.1 What Phase-X² closed

Phase-X² (commit 291f6f8, 2026-05-31) introduced a pre-dispatch
field-VALUE validator in `orchestrator/orchestrator/rka_enums.py`:

- `TOOL_ARG_ENUMS: dict[str, dict[str, frozenset[str]]]` —
  per-tool, per-field set of allowed enum values, manually mirrored
  from `rka/db/schema.sql` CHECK constraints and `rka/models/*.py`
  Pydantic Literals.
- `validate_action_args(tool, args)` — returns a list of
  human-readable error reasons for each (field, value) pair whose
  value is not in the allowed set.
- `ratified_action_arg_invalid_enum_value` ErrorRecord, wired into
  `execute_ratified_actions` immediately before dispatch, with
  skip-and-continue semantics that integrate cleanly with EC8
  partial-dispatch routing.
- Lock-tests at `tests/test_rka_enums.py` pin the mirror table
  against drift via `RKA_CONFIDENCES == frozenset({...})` style
  assertions. The module additionally has an AST-scan invariant
  forbidding `from rka` / `import rka` imports.

Phase-X² shipped 64 net new tests (1084 → 1148) and was empirically
validated on Run-5 of the hyperscaler-auditing test harness.

### 2.2 What Phase-X² left open

The validator catches *invalid values for known field names*. It is
blind to *invalid (unknown or missing) field names*. Two empirical
events surfaced this gap:

- **Run-5 PA-2 (2026-05-31)** — Brain emitted
  `confidence='confirmed'`. Phase-X² validator caught it
  pre-dispatch. ✅
- **Hyperscaler-auditing PA-2 (2026-06-01, this session)** — Brain
  emitted `rka_submit_checkpoint(content=...)` instead of
  `description=...`. Phase-X² validator could not catch it (no
  field-name table). The adapter at `mcp_client.py:574` raised
  `ValueError('rka_submit_checkpoint requires a description/
  message/reason')`. EC8 partial-dispatch handler caught the failure
  and escalated correctly (PA-1 ok, PA-2 dead → blocking
  checkpoint). The PI session observed
  `ratified_action_call_failed` with the embedded `ValueError`
  message and resolved manually. ❌

The structural gap: the validation chain has a hole at the
field-name layer that mirrors the hole Phase-X² closed at the
field-value layer.

---

## 3. Root Cause — The Five-Vocabulary Attractor

### 3.1 The naming inconsistency

For each of the 9 WRITE_TOOLS, the canonical primary-body field
name (as defined in `rka/mcp/server.py`):

| Tool | Primary body field | server.py:line |
|---|---|---|
| `rka_add_note` | `content` | 219 |
| `rka_update_note` | `id + content` | 269-270 |
| `rka_add_decision` | `question` | 467 |
| `rka_create_mission` | `objective` | 1109 |
| `rka_update_mission_status` | `id + status` | 1195-1196 |
| `rka_submit_checkpoint` | `description` | 1365 |
| `rka_submit_report` | `summary` (synthetic — see §3.4) | 1285 |
| `rka_ingest_document` | `content` | 2216 |
| `rka_bulk_update` | `updates` | 1043 |

`content` appears 3 times. `question`, `objective`, `description`,
`summary`, `updates` each appear once. `id+status` and `id+content`
each appear once for update-shape tools.

### 3.2 The LLM error mechanism

The Brain LLM is mapping an abstract pattern ("record with primary
body field") onto a tool surface whose canonical names are NOT
pattern-consistent. Without explicit grounding, an LLM trained on
the abstract shape will hallucinate the most common synonym
(`content`) any time it isn't actively grounding off the specific
tool's docstring. The orchestrator's prompts make this worse in two
ways:

- **Only worked example uses `content`.** `nodes/executor.py:156`
  renders the canonical write-tool example as
  `{tool: "rka_add_note", args: {content: "...",
   related_decisions: ["{{PA-1.id}}"]}}`. This is the ONLY rendered
  arg-shape example in either prompt. Extrapolated to
  `rka_submit_checkpoint` → `content=` is the most natural guess.
- **Verbs prime the wrong fields.** `nodes/brain.py:143` and
  `nodes/executor.py:143, 220, 258` use prose like *"describe the
  gap"*, *"reason for the decision"*, *"message conveying the
  issue"*. These verbs prime `description=`, `reason=`,
  `message=` — three of the four aliases `rka_submit_checkpoint`
  already accepts. Brain learned aliases work; Brain did NOT learn
  the canonical name.

### 3.3 Why the orchestrator's existing alias surface is a treadmill

The orchestrator's `RestMCPClient` adapter at
`orchestrator/orchestrator/mcp_client.py:567-576` accepts
`description`, `message`, and `reason` as aliases for the body
field of `rka_submit_checkpoint`. The docstring at lines 547-551
explicitly admits this is empirical absorption of Brain emissions:
*"Brain-ism aliases tolerated: message → description (the Brain
LLM frequently emits message)"*. The Phase-D2.4 commit `2c7c59b`
added these aliases reactively after observing Brain mis-emit. The
adapter alias surface is **asymmetric across sibling tools**:

| Tool | Adapter accepts as body alias |
|---|---|
| `rka_submit_checkpoint` | `description`, `message`, `reason`, *positional `args[0]`* |
| `rka_submit_report` | `summary`, **`content`**, *positional `args[0]`* |
| `rka_add_decision` | **positional `content`** — TypeError on canonical `question=` |
| `rka_create_mission` | `objective` — no aliases |

The sibling tools were fixed in the same Phase-D2.4 commit, but the
alias surfaces ended up asymmetric. `rka_submit_report` accepts
`content`. `rka_submit_checkpoint` does not. **The asymmetry IS the
proximate bug**: a Brain extrapolating from `rka_submit_report` (or
from the `rka_add_note` worked example) will emit `content=` on
`rka_submit_checkpoint` and crash.

Adding `content` as a fourth alias closes the proximate bug. But
without the structural fix (validator + prompt enumeration), the
next field-name attractor (`body`, `text`, `message_text`) on
another tool repeats the pattern. The defensible posture is to add
`content` *for symmetry* AND add the structural fix.

### 3.4 Latent traps the audit surfaced

These are not active bugs today but are structurally equivalent
attractors that will surface under sufficient Brain creativity:

- **`rka_add_decision` adapter raises TypeError on canonical
  `question=`.** Adapter at `mcp_client.py:498-507` accepts
  `content` (positional) but RKA's canonical (server.py:466-477)
  is `question` (positional). If Brain reads canonical RKA docs
  and emits `question=`, the adapter raises
  `TypeError: unexpected keyword argument 'question'`. Same shape
  as today's bug, opposite direction. The adapter additionally
  drops canonical fields (`kind`, `options`, `chosen`,
  `parent_id`, `related_literature`, `assumptions`) — silent
  data-loss trap.
- **`rka_create_mission` adapter silently drops canonical
  `tasks`, `context`, `checkpoint_triggers`.** Adapter at
  `mcp_client.py:718-727` does not accept them. Brain emissions
  vanish — no error, no data, no diagnostic.
- **`rka_submit_report` schema-lie.** MCP signature exposes
  `summary: str` but `MissionReportCreate` in
  `rka/models/mission.py:65-78` has **no `summary` field**. The
  wrapper at `server.py:1313-1320` silently synthesizes
  `tasks_completed=[summary]`. Brain reading the canonical schema
  is misled about what's actually persisted.
- **`**kw` adapters silently drop typos.**
  `rka_add_note(confiednce='hypothesis')` is silently lost today.
  Want `ratified_action_unknown_kwarg` warning, not silent drop.
- **404 / 409 / 500 responses collapse to opaque
  `ratified_action_call_failed`.** Phase-X² enriched HTTP 422
  responses with structured Pydantic-validation detail; the same
  treatment for 404 / 409 / 500 would lift ID-prefix mistakes
  (404) and business-logic refusals (409) out of the catch-all
  bucket.
- **`_route_after_pi_decision` dead-end.** Same topology shape as
  the Phase-X² `_route_after_pi_greenlight` bug. Already filed in
  the Phase-X² deferred-followups; the audit confirms this is the
  same class of bug.

---

## 4. Goals + Non-goals

### 4.1 Goals

- **G1** — Close the field-NAME validation gap at the orchestrator
  layer (mirror of Phase-X² at the field-VALUE layer).
- **G2** — Eliminate the alias-surface asymmetry on
  `rka_submit_checkpoint` vs `rka_submit_report` (add `content`).
- **G3** — Ground Brain on canonical field names per tool with an
  explicit prompt block (symmetric to the Phase-X² enum-value
  block, including the "common Brain hallucination" callout
  pattern).
- **G4** — Improve PI diagnostic surface so the specific
  `error_type` and `failed_tool` surface on `pi_acceptance`
  payloads (without drilling into `errors[]`).
- **G5** — Land the structural root-cause fixes on RKA as
  backward-compatible v2.6.x patches: additive aliases,
  `Annotated[Literal[...]]` enum hints, docstring conventions,
  schema-lie fix on `rka_submit_report`.
- **G6** — Bookkeeper invariant intact: zero `rka/` changes from
  agentic; `from rka` / `import rka` grep-gate intact in
  `orchestrator/`.
- **G7** — Maintain first-class documentation throughout.

### 4.2 Non-goals

- **NG1** — Rename canonical RKA field names (v3.0 breaking
  change, out of scope).
- **NG2** — Pin a minimum RKA MCP-binary version in the
  orchestrator (separate, gated work — without it the adapter must
  continue accepting old-shape emissions for back-compat).
- **NG3** — Remove the orchestrator's defensive adapter aliasing
  (gated on NG2's resolution).
- **NG4** — Extend the validator to deeply recurse into nested
  structure (Pydantic's job; we only check top-level kwarg
  presence).
- **NG5** — Touch the active mission's workflow position or RKA
  domain truth (three-storage discipline intact).

---

## 5. Design — Three Layers, Two Branches, Eight Items

### 5.1 Layer 1 (agentic, xs) — `content`→`description` alias

**File:** `orchestrator/orchestrator/mcp_client.py:567-576`
+ docstring lines 547-551

**Change:** Extend the description-pop chain to accept `content` as
a fourth alias, symmetric with `rka_submit_report` at line 665:

```python
description = (
    kw.pop("description", None)
    or kw.pop("message", None)
    or kw.pop("reason", None)
    or kw.pop("content", None)   # NEW — symmetric with submit_report
    or (args[0] if args else None)
)
```

Docstring update: add `content → description` to the Brain-ism
alias list and note the symmetry with `rka_submit_report`.

**Rationale:** closes the proximate live bug; defensible on
symmetry grounds; pairs with Layer 2 and Layer 3 (alone it would
be a treadmill).

**Risk:** Low. Strictly additive; existing canonical callers
unaffected.

### 5.2 Layer 2 (agentic, s) — `TOOL_REQUIRED_FIELDS` validator

**File:** `orchestrator/orchestrator/rka_enums.py` (new section)
+ `orchestrator/orchestrator/nodes/executor.py:~928` (wire-in)

**Data structure:**

```python
TOOL_REQUIRED_FIELDS: dict[str, list[frozenset[str]]] = {
    "rka_add_note": [frozenset({"content"})],
    "rka_add_decision": [
        frozenset({"question", "content"}),   # adapter accepts both
        frozenset({"phase"}),
        frozenset({"decided_by"}),
    ],
    "rka_create_mission": [
        frozenset({"phase"}),
        frozenset({"objective"}),
    ],
    "rka_submit_checkpoint": [
        # Alias-set: any of {description, message, reason, content}
        # satisfies. Layer 1 adds content; this set reflects the
        # post-Layer-1 adapter surface.
        frozenset({"description", "message", "reason", "content"}),
        frozenset({"mission_id", "related_mission"}),  # canonical or legacy
        frozenset({"type"}),
    ],
    "rka_submit_report": [
        frozenset({"summary", "content"}),
        frozenset({"mission_id", "related_mission"}),
    ],
    "rka_ingest_document": [frozenset({"content"})],
    "rka_update_note": [frozenset({"id"})],
    "rka_update_mission_status": [
        frozenset({"id"}),
        frozenset({"status"}),
    ],
    "rka_bulk_update": [frozenset({"updates"})],
}
```

**Function:**

```python
def check_required_fields(tool: str, args: dict) -> list[str]:
    """Return a list of human-readable error reasons for any
    required-field-set that is NOT satisfied by `args`.
    Returns [] for unknown tool (open-world) — let the adapter
    deal with it. Returns [] when all sets satisfied.
    """
    required_sets = TOOL_REQUIRED_FIELDS.get(tool)
    if required_sets is None:
        return []   # open-world; not our concern
    errors: list[str] = []
    for required_set in required_sets:
        # Any field in the set satisfies — treat None as missing.
        if not any(
            args.get(field) is not None for field in required_set
        ):
            if len(required_set) == 1:
                (canonical,) = required_set
                errors.append(
                    f"{tool}: required field {canonical!r} is "
                    f"missing or None"
                )
            else:
                alts = sorted(required_set)
                errors.append(
                    f"{tool}: at least one of {alts} is required "
                    f"(all missing or None)"
                )
    return errors
```

**Wire-in:** `nodes/executor.py:~928` (immediately after the
existing enum-check block):

```python
missing_errors = check_required_fields(tool, resolved_args)
if missing_errors:
    for reason in missing_errors:
        errors.append(ErrorRecord(
            error_type="ratified_action_arg_missing_required_field",
            scope="execute_ratified_actions",
            details={"action_index": i, "tool": tool, "reason": reason},
            recovery_hint="..." ,
        ))
    continue   # skip this action; EC8 routing handles escalation
```

**Rationale:** structural mirror of Phase-X²'s enum-value
validator; same ErrorRecord-emission posture; same EC8 routing
integrates without graph changes (`graph.py:145-175` routes on
`node_name='execute_ratified_actions'`, not `error_type`).

**Risk:** alias-set semantics MUST consult Layer 1's adapter
alias table or the validator false-positives. The
`frozenset({"description", "message", "reason", "content"})`
shape is the resolution: any of the four satisfies. Lock-tests
prevent silent drift.

### 5.3 Layer 3 (agentic, s) — Canonical-name prompt block

**Files:** `orchestrator/orchestrator/nodes/brain.py:~118` +
`orchestrator/orchestrator/nodes/executor.py:~130` (parallel
inserts after the Phase-X² allowed-tools / enum-values block)

**Block content (proposed):**

```text
=== Canonical field names per WRITE_TOOL ===
Emit the canonical field names below. Some tools also accept
aliases for backward compatibility, but canonical names are
preferred for clarity and self-documenting code.

- rka_add_note: content (required)
- rka_add_decision: question (required, NOT content), phase, decided_by
- rka_create_mission: phase, objective
- rka_update_mission_status: id, status
- rka_submit_checkpoint: description (required, NOT content/message/reason —
  these are tolerated legacy aliases), mission_id, type
- rka_submit_report: summary (required, NOT content), mission_id
- rka_ingest_document: content
- rka_update_note: id, content
- rka_bulk_update: updates

Common Brain hallucination: emitting content= on
rka_submit_checkpoint. The canonical field is description. The
adapter tolerates content for backward compatibility but emit
description for clarity.
```

**Rationale:** closes the root cause at the LLM prompting layer.
Without this, the validator is a treadmill: Brain learns
`content` is wrong, but the next field-name attractor (`body`,
`text`, `message_text`) on another tool repeats the pattern. The
Phase-X² precedent (the `confidence='confirmed'` callout)
demonstrates that explicit negative callouts work.

**Risk:** prompt grows ~25 lines per system message. Token-budget
impact minimal (verified by Phase-X²'s enum-values block, which
added similar volume without incident).

### 5.4 Layer 4 (agentic, s) — PI diagnostic surface

**File:** `orchestrator/orchestrator/nodes/pi.py`
(`_compose_acceptance_summary` ~L233) + interrupt payload
builder

**Change:** Surface `latest_error_type`, `latest_failed_tool`,
`latest_checkpoint_reason` on the `pi_acceptance` interrupt
payload. Today the PI sees `error_count` prominently and must
drill into `errors[]` to find the specific failure (this is
already on the Phase-X² deferred-followups list as item (e)).

**Rationale:** pairs with Layer 2 — once the validator emits a
precise `error_type`, the PI cockpit should surface it without
drilling.

### 5.5 Layer 5 (main v2.6.1, s) — Additive aliases on three tools

**Files:** `rka/mcp/server.py` (3 functions)

**Change:** Accept `content` as an alias kwarg on
`rka_submit_checkpoint`, `rka_submit_report`, `rka_update_status`
(server-side, not just orchestrator-adapter side). Mapped to the
canonical body field. Collision rule: explicit canonical wins;
both supplied → 400 with diagnostic.

```python
async def rka_submit_checkpoint(
    mission_id: str,
    type: str,
    description: str | None = None,
    *,
    content: str | None = None,   # NEW — backward-compat alias
    ...
    project_id: str,
) -> str:
    """..."""
    if description is None and content is None:
        raise ValueError("rka_submit_checkpoint requires `description`")
    if description is not None and content is not None:
        raise ValueError("rka_submit_checkpoint: pass either "
                         "`description` or `content`, not both")
    description = description or content
    ...
```

**Rationale:** structural fix at the tool-surface layer. Once
landed, the orchestrator's defensive adapter aliases become a
soft-redundancy (kept for back-compat with old MCP binaries).

**Risk:** strictly additive; existing canonical callers
unaffected.

### 5.6 Layer 6 (main v2.6.1, m) — `Annotated[Literal[...]]` promotion

**Files:** `rka/mcp/server.py` (type hints on enum-typed params
across WRITE_TOOLS)

**Change:** Promote enum-typed parameters from `str` to
`Annotated[Literal["v1", "v2", ...], Field(description="...")]`
so FastMCP renders them into the tool's `inputSchema.properties.*
.enum` (LLM-readable structured schema).

Target parameters across WRITE_TOOLS: `type`, `confidence`,
`importance`, `source`, `kind`, `status`, `decided_by`,
`added_by`, `default_type`.

**Rationale:** root-cause fix at the tool-surface layer.
Eliminates the divergence between MCP tool surface (today:
docstring-only enums) and Pydantic models (already strict
Literals). After this lands, the orchestrator's manual mirror in
`rka_enums.py` becomes redundant for enum-VALUE coverage and can
be retired in a follow-up (gated on minimum-version pin).

**Risk:** type-hint change. Verify FastMCP renders the
`Annotated[Literal[...]]` form correctly into `inputSchema`.
Pydantic-validation behavior unchanged (already strict).

### 5.7 Layer 7 (main v2.6.1, s) — `rka_submit_report` schema-lie fix

**Files:** `rka/models/mission.py:65-78` (MissionReportCreate)
+ `rka/mcp/server.py:1313-1320` (wrapper)

**Change:** Add `summary: str | None = None` to
`MissionReportCreate` (nullable, no DB migration needed since
SQLite is schema-flexible and the wrapper persists into existing
columns). Remove the synthetic
`tasks_completed=[summary]` wrap; store `summary` in its own
column.

**Rationale:** Brain cannot self-correct from `/api/docs`
OpenAPI because the MCP signature *lies* about the underlying
schema. This is worse than other field-name divergences because
reading the canonical schema is misleading rather than just
under-specified.

**Risk:** additive; existing `tasks_completed=[summary]`
persistence path can be retained for one release as a fallback
to give downstream readers a migration window.

### 5.8 Layer 8 (main v2.6.1, xs+s) — Docstring sweep + cross-check test

**Files:** `rka/mcp/server.py` (all 9 WRITE_TOOLS) +
`docs/CONTRIBUTING.md` + new `tests/test_mcp_tool_surface.py`

**Change A — docstring convention sweep:** every WRITE_TOOLS
docstring summary line opens with `PRIMARY FIELD: <name>`. The
first body-field param description starts with the literal field
name. Add the convention to `CONTRIBUTING.md`.

**Change B — cross-check test:** new
`tests/test_mcp_tool_surface.py` uses `inspect.signature` +
Pydantic CreateModels from `rka/models/`. For every WRITE_TOOL,
assert: primary-body field name in MCP signature matches an
existing field in the underlying Pydantic CreateModel (or is
allowlisted as a synthetic MCP-only alias). This would have
caught the `rka_submit_report` schema-lie at CI time.

**Rationale:** zero behavioral change; pure LLM-grounding +
test-discipline signal. Brain reading the FastMCP-rendered
docstring would have its first guess anchored to the canonical
field.

### 5.9 Layer 9 (main v2.6.2, s) — 4xx/5xx response enrichment

**Files:** `rka/api/*` (response shape) +
`orchestrator/orchestrator/mcp_client.py:_request` (consumer)

**Change:** Extend Phase-X²'s 422 enrichment (already in place
since 291f6f8) to also parse 404 / 409 / 500 JSON bodies and lift
detail strings into `CheckpointError.reason`. Today these collapse
into the catch-all `ratified_action_call_failed` bucket with
opaque `HTTPStatusError` repr.

**Rationale:** diagnostic gap for ID-prefix mistakes (`mis_` vs
`prj_` → 404) and business-logic refusals (409). Orthogonal to
field-name divergence per se, but lives in the same
"shorten-the-diagnostic-chain" theme as the Phase-X²' polish PR.

**Risk:** low. Strict superset of current behavior; legacy
callers parsing raw `HTTPStatusError` still work.

---

## 6. Bookkeeper Invariant Analysis

### 6.1 Manual-mirror posture

`TOOL_REQUIRED_FIELDS` is a manual mirror of `rka/mcp/server.py`
WRITE_TOOLS signatures + `rka/models/*.py` Pydantic
CreateModel required-field sets. The orchestrator MUST NOT
`from rka import ...` to populate it (grep-gate invariant). The
mirror posture is identical to Phase-X²'s `RKA_CONFIDENCES`
posture.

### 6.2 Drift detection

Per-tool lock-tests in `orchestrator/tests/test_rka_enums.py`:

```python
def test_rka_add_note_required_fields():
    assert TOOL_REQUIRED_FIELDS["rka_add_note"] == [
        frozenset({"content"})
    ]

def test_required_fields_excludes_project_id():
    # project_id is dispatcher-injected; never appears in TOOL_REQUIRED_FIELDS
    for tool, sets in TOOL_REQUIRED_FIELDS.items():
        all_fields = set().union(*sets)
        assert "project_id" not in all_fields, tool
```

When the RKA schema rotates (a future migration adds a required
field), the orchestrator's mirror silently drifts; the failure
mode is REST 422 at the boundary (caught by Phase-X²'s 422
enrichment as a clean diagnostic). Drift is bounded by the
release-coordination cycle: any RKA change to WRITE_TOOLS
signatures must be paired with a manual update to
`TOOL_REQUIRED_FIELDS` (CHANGELOG entry will reference this when
relevant).

### 6.3 Grep-gate intact

The new module additions in `rka_enums.py` and the new tests in
`test_rka_enums.py` must NOT import from `rka`. The existing
AST-scan test (`test_module_does_not_import_rka`) already
enforces this for `rka_enums.py` and extends naturally to any
new orchestrator-side validator.

---

## 7. Test Plan

### 7.1 Layer 2 — validator unit tests (new file or extension of
`test_rka_enums.py`)

Mirror the 4 Phase-X² patterns:

- `test_check_required_fields_happy_path` — well-formed args
  return `[]`.
- `test_check_required_fields_missing_canonical` — empirical
  Run-5 analog: `rka_submit_checkpoint` missing the
  description-set → returns one error mentioning all aliases.
- `test_check_required_fields_alias_satisfies` — `{message:
  'foo'}` for `rka_submit_checkpoint` must NOT flag
  description-set as missing. (Pins alias-set semantics.)
- `test_check_required_fields_multi_missing` — `rka_add_decision`
  missing both `phase` and `decided_by` → returns 2 errors.
- `test_check_required_fields_unknown_tool_open_world` —
  unknown tool name returns `[]`.
- `test_check_required_fields_excludes_project_id` — invariant
  pin: `project_id` never appears in TOOL_REQUIRED_FIELDS.
- `test_check_required_fields_explicit_none_treated_as_missing`
  — `{description: None}` flagged the same as `{}`.
- Per-tool lock-tests (9 tools × 1 assertion each).

### 7.2 Layer 2 — dispatcher integration tests
(`tests/test_executor_dispatch.py` or new file)

- `test_dispatcher_emits_missing_required_field_error_record` —
  feed a `{tool: 'rka_submit_checkpoint', args: {mission_id:
  '...', type: 'decision'}}` (no description-alias). Assert the
  dispatcher emits `ratified_action_arg_missing_required_field`
  ErrorRecord; subsequent actions still dispatch
  (skip-and-continue semantics).
- `test_dispatcher_does_not_false_positive_on_alias` — feed
  `{tool: 'rka_submit_checkpoint', args: {message: 'foo',
  mission_id: '...', type: 'decision'}}`. Assert no missing-field
  error; dispatcher proceeds to the adapter.

### 7.3 EC8 routing tests

The new ErrorRecord type integrates with EC8 partial-dispatch
routing without graph changes. Confirm:

- `test_ec8_routes_missing_required_field_via_escalation_router`
  — single proposed action with missing required field →
  escalation_router → pi_acceptance.
- `test_ec8_partial_dispatch_with_one_missing_field` — PA-1 ok,
  PA-2 missing required field → checkpoint emitted with
  diagnostic; PA-1 write landed; PA-2 not dispatched.

### 7.4 Regression test for today's bug

- `test_brain_emits_content_on_submit_checkpoint_caught_pre_dispatch`
  — recreates the empirical hyperscaler-auditing scenario. Feed
  `{tool: 'rka_submit_checkpoint', args: {content: 'foo',
  mission_id: '...', type: 'decision'}}`. Assert: with Layer 1
  alone, this would have succeeded (alias absorbed). With Layer
  1 + Layer 2 only, this succeeds. With Layer 2 alone (no Layer
  1 alias), this is caught pre-dispatch with a clear error
  mentioning all four accepted aliases. Pins the Layer 1 + Layer
  2 collaboration.

### 7.5 Prompt-block tests (Layer 3)

- `test_brain_system_includes_canonical_field_block` — assert
  the prompt includes a section mentioning canonical names for
  all 9 WRITE_TOOLS.
- `test_brain_system_warns_against_content_on_submit_checkpoint`
  — pin the explicit negative callout.

### 7.6 PI diagnostic tests (Layer 4)

- `test_pi_acceptance_surfaces_latest_error_type` — pi_acceptance
  payload includes `latest_error_type`,
  `latest_failed_tool`,
  `latest_checkpoint_reason` when errors are present.
- `test_pi_acceptance_empty_when_no_errors` — fields are absent
  or `null` when `error_count == 0`.

### 7.7 Cross-check test (Layer 8, main v2.6.1)

- `test_mcp_tool_surface_matches_pydantic_model` — for every
  WRITE_TOOL, assert primary-body field name in MCP signature
  appears in the underlying Pydantic CreateModel (or is on a
  small allowlist of synthetic aliases). Would catch
  `rka_submit_report` schema-lie at CI time.

### 7.8 Test count delta

- Layers 1-4 (agentic polish PR): +25 to +30 tests.
- Layer 5-8 (main v2.6.1): +15 to +20 tests.
- Layer 9 (main v2.6.2): +5 tests.

Test floor in `test_invariants.py` will need bumping in lockstep.
Current floor: 1148 (post-Phase-X²). Post-Phase-X²' polish:
~1175. Post-v2.6.1: ~1190. Post-v2.6.2: ~1195.

---

## 8. Trade-offs and Risks

### 8.1 Treadmill risk

**Risk:** shipping Layer 1 alone (alias-only) without Layers 2
and 3 leaves the next field-name attractor (`body`, `text`,
`message_text`) on a different tool exposed. The polish PR MUST
bundle all three layers or skip the alias entirely.

**Mitigation:** the Phase-X²' polish PR (agentic) bundles Layers
1-4 atomically. Lock-tests in Layer 2 pin the alias-set
semantics to the Layer 1 adapter surface.

### 8.2 Validator false-positives

**Risk:** the TOOL_REQUIRED_FIELDS validator must consult the
adapter's alias table or it false-positives on legitimate calls.
A naive `frozenset({"description"})` would flag a valid
`{message: 'foo'}` call as missing.

**Mitigation:** declare required fields as `list[frozenset[str]]`
(alias-set-of-sets); any field in the set satisfies. Explicit
lock-test
`test_check_required_fields_alias_satisfies` pins this.

### 8.3 Manual-mirror drift

**Risk:** TOOL_REQUIRED_FIELDS is a manual mirror. A future RKA
migration that adds a required field to a Pydantic CreateModel
silently passes the orchestrator validator; the failure surfaces
at REST 422.

**Mitigation:** Phase-X²'s 422 enrichment already lifts the
Pydantic-validation detail into the CheckpointError reason
string. Drift is bounded by the release-coordination cycle —
RKA WRITE_TOOLS signature changes must be paired with manual
TOOL_REQUIRED_FIELDS updates (documented in CHANGELOG).

### 8.4 Prompt token-budget impact

**Risk:** Layer 3 grows BRAIN_SYSTEM ~25 lines (today ~150 lines)
and EXECUTOR_SYSTEM ~25 lines (today ~250 lines). Cumulative cost
across thousands of LLM calls is non-trivial.

**Mitigation:** Phase-X² added similar enum-value blocks (~30
lines) without measurable token-budget impact. Layer 3 follows
the same posture; cost is amortized across many calls.

### 8.5 Alias-only fix on main without orchestrator-side prompt
+ validator

**Risk:** if the main-side Layer 5 (additive aliases) ships
without the agentic-side Layers 2 and 3, Brain continues to mis-
emit at the prompt layer; the adapter aliases absorb but the
orchestrator's diagnostic surface remains opaque.

**Mitigation:** roadmap sequences agentic polish BEFORE main
v2.6.1. Even if main v2.6.1 ships first, the agentic polish is
still valuable.

### 8.6 v2.6.x-only commitment

**Risk:** Layer 6 (`Annotated[Literal[...]]` promotion) is a
type-hint refinement, NOT a breaking change. But it changes the
FastMCP `inputSchema` rendering. Downstream consumers (LLMs,
SDKs) that depend on the previous schema shape may behave
differently — generally for the better (stricter validation),
but the change is observable.

**Mitigation:** the FastMCP rendering change is the *intended*
benefit (LLM-readable enums). Test coverage in Layer 8's
cross-check test (`test_mcp_tool_surface_matches_pydantic_model`)
verifies the rendered schemas remain consistent.

### 8.7 Orchestrator defensive aliasing becomes soft-redundant

**Trade-off:** after main v2.6.1 lands, the orchestrator's
adapter aliasing (`mcp_client.py:528-622`) becomes a soft
redundancy — the server now accepts `content=` natively. The
adapter aliasing should NOT be removed until the orchestrator
pins a minimum RKA MCP-binary version. Documented as
deferred-followup.

---

## 9. Latent Traps Banked for Future Work

Filed in `CLAUDE.md` deferred-followups; each warrants its own
PR if/when prioritized:

1. **`rka_add_decision` adapter expansion** — accept canonical
   `question`, `options`, `chosen`, `parent_id`,
   `related_literature`, `kind`, `assumptions` kwargs. Keep
   `content` as back-compat alias.
2. **`rka_create_mission` adapter expansion** — accept `tasks`,
   `context`, `checkpoint_triggers` (currently silently absent;
   TypeError on canonical names).
3. **`**kw` adapter tightening** — convert silent-drop on
   unknown kwargs to `ratified_action_unknown_kwarg`
   warning-class ErrorRecord. Narrow scope: `rka_add_note` /
   `rka_update_note` / `rka_ingest_document` /
   `rka_update_mission_status` / `rka_submit_checkpoint` /
   `rka_submit_report`.
4. **Pre-dispatch ID-prefix validator** — new module
   `orchestrator/orchestrator/rka_id_prefixes.py` catches
   `mission_id='dec_01...'` before 404. Single
   source-of-truth for canonical prefixes (jrn_, lit_, dec_,
   mis_, clm_, ecl_, chk_, prj_, lnk_, scn_) per CLAUDE.md.
5. **Pre-dispatch type-shape validator** — catch
   `acceptance_criteria='one string'` when `list[str]` expected.
   Top-level kwargs only.
6. **`_route_after_pi_decision` dead-end** — Phase-X² sibling
   bug. `pi_decision_select` is the TWO-TAP autonomy-licensing
   gate; fix deserves isolated PR for autonomy-contract review.
7. **WRITE_TOOLS formatting unification** — `brain.py:120`
   sorts the WRITE_TOOLS list; `executor.py:131` does not.
   Cosmetic but indicates organic drift.
8. **Minimum RKA MCP-binary version pin** — gating step for
   removing the orchestrator's defensive adapter aliasing.

---

## 10. Acceptance Criteria

For the agentic-side Phase-X²' polish PR:

- [ ] `mcp_client.py` accepts `content` as a fourth alias on
      `rka_submit_checkpoint`; docstring updated; symmetric with
      `rka_submit_report`.
- [ ] `rka_enums.py` exports `TOOL_REQUIRED_FIELDS` and
      `check_required_fields`; AST-scan invariant intact
      (no `from rka` imports).
- [ ] `nodes/executor.py:execute_ratified_actions` wires
      `check_required_fields` after the existing enum check;
      emits `ratified_action_arg_missing_required_field`
      ErrorRecord; integrates with existing EC8 routing.
- [ ] `nodes/brain.py:BRAIN_SYSTEM` and
      `nodes/executor.py:EXECUTOR_SYSTEM` include the canonical-
      field-name block with explicit "common Brain hallucination"
      callout.
- [ ] `nodes/pi.py:_compose_acceptance_summary` surfaces
      `latest_error_type`, `latest_failed_tool`,
      `latest_checkpoint_reason` on pi_acceptance payload.
- [ ] All Layer 2-4 unit + integration tests pass.
- [ ] Test count delta matches expectations (+25 to +30).
- [ ] `test_invariants.py` floor bumped to ~1175.
- [ ] CLAUDE.md "Phase-X²' polish" section added documenting the
      validation chain.
- [ ] CHANGELOG.md updated under `[agentic]` Unreleased section.
- [ ] `git diff main -- rka/` returns empty (bookkeeper
      invariant intact).
- [ ] `grep -rn "from rka\|import rka" orchestrator/` returns
      empty (grep-gate intact).

For the main-side v2.6.1 PR:

- [ ] `rka_submit_checkpoint`, `rka_submit_report`,
      `rka_update_status` accept `content` as additive alias
      server-side; collision rule documented.
- [ ] WRITE_TOOLS enum-typed parameters promoted to
      `Annotated[Literal[...], Field(description=...)]` shape.
- [ ] `MissionReportCreate` has a real `summary` field; schema-
      lie wrapper retired.
- [ ] WRITE_TOOLS docstrings open with `PRIMARY FIELD: <name>`
      convention; `CONTRIBUTING.md` updated.
- [ ] `tests/test_mcp_tool_surface.py` exists and pins MCP-
      surface vs Pydantic-model alignment.
- [ ] `pyproject.toml` + `rka/__init__.py` version bumped to
      2.6.1.
- [ ] CHANGELOG.md `[2.6.1]` section drafted.

For the main-side v2.6.2 PR:

- [ ] `RestMCPClient._request` parses 404 / 409 / 500 JSON
      bodies and lifts detail into `CheckpointError.reason`.
- [ ] Regression tests for each new status-code branch.
- [ ] `pyproject.toml` + `rka/__init__.py` version bumped to
      2.6.2.
- [ ] CHANGELOG.md `[2.6.2]` section drafted.

---

## 11. Cross-References

- Phase-X² polish (commit 291f6f8, 2026-05-31) — sibling validator
  at the field-VALUE layer. CLAUDE.md "Phase-X² polish —
  validation-chain hardening".
- Phase-X — Cross-Run Correction Channel
  (`cross-run-correction-channel.md`) — earlier validation-chain
  hardening for a different failure class (PI redirect
  durability). Same bookkeeper-invariant + three-storage posture.
- Empirical event: hyperscaler-auditing mission
  `mis_01KSTWTJNZMV3893S2FWG4HBYZ`, PA-2 dispatch failure
  2026-06-01.
- Audit workflow `wjyk2x82n` (2026-06-01) — 5-facet discovery +
  synthesis that produced this design.
- Bookkeeper invariant tests:
  `orchestrator/tests/test_invariants.py` —
  `test_bookkeeper_invariant_rka_untouched_by_agentic`,
  `test_module_does_not_import_rka` (AST scan).
