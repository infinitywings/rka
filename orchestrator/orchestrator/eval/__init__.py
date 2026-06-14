"""End-to-end research-lifecycle evaluation harness for the agentic orchestrator.

Lives in the orchestrator package (importable as ``orchestrator.eval``) so the
test suite and live drivers share one harness. Agentic-branch code only —
bookkeeper invariant safe (no rka/ changes, no ``import rka``). Components:

  - pi_oracle.py   — rubric-driven, subject-parameterized PI responder that
                     replaces driver.py's stdin / pilot's happy-path, so live
                     runs are reproducible and gradeable.
  - run_record.py  — the per-run artifact schema (one JSON per orchestrator run)
                     that the graders consume.
  - subject.py     — the (subject-agnostic) sealed research-subject spec + the
                     CoT × GSM8K synthetic effect model.
  - sort_crossover.py — a self-contained, CPU-only subject whose experiment is a
                     REAL computation (instrumented insertion sort vs naive
                     first-pivot quicksort, counting comparisons). Its planted
                     surprise — quicksort's O(n^2) degradation on nearly-sorted
                     input — is a genuine, reproducible phenomenon, runnable with
                     only the Bash/Python tools the Executor already has (no GPU,
                     no model download, no API key).
  - experiment.py  — deterministic surprising-experiment harness: synthesizes
                     results from the sealed effect model and classifies whether
                     they contradict the naive hypothesis (the pivot trigger).
  - graders.py     — three-axis scorers (capability / reliability / provenance);
                     the provenance grader scores the claim-pivot AND its
                     traceability.

The experiment harness + grader suite land alongside the oracle so the whole
Phase-0 measurement loop is offline-testable before the live phases run.
"""
