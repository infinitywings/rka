# Executor — Worked Examples

Concrete examples for the Executor skill. Load when you need to see the shape of a good Backbrief or report, or compare good-vs-bad escalation timing.

---

## Backbrief — Bug B URL Fix

Mission: *"Fix the entity_links edge type mismatch — `related_journal` on decisions creates `references` instead of `justified_by`."*

Executor Backbrief:

> Before I start, here's my plan:
>
> **Plan**: I'll investigate `DecisionService.create()` and `update()` in `rka/services/decisions.py` to find where `entity_links` rows get `link_type='references'` instead of `'justified_by'`. Then fix the code and write a migration to repair existing edges.
>
> **Acceptance criteria interpretation**: "`justified_by` edge count matching decisions with `related_journal`" means every decision with a non-null `related_journal` should have at least one `justified_by` edge in `entity_links`.
>
> **Assumptions**:
> 1. The `entity_links` table schema doesn't need changes — only the `link_type` values (per mission assumption #1).
> 2. The migration converts `references` → `justified_by` only for decision↔journal pairs, not ALL `references` edges.
> 3. `NoteService` and `MissionService` may have the same bug — I'll check them too.
>
> **Risks**: The migration could incorrectly convert `references` edges that are genuinely references. I'll scope it to only edges where source is a decision and target is a journal entry.
>
> **Approach**: modify files `decisions.py`, `notes.py`, `missions.py`; write migration `012_fix_entity_link_types.sql`; verify with `pytest tests/test_services/test_decisions.py` + live migration dry-run.
>
> Does this look right?

Then record the Backbrief as a journal note with `tags=["backbrief"]` and wait for Brain approval.

---

## Reports — Good vs Bad

### BAD report

```
summary: "Fixed the bug."
findings: "The bug is fixed."
anomalies: ""
```

Unreviewable. The Brain can't verify anything without reading the diff. Defeats the purpose of structured reporting.

### GOOD report

```
summary: "Root cause was query-param vs path-param mismatch at rka/mcp/server.py:2660.
The tool called GET /api/graph/ego?entity_id=X but the route is defined as
/graph/ego/{entity_id} — FastAPI returned 404 which surfaced as empty result.
Fixed with one-line URL construction change; verified via curl and MCP live call."

findings:
"One-line fix at server.py:2660 resolves the URL mismatch.
Decision trace returns 56 nodes / 65 edges post-fix.
Cluster trace still returns 0 nodes (separate bug — claim_edges not walked in ego graph)."

anomalies:
"Runtime Docker image lacks pytest; test suite runs via ad-hoc docker cp + pip install.
17 pre-existing test failures unrelated to this fix."

questions:
"Cluster-provenance gap is a separate pre-existing bug — follow-up mission or bundle into this one?"

codebase_state: "..."
recommended_next: "..."
```

Reviewable. Each claim has a testable anchor (file:line, wall-time, count). Anomalies flagged. Open question surfaced for Brain.

---

## Checkpoint Timing — Too Late vs Just Right

### TOO LATE

```
[After 3 hours of coding]
Executor: "I ran into a scope issue — I had to expand to also refactor NoteService
          and update 40 test files to match. Here's the 2000-line diff."
```

The Brain now has to review 2000 lines to decide if the expansion was warranted. The Executor spent 3 hours that might have been rejected.

### JUST RIGHT

```
[After 10 minutes of investigation]
Executor: [rka_submit_checkpoint type="decision"]
  "Completing the DecisionService fix requires also touching NoteService and
   MissionService — they share the bug. Scope expansion per the 'Must Escalate'
   rule. Three options: (1) expand scope to all three, (2) this mission only
   fixes Decision, (3) split into three missions. Recommendation: option 1."
Brain: [resolves with option 1 in ~5 min]
Executor: [proceeds with approved expanded scope]
```

Total turnaround ~15 minutes; Brain has context to make the call; no wasted work.

---

## Good vs Bad Tagging on Journal Notes

### BAD

```python
rka_add_note(
    content="Fixed the bug.",
    type="log",
    tags=["interesting", "important", "need-to-remember", "todo-followup",
          "pi-asked-about-this", "see-also-mission-123", "bug"],
)
```

Opinion tags, not categories. No category that surfaces usefully in search. Length and miscellany signal indecision.

### GOOD

```python
rka_add_note(
    content="Fixed URL construction bug in rka_trace_provenance; see commit ca53cb1.",
    type="log",
    source="executor",
    related_mission="mis_01KPE5168149A9HC1MT2NMTF6H",
    importance="normal",
    tags=["bug-fix", "mcp", "provenance"],
)
```

Three load-bearing tags, each suggesting a useful search. `importance` is a field, not a tag. Mission link is in `related_mission`, not a tag.

---

## When NOT to Backbrief — A Trivial Hotfix

Mission: *"Change pyproject.toml version from 2.1.0 to 2.2.0-dev."*

**WRONG** — over-backbriefing:

> Before I start, here's my plan:
> **Plan**: I'll edit line 3 of pyproject.toml to change the version string.
> **Acceptance criteria interpretation**: The version string must be "2.2.0-dev" exactly.
> **Assumptions**: (1) pyproject.toml is in the repo root. (2) No other files reference this version.
> **Risks**: None.
> **Approach**: Use the Edit tool on the exact string.
> Does this look right?

The 5-line diff doesn't need 15 lines of ceremony. Just do it. Document in the report.

**RIGHT** — just do it:

> [edit applied]
> [commit + push]
> [report submitted — includes the commit SHA and mentions grep of other version references]

---

## Related

- Every-mission discipline: `SKILL.md`.
- Full Backbrief / Report / Escalation procedures + migration registry + MCP reinstall: `workflows.md`.
- Brain counterpart: `../brain/SKILL.md`.
