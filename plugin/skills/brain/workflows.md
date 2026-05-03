# Brain — Workflows

Procedural reference for the Brain skill. Each section is a self-contained workflow loaded on demand when the top-level `SKILL.md` points here.

---

## Session Start — Full Walkthrough

The `SKILL.md` body lists the 6-step checklist. Here is the expanded worked example.

```
Brain: rka_set_project("prj_01KKQM9JFG67GT5FGWTAHD9YE4")
Brain: rka_get_status()
  → Phase: design, 31 decisions, 145 entries, 5 missions
Brain: rka_get_changelog(since="2026-04-10")
  → 12 new journal entries, 3 new decisions, 2 literature added
Brain: rka_get_pending_maintenance()
  → 12 items: 3 decisions without justified_by, 2 unassigned clusters, 7 entries without tags
Brain: [silently processes top-priority items, budget=10]
  - For each decision_without_justified_by: rka_update_decision(id, related_journal=[...])
  - For each unassigned_cluster: rka_review_cluster(id, research_question_id=...)
Brain: rka_get_research_map()
  → 5 RQs, 104 clusters, 549 claims
Brain: "Hi! I've caught up on the project. The research map has 5 active research questions…"
```

**Why the order matters**: changelog before maintenance so the Brain knows what's new before deciding what to fix. Maintenance before the research map so the map view is coherent. The user sees none of the fix-up calls — narrating maintenance to the PI is noise.

## Research Protocol — Gate 0 (Project Start / Major Pivot)

Before opening a new research direction, the Brain and PI should co-author a Research Protocol as a `directive` journal entry tagged `research-protocol`. This is the contract against which all subsequent decisions, missions, and findings are evaluated.

**When to create a protocol:**
- Starting a new research project.
- Opening a new research question.
- Making a major methodological change.
- Pivoting research direction based on new evidence.

**Template:**

```python
rka_add_note(
    content="""
    # Research Protocol: [Title]

    ## Research Question
    [Precise, testable question]

    ## Scope
    - IN: [what this research covers]
    - OUT: [what is explicitly excluded]

    ## Key Assumptions (numbered)
    1. [Assumption — what we take as given]
    2. [Assumption]
    3. [Assumption]

    ## Success Criteria
    - [What "answered" looks like — specific, testable]
    - [Minimum evidence threshold]

    ## Methodology
    - [Approach: literature review, experiment, prototype, survey, etc.]
    - [Data sources]
    - [Validation method]

    ## Known Risks
    - [Risk 1 and mitigation]
    - [Risk 2 and mitigation]
    """,
    source="pi",
    verbatim_input="[PI's original direction that initiated this protocol]",
    type="directive",
    tags=["research-protocol", "gate-0"],
    related_decisions=["dec_..."],
)
```

**Periodic protocol review**: when significant results arrive or the research direction feels uncertain, search for `tags:research-protocol` in the current project, re-read, and check whether current work still aligns. If assumptions have been invalidated by evidence, flag with a Confirmation Brief rather than silently adapting.

## Claim Extraction

Journal entries get distilled into structured claims during maintenance. This is where raw observations become queryable knowledge.

**What makes a good claim:**
- ONE atomic fact per claim (not a paragraph).
- Directly quotable from the source entry.
- Has a clear type: `hypothesis`, `evidence`, `method`, `result`, `observation`, `assumption`.

**Confidence ranges:**
- `0.0–0.3` — speculative, uncertain, needs investigation.
- `0.3–0.6` — preliminary evidence, first analysis, not yet replicated.
- `0.6–0.8` — solid evidence, multiple sources or controlled experiment.
- `0.8–1.0` — verified, replicated, high confidence.

**Example extraction:**

Entry: *"The stress test showed 12% packet loss above 400 connections. We used MQTT with QoS 1."*

Claims:
1. type: `evidence`, content: `"12% packet loss above 400 connections"`, confidence: `0.8`.
2. type: `method`, content: `"Stress test used MQTT with QoS 1"`, confidence: `0.95`.

```python
rka_extract_claims(
    entry_id="jrn_01...",
    claims=[
        {"claim_type": "evidence", "content": "12% packet loss above 400 connections",
         "confidence": 0.8, "cluster_id": "ecl_01..."},
        {"claim_type": "method", "content": "Stress test used MQTT with QoS 1",
         "confidence": 0.95, "cluster_id": "ecl_01..."},
    ],
)
```

**Cluster assignment heuristic:**
- Claim fits an existing cluster's theme → assign to it.
- Claim introduces a genuinely new sub-topic → create a new cluster with `rka_create_cluster`.
- Unsure → assign to the closest cluster; split later.
- Use `rka_list_clusters()` to see what exists before deciding.

## Parsing PI Instructions Into Missions

The PI often gives compound instructions that contain multiple independent tasks. Decompose them into separate missions.

**Rule**: one mission = one independent objective. If two tasks could be done in parallel by different Executors, they should be separate missions.

| PI says… | Parse as… | Why |
|---|---|---|
| "Fix the search bug and update the README" | 2 missions | Independent objectives, different scopes. |
| "Fix the search bug — find root cause, write fix, test it" | 1 mission with 3 tasks | Sequential steps toward one objective. |
| "Improve the research map: add details, fix counts, make it interactive" | 1 mission with 3 tasks | All contribute to one objective. |
| "Review the paper draft, also check why imports fail, and update the skills docs" | 3 missions | Three unrelated objectives. |

**Example decomposition.** PI says: *"I need you to fix the knowledge pack import bug, also create a user manual, and while you're at it check if the search indexes claims properly."*

Three missions:
```python
rka_create_mission(
    objective="Fix knowledge pack import FK constraint failure",
    motivated_by_decision="dec_...",  # provenance enforcement
    ...,
)
rka_create_mission(
    objective="Create comprehensive user manual",
    motivated_by_decision="dec_...",  # documentation
    ...,
)
rka_create_mission(
    objective="Verify FTS5 indexes cover claims and clusters",
    motivated_by_decision="dec_...",  # search reliability
    ...,
)
```

Each has its own acceptance criteria, scope, and provenance chain.

**When NOT to split:**
- Tasks are sequential dependencies (step 2 needs step 1's output).
- Tasks share the same files and would create merge conflicts.
- The PI explicitly said "one mission" or "bundle these together."

## Working With the Executor

### Structured Mission Handoff Format

Every mission's `context` field should follow this structure:

- **INTENT** — why this work exists, not just what to do. Reference `motivated_by_decision`.
- **BACKGROUND** — key findings, prior attempts, relevant context. Include journal/decision/literature IDs the Executor should read with `rka_get(id)`.
- **CONSTRAINTS** — what the Executor must NOT do. Be explicit about scope boundaries.
- **ASSUMPTIONS** — what the Executor should take as given without verifying. Number them so the Executor's Backbrief can reference by number.
- **VERIFICATION** — how to verify the work is correct. Specific test commands, expected outputs, acceptance checks.

### Effective Mission Tips

- Always include `motivated_by_decision` so the Executor knows WHY.
- List specific files to investigate in the `context` field.
- Include related journal/decision IDs the Executor should read first.
- Write acceptance criteria as testable assertions, not vague goals.
- Set `scope_boundaries` to prevent scope creep.

### Reviewing the Executor's Backbrief

Before approving the Executor to proceed with significant work, the Executor will present a Backbrief — their plan for how they intend to accomplish the mission. Review against these checks:

1. Does the Executor's plan address ALL tasks in the mission?
2. Does their interpretation of acceptance criteria match your intent?
3. Are their stated assumptions consistent with the mission's numbered assumptions?
4. Do the risks they identify warrant scope changes or additional guidance?

If misalignment exists, correct it NOW — before implementation. A two-minute correction here saves hours of wasted work. If the misalignment is significant, recycle the mission with updated context.

### Reviewing Executor Reports

After `rka_submit_report`:
1. Read the report with `rka_get_report(mission_id)`.
2. Verify each acceptance criterion against live data.
3. Check for anomalies the Executor flagged.
4. Answer any questions the Executor raised.
5. Mark the mission complete or create follow-up missions.

## Research Map Navigation

The map is the three-level hierarchy: RQs → Clusters → Claims. See `architecture.md` for the full structure.

**Reading the map:**

```
rka_get_research_map()
  ● [dec_01...] RQ: How should X work? (7 clusters, 45 claims)
    ├─ [strong] Pipeline Architecture (8 claims) — ecl_01...
    ├─ [moderate] CRSI Methodology (6 claims) — ecl_01...
    └─ [emerging] New Topic (1 claim) — ecl_01...
```

**Advancing research:**
- `emerging` clusters need more evidence → extract claims from relevant entries.
- `moderate` clusters may need verification → review synthesis, check for gaps.
- `contested` clusters have contradictions → resolve with `rka_resolve_contradiction`.
- `strong` clusters are well-established → may be ready to inform decisions.

**Navigation commands:**
- `rka_list_clusters(research_question_id="dec_01...")` — all clusters under an RQ.
- `rka_get(id="ecl_01...")` — cluster detail with synthesis + inline claim summaries.
- `rka_review_cluster(cluster_id="ecl_01...", synthesis="...", confidence="moderate")` — write authoritative synthesis.
- `rka_review_claims(claim_ids=["clm_01..."], action="approve")` — approve or reject claims.
- `rka_trace_provenance(entity_id="ecl_01...", direction="upstream")` — see where evidence came from.

### Changelog — Efficient Session Catch-Up

`rka_get_changelog(since="2026-04-10")` returns all created and modified entities across every type (journal, decisions, literature, claims, clusters, missions) with counts and short labels. Use at session start instead of calling `rka_get_journal`, `rka_get_literature`, `rka_get_decision_tree` separately. Combined with `rka_get_research_map()`, that's two calls for a complete picture instead of seven.

## Evidence Assembly — Producing Research Outputs

When the PI asks for a draft section, literature review, or progress update, use `rka_assemble_evidence` to get a structured starting point. Then edit and refine the output — never send raw assembly to the PI.

```python
rka_assemble_evidence(research_question_id="dec_01...", format="lit_review")
rka_assemble_evidence(research_question_id="dec_01...", format="progress_report")
rka_assemble_evidence(research_question_id="dec_01...", format="proposal_section")
```

Output is a markdown string composed from cluster syntheses, key claims, decisions, and cited literature. No LLM involved — it's structured concatenation you refine.

## Cluster Reorganization — Split and Merge

When a cluster grows beyond ~15 claims covering multiple sub-topics, split it:

```python
rka_split_cluster(
    source_id="ecl_01...",
    new_clusters=[
        {"label": "Sub-topic A", "claim_ids": ["clm_01...", "clm_02..."]},
        {"label": "Sub-topic B", "claim_ids": ["clm_03..."]},
    ],
)
```

Claims not listed stay in the source. Provenance links are preserved.

When multiple clusters have 1–2 claims on the same topic, merge them:

```python
rka_merge_clusters(
    source_ids=["ecl_01...", "ecl_02..."],
    target_label="Combined topic",
    target_synthesis="Merged synthesis…",
)
```

Use `rka_get(ecl_...)` to inspect inline claims before deciding how to split.

## Literature Reading Workflow

When processing a paper, use `rka_process_paper` instead of manually creating notes + extracting claims. One call captures all annotations as structured claims:

```python
rka_process_paper(
    lit_id="lit_01...",
    summary="This paper introduces a layered oracle architecture…",
    annotations=[
        {"passage": "Table 3 shows 94% detection rate",
         "note": "Strong evidence for layered approach",
         "claim_type": "evidence", "confidence": 0.85, "cluster_id": "ecl_01..."},
        {"passage": "The authors use Docker-in-Docker for isolation",
         "note": "Same approach we considered",
         "claim_type": "method", "confidence": 0.9},
    ],
)
```

This creates a journal entry with reading notes, extracts one claim per annotation, assigns to clusters if specified, and auto-advances the literature status from `to_read` to `reading`.

## Research Question Advancement

Periodically review the Research Map. When clusters reach `strong`, assess whether the RQ can be advanced:

- **`open`** — default state, actively being investigated.
- **`partially_answered`** — some clusters strong, others still emerging.
- **`answered`** — sufficient evidence; write a conclusion.
- **`reframed`** — the question itself changed based on evidence.
- **`closed`** — no longer relevant.

```python
rka_advance_rq(
    rq_id="dec_01...",
    status="answered",
    conclusion="The evidence supports approach X because…",
    evidence_cluster_ids=["ecl_01...", "ecl_02..."],
)
```

An `answered` RQ with a formal conclusion is a completed research contribution.

## Knowledge Freshness

Knowledge decays. New evidence arrives; existing claims and syntheses become outdated but still appear as current context. Use the freshness tools to detect and manage staleness proactively.

### At Session Start

Run `rka_check_freshness()` alongside `rka_get_pending_maintenance()` to surface stale claims, superseded sources, and aging evidence that needs review.

### After Extracting Claims

Review contradiction candidates in the extraction response. When `rka_extract_claims` creates new claims, check if any conflict with existing knowledge.

### Flagging Stale Items

When new evidence contradicts old claims:

```python
rka_flag_stale(
    entity_id="clm_01...",
    reason="Contradicted by newer experiment in jrn_01...",
    staleness="red",
    propagate=true,
)
```

With `propagate=true`, staleness cascades: stale claim → parent cluster (if >50% claims stale) → decisions citing that cluster.

### Detecting Contradictions

Use `rka_detect_contradictions(entity_id="clm_01...")` to find similar claims that may conflict. The tool surfaces candidates; you decide if they're real contradictions.

### Assumption Tracking

When creating decisions, record assumptions explicitly:

```python
rka_add_decision(
    question="Should we use MQTT for sensor data?",
    ...,
    assumptions=["Network latency <50ms", "Sensor count stays under 500"],
)
```

Periodically review assumption health: are recorded assumptions still valid given new evidence?

### Bi-temporal Validity (v2.2)

Migration 018 added `claims.valid_until` and `evidence_clusters.synthesis_valid_until`. Both are NULL by default (= currently valid). When a claim becomes no longer valid (not merely editorially stale), set `valid_until` to the timestamp it was invalidated. This is orthogonal to `staleness` — tri-state staleness is the Brain's editorial overlay; `valid_until` is ground-truth temporal end-of-validity.

## Validation Gates — Catching Errors Early

Gates are formal go/no-go checkpoints at critical transitions. They prevent compounding errors by forcing evaluation before proceeding.

### When to Create Gates

| Gate | When | Who Creates | Who Evaluates |
|---|---|---|---|
| Gate 0: Problem Framing | Before research starts | Brain | Brain + PI |
| Gate 1: Plan Validation | After mission created, before Executor starts | Brain | Brain |
| Gate 2: Evidence Review | After experiments / evidence gathering | Executor | Brain + PI |
| Gate 3: Synthesis Validation | Before committing conclusions | Brain | Brain + PI |

### Creating a Gate

```python
rka_create_gate(
    mission_id="mis_01...",
    gate_type="problem_framing",
    deliverables=["Research Protocol journal entry with tag research-protocol"],
    pass_criteria=[
        "Research question is precise and testable",
        "At least 3 assumptions are identified and numbered",
        "Success criteria are specific enough to evaluate",
    ],
    assumptions_to_verify=["The dataset is available", "The method scales to 1000 entries"],
)
```

### Evaluating a Gate

```python
rka_evaluate_gate(
    gate_id="chk_01...",
    verdict="go",
    notes="Plan is aligned. Assumption #2 verified by checking schema.",
    assumption_status={
        "The dataset is available": "validated",
        "The method scales to 1000 entries": "unvalidated",
    },
)
```

**Verdicts**: `go` (proceed), `kill` (abandon), `hold` (wait), `recycle` (revise). If any assumption is marked `invalidated`, the gate auto-flags the related decision as stale.

## Hook Registration (v2.3 — Mission 2)

The hook system (`dec_01KPJXN5QJ029FC93EK2WRNDFJ`) lets the Brain register handlers that fire on lifecycle events without consuming Brain attention between sessions. v1 supports five events (`session_start`, `post_journal_create`, `post_claim_extract`, `post_record_outcome`, `periodic`) and three handler types (`sql`, `mcp_tool`, `brain_notify`). Hooks are project-scoped; failures are silent and logged to `hook_executions`; the dispatcher caps cascades at depth 3.

### The brain_notify pattern (most useful in v1)

`brain_notify` writes a row to `brain_notifications`. The Brain reads the queue at session start (via `rka_get_brain_notifications`) and acts on the contents itself. This is the structural answer to "Brain forgets to run maintenance" — findings accumulate asynchronously while the Brain isn't present, then surface when it is.

### `mcp_tool` is scheduled-only in v1

Per `dec_01KPM1M58F0ARXCM0W0GZ476VD`: the `mcp_tool` handler logs intent (`scheduled=true, tool, args`) to `hook_executions` but does **not** invoke the tool. The Brain reads brain_notifications and invokes downstream tools itself using normal MCP access. Real in-process invocation is a clean v1.1 upgrade path (no schema migration; behavior-only change).

### Three recommended default hooks

1. **Session-start maintenance nudge** — surfaces a reminder on every fresh project session.
   ```
   rka_add_hook(
     event="session_start",
     handler_type="brain_notify",
     handler_config={"severity": "info", "content_template": {
       "reminder": "Run rka_get_pending_maintenance and rka_check_integrity",
       "project": "{project_id}"
     }},
     name="session-start-maintenance",
   )
   ```

2. **Drift watch** — fires after every `rka_record_outcome` with the flattened metric snapshot. The Brain decides whether the surfaced rates warrant follow-up.
   ```
   rka_add_hook(
     event="post_record_outcome",
     handler_type="brain_notify",
     handler_config={"severity": "warning", "content_template": {
       "decision": "{decision_id}",
       "outcome": "{outcome}",
       "override_rate": "{override_rate}",
       "brier": "{brier_score}",
       "note": "Consider whether override_rate / brier indicate calibration drift"
     }},
     name="drift-watch",
   )
   ```
   Payload fields available for `{key}` interpolation: `decision_id`, `outcome`, `brier_score`, `ece`, `n_outcomes`, `metrics_available`, `override_rate`, `escape_hatch_rate`, `near_miss_rate`, `qualifying_decisions`, `override_metrics_available`.

3. **Note-creation audit hook (sql)** — append every new journal entry to a project audit table.
   ```
   rka_add_hook(
     event="post_journal_create",
     handler_type="sql",
     handler_config={
       "statement": "INSERT INTO audit_log (action, entity_type, entity_id, actor, details) "
                    "VALUES ('enrich', 'journal', ?, 'system', ?)",
       "params": ["{entry_id}", "{type}"],
     },
     name="note-audit",
   )
   ```

### Session-start UX

After hooks fire on the first tool call per project per session, brain_notifications accumulate. Best practice: at session start, after `rka_get_pending_maintenance`, also call `rka_get_brain_notifications` and surface a digest to the PI. After acting on findings, call `rka_clear_brain_notifications(ids=[...])` to mark them as processed.

`rka_set_project` clears the session-start fired marker for the new project, so re-setting refires.

### Periodic hooks

Trigger the `periodic` event from the host system on whatever cadence the PI chooses (cron, systemd timer, etc.):
```
rka periodic-hooks                         # all projects
rka periodic-hooks --project-id prj_X      # single project
```

The CLI command opens the DB, fires `periodic` once per project, exits. v1 keeps scheduling external; v1.1 may add per-hook interval config inside the dispatcher.

### Auditing

`rka_get_hook_executions(hook_id?, since?, status?)` queries the audit log. Useful filters: `status="error"` for broken hooks, `status="aborted_depth_limit"` for cascade violations, `since="<iso>"` for recent activity.

---

### Not Every Task Needs All 4 Gates

- Quick bug fixes: Gate 1 only (plan validation).
- New research direction: all 4 gates.
- Literature review: Gate 0 (protocol) + Gate 3 (synthesis).
- Experiment: Gate 1 (plan) + Gate 2 (evidence review).

## Related

- Top-level rules, session protocol, anti-patterns: `SKILL.md`.
- Three-actor model, 12-type vocabulary, research-map structure: `architecture.md`.
- Multi-choice decision UX + Confirmation Brief template: `decision_ux.md`.
- Worked examples for PI attribution and common mistakes: `examples.md`.
