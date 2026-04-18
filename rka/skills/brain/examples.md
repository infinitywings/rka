# Brain — Worked Examples

Concrete examples for the discipline patterns in `SKILL.md`. Each example contrasts the WRONG shape with the CORRECT one so the right move is obvious at a glance.

---

## PI Attribution — Preserving the PI's Voice

When the PI says something strategic, you MUST preserve their exact words.

### The rule

- Set `source: "pi"` (not `"brain"`).
- Set `verbatim_input` to the PI's exact words.
- Put YOUR analysis in `content`.
- These are different things. The PI's words are ground truth; your analysis derives from them.

### Worked example — full contrast

PI says: *"I think the RL score calculation will be an important task, you need to expand it."*

**CORRECT:**

```python
rka_add_note(
    content="Brain analysis: The PI directed that CRSI should be elevated "
            "from an engineering filter to a formal methodological contribution. "
            "This reframes Aim 1 of the proposal around calibrated reward signals "
            "rather than generic scoring…",
    source="pi",
    verbatim_input="I think the RL score calculation will be an important task, you need to expand it",
    related_decisions=["dec_01KMVSP1..."],
)
```

**WRONG:**

```python
rka_add_note(
    content="The RL score calculation should be expanded into a formal methodology…",
    source="brain",   # ← PI's insight erased, attributed to Brain
)
```

The WRONG version makes the Brain look like the originator. Three months later no one can tell this was a PI insight. Provenance broken.

### `decided_by` rule

- PI directed a specific choice → `decided_by: "pi"`.
- You recommended and the PI approved → `decided_by: "pi"` (it's their call).
- You made a technical choice the PI didn't weigh in on → `decided_by: "brain"`.

---

## Confirmation Brief — Privacy-Aware Decomposition Pivot

PI says: *"I think we should pivot the paper to focus on privacy-aware task decomposition instead of model routing."*

Brain responds naturally in conversation — not a rigid checklist:

> Let me make sure I understand your direction:
>
> **Intent**: Reframe the paper's primary contribution from optimal model routing (already well-studied) to making data sensitivity a first-class constraint in task decomposition (genuinely novel).
>
> **Assumptions**:
> 1. The existing Brain/Executor architecture remains — we're reframing, not redesigning.
> 2. The formal model stays but sensitivity becomes the key constraint variable.
> 3. Prior work on model routing moves to "related work" rather than "our approach."
>
> **Scope**: This affects the introduction, related work, problem formulation, and evaluation sections. Experimental baselines may need updating.
>
> **Success criteria**: The paper clearly articulates why privacy-aware decomposition is distinct from model routing, with at least one formal property that doesn't hold under naive routing.
>
> Does this match your intent, or should I adjust?

After PI confirms or corrects, record the confirmed understanding:

```python
rka_add_note(
    content="Confirmed PI direction: Reframe paper contribution from model routing to "
            "privacy-aware task decomposition. [detailed confirmed understanding]",
    source="pi",
    verbatim_input="I think we should pivot the paper to focus on privacy-aware task decomposition instead of model routing",
    type="directive",
    tags=["confirmation-brief"],
    related_decisions=["dec_01..."],
)
```

Note the `confirmation-brief` tag — it makes these findable via `rka_search(query="confirmation-brief", entity_types=["journal"])` when the Executor wonders why a mission's intent looks the way it does.

---

## Session Opener — Natural vs Narrated

The session-start protocol runs silently; the greeting to the user should feel natural.

**CORRECT:**

> Hi! I've caught up on the project. The research map has 5 active research questions — the CRSI methodology cluster just reached "strong" confidence, and there's a contested cluster on broker-limit experiments that I'd like to walk through with you. Where would you like to start?

**WRONG:**

> I'm now going to run `rka_set_project`, then `rka_get_changelog`, then `rka_get_pending_maintenance`, then process 3 decisions without justified_by links, then…

The PI does not need narration of graph bookkeeping. Tool-call narration is noise.

---

## Good vs Bad Tags

Tags support search and filtering. They are not a comment channel.

**GOOD tags:**
- `["mqtt", "scalability", "broker-limits"]` — subject matter.
- `["confirmation-brief", "research-protocol", "gate-0"]` — structural role.
- `["v2.2", "phase-1a", "thread-2"]` — project-phase milestones.

**BAD tags:**
- `["interesting", "todo", "check-this-later"]` — opinion, not category.
- `["asked-by-pi"]` — use `source:"pi"` + `verbatim_input`, not a tag.
- `["important"]` — use `importance` field (`critical | high | normal | low`).
- 30 tags on one entry — pick 3–5 load-bearing categories. Taglists longer than 5 are usually a sign of indecision.

---

## Common Anti-Patterns — Before/After

### Anti-pattern: missing `justified_by`

**Before:**
```python
rka_add_decision(
    question="Use PostgreSQL or SQLite?",
    chosen="SQLite",
    rationale="Simpler for local-first deployment.",
    # related_journal missing
)
```

Decision is orphan. Three months later, "why SQLite?" has no answer in the graph.

**After:**
```python
rka_add_decision(
    question="Use PostgreSQL or SQLite?",
    chosen="SQLite",
    rationale="Simpler for local-first deployment.",
    related_journal=["jrn_01...benchmarks", "jrn_01...deployment-survey"],
)
```

Now the decision has a reasoning chain. The maintenance manifest's `decisions_without_justified_by` count is one lower.

### Anti-pattern: bundling independent tasks

**Before:**
```python
rka_create_mission(
    objective="Fix search bug, update README, and audit test coverage",
    ...,
)
```

Three unrelated objectives merged. Can't cancel one without cancelling all; Executor's Backbrief can't cleanly address the mission.

**After:**
```python
rka_create_mission(objective="Fix search bug: root-cause + fix + test", motivated_by_decision="dec_...", ...)
rka_create_mission(objective="README accuracy pass", motivated_by_decision="dec_...", ...)
rka_create_mission(objective="Audit test coverage; open issues for gaps", motivated_by_decision="dec_...", ...)
```

Three missions, three acceptance-criteria sets. Parallel-capable if the Executor is.

### Anti-pattern: canonicalizing a generated summary

**Before:**
```python
rka_ask(query="What are the main findings on broker limits?")
  → "The main findings are: 1) packet loss increases above 400 connections…"
# Brain paraphrases the summary into a decision rationale.
rka_add_decision(rationale="Findings show packet loss above 400…", ...)
```

The summary was disposable LLM output. Baking it into a decision rationale canonizes a source that doesn't exist in the knowledge graph.

**After:**
```python
# Brain reads the actual clusters + claims.
rka_get(id="ecl_01...broker-limits")
# Then writes rationale with citable claim IDs.
rka_add_decision(
    rationale="Cluster ecl_01...broker-limits shows packet loss above 400 connections "
              "(clm_01..., clm_02...); sharding proposal is justified by…",
    related_journal=[…],
    ...,
)
```

Summaries are navigational aids. They are not knowledge.

### Anti-pattern: long search queries

**Before:**
```python
rka_search(query="what are the scalability tradeoffs between MQTT and AMQP in IoT deployments with many sensors")
# Returns empty — FTS5 over-narrows with long phrases.
```

**After:**
```python
rka_search(query="MQTT scalability")
# Returns relevant hits. Refine by iterating on 2–4 word queries.
```

Keep queries to 2–4 words. Long queries behave worse than intuitive.

---

## Related

- Top-level rules: `SKILL.md`.
- Three-actor model + 12-type provenance vocabulary: `architecture.md`.
- Procedures (session start, claim extraction, cluster mgmt, gates, freshness): `workflows.md`.
- Multi-choice decision UX + Confirmation Brief template: `decision_ux.md`.
