"""Utility nodes (3).

Scaffold stub. T6 will implement:

  - budget_check        — abort/escalate on $ cap or loop bound
  - consensus_check     — detect Brain⇄Executor disagreement → escalate
  - escalation_router   — checkpoint creation + PI handoff selector
"""

from __future__ import annotations


def budget_check(state):  # pragma: no cover
    raise NotImplementedError("utility.budget_check arrives in T6")


def consensus_check(state):  # pragma: no cover
    raise NotImplementedError("utility.consensus_check arrives in T6")


def escalation_router(state):  # pragma: no cover
    raise NotImplementedError("utility.escalation_router arrives in T6")
