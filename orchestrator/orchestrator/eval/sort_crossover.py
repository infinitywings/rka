"""Sorting-crossover subject — a REAL, CPU-only, fully reproducible experiment.

Unlike the CoT×GSM8K subject (whose live experiment needs a GPU + an LLM), this
subject's experiment is pure Python on CPU: it instruments insertion sort and a
naive first-pivot quicksort, counts the exact number of element comparisons each
performs, and compares them across input size × input ordering. Comparison count
(not wall-clock time) is the cost metric, so results are *exactly* reproducible —
no timing noise, no hardware dependence. Everything here runs in well under a
second and uses only the Bash/Python tools the orchestrator's Executor already
has; nothing is downloaded, no API key is needed.

The planted surprise is a REAL, textbook phenomenon, not a synthetic effect:

  - Naive first-pivot quicksort degrades to its O(n^2) WORST case on sorted /
    nearly-sorted input — precisely the input a naive researcher expects to be
    "easy" — because every pivot is near-extremal and partitions are maximally
    unbalanced.
  - Insertion sort hits its O(n) BEST case on that same nearly-sorted input.
  - So the comparison-count advantage of quicksort over insertion sort FLIPS
    sign: quicksort wins big on large random arrays (the headline) but loses on
    nearly-sorted input and on small arrays. An interaction between algorithm,
    size, and input ordering — not the uniform "quicksort is faster" main effect.

This is exactly why production sorts hybridize and harden the pivot (introsort,
Timsort, median-of-three) — strong, web-searchable literature anchors that a
thorough review surfaces.

The 2x2 result quadrant mirrors the CoT subject's structure (one cell positive,
three negative), so the same ``graders.py`` scores it unchanged.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from orchestrator.eval.subject import LiteratureAnchor, SubjectSpec

# Size tiers (element counts) and the orderings probed.
SMALL_N = 12
LARGE_N = 384
NEARLY_SORTED_SWAP_FRAC = 0.05      # fraction of n random transpositions


# --- instrumented sorts (count element comparisons) ----------------------


def insertion_sort_comparisons(arr: list[int]) -> tuple[list[int], int]:
    """Insertion sort; returns (sorted_copy, comparison_count). O(n) on already-
    sorted input (one comparison per element), O(n^2) worst case."""
    a = list(arr)
    comparisons = 0
    for i in range(1, len(a)):
        key = a[i]
        j = i - 1
        while j >= 0:
            comparisons += 1
            if a[j] > key:
                a[j + 1] = a[j]
                j -= 1
            else:
                break
        a[j + 1] = key
    return a, comparisons


def quicksort_first_pivot_comparisons(arr: list[int]) -> tuple[list[int], int]:
    """Quicksort with a naive first-element pivot, explicit stack (no recursion
    limit). Returns (sorted_copy, comparison_count). Degrades to O(n^2) on
    sorted / nearly-sorted input because the pivot is always near-extremal."""
    a = list(arr)
    comparisons = 0
    stack: list[tuple[int, int]] = [(0, len(a) - 1)]
    while stack:
        lo, hi = stack.pop()
        if lo >= hi:
            continue
        pivot = a[lo]
        store = lo + 1
        for i in range(lo + 1, hi + 1):
            comparisons += 1
            if a[i] < pivot:
                a[i], a[store] = a[store], a[i]
                store += 1
        a[lo], a[store - 1] = a[store - 1], a[lo]
        p = store - 1
        stack.append((lo, p - 1))
        stack.append((p + 1, hi))
    return a, comparisons


# --- deterministic input generation --------------------------------------


def make_array(n: int, ordering: str, seed: int) -> list[int]:
    """Deterministic input of the requested ordering. ``ordering`` ∈
    {"random", "nearly_sorted", "sorted", "reversed"}."""
    rng = random.Random(seed)
    base = list(range(n))
    if ordering == "sorted":
        return base
    if ordering == "reversed":
        return base[::-1]
    if ordering == "random":
        arr = base[:]
        rng.shuffle(arr)
        return arr
    if ordering == "nearly_sorted":
        arr = base[:]
        for _ in range(max(1, int(n * NEARLY_SORTED_SWAP_FRAC))):
            i, j = rng.randrange(n), rng.randrange(n)
            arr[i], arr[j] = arr[j], arr[i]
        return arr
    raise ValueError(f"unknown ordering {ordering!r}")


# --- experiment design + run ---------------------------------------------


@dataclass(frozen=True)
class SortCell:
    """One (size, ordering) cell; both algorithms are run on identical inputs."""

    n: int
    ordering: str


@dataclass(frozen=True)
class SortDesign:
    label: str
    cells: list[SortCell] = field(default_factory=list)

    def size_tiers(self) -> set[int]:
        return {c.n for c in self.cells}

    def orderings(self) -> set[str]:
        return {c.ordering for c in self.cells}


@dataclass(frozen=True)
class SortCellResult:
    n: int
    ordering: str
    insertion_comparisons: float
    quicksort_comparisons: float

    @property
    def quicksort_advantage(self) -> float:
        """Fewer comparisons for quicksort ⇒ positive ⇒ quicksort better."""
        return round(self.insertion_comparisons - self.quicksort_comparisons, 2)


@dataclass(frozen=True)
class SortResult:
    design_label: str
    seed: int
    n_trials: int
    cells: list[SortCellResult]

    def by_cell(self) -> dict[tuple[int, str], float]:
        return {(c.n, c.ordering): c.quicksort_advantage for c in self.cells}


def run_sort_experiment(
    design: SortDesign, *, seed: int = 0, n_trials: int = 5
) -> SortResult:
    """Actually run both sorts on freshly generated inputs and count
    comparisons, averaging across ``n_trials`` seeded inputs per cell. Verifies
    each sort returns correctly-ordered output (a broken experiment is not a
    valid one)."""
    out: list[SortCellResult] = []
    for cell in design.cells:
        ins_total = 0
        qs_total = 0
        for t in range(n_trials):
            arr = make_array(cell.n, cell.ordering, seed=seed * 1000 + t)
            ins_sorted, ins_c = insertion_sort_comparisons(arr)
            qs_sorted, qs_c = quicksort_first_pivot_comparisons(arr)
            assert ins_sorted == sorted(arr), "insertion sort produced wrong order"
            assert qs_sorted == sorted(arr), "quicksort produced wrong order"
            ins_total += ins_c
            qs_total += qs_c
        out.append(
            SortCellResult(
                n=cell.n,
                ordering=cell.ordering,
                insertion_comparisons=round(ins_total / n_trials, 2),
                quicksort_comparisons=round(qs_total / n_trials, 2),
            )
        )
    return SortResult(
        design_label=design.label, seed=seed, n_trials=n_trials, cells=out
    )


# --- surprise classification (grader-compatible: .shape + .contradicts_naive) ---


@dataclass(frozen=True)
class SortSurprise:
    """Structurally compatible with ``graders.SurpriseLike`` (exposes ``shape``
    and ``contradicts_naive``). ``quicksort_advantage`` maps (n, ordering) → the
    observed comparison-count advantage of quicksort over insertion sort."""

    shape: str
    contradicts_naive: bool
    quicksort_advantage: dict[tuple[int, str], float]
    observed_sign_flip: bool
    detail: dict = field(default_factory=dict)


def sort_surprise_signal(result: SortResult) -> SortSurprise:
    """Classify the observed quadrant against the naive 'quicksort is faster
    everywhere' frame. Any cell where quicksort uses MORE comparisons (negative
    advantage) breaks the naive frame; a mix of signs is the planted
    interaction."""
    deltas = result.by_cell()
    if not deltas:
        return SortSurprise("underpowered", False, {}, False,
                            {"reason": "no cells"})
    has_pos = any(d > 0 for d in deltas.values())
    has_neg = any(d < 0 for d in deltas.values())
    sign_flip = has_pos and has_neg
    if sign_flip:
        shape = "interaction"
    elif has_neg and not has_pos:
        shape = "uniform_quicksort_worse"
    elif has_pos and not has_neg:
        shape = "confirms_naive"
    else:
        shape = "underpowered"
    return SortSurprise(
        shape=shape,
        contradicts_naive=has_neg,
        quicksort_advantage=deltas,
        observed_sign_flip=sign_flip,
        detail={
            "n_cells": len(deltas),
            "n_quicksort_worse": sum(1 for d in deltas.values() if d < 0),
            "n_quicksort_better": sum(1 for d in deltas.values() if d > 0),
        },
    )


# --- canonical designs ----------------------------------------------------


def full_quadrant_design() -> SortDesign:
    """The *good* design: both size tiers × {random, nearly_sorted}. Observes
    the full sign flip → forces the pivot."""
    return SortDesign(
        label="full-quadrant",
        cells=[
            SortCell(SMALL_N, "random"),
            SortCell(SMALL_N, "nearly_sorted"),
            SortCell(LARGE_N, "random"),
            SortCell(LARGE_N, "nearly_sorted"),
        ],
    )


def naive_design() -> SortDesign:
    """The *weak* design: only the large random array, where quicksort shines.
    Confirms the naive frame by omission and misses the surprise."""
    return SortDesign(label="naive-large-random-only", cells=[SortCell(LARGE_N, "random")])


# --- the subject ----------------------------------------------------------


def sort_crossover_subject() -> SubjectSpec:
    """Self-contained, CPU-only research subject — quicksort vs insertion sort
    with a planted size × ordering interaction (real comparison-count sign flip)."""
    return SubjectSpec(
        subject_id="sort-crossover",
        title="Quicksort efficiency across input distributions",
        research_question=(
            "Is quicksort an efficient general-purpose comparison sort across "
            "input sizes and input orderings, or does its advantage over a "
            "simple insertion sort depend on the input?"
        ),
        naive_hypothesis=(
            "Quicksort's O(n log n) average-case running time makes it use fewer "
            "comparisons than insertion sort's O(n^2) across input sizes and "
            "orderings."
        ),
        ground_truth_claim=(
            "Whether quicksort beats insertion sort is an interaction between the "
            "algorithm and the input's existing order, not a main effect. A naive "
            "first-pivot quicksort hits its O(n^2) worst case on sorted / "
            "nearly-sorted input — where insertion sort hits its O(n) best case — "
            "so it uses far MORE comparisons there, at both small and large sizes. "
            "Quicksort wins only on unordered (random) input. The comparison-count "
            "advantage exhibits a crossover (it flips sign) as input ordering "
            "changes, which is why production sorts hybridize with insertion sort "
            "and harden the pivot (introsort, Timsort, median-of-three)."
        ),
        effect=None,  # the experiment is a REAL computation, not a synthetic model
        sealed_extra={
            "metric": "element_comparisons",
            "small_n": SMALL_N,
            "large_n": LARGE_N,
            # Empirically measured (stable across 12 seeds): the sign flip is
            # driven by input ORDERING — quicksort wins on random input at both
            # sizes and loses on nearly-sorted input at both sizes. (The classic
            # "insertion wins for small n" is a wall-clock constant-factor effect,
            # not a comparison-count one, so it does not appear in this metric.)
            "quadrant_quicksort_advantage_sign": {
                "small/random": "positive",
                "small/nearly_sorted": "negative",
                "large/random": "positive",
                "large/nearly_sorted": "negative",
            },
            "headline_win_cell": "large/random",
        },
        literature_anchors=[
            LiteratureAnchor(
                "hoare1962quicksort",
                "Quicksort: partition-exchange sort with O(n log n) average comparisons.",
                supports_cot=True,
            ),
            LiteratureAnchor(
                "sedgewick1978implementing",
                "Pivot choice is decisive: a first/last-element pivot makes already-sorted "
                "input the O(n^2) worst case.",
                supports_cot=False,
                hints_interaction=True,
            ),
            LiteratureAnchor(
                "musser1997introspective",
                "Introsort caps quicksort's worst case by switching to heapsort, and to "
                "insertion sort on small subarrays.",
                supports_cot=False,
                hints_interaction=True,
            ),
            LiteratureAnchor(
                "peters2002timsort",
                "Timsort uses insertion sort for small runs and exploits existing order, "
                "so nearly-sorted input is its best case.",
                supports_cot=False,
                hints_interaction=True,
            ),
        ],
        required_claim_keywords=["interaction", "nearly-sorted", "worst case", "crossover"],
        forbidden_claim_keywords=[
            "always faster", "always fastest", "uniformly faster", "regardless of input",
        ],
    )
