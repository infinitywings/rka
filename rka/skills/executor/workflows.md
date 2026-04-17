# Executor — Workflows

Procedural reference for the Executor skill. Loaded on demand when `SKILL.md` points here. Keeps every-mission discipline at the top-level and the detailed procedures here.

---

## Backbrief Format — Full Template

Before starting significant implementation work, present a Backbrief to the Brain. Five required elements:

1. **Plan summary** — "I will accomplish this by doing X, Y, Z."
2. **Acceptance criteria interpretation** — "I interpret the acceptance criteria to mean [specific interpretation]."
3. **Assumptions** — numbered list, referencing mission assumptions where applicable.
4. **Risks** — including any that might require scope changes.
5. **Approach** — which files will be modified, how will it be tested.

After presenting, WAIT for Brain approval, correction, or recycle before beginning implementation. Record the Backbrief as a journal note linked to the mission:

```python
rka_add_note(
    content="Executor Backbrief for mission mis_01...: [plan summary, assumptions, risks]",
    type="log",
    source="executor",
    related_mission="mis_01...",
    tags=["backbrief"],
)
```

Worked example: `examples.md` § "Backbrief — Bug B URL fix".

### When NOT to Backbrief

- Trivial tasks (single file edit, simple config change, documentation fix).
- Tasks the Brain explicitly said "just do it" for.
- Follow-up tasks where the approach was already approved in an earlier Backbrief.

---

## Report Submission — Full Section Structure

Use `rka_submit_report` with structured sections:

- **`summary`** — full narrative of what was done, methodology, results. This is the main report body.
- **`findings`** — key findings, one per line.
- **`anomalies`** — unexpected observations or issues.
- **`questions`** — open questions for the Brain or PI.
- **`codebase_state`** — state of the codebase after the mission.
- **`recommended_next`** — suggested next steps as a single string.

Write the summary as you'd write a PR description: what changed, what you found, how you verified it. The structured sections are for scanning; the summary is for deep reading.

Good/bad report contrast: `examples.md` § "Reports — Good vs Bad".

---

## Escalation Triggers — Detailed Examples

### Must Escalate (type="decision")

**Assumption invalidation** — an assumption from the mission turns out to be false:

> "Mission assumes `entity_links` has no FK constraints, but it does — the additive-only migration plan needs revision."

**Scope expansion required** — completing the task properly requires changes outside the stated scope:

> "To fix `DecisionService`, I also need to fix `MissionService` and `NoteService` — expanding scope. Also: the schema column they all use has a different name than the mission assumed."

**Contradictory results** — experiment results contradict the expected outcome or existing knowledge:

> "Migration converted 80 edges but maintenance still reports 29 decisions without `justified_by` — the conversion logic isn't finding all the rows the Brain expected."

### Should Escalate (type="clarification")

**Ambiguous acceptance criteria** — multiple valid interpretations exist and the choice matters:

> "Acceptance says 'export succeeds' but doesn't specify whether empty tables are valid or require skipping. Both interpretations are defensible; the choice changes the schema of the exported archive."

**Missing context** — information referenced in the mission doesn't exist or can't be found:

> "Mission references `dec_01KPE2QWY...` but that ID isn't in the DB. Either it was deleted or the mission context has a typo."

**Unexpected complexity** — task is significantly more complex than the mission anticipated:

> "Mission estimates ~1 day; root-cause investigation shows this is a 3-day refactor because the bug involves the shared HTTP client, not just the PUT wrappers."

### Can Proceed — Document in Report

- Technical choices within scope (which library, which algorithm, which test approach).
- Minor bugs found and fixed along the way.
- Performance optimizations that don't change behavior.
- Code quality improvements in files you're already modifying.

Don't checkpoint for these — log them in the report's `anomalies` section.

---

## Your Counterpart: The Brain

### What the Brain Provides in Missions

- `motivated_by_decision` — the decision that triggered this work. Read it with `rka_get(id="dec_...")` to understand WHY.
- `context` field — follows INTENT / BACKGROUND / CONSTRAINTS / ASSUMPTIONS / VERIFICATION. Contains related journal/decision/literature IDs. Read these before starting.
- `acceptance_criteria` — testable assertions you must verify before submitting a report.
- `scope_boundaries` — what NOT to do. Respect these strictly.
- `checkpoint_triggers` — explicit triggers the Brain wants you to escalate on.

### Gate 1: Plan Validation

For significant missions, the Brain may create a Gate 1 (`plan_validation`) checkpoint that formally records the Backbrief approval. This gate blocks until the Brain evaluates your plan. When you see a gate checkpoint on your mission, present your Backbrief and wait for the Brain to evaluate it with `rka_evaluate_gate`. The gate verdict (`go` / `kill` / `hold` / `recycle`) determines whether you proceed, revise, or stop.

### The Confirmation Brief — Why Your Missions Are Vetted

Before creating your mission, the Brain verified its understanding of the PI's intent through a Confirmation Brief — restating the PI's direction and getting explicit correction. This means:

- The mission's objectives have been validated against the PI's actual intent.
- The numbered assumptions in the mission context have been reviewed by the PI.
- If the mission still seems confusing or contradictory, that's a signal to raise a checkpoint — the Confirmation Brief may have missed something.

Find the Confirmation Brief via `rka_search(query="confirmation-brief", entity_types=["journal"])`.

### When to Raise a Checkpoint vs Proceed

- Strategic ambiguity (which approach?) → checkpoint `type="decision"`.
- Missing information (what did the PI mean?) → checkpoint `type="clarification"`.
- Work needs review before continuing → checkpoint `type="inspection"`.
- Technical choice within scope → proceed, document in report.

---

## Migration Table Registry

When writing a migration that creates a new table with a `project_id` column, you MUST also add it to `_TABLE_CATEGORIES` in `rka/services/knowledge_pack.py`. Choose the correct category:

- **`core_data`** — research knowledge that MUST be preserved (journal, decisions, claims, clusters, decision_options, calibration_outcomes, etc.).
- **`derived_data`** — can be rebuilt if missing (review_queue, topics, exploration_summaries).
- **`system`** — infrastructure tables not exported (jobs, kv_store, schema_migrations).
- **`bulk_logs`** — large log tables exported only on request (audit_log, events).

If you skip this step, the pre-export validation will fail with an explicit error — but catching it at development time is better than catching it at export time.

Supporting plumbing that usually goes with a new `core_data` entry: `_INSERT_ORDER` (FK-safe position), `_ID_ENTITY_TYPES` (singular-form entity name), `_DIRECT_ID_COLUMNS` (columns whose values must be remapped during import). See migration 017 commit `b577211` for the canonical pattern.

---

## MCP Binary Reinstall

After ANY code changes to `rka/` source that affect the MCP layer:

```bash
cd /path/to/rka
uv tool uninstall rka
rm -rf /tmp/uv-cache
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force --reinstall .
```

Plain `uv tool install --force .` uses cached wheels and does NOT pick up changes.

After the reinstall, the PI needs to restart Claude Desktop (and you need to restart Claude Code) for the MCP subprocess to pick up the new binary. A subprocess spawned against the pre-reinstall binary keeps the old file handle through the replacement and runs stale code.

---

## Related

- Every-mission discipline (role, session start, Backbrief rule, escalation categories, guardrails): `SKILL.md`.
- Worked examples (Backbrief, reports, checkpoint timing): `examples.md`.
- Brain counterpart skill: `../brain/SKILL.md`.
