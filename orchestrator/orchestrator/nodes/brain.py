"""Brain nodes (6).

Scaffold stub. T3 will implement:

  - strategy_node        — `rka_get_status` + `rka_get_context` synthesis
  - confirmation_brief   — Gate 1 plan validation
  - decision_present     — `rka_present_decision` wrapper
  - cluster_review       — `rka_review_cluster` integration
  - gate1_validation     — accept/redirect Executor Backbriefs
  - final_synthesis      — mission-acceptance writeup
"""

from __future__ import annotations


def strategy_node(state):  # pragma: no cover
    raise NotImplementedError("brain.strategy_node arrives in T3")


def confirmation_brief(state):  # pragma: no cover
    raise NotImplementedError("brain.confirmation_brief arrives in T3")


def decision_present(state):  # pragma: no cover
    raise NotImplementedError("brain.decision_present arrives in T3")


def cluster_review(state):  # pragma: no cover
    raise NotImplementedError("brain.cluster_review arrives in T3")


def gate1_validation(state):  # pragma: no cover
    raise NotImplementedError("brain.gate1_validation arrives in T3")


def final_synthesis(state):  # pragma: no cover
    raise NotImplementedError("brain.final_synthesis arrives in T3")
