# Eval-v3 Track — Writer grounding & evidence-utilization protocol

Question: **do the saved evidence and the knowledge graph produce a better
manuscript draft** than the same model writing from the same raw material
without the graph? "Better" is split into what can be measured mechanically
(grounding, currency, evidence use) and what needs judged grading (coherence,
faithfulness of emphasis).

## Arms (same model, same section brief, blind labels)

| Arm | Setup |
|---|---|
| **A — RKA Writer** | Writer skill with the live knowledge base: claim spine, evidence bindings, `% provenance:` discipline, discourse-synthesis workflow, gates enabled. |
| **B — flat dump** | Same model, same *source material* exported as a flat text dump (journals, claims, literature notes concatenated), no graph, no gates, no provenance discipline required. |
| **C — brief only** (optional) | Same model, only the section brief. Measures the fabrication baseline the record is supposed to prevent. |

Every arm's output is audited with the same instruments; Arm A's advantage
must show up in the metrics, not in the protocol.

## Mechanical metrics (per draft, via `score_drafts.py`)

Grounding — computed from `verify_provenance.py --output report.json`
(run each draft through the verifier against the same project; for arms B/C,
first annotate citations mechanically where the draft names sources, so the
verifier has something to check — un-annotatable assertions count as
uncovered):

- `coverage_rate` — substantive blocks carrying provenance / all substantive blocks
- `fabrication_rate` — MISSING citations / total citations (cited entity does not exist)
- `stale_rate` — STALE or RETRACTED citations / total (cites superseded or retracted knowledge as current — the pivot failure in writing form)
- `contradiction_rate`, `low_support_rate` — cited entity is contested or does not support the claim
- `ok_rate` and the verifier's overall PASS/WARN/BLOCK verdict

Evidence utilization — against the scenario's PI-ratified expected evidence
set (what *should* inform this section, typically the spine's bindings):

- `utilization_critical` / `utilization_expanded` — expected evidence actually cited
- `missed_critical` — the concrete list of critical evidence the draft ignored
  (unused critical evidence is the "evidence faded away" failure appearing in
  the manuscript instead of the chat)

## Judged rubric (blind, per draft, 1–5 each)

1. **Groundedness** — assertions feel anchored; no confident claims beyond the record.
2. **Evidence fidelity** — numbers, conditions, and caveats match the record exactly.
3. **Currency** — reflects the *current* state after pivots; superseded plans appear only as acknowledged history.
4. **Coherence** — reads as an argument, not record-shaped prose (the discourse-synthesis target).
5. **Completeness** — the section's key evidence and counterpoints are present.

Grade with a model family different from the drafting model where feasible,
plus human spot-checks on a sample; graders see drafts in random order with
arm labels stripped.

## Scenario format (`scenario.example.json`)

One scenario = one section brief + the ratified expected-evidence set +
paths to each arm's draft and verifier report. `score_drafts.py` consumes
scenarios and emits a per-arm comparison table with deltas against Arm B.

## Interpretation guardrails

- Arm A winning on grounding while losing on coherence is a real finding,
  not a scoring error — report the divergence (Eval-v1/v2 house rule).
- The verifier's lexical support check is a Phase-1 heuristic; for quoted
  numbers use `--support-backend llm` or human verification before quoting
  `low_support_rate` in the paper.
- Drafting runs happen on the machine with the live RKA instance and model
  keys; this directory's tooling scores the artifacts they produce.
