"""Phase O — structured dataclasses for the project-onboarding workflow.

Holds the schema for artifacts that flow between Phase O sub-phases:

  - **PolishedIdea** (O1.2 output)  — what idea_polish writes.
  - **HypothesisSpec / VariableSpec / MissionMilestone / ResearchPlan**
    (O4.1 output) — what plan_synthesis writes; lands as ratified-plan
    contract gate at pi_plan_ratify.

These are pure schema + (de)serialization helpers. No LLM, no MCP, no
disk IO. The orchestrator's Brain node prompts emit JSON conforming to
these dataclasses; this module rehydrates and validates.

Conventions:
- All fields use plain types (no Optional with sentinels) for stable
  JSON round-trip. Truly optional fields use Optional[T] with None
  default — preserved across asdict / from_dict.
- Validation raises ValueError on missing required fields or
  shape mismatches. Callers (the node) wrap in a parse-retry pattern,
  mirroring nodes/executor.py:_parse_proposed_actions.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# O1.2 — PolishedIdea
# ---------------------------------------------------------------------------


@dataclass
class PolishedIdea:
    """Structured polish of the PI's free-form idea description.

    Output of the O1.2 ``idea_polish`` Brain node. Lands as a single
    journal entry tagged ``[project_id, "polished-idea"]`` for the
    plan_synthesis step to read at O4.

    Field meanings:
      - ``research_question``     — one sentence; the project's RQ.
      - ``motivation``            — 1 short paragraph on why it matters.
      - ``scope``                 — what's in vs out of scope.
      - ``target_venue``          — conference/journal acronym, if any.
      - ``novelty_hypothesis``    — what the project claims is new.
      - ``ingested_sources``      — jrn_… IDs of the PI-summarized sources
                                    fed into the polish step (backlinks
                                    to PI ingestion at O1.1).
      - ``open_assumptions``      — list of things the PI should validate
                                    before O4 plan synthesis.
    """

    research_question: str
    motivation: str
    scope: str
    novelty_hypothesis: str
    ingested_sources: list[str] = field(default_factory=list)
    open_assumptions: list[str] = field(default_factory=list)
    target_venue: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PolishedIdea":
        """Build from a plain dict (e.g., LLM JSON output).

        Validates required fields are non-empty strings. Lists default
        to empty if absent. Raises ValueError on missing/malformed
        required fields so the caller can retry with corrective
        feedback.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"PolishedIdea.from_dict expected dict, got {type(data).__name__}"
            )
        required = ("research_question", "motivation", "scope", "novelty_hypothesis")
        missing = [k for k in required if not (data.get(k) or "").strip()]
        if missing:
            raise ValueError(
                f"PolishedIdea missing required field(s): {', '.join(missing)}"
            )
        ingested = data.get("ingested_sources") or []
        if not isinstance(ingested, list):
            raise ValueError("PolishedIdea.ingested_sources must be a list")
        assumptions = data.get("open_assumptions") or []
        if not isinstance(assumptions, list):
            raise ValueError("PolishedIdea.open_assumptions must be a list")
        return cls(
            research_question=str(data["research_question"]).strip(),
            motivation=str(data["motivation"]).strip(),
            scope=str(data["scope"]).strip(),
            novelty_hypothesis=str(data["novelty_hypothesis"]).strip(),
            ingested_sources=[str(x) for x in ingested if x],
            open_assumptions=[str(x).strip() for x in assumptions if str(x).strip()],
            target_venue=(
                str(data["target_venue"]).strip()
                if data.get("target_venue") and str(data["target_venue"]).strip()
                else None
            ),
        )


# ---------------------------------------------------------------------------
# JSON extraction helper (shared by Phase O brain nodes)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# O4.1 — ResearchPlan + nested specs
# ---------------------------------------------------------------------------


HYPOTHESIS_CONFIDENCE_LITERALS = ("high", "medium", "low")
VARIABLE_KINDS = ("independent", "dependent", "confound")
MILESTONE_PHASES = (
    "literature",
    "research_design",
    "experiment_design",
    "experiment_execution",
    "analysis",
    "writeup",
)
MILESTONE_ID_PATTERN = re.compile(r"^m_\d{2,4}$")


@dataclass
class HypothesisSpec:
    statement: str
    falsifier: str
    confidence: str  # one of HYPOTHESIS_CONFIDENCE_LITERALS

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HypothesisSpec":
        if not isinstance(d, dict):
            raise ValueError(f"HypothesisSpec expected dict, got {type(d).__name__}")
        statement = str(d.get("statement", "")).strip()
        falsifier = str(d.get("falsifier", "")).strip()
        confidence = str(d.get("confidence", "")).strip().lower()
        if not statement:
            raise ValueError("HypothesisSpec.statement is required")
        if not falsifier:
            raise ValueError("HypothesisSpec.falsifier is required (what would refute it)")
        if confidence not in HYPOTHESIS_CONFIDENCE_LITERALS:
            raise ValueError(
                f"HypothesisSpec.confidence must be one of "
                f"{HYPOTHESIS_CONFIDENCE_LITERALS}, got {confidence!r}"
            )
        return cls(statement=statement, falsifier=falsifier, confidence=confidence)


@dataclass
class VariableSpec:
    name: str
    kind: str  # one of VARIABLE_KINDS
    description: str
    measurement: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "VariableSpec":
        if not isinstance(d, dict):
            raise ValueError(f"VariableSpec expected dict, got {type(d).__name__}")
        name = str(d.get("name", "")).strip()
        kind = str(d.get("kind", "")).strip().lower()
        description = str(d.get("description", "")).strip()
        if not name:
            raise ValueError("VariableSpec.name is required")
        if kind not in VARIABLE_KINDS:
            raise ValueError(
                f"VariableSpec.kind must be one of {VARIABLE_KINDS}, got {kind!r}"
            )
        if not description:
            raise ValueError("VariableSpec.description is required")
        measurement_raw = d.get("measurement")
        measurement = (
            str(measurement_raw).strip()
            if measurement_raw is not None and str(measurement_raw).strip()
            else None
        )
        return cls(name=name, kind=kind, description=description, measurement=measurement)


@dataclass
class MissionMilestone:
    """One executable mission the orchestrator dispatches in Phase H."""

    milestone_id: str       # m_01, m_02, … (auto-generated if Brain omits)
    phase: str              # one of MILESTONE_PHASES
    objective: str
    acceptance_criteria: str
    scope_boundaries: str
    estimated_llm_cost_usd: float
    estimated_wall_clock_min: int
    depends_on_milestone: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MissionMilestone":
        if not isinstance(d, dict):
            raise ValueError(f"MissionMilestone expected dict, got {type(d).__name__}")
        milestone_id = str(d.get("milestone_id", "")).strip()
        if not milestone_id:
            raise ValueError("MissionMilestone.milestone_id is required")
        if not MILESTONE_ID_PATTERN.match(milestone_id):
            raise ValueError(
                f"MissionMilestone.milestone_id must match pattern "
                f"{MILESTONE_ID_PATTERN.pattern!r}; got {milestone_id!r}"
            )
        phase = str(d.get("phase", "")).strip().lower()
        if phase not in MILESTONE_PHASES:
            raise ValueError(
                f"MissionMilestone.phase must be one of {MILESTONE_PHASES}; "
                f"got {phase!r}"
            )
        objective = str(d.get("objective", "")).strip()
        if not objective:
            raise ValueError("MissionMilestone.objective is required")
        acceptance = str(d.get("acceptance_criteria", "")).strip()
        if not acceptance:
            raise ValueError("MissionMilestone.acceptance_criteria is required")
        scope = str(d.get("scope_boundaries", "")).strip()
        if not scope:
            raise ValueError("MissionMilestone.scope_boundaries is required")
        try:
            cost = float(d.get("estimated_llm_cost_usd", 0.0))
        except (TypeError, ValueError):
            raise ValueError("MissionMilestone.estimated_llm_cost_usd must be numeric")
        if cost < 0:
            raise ValueError("MissionMilestone.estimated_llm_cost_usd must be ≥ 0")
        try:
            wall = int(d.get("estimated_wall_clock_min", 0))
        except (TypeError, ValueError):
            raise ValueError("MissionMilestone.estimated_wall_clock_min must be int")
        if wall < 0:
            raise ValueError("MissionMilestone.estimated_wall_clock_min must be ≥ 0")
        depends_raw = d.get("depends_on_milestone")
        depends = (
            str(depends_raw).strip()
            if depends_raw is not None and str(depends_raw).strip()
            else None
        )
        if depends is not None and not MILESTONE_ID_PATTERN.match(depends):
            raise ValueError(
                f"MissionMilestone.depends_on_milestone must match the milestone_id "
                f"pattern; got {depends!r}"
            )
        return cls(
            milestone_id=milestone_id,
            phase=phase,
            objective=objective,
            acceptance_criteria=acceptance,
            scope_boundaries=scope,
            estimated_llm_cost_usd=cost,
            estimated_wall_clock_min=wall,
            depends_on_milestone=depends,
        )


@dataclass
class ResearchPlan:
    """O4.1 output. THE contract licensing autonomy at pi_plan_ratify."""

    refined_research_question: str
    hypotheses: list[HypothesisSpec]
    variables: list[VariableSpec]
    experimental_matrix: str
    literature_gaps: list[str]
    milestones: list[MissionMilestone]
    open_risks: list[str]
    polished_idea_journal_id: str  # backlink to O1.2 output

    def to_dict(self) -> dict:
        return {
            "refined_research_question": self.refined_research_question,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "variables": [v.to_dict() for v in self.variables],
            "experimental_matrix": self.experimental_matrix,
            "literature_gaps": list(self.literature_gaps),
            "milestones": [m.to_dict() for m in self.milestones],
            "open_risks": list(self.open_risks),
            "polished_idea_journal_id": self.polished_idea_journal_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ResearchPlan":
        if not isinstance(d, dict):
            raise ValueError(f"ResearchPlan expected dict, got {type(d).__name__}")
        rq = str(d.get("refined_research_question", "")).strip()
        if not rq:
            raise ValueError("ResearchPlan.refined_research_question is required")
        matrix = str(d.get("experimental_matrix", "")).strip()
        if not matrix:
            raise ValueError("ResearchPlan.experimental_matrix is required")
        hypotheses_raw = d.get("hypotheses") or []
        variables_raw = d.get("variables") or []
        milestones_raw = d.get("milestones") or []
        if not isinstance(hypotheses_raw, list):
            raise ValueError("ResearchPlan.hypotheses must be a list")
        if not isinstance(variables_raw, list):
            raise ValueError("ResearchPlan.variables must be a list")
        if not isinstance(milestones_raw, list):
            raise ValueError("ResearchPlan.milestones must be a list")
        if not milestones_raw:
            raise ValueError("ResearchPlan.milestones must contain ≥ 1 milestone")

        hypotheses = [HypothesisSpec.from_dict(h) for h in hypotheses_raw]
        variables = [VariableSpec.from_dict(v) for v in variables_raw]
        milestones = [MissionMilestone.from_dict(m) for m in milestones_raw]

        # Milestone DAG integrity: every depends_on_milestone must exist.
        known_ids = {m.milestone_id for m in milestones}
        for m in milestones:
            if (
                m.depends_on_milestone is not None
                and m.depends_on_milestone not in known_ids
            ):
                raise ValueError(
                    f"MissionMilestone {m.milestone_id!r} depends on "
                    f"{m.depends_on_milestone!r} which is not in the plan"
                )

        literature_gaps = d.get("literature_gaps") or []
        if not isinstance(literature_gaps, list):
            raise ValueError("ResearchPlan.literature_gaps must be a list")
        open_risks = d.get("open_risks") or []
        if not isinstance(open_risks, list):
            raise ValueError("ResearchPlan.open_risks must be a list")
        return cls(
            refined_research_question=rq,
            hypotheses=hypotheses,
            variables=variables,
            experimental_matrix=matrix,
            literature_gaps=[str(x).strip() for x in literature_gaps if str(x).strip()],
            milestones=milestones,
            open_risks=[str(x).strip() for x in open_risks if str(x).strip()],
            polished_idea_journal_id=str(d.get("polished_idea_journal_id", "")).strip(),
        )

    def total_estimated_cost_usd(self) -> float:
        return sum(m.estimated_llm_cost_usd for m in self.milestones)

    def total_estimated_wall_clock_min(self) -> int:
        return sum(m.estimated_wall_clock_min for m in self.milestones)


_FENCED_JSON_RE = re.compile(r"```json\s*\n(.+?)\n```", re.DOTALL | re.IGNORECASE)


def extract_json_block(text: str) -> Optional[dict]:
    """Pull the last ```json fenced block, or fall back to the last
    balanced ``{...}`` substring. Returns the parsed dict or None.

    Same robustness as ``executor._parse_proposed_actions`` — tolerates
    Brain replies with surrounding prose, malformed first attempts
    followed by a corrected second block, etc. Always returns the LAST
    parseable JSON object so a Brain that "thinks out loud" then emits
    final structured output still parses cleanly.
    """
    if not text:
        return None

    candidates: list[str] = []
    fenced = list(_FENCED_JSON_RE.finditer(text))
    if fenced:
        candidates.append(fenced[-1].group(1))

    last_close = text.rfind("}")
    if last_close >= 0:
        depth = 0
        for i in range(last_close, -1, -1):
            ch = text[i]
            if ch == "}":
                depth += 1
            elif ch == "{":
                depth -= 1
                if depth == 0:
                    candidates.append(text[i : last_close + 1])
                    break

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
