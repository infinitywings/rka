# Brain — Decision UX

Supplementary reference for the multi-choice decision UX, plus the Confirmation Brief template. Load when the Brain needs to present structured options to the PI or confirm intent before significant work.

Authoritative source: `dec_01KPE2RKT838TJXDYT7W23K26B` (multi-choice decision spec, v2.2). Literature grounding: `lit_01KPE2N5386DSKYQTD5XZ22MQ4` (Sharma sycophancy), `lit_01KPE2NCCXAV23N7SSQVN1Z5JG` (Huber decoy), `lit_01KPE2NKXH8ZM0XPYP4GMBQGWK` (Chernev choice overload), `lit_01KPE2P2BHT37ZVNSSDSXM0XTX` (Buccinca cognitive forcing), `lit_01KPE2PAXE72EAE9EHNBBAQ1KV` (Ma calibrated trust), `lit_01KPE2PKEZRJB0D3KAY83J4DHG` (Klein RPDM). Substrate: migrations 017 (`decision_options` table) + 018 (`calibration_outcomes`).

---

## Confirmation Brief — Verifying PI Intent

When the PI gives a new directive that leads to significant work — a mission, a research direction change, a design decision, or any task requiring more than a few tool calls — ALWAYS respond with a Confirmation Brief before proceeding.

### What to Include

1. **Restated intent** — not just the task, but WHY. What outcome does the PI want?
2. **Assumptions you are making** — what are you taking as given that the PI hasn't explicitly stated?
3. **Proposed scope** — what's in, what's out, what are the boundaries?
4. **Success criteria** — how will we know this is done correctly?

Present this naturally in conversation, not as a formal checklist. The PI corrects any misalignment. Only AFTER PI confirmation do you proceed to planning or execution.

### When to Use

- PI gives a research direction ("focus on privacy-aware decomposition").
- PI requests a significant deliverable ("create a user manual").
- PI describes a problem to solve ("the import is failing with a 500 error").
- PI asks for multi-step work ("fix the search, update the docs, and check the import").

### When NOT to Use

- PI asks a simple question ("what's the current graph stats?").
- PI gives a small, unambiguous instruction ("mark that mission complete").
- PI is reviewing your previous Confirmation Brief (don't loop).

### Worked example

See `examples.md` § "Confirmation Brief — privacy-aware decomposition pivot" for a full worked example with the recording template.

---

## Multi-Choice Decision UX — The Core Loop

The v2.2 decision UX addresses six documented failure modes of naive LLM recommendations: sycophancy (Sharma 2023), decoy effects (Huber 1982), choice overload (Chernev 2015), cognitive underforcing (Buccinca 2021), miscalibrated trust (Ma 2023), and failure to support naturalistic recognition-primed decision making (Klein 1998).

The loop has **three staged steps**, and **the ordering is load-bearing**. Getting the stages in the wrong order — especially the preference handling — reintroduces the sycophancy failure mode the protocol was designed to prevent.

```
┌──────────────────────────────┐
│ 1. GENERATION                │  Strip PI preference from context.
│   Internally generate 5      │  Produce options without knowing
│   candidate options.         │  which the PI would prefer.
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│ 2. PRUNING                   │  Pareto non-dominance filter.
│   Drop options that are      │  Each remaining option is
│   dominated on every         │  genuinely non-dominated.
│   dimension. Target 3.       │  (dominated_by column = NULL)
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│ 3. RANKING                   │  Re-inject PI preference as
│   Re-inject PI preference    │  OPPOSING-CRITIQUE, not steering.
│   to rank + recommend.       │  One option is recommended; all
│                              │  remain visible and selectable.
└──────────────────────────────┘
```

### Why the order matters — the strip-then-re-inject discipline

**Stage 1 — Generation (preference stripped):** When generating the 5 candidate options, the PI's preference must be **completely absent** from the generation context. This is the anti-sycophancy step. Per Sharma 2023, LLMs will bias their outputs toward perceived user preferences even when that bias damages accuracy. Stripping the preference during generation produces a candidate set that reflects the evidence, not the asker.

**Stage 2 — Pruning (Pareto non-dominance):** Discard any option that is worse-or-equal to another on every dimension. The remaining options are Pareto non-dominated — each represents a distinct legitimate trade-off. Per Huber 1982, presenting dominated options creates a decoy effect that systematically biases choice. The `decision_options.dominated_by` column records which option dominated (if any); only rows with `dominated_by IS NULL` are presented to the PI.

**Stage 3 — Ranking (preference re-injected as critique):** Now — and only now — does the PI's stated preference enter. It comes in as an **opposing-critique** pass: for each option, explicitly argue why the PI's preference does NOT favor it, then use the residual alignment to rank. One option is marked `is_recommended=1`, but all surviving options are presented to the PI. Per Buccinca 2021, cognitive-forcing affordances improve decision quality — the PI is not shown only the recommendation.

**Common failure mode**: short-circuiting to "generate 3 options the PI will like" collapses the three stages into one. The output superficially looks like a choice, but it's three variations of a single preference-biased recommendation. The literature is clear: this fails.

### Per-option required fields

Every option presented to the PI must have these fields populated. The `decision_options` table (migration 017) enforces many of them via schema constraints.

| Field | Semantics | Schema constraint |
|---|---|---|
| `label` | Short memorable name. | NOT NULL. |
| `summary` | One-sentence framing. | NOT NULL. |
| `justification` | Why this option is on the slate. | NOT NULL. |
| `expert_archetype` | *Optional* persona — "the risk-averse incrementalist", "the greenfield architect". Orients the PI to the reasoning lens. | nullable. |
| `explanation` | The detailed case. | NOT NULL. |
| `pros` | JSON array of **exactly 3** strings. | CHECK `json_array_length(pros) = 3`. |
| `cons` | JSON array of **exactly 3** strings. Last entry must be a **steelman con** — the strongest argument against this option, not a straw-man. | CHECK `json_array_length(cons) = 3`. |
| `evidence` | JSON array of `{claim_id, strength_tier}`. Empty array = no citable evidence yet (flag this in the explanation). | NOT NULL. |
| `confidence_verbal` | `low \| moderate \| high`. | NOT NULL. |
| `confidence_numeric` | 0.0–1.0. | CHECK `BETWEEN 0 AND 1`. |
| `confidence_evidence_strength` | `weak \| moderate \| strong` — separate from confidence because strong evidence can still yield low confidence if the question is inherently uncertain. | NOT NULL. |
| `confidence_known_unknowns` | JSON array of 1–2 strings naming the things you *don't* know. | CHECK `json_array_length BETWEEN 1 AND 2`. |
| `effort_time` | `S \| M \| L \| XL`. | NOT NULL. |
| `effort_cost` | Optional — non-time costs (compute, licensing, human review). | nullable. |
| `effort_reversibility` | `reversible \| costly \| irreversible`. | NOT NULL. |
| `dominated_by` | Self-FK to another `decision_options.id` if this option is Pareto-dominated. | NULL at presentation time. |
| `presentation_order_seed` | Integer used to randomize order in the UI (prevents position bias). | NOT NULL. |
| `is_recommended` | 0 or 1 — one option per decision should be recommended. | NOT NULL, default 0. |

### Escape hatches

The PI must always have affordances to refuse the slate:

- **"None of these"** — the PI rejects all options and writes a free-form counter. Record as `pi_override_rationale` on the decisions row; `pi_selected_option_id` stays NULL.
- **"Frame is wrong"** — the question itself needs reframing. Mark the decision `revisit` and open a new research-question decision with `kind='research_question'`.
- **"More evidence first"** — the PI wants to pause. Record a checkpoint with `type='clarification'`; don't force a choice.

### The Elicitation Substrate (MCP 2025-11-25)

When presenting the slate via Claude Desktop, use MCP's `elicitation` primitive — it's purpose-built for structured user input via JSON Schema. The decision_options schema maps naturally to elicitation's request/response shape. Do NOT render the slate as ad-hoc markdown; the structured primitive carries the schema constraints through to the UI and prevents partial-input ambiguity.

### Immutable Decision Archive

Once an option is selected (`pi_selected_option_id` set) or rejected via escape hatch (`pi_override_rationale` set), **the `decision_options` rows for that decision become immutable**. If the decision is later revisited, a new decision row supersedes it (edge: `supersedes`), and a fresh set of options is generated. Never edit a presented option in place — that erases the audit trail.

### The Calibration Loop

The `rka_record_outcome` tool records what actually happened after a decision played out, writing to `calibration_outcomes` (migration 018). The `/api/calibration/metrics` endpoint computes Brier score and ECE on demand from those outcomes — both ship in v2.2 (Mission 1B-iii). The Brain or PI calls `rka_record_outcome` once a decision's real-world outcome becomes known:

```python
rka_record_outcome(
    decision_id="dec_01...",
    outcome="succeeded",      # succeeded | failed | mixed | unresolved
    outcome_details="The sharding migration met its 2% loss target at 500 connections.",
)
```

Periodically — quarterly or after 20+ outcomes — `GET /api/calibration/metrics` reports Brier score and ECE on recommended options vs. actual outcomes (returns a warning if N<5):

- **Brier score**: mean squared error between `confidence_numeric` and the binary outcome. Lower is better. Uncalibrated Brain = high Brier.
- **ECE (Expected Calibration Error)**: over binned confidence, the average gap between stated confidence and actual accuracy. Flags systematic over- or under-confidence.

A Brain with good calibration metrics is trustworthy to the PI. A Brain with poor metrics should flag its own confidence claims as unreliable until recalibrated.

## Recording a Decision After PI Selection

```python
rka_update_decision(
    id="dec_01...",
    pi_selected_option_id="opt_01...",
    pi_override_rationale=None,          # set to a string if PI invoked "None of these"
    presentation_method="elicitation",   # elicitation | markdown_fallback
)
```

The `chosen` and `rationale` columns also get populated from the selected option's `label` and `justification` via the service layer. Don't set them manually.

## Related

- Top-level rules and the overall session protocol: `SKILL.md`.
- Three-actor model and entity taxonomy: `architecture.md`.
- Full procedures for gates, freshness, cluster management: `workflows.md`.
- Worked examples of Confirmation Briefs and PI attribution: `examples.md`.
