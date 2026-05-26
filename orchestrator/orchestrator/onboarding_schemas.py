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
