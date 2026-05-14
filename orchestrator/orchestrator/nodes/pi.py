"""PI interaction nodes (3).

Scaffold stub. T5 will implement three `interrupt()` points:

  - pi_greenlight       — Backbrief / Confirmation Brief approval
  - pi_decision_select  — choose between presented options
  - pi_acceptance       — final mission acceptance review

Per rehearsal observation #15 (labeler-UX-scaling-friction), payloads
larger than `PI_BATCH_REVIEW_THRESHOLD` items must surface a batch-review
affordance instead of a single monolithic blob. Default threshold is 10.
"""

from __future__ import annotations

PI_BATCH_REVIEW_THRESHOLD: int = 10


def pi_greenlight(state):  # pragma: no cover
    raise NotImplementedError("pi.pi_greenlight arrives in T5")


def pi_decision_select(state):  # pragma: no cover
    raise NotImplementedError("pi.pi_decision_select arrives in T5")


def pi_acceptance(state):  # pragma: no cover
    raise NotImplementedError("pi.pi_acceptance arrives in T5")
