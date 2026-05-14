"""Budget tracking + loop bounds.

Scaffold stub. T6 utility node `budget_check` and T7 topology will use
this module. Loop bound for Phase 1 is ≤2 per the decision spec (consensus
failures escalate to PI rather than retrying indefinitely).
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_BUDGET_USD: float = 5.0
MAX_LOOP_DEPTH: int = 2


@dataclass(slots=True)
class BudgetSnapshot:
    """Current spend + loop counts for one workflow thread."""

    usd_spent: float = 0.0
    loop_iterations: int = 0

    def exceeds(self, cap_usd: float) -> bool:
        return self.usd_spent >= cap_usd

    def at_loop_cap(self) -> bool:
        return self.loop_iterations >= MAX_LOOP_DEPTH
