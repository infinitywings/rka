# End-to-end live-test runbook — sorting-crossover subject

This runbook drives the agentic orchestrator through a complete computer-science
research lifecycle — the fourteen stages from literature investigation to
manuscript refinement — on a **CPU-only** research subject that needs no GPU, no
model download, and no external API key. Everything the Executor must do is
reachable with the built-in `Bash`/`Read`/`Write`/`Grep`/`Glob`/`WebSearch`
tools it already has.

It pairs with the code in
[`orchestrator/eval/runbook_sort.py`](../orchestrator/eval/runbook_sort.py) and
[`orchestrator/eval/sort_crossover.py`](../orchestrator/eval/sort_crossover.py).
The PI-oracle in `runbook_sort.build_sort_oracle()` is the *reproducible*
driver (for automated arm-A runs); a human PI following the prompts below is the
*gold* cross-check.

## The subject (open framing the agent sees)

> Is quicksort an efficient general-purpose comparison sort across input sizes
> and input orderings, or does its advantage over a simple insertion sort depend
> on the input?

Naive hypothesis (the agent's starting frame): *quicksort's O(n log n) average
makes it use fewer comparisons than insertion sort across the board.*

The **sealed** answer (graders only — do not show the agent): the advantage is a
size × ordering **interaction**. Naive first-pivot quicksort hits its O(n²)
worst case on nearly-sorted input where insertion sort hits its O(n) best case,
so quicksort uses far more comparisons there; it wins only on random input. The
comparison-count advantage flips sign with input ordering. Sealed ground-truth
hash is published by `sort_crossover_subject().ground_truth_hash()`.

## Why this subject is a good test

The pivot stage is the discriminator. A plain agent tends to either (a) parrot
the naive "quicksort is faster" framing, or (b) assert the interaction without
evidence. The agentic system should **pivot the claim *and* record it with
provenance** — a decision that supersedes the naive hypothesis, traceable via
the run's `workflow_thread_id`. The three-axis grader rewards the pivot only
when it is correct *and* provenance-backed.

## Sequence of runs

The PhD workflow is a **sequence** of orchestrator runs, not one graph (Phase-H
auto-dispatch is design-only). The PI conducts the sequence.

### 1. Phase-O run (idea → ratified plan → mission queue)

Start: `orchestrator_onboard_start(project_id)` then drive the gates.

| Gate | What to submit |
|---|---|
| `pi_idea_capture` | `runbook_sort.idea_capture_text("<ABSOLUTE workspace path>")` — poses the open question. **Absolute path only** (tilde breaks the bind mount). |
| `pi_scope_ratify` | Accept; the scope note is `runbook_sort.SCOPE_NOTE`. |
| `pi_deepresearch_prompt` | Run `runbook_sort.DEEPRESEARCH_PROMPT` (Claude Desktop deep-research, or the Executor's `WebSearch`). Accept when sources are in. |
| `pi_claims_review` | Accept the extracted claims (should include the naive hypothesis as a *to-test* claim and the pivot-selection insight). |
| `pi_plan_ratify` | Accept the plan whose missions match `runbook_sort.MISSION_SPECS` (M1…M5). **This is the autonomy-licensing gate.** |
| `pi_phase_entry_ack` | Accept per milestone. |

### 2. Mission runs (M1 … M5)

For each spec in `runbook_sort.MISSION_SPECS`, `orchestrator_run_start(mission_id)`
and drive its gates. The two gates that matter:

- **`pi_greenlight`** — if the confirmation brief proposes an experiment that
  varies only array *size* and ignores *ordering*, **redirect** with
  `runbook_sort.DESIGN_REDIRECT_TEXT`. This drives the in-run
  `confirmation_brief_redraft` loop; accept once the design includes an
  input-ordering factor. (Most relevant in M2 *proposal-and-design*.)
- **`pi_decision_select`** — in M3 *experiment-and-pivot*, after the experiment
  runs, if Brain proposes the naive "quicksort is always faster" claim,
  **redirect** with `runbook_sort.PIVOT_REDIRECT_TEXT`. This drives the
  `mission_redraft` loop; accept once Brain re-proposes the interaction claim.

The experiment the Executor actually runs in M3 is exactly
`sort_crossover.run_sort_experiment(full_quadrant_design())` — pure Python,
sub-second, deterministic. It will reproduce the sign flip (`sort_surprise_signal`
returns `shape="interaction"`, `contradicts_naive=True`).

### 3. Writer + revision runs

- **M4 manuscript-draft** — Writer skill drafts the manuscript and the
  comparison-count figure. (Note: `rka/skills/writer/scripts/chart_render.py` is
  a Phase-1 stub; if diagram auto-generation is required, that is a **main-branch**
  fix — branch from `main`, PR to `main` — not an agentic change.)
- **M5 review-and-refine** — a revision arc; incorporate reviewer feedback,
  scope the claim to first-pivot quicksort + the comparison-count metric, don't
  reintroduce the overclaim.

## Grading

After each run, build a `RunRecord` (`from_final_state(...)` + the oracle's
`as_dicts()`), then `graders.grade_run(record, subject=sort_crossover_subject(),
claim_text=<final claim>, surprise=sort_surprise_signal(<result>))`.

Run the reliability grader with `max_redrafts >= 4` — the design redraft (M2)
and the pivot redraft (M3) are *expected*, not failures. Targets for a correct
arm-A run are in `runbook_sort.GRADE_TARGETS`: capability / reliability /
provenance all 1.0.

**Arm B (plain Claude Code, no RKA)** runs the same subject without the
orchestrator. The expected, thesis-supporting gap: comparable capability, but
materially lower **provenance** — no recorded, traceable, superseding pivot
decision.

## Reproducibility

Every run records `subject_ground_truth_hash` (seal), `workflow_thread_id`
(provenance tag), seed, orchestrator version, and rka HEAD on its `RunRecord`.
Because the experiment is comparison-count based, results are bit-identical
across machines — no GPU, no wall-clock variance.
