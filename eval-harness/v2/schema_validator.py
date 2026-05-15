"""Scenario validator built on top of the JSON Schema in ``schema.json``.

Adds two runtime checks JSON Schema can't express cleanly:

  1. **Critical-floor**: each scenario must have >=3 entries in
     ``expected_entities`` tagged ``importance="critical"`` (in addition
     to the schema-level ``minItems: 5`` total).
  2. **Type/prefix consistency**: each entry's ``entity_id`` prefix
     must match its declared ``entity_type``. JSON Schema would need a
     verbose ``oneOf`` to express this; a 5-line Python rule is clearer.

The validator raises ``ScenarioValidationError`` on any failure with a
human-readable message + the offending field path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import jsonschema

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"

_TYPE_TO_PREFIX = {
    "journal": "jrn_",
    "decision": "dec_",
    "mission": "mis_",
    "claim": "clm_",
    "cluster": "ecl_",
    "literature": "lit_",
    "checkpoint": "chk_",
}


class ScenarioValidationError(ValueError):
    """Raised when a scenario fails schema OR the runtime constraints."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field


def _load_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text())


_SCHEMA = _load_schema()


def validate_scenario(scenario: dict[str, Any]) -> None:
    """Validate one scenario against schema + runtime rules.

    Raises ``ScenarioValidationError`` on failure. Returns ``None`` on success.
    """
    # Step 1: JSON Schema validation (structural).
    try:
        jsonschema.validate(scenario, _SCHEMA)
    except jsonschema.ValidationError as exc:
        path = "/".join(str(p) for p in exc.absolute_path) or "(root)"
        raise ScenarioValidationError(
            f"schema violation at {path}: {exc.message}",
            field=path,
        ) from exc

    # Step 2: critical-floor rule (>=3 entries tagged critical).
    expected = scenario["expected_entities"]
    critical_count = sum(1 for e in expected if e.get("importance") == "critical")
    if critical_count < 3:
        raise ScenarioValidationError(
            f"scenario '{scenario['scenario_id']}' has {critical_count} "
            f"critical-tagged entities; minimum is 3",
            field="expected_entities[].importance",
        )

    # Step 3: entity_type / entity_id prefix consistency.
    for i, entity in enumerate(expected):
        prefix = _TYPE_TO_PREFIX[entity["entity_type"]]
        if not entity["entity_id"].startswith(prefix):
            raise ScenarioValidationError(
                f"scenario '{scenario['scenario_id']}' expected_entities[{i}]: "
                f"entity_id {entity['entity_id']!r} does not match the "
                f"entity_type {entity['entity_type']!r} (expected prefix {prefix!r})",
                field=f"expected_entities[{i}].entity_id",
            )


def validate_corpus(scenarios: Iterable[dict[str, Any]]) -> list[str]:
    """Validate every scenario; return the list of scenario_ids on success.

    Raises on the first failure (fail-fast). Callers that want to collect
    all failures should iterate + call ``validate_scenario`` individually.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for scenario in scenarios:
        validate_scenario(scenario)
        sid = scenario["scenario_id"]
        if sid in seen:
            raise ScenarioValidationError(
                f"duplicate scenario_id {sid!r} in corpus",
                field="scenario_id",
            )
        seen.add(sid)
        ids.append(sid)
    return ids


def load_corpus(path: Path | str) -> list[dict[str, Any]]:
    """Read a JSONL corpus file; return validated scenario list."""
    raw_lines = Path(path).read_text().splitlines()
    scenarios = [json.loads(line) for line in raw_lines if line.strip()]
    validate_corpus(scenarios)
    return scenarios
