"""Per-run record schema for the end-to-end research-lifecycle eval.

One ``RunRecord`` is written (as JSON) per orchestrator run (a Phase-O run, a
mission run, a writer/revision pass). The grader suite consumes these plus the
RKA knowledge-graph state and the sealed subject ground truth.

Captures the three measurement axes from the test plan:
  - capability:  artifacts produced (artifact ids by kind)
  - reliability: terminal_state, segments, watchdog/escalation signals,
                 PI-interventions (oracle decisions), redraft-loop usage, cost
  - provenance:  the workflow_thread_id that tags every RKA write this run made,
                 so a run's artifacts are recoverable via
                 rka_get_journal(tags=[workflow_thread_id]).

Reproducibility provenance (corpus hash / rka HEAD / orchestrator version /
seed) lives on the record so a result is reconstructable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# The mission/Phase-O graphs emit artifacts shaped
# ``{rka_id, entity_type, node_name, timestamp}`` (see nodes/brain.py::_artifact
# and nodes/executor.py::_artifact), but the grader suite reads ``kind`` / ``id``
# / ``node``. Normalize at the from_final_state boundary so the documented
# ``from_final_state(...) -> grade_run(...)`` flow scores capability on a real
# run. Aliases are additive — hand-built ``{"kind": ...}`` artifacts (tests,
# the offline smoke) pass through unchanged.
_ARTIFACT_KIND_KEYS = ("kind", "entity_type")
_ARTIFACT_ID_KEYS = ("id", "rka_id")
_ARTIFACT_NODE_KEYS = ("node", "node_name")


def _first_present(d: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return None


def _normalize_artifact(a: Any) -> Any:
    """Add canonical ``kind``/``id``/``node`` aliases to a graph artifact dict
    without dropping the original ``entity_type``/``rka_id``/``node_name`` keys.
    Non-dict entries pass through unchanged."""
    if not isinstance(a, dict):
        return a
    out = dict(a)
    for canonical, sources in (
        ("kind", _ARTIFACT_KIND_KEYS),
        ("id", _ARTIFACT_ID_KEYS),
        ("node", _ARTIFACT_NODE_KEYS),
    ):
        if canonical not in out:
            val = _first_present(a, sources)
            if val is not None:
                out[canonical] = val
    return out


@dataclass
class RunRecord:
    # identity / reproducibility
    arc: str                       # "phase_o" | "mission" | "writer" | "revision"
    run_label: str                 # human label, e.g. "mission-3-experiment"
    workflow_thread_id: Optional[str] = None
    project_id: Optional[str] = None
    mission_id: Optional[str] = None
    seed: Optional[int] = None
    orchestrator_version: Optional[str] = None
    rka_head: Optional[str] = None
    subject_id: Optional[str] = None
    subject_ground_truth_hash: Optional[str] = None
    arm: str = "A"                 # "A" agentic | "B" plain-claude | "C" human

    # capability
    terminal_state: Optional[str] = None   # complete | escalated | failed | cancelled
    artifacts: list[dict[str, Any]] = field(default_factory=list)  # [{id, kind, node}]

    # reliability telemetry
    segments: int = 0
    watchdog_escalations: int = 0
    escalation_router_hits: int = 0
    greenlight_redrafts: int = 0
    decision_redrafts: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    usd_spent: float = 0.0
    wall_clock_s: Optional[float] = None

    # PI interaction (oracle decision log, or human-PI transcript summary)
    pi_decisions: list[dict[str, Any]] = field(default_factory=list)
    pi_intervention_count: int = 0     # corrections + rejects (not bare accepts)

    # free-form notes (e.g. "mission_guard surfaced 2 warnings at pickup")
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_final_state(
        cls,
        *,
        arc: str,
        run_label: str,
        final_state: dict,
        oracle_decisions: Optional[list[dict]] = None,
        **kw: Any,
    ) -> "RunRecord":
        """Build a record from a LangGraph terminal state + oracle log."""
        decisions = oracle_decisions or []
        interventions = sum(1 for d in decisions if d.get("action") in ("correct", "reject"))
        return cls(
            arc=arc,
            run_label=run_label,
            workflow_thread_id=final_state.get("workflow_thread_id"),
            project_id=final_state.get("project_id"),
            mission_id=final_state.get("mission_id"),
            terminal_state=final_state.get("terminal_state"),
            artifacts=[_normalize_artifact(a) for a in (final_state.get("artifacts", []) or [])],
            greenlight_redrafts=int(final_state.get("greenlight_redrafts", 0) or 0),
            decision_redrafts=int(final_state.get("decision_redrafts", 0) or 0),
            errors=list(final_state.get("errors", []) or []),
            usd_spent=float(final_state.get("usd_spent", 0.0) or 0.0),
            escalation_router_hits=sum(
                1 for e in (final_state.get("errors") or [])
                if (e.get("node_name") == "escalation_router")
            ),
            pi_decisions=decisions,
            pi_intervention_count=interventions,
            **kw,
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(), encoding="utf-8")
        return p
