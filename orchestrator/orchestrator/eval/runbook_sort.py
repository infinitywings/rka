"""Live-phase runbook for the CPU-only sorting-crossover subject.

Turns ``sort_crossover.py`` (the sealed subject + real experiment) into an
executable end-to-end plan: the exact text the PI types at the Phase-O idea
gate, the mission specs that cover all fourteen PhD-workflow stages, and — the
keystone — a ``PIOracle`` rubric that makes the PI behave *correctly per the
sealed ground truth*, including the **claim pivot** when the experiment
contradicts the naive hypothesis.

How the pieces drive the live orchestrator (each is a separate run; the PI
conducts the sequence):

  Phase-O run        idea_capture → scope → deep-research → hygiene → claims →
                     plan synthesis → plan ratify → mission queue
  Mission runs       M1..M5 below, each: strategy → confirmation_brief →
                     pi_greenlight → backbrief → experiment → decision_present →
                     pi_decision_select → synthesis → pi_acceptance
  Writer / revision  manuscript draft (+ figure) → reviewer feedback → refine

Two rubric rules exercise the parts where agentic+provenance should beat a plain
agent:

  - **demand-ordering-variation** (at ``pi_greenlight``): if a confirmation
    brief proposes an experiment that varies only array *size* and ignores input
    *ordering*, the PI redirects — driving the Phase-X² ``confirmation_brief_redraft``
    loop — because a size-only design would never observe quicksort's worst case.
  - **pivot-from-naive-claim** (at ``pi_decision_select``): if Brain proposes a
    decision asserting the naive "quicksort is always faster" claim after the
    results are in, the PI redirects toward the size×ordering interaction —
    driving the v0.6.12 ``mission_redraft`` loop — until Brain re-proposes the
    correct (pivoted) claim, which the PI then ratifies.

The redirects reference only what the PI can legitimately see at that gate (the
proposed brief / decision and, post-``mission_execute``, the observed results) —
not the sealed effect key.
"""

from __future__ import annotations

from orchestrator.eval.pi_oracle import PIOracle, Rubric, Rule
from orchestrator.eval.sort_crossover import sort_crossover_subject

# --- Phase-O entry text (agent-visible framing only; no sealed answer) ----


def idea_capture_text(workspace_path: str = "/workspace/research/sort-crossover") -> str:
    """The free-form idea the PI submits at ``pi_idea_capture``. Poses the OPEN
    question + the naive assumption; deliberately does NOT state the answer.

    ``workspace_path`` must be ABSOLUTE (tilde paths break the HOST_WORKSPACE_ROOT
    bind mount per Phase D2.1)."""
    return (
        "I want to study whether quicksort is an efficient general-purpose "
        "comparison sort. The common assumption is that quicksort's O(n log n) "
        "average case makes it use fewer comparisons than a simple insertion "
        "sort across the board. I'd like to test that assumption empirically by "
        "instrumenting both algorithms to count element comparisons and running "
        "them on a range of inputs, then write up what we find. "
        f"Workspace: {workspace_path}."
    )


SCOPE_NOTE = (
    "Scope: a comparison-count study of insertion sort vs a naive first-pivot "
    "quicksort on integer arrays, varying array size and input ordering. "
    "Out of scope: wall-clock benchmarking, cache effects, parallel sorts, and "
    "non-comparison sorts (radix/counting)."
)

DEEPRESEARCH_PROMPT = (
    "Survey the literature on comparison-sort performance: the average- and "
    "worst-case comparison complexity of quicksort and insertion sort; how pivot "
    "selection (first/last element vs median-of-three vs randomized) changes "
    "quicksort's worst case; and why production sorts hybridize (introsort, "
    "Timsort) and fall back to insertion sort for small or nearly-sorted inputs. "
    "Collect citations with their key findings."
)

# --- PI redirect texts (drive the redraft loops) --------------------------

DESIGN_REDIRECT_TEXT = (
    "This design only varies array size, so it cannot detect input-ordering "
    "effects. Vary input ordering too — include nearly-sorted (and ideally "
    "already-sorted) inputs alongside random ones — otherwise the experiment "
    "will miss the worst-case behavior that separates these algorithms. Redraft "
    "the brief with an explicit input-ordering factor."
)

PIVOT_REDIRECT_TEXT = (
    "The results contradict 'quicksort is always faster': on nearly-sorted "
    "inputs the first-pivot quicksort used far MORE comparisons than insertion "
    "sort (its O(n^2) worst case), while it won on random inputs. Pivot the claim "
    "from a uniform advantage to the size-by-ordering interaction — quicksort's "
    "comparison-count advantage crosses over with input ordering, and nearly-"
    "sorted input is its worst case. Re-propose the decision naming the "
    "interaction."
)


# --- the oracle (the keystone) -------------------------------------------


def build_sort_oracle() -> PIOracle:
    """A subject-aware PI responder for the sorting runbook. Accepts good
    proposals, redirects a size-only experiment design, and redirects a naive
    final claim toward the pivoted interaction claim — recording every decision
    for grading. Naive/interaction vocabularies are sourced from the sealed
    subject so the rubric stays in sync with the answer key."""
    subject = sort_crossover_subject()
    rules = [
        # Research-design quality gate: demand an ordering factor.
        Rule(
            type="pi_greenlight",
            action="correct",
            label="demand-ordering-variation",
            contains_any=["experiment", "benchmark", "measur", "design", "plan", "evaluat"],
            not_contains=["nearly-sorted", "ordering", "ordered", "presort"],
            correct_text=DESIGN_REDIRECT_TEXT,
        ),
        # The pivot: redirect a naive claim that lacks the interaction framing.
        Rule(
            type="pi_decision_select",
            action="correct",
            label="pivot-from-naive-claim",
            contains_any=subject.forbidden_claim_keywords,
            not_contains=subject.required_claim_keywords,
            correct_text=PIVOT_REDIRECT_TEXT,
        ),
        # Ratify a decision that names the interaction (the pivoted claim).
        Rule(
            type="pi_decision_select",
            action="accept",
            label="ratify-interaction-claim",
            contains_any=subject.required_claim_keywords,
        ),
    ]
    return PIOracle(Rubric(rules=rules, default_action="accept"))


# --- mission specs: the fourteen stages → five missions -------------------
#
# Each spec maps to rka_create_mission kwargs (objective + phase/tags +
# scope_boundaries/checkpoint_triggers as mission metadata). `stages` records
# which of the 14 PhD-workflow stages the mission covers; `depends_on` chains
# the milestone DAG; `expected_artifact_kinds` feeds the capability grader.

MISSION_SPECS: list[dict] = [
    {
        "name": "literature-and-framing",
        "objective": (
            "Survey comparison-sort performance literature, frame the research "
            "question (is quicksort efficient across input distributions?), and "
            "identify the open problem and the key insight that pivot choice and "
            "input ordering may govern the answer."
        ),
        "stages": [
            "literature investigation", "frame pitch", "problem finding",
            "insight discovery",
        ],
        "tasks": [
            "Search and ingest prior work on quicksort/insertion-sort comparison complexity.",
            "Record the naive hypothesis as a decision (to be tested, not assumed).",
            "Surface the pivot-selection / hybrid-sort literature as the insight seed.",
        ],
        "scope_boundaries": ["comparison counts only; no wall-clock or hardware claims"],
        "checkpoint_triggers": ["if the literature already settles the question, checkpoint"],
        "capabilities": ["record_knowledge"],
        "depends_on": [],
        "expected_artifact_kinds": ("journal", "decision", "claim"),
    },
    {
        "name": "proposal-and-design",
        "objective": (
            "Write a small proposal and design the experiment: a full factorial "
            "over algorithm (insertion vs first-pivot quicksort) x size x input "
            "ordering, measured in element comparisons. Refine the literature "
            "with pivot-selection sources."
        ),
        "stages": [
            "small pitch proposal generation", "research design",
            "evidence collection and literature refinement", "experiment design",
        ],
        "tasks": [
            "Draft the proposal as a decision.",
            "Specify the factorial design INCLUDING an input-ordering factor "
            "(random AND nearly-sorted) — not size alone.",
            "Add the pivot-selection citations missed in M1.",
        ],
        "scope_boundaries": ["design must vary input ordering, not only size"],
        "checkpoint_triggers": ["if a sound design cannot be specified, checkpoint"],
        "capabilities": ["record_knowledge"],
        "depends_on": ["literature-and-framing"],
        "expected_artifact_kinds": ("journal", "decision"),
    },
    {
        "name": "experiment-and-pivot",
        "objective": (
            "Conduct the experiment (instrument both sorts, count comparisons "
            "across the factorial), interpret the results, and — if they "
            "contradict the naive hypothesis — pivot the claim to the "
            "size-by-ordering interaction, recording the pivot as a decision."
        ),
        "stages": [
            "experiment conduction", "result interpretation", "claim pitch pivot",
        ],
        "tasks": [
            "Run insertion_sort and first-pivot quicksort, counting comparisons, "
            "across random and nearly-sorted inputs at two sizes.",
            "Interpret the comparison-count quadrant; note the sign flip on "
            "nearly-sorted input.",
            "Pivot the claim from 'quicksort always wins' to the interaction, and "
            "record it as a decision that supersedes the naive hypothesis.",
        ],
        "scope_boundaries": ["claim must follow the observed comparison counts"],
        "checkpoint_triggers": [
            "if results are ambiguous or the sort is incorrect, checkpoint",
        ],
        "capabilities": ["record_knowledge", "execution_gates"],
        "depends_on": ["proposal-and-design"],
        "expected_artifact_kinds": ("journal", "decision", "claim", "report"),
    },
    {
        "name": "manuscript-draft",
        "objective": (
            "Draft a short manuscript reporting the interaction finding, with a "
            "comparison-count figure (quicksort advantage vs input ordering), "
            "citing the surfaced literature."
        ),
        "stages": ["manuscript drafting with diagram generation"],
        "tasks": [
            "Draft the manuscript sections from the recorded claims + report.",
            "Generate the comparison-count figure.",
            "Ensure every quantitative claim cites a recorded result.",
        ],
        "scope_boundaries": ["only claims backed by the recorded experiment"],
        "checkpoint_triggers": ["if a claim lacks provenance, checkpoint"],
        "capabilities": ["record_knowledge"],
        "depends_on": ["experiment-and-pivot"],
        "expected_artifact_kinds": ("manuscript", "diagram", "report"),
    },
    {
        "name": "review-and-refine",
        "objective": (
            "Incorporate reviewer feedback and refine the manuscript: address "
            "concerns about pivot-choice generality and the comparison-count "
            "(vs wall-clock) metric, without overclaiming."
        ),
        "stages": ["reviewers feedback", "manuscript refinement"],
        "tasks": [
            "Triage reviewer comments into a decision list.",
            "Refine the manuscript; scope the claim to first-pivot quicksort and "
            "the comparison-count metric.",
            "Record what changed and why as decisions.",
        ],
        "scope_boundaries": ["refinement must not reintroduce the naive overclaim"],
        "checkpoint_triggers": ["if a reviewer demand conflicts with the data, checkpoint"],
        "capabilities": ["record_knowledge"],
        "depends_on": ["manuscript-draft"],
        "expected_artifact_kinds": ("journal", "decision", "manuscript"),
    },
]


def mission_spec(name: str) -> dict:
    for m in MISSION_SPECS:
        if m["name"] == name:
            return m
    raise KeyError(name)


# All fourteen workflow stages the runbook must cover, in order.
ALL_STAGES: tuple[str, ...] = (
    "literature investigation", "frame pitch", "problem finding",
    "insight discovery", "small pitch proposal generation", "research design",
    "evidence collection and literature refinement", "experiment design",
    "experiment conduction", "result interpretation", "claim pitch pivot",
    "manuscript drafting with diagram generation", "reviewers feedback",
    "manuscript refinement",
)


# Expected per-axis grades for a correct agentic (arm A) run. Arm B (plain
# Claude Code, no RKA) is expected to score well on capability but materially
# lower on provenance (no recorded, traceable pivot) — that gap is the thesis.
GRADE_TARGETS = {
    "arm_A_agentic": {"capability": 1.0, "reliability": 1.0, "provenance": 1.0},
    # The design + pivot redrafts are EXPECTED, so the reliability grader should
    # be run with a redraft budget that allows them (max_redrafts >= 2).
    "expected_redrafts": {"greenlight_design": 1, "decision_pivot": 1},
    "min_reliability_max_redrafts": 4,
}
