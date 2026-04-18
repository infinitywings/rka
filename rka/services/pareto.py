"""Pareto dominance computation for v2.2 decision options.

Used by ``rka_present_decision`` in Stage 2 (PRUNING) of the strip-then-re-inject
protocol (see ``skills/brain/decision_ux.md``). The function here populates
``decision_options.dominated_by`` so ``DecisionOptionsService.pareto_filter``
can surface only non-dominated options to the PI.

Scope: three fixed dimensions. Expanding the set is explicitly out of scope per
Mission 1B-ii; revisit in a future mission if real decisions need richer
dominance semantics.
"""

from __future__ import annotations

from typing import Any


# Dominance dimensions. Ordering conventions below are LOAD-BEARING — changing
# them silently flips the dominance semantics.
DOMINANCE_DIMS: tuple[str, ...] = (
    "confidence_numeric",       # higher is better (float, 0-1)
    "effort_time",              # lower is better (S > M > L > XL)
    "effort_reversibility",     # lower is better (reversible > costly > irreversible)
)

_EFFORT_TIME_RANK: dict[str, int] = {"S": 0, "M": 1, "L": 2, "XL": 3}
_REVERSIBILITY_RANK: dict[str, int] = {
    "reversible": 0,
    "costly": 1,
    "irreversible": 2,
}


def _score(option: dict[str, Any], dim: str) -> float | int:
    """Return a comparable score for ``dim`` where HIGHER = BETTER universally.

    confidence_numeric is already higher-better; the two effort dimensions are
    inverted so the full comparison direction is uniform.
    """
    if dim == "confidence_numeric":
        return float(option.get(dim, 0.0))
    if dim == "effort_time":
        rank = _EFFORT_TIME_RANK.get(option.get(dim, "XL"), 3)
        return -rank  # invert: S (rank 0) becomes 0, XL (rank 3) becomes -3
    if dim == "effort_reversibility":
        rank = _REVERSIBILITY_RANK.get(option.get(dim, "irreversible"), 2)
        return -rank
    raise ValueError(f"Unknown dominance dimension: {dim!r}")


def _dominates(a: dict[str, Any], b: dict[str, Any], dims: tuple[str, ...]) -> bool:
    """True iff option ``a`` dominates option ``b`` on ``dims``.

    Dominance = A is ≥ B on every dimension AND > B on at least one. Ties on
    every dimension are NOT dominance — each option remains non-dominated.
    """
    at_least_one_strict = False
    for dim in dims:
        sa, sb = _score(a, dim), _score(b, dim)
        if sa < sb:
            return False
        if sa > sb:
            at_least_one_strict = True
    return at_least_one_strict


def compute_dominance(
    options: list[dict[str, Any]],
    dimensions: tuple[str, ...] = DOMINANCE_DIMS,
) -> dict[int, int | None]:
    """Compute Pareto dominance across ``options``.

    Returns a mapping ``{idx → idx_of_dominator | None}``. If option at index
    ``i`` is dominated by option at index ``j``, the mapping records
    ``i → j``. If option ``i`` is Pareto non-dominated, the mapping records
    ``i → None``. Every index in ``range(len(options))`` appears as a key.

    If multiple options dominate ``i``, the FIRST dominator encountered in
    iteration order wins — caller gets a single reference for setting the
    ``dominated_by`` FK. Picking any valid dominator preserves the Pareto
    semantics (dominated options are excluded regardless of which dominator
    is recorded).
    """
    result: dict[int, int | None] = {}
    for i, option in enumerate(options):
        dominator: int | None = None
        for j, other in enumerate(options):
            if i == j:
                continue
            if _dominates(other, option, dimensions):
                dominator = j
                break
        result[i] = dominator
    return result
