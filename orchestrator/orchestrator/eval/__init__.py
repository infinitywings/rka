"""End-to-end research-lifecycle evaluation harness for the agentic orchestrator.

Lives in the orchestrator package (importable as ``orchestrator.eval``) so the
test suite and live drivers share one harness. Agentic-branch code only —
bookkeeper invariant safe (no rka/ changes, no ``import rka``). Components:

  - pi_oracle.py   — rubric-driven, subject-parameterized PI responder that
                     replaces driver.py's stdin / pilot's happy-path, so live
                     runs are reproducible and gradeable.
  - run_record.py  — the per-run artifact schema (one JSON per orchestrator run)
                     that the graders consume.
  - subject.py     — the sealed research-subject spec + ground-truth effect
                     model (CoT × GSM8K, with a planted size×depth interaction).
  - experiment.py  — deterministic surprising-experiment harness: synthesizes
                     results from the sealed effect model and classifies whether
                     they contradict the naive hypothesis (the pivot trigger).
  - graders.py     — three-axis scorers (capability / reliability / provenance);
                     the provenance grader scores the claim-pivot AND its
                     traceability.

The experiment harness + grader suite land alongside the oracle so the whole
Phase-0 measurement loop is offline-testable before the live phases run.
"""
