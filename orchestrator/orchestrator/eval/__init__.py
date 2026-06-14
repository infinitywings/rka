"""End-to-end research-lifecycle evaluation harness for the agentic orchestrator.

Lives in the orchestrator package (importable as ``orchestrator.eval``) so the
test suite and live drivers share one harness. Agentic-branch code only —
bookkeeper invariant safe (no rka/ changes, no ``import rka``). Components:

  - pi_oracle.py   — rubric-driven, subject-parameterized PI responder that
                     replaces driver.py's stdin / pilot's happy-path, so live
                     runs are reproducible and gradeable.
  - run_record.py  — the per-run artifact schema (one JSON per orchestrator run)
                     that the graders consume.

The subject spec, experiment harness, and grader suite land alongside these in
later Phase-0 commits.
"""
