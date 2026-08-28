#!/usr/bin/env python3
"""Score externally produced cold-session research-story answers.

The PI/Brain/Executor sessions run outside this harness.  Each receives only a
project id and one natural-language question, uses RKA Core reads, and writes a
small JSONL answer artifact.  A separate collector saves normalized raw RKA
tool calls, and a separate reviewer may save semantic rubric scores.  This CLI
binds all three artifacts to one run, cold session, role, project, query, and
answer hash without embedding an LLM or a second orchestrator in Eval-v3.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_V3_DIR = Path(__file__).resolve().parent.parent
if str(_V3_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_V3_DIR.parent))

from v3.tracing.metrics import (  # noqa: E402
    aggregate_story_responses,
    score_story_response,
)
from v3.tracing.runner import (  # noqa: E402
    ENTITY_ID_PATTERN,
    extract_entity_ids,
    load_corpus,
    resolved_entity_ids,
)

DEFAULT_ROLES = ("pi", "brain", "executor")
PREVIEW_EVIDENCE_PREFIXES = frozenset(
    {"exp", "epv", "run", "rue", "obs", "elc", "evr"}
)
GRAPH_ID_FIELDS = (
    "cited_entity_ids",
    "current_entity_ids",
    "causal_chain",
    "rejected_entity_ids",
)

# Only these typed experiment reads return authoritative preview-subsystem
# records.  Each top-level record and named child collection is constrained to
# the prefixes its response model actually owns.  In particular, arbitrary
# config/environment/summary dictionaries are never walked for attestation.
TYPED_EXPERIMENT_RECORD_LAYOUTS = {
    "experiments": {
        None: frozenset({"exp"}),
        "current_plan": frozenset({"epv"}),
        "plan_versions": frozenset({"epv"}),
        "runs": frozenset({"run"}),
    },
    "experiment_runs": {
        None: frozenset({"run"}),
        "events": frozenset({"rue"}),
        "observations": frozenset({"obs"}),
    },
    "experiment_observations": {
        None: frozenset({"obs"}),
        "locators": frozenset({"elc"}),
        "claim_relations": frozenset({"evr"}),
    },
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{path}:{line_no}: each record must be an object")
        records.append(record)
    return records


def canonical_record_sha256(record: dict[str, Any]) -> str:
    """Stable digest used to bind an independent rating to one exact answer."""
    payload = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_trace_response(payload: Any, *, context: str) -> Any:
    """Decode exact JSON captured as text without changing the raw trace.

    Collectors may see either the JSON value returned by REST, its exact JSON
    serialization, or the standard single-text MCP content envelope.  The
    scorer consumes an in-memory decoded value while the caller's trace and
    on-disk hash remain byte-for-byte raw.  Markdown fences and multi-content
    envelopes are deliberately not guessed at.
    """
    candidate = payload
    if isinstance(payload, dict):
        content = payload.get("content")
        if (
            isinstance(content, list)
            and len(content) == 1
            and isinstance(content[0], dict)
            and content[0].get("type") == "text"
            and isinstance(content[0].get("text"), str)
        ):
            candidate = content[0]["text"]
        else:
            return payload
    if not isinstance(candidate, str):
        return payload
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        if candidate is not payload:
            raise ValueError(
                f"{context}: single MCP text content must contain one exact JSON value"
            ) from None
        return payload


def _validate_response_id_arrays(
    response: dict[str, Any],
    key: tuple[str, str, str],
) -> None:
    rendered = ":".join(key)
    for field in GRAPH_ID_FIELDS:
        values = response.get(field, [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) or ENTITY_ID_PATTERN.fullmatch(value) is None
            for value in values
        ):
            raise ValueError(
                f"response {field} must be a flat array of entity ID strings: {rendered}"
            )
        preview_ids = [
            value for value in values if value.partition("_")[0] in PREVIEW_EVIDENCE_PREFIXES
        ]
        if preview_ids:
            raise ValueError(
                f"response {field} is graph/resolver-only; move preview IDs to "
                f"preview_evidence_ids: {rendered}"
            )

    preview_ids = response.get("preview_evidence_ids", [])
    if not isinstance(preview_ids, list) or any(
        not isinstance(value, str)
        or ENTITY_ID_PATTERN.fullmatch(value) is None
        or value.partition("_")[0] not in PREVIEW_EVIDENCE_PREFIXES
        for value in preview_ids
    ):
        raise ValueError(
            "response preview_evidence_ids must be a flat array of "
            "exp_/epv_/run_/rue_/obs_/elc_/evr_ "
            f"IDs: {rendered}"
        )


def _direct_records(value: Any) -> list[dict[str, Any]]:
    """Return direct structured records without recursively mining payloads."""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _attested_preview_record_ids(
    operation: str,
    payload: Any,
    expected_project_id: str,
) -> set[str]:
    """Return preview IDs backed by typed, same-project experiment records.

    A broad string scan is intentionally insufficient: preview identifiers can
    occur in search snippets, journal prose, relationship fields, or arbitrary
    experiment config.  Attestation requires an exact ``id`` plus an exact
    record-level ``project_id`` at a response location owned by the typed
    experiment operation.
    """
    layout = TYPED_EXPERIMENT_RECORD_LAYOUTS.get(operation)
    if layout is None:
        return set()

    found: set[str] = set()

    def add_records(value: Any, allowed_prefixes: frozenset[str]) -> None:
        for record in _direct_records(value):
            record_id = record.get("id")
            if (
                isinstance(record_id, str)
                and ENTITY_ID_PATTERN.fullmatch(record_id) is not None
                and record_id.partition("_")[0] in allowed_prefixes
                and record.get("project_id") == expected_project_id
            ):
                found.add(record_id)

    add_records(payload, layout[None])
    if isinstance(payload, dict):
        for field, allowed_prefixes in layout.items():
            if field is not None:
                add_records(payload.get(field), allowed_prefixes)
    return found


def _artifact_key(record: dict[str, Any], label: str, index: int) -> tuple[str, str, str]:
    try:
        return record["scenario_id"], record["query_variant"], record["role"]
    except KeyError as exc:
        raise ValueError(f"{label} {index}: missing required field {exc.args[0]!r}") from exc


def _validate_bound_artifact(
    record: dict[str, Any],
    scenario: dict[str, Any],
    variant: dict[str, Any],
    label: str,
    key: tuple[str, str, str],
    run_id: str,
) -> None:
    rendered = ":".join(key)
    if record.get("run_id") != run_id:
        raise ValueError(f"{label} run mismatch: {rendered}")
    if record.get("project_id") != scenario["project_id"]:
        raise ValueError(f"{label} project mismatch: {rendered}")
    if record.get("query") != variant["query"]:
        raise ValueError(f"{label} query mismatch: {rendered}")
    if not isinstance(record.get("session_id"), str) or not record["session_id"].strip():
        raise ValueError(f"{label} requires session_id: {rendered}")


def score_response_set(
    scenarios: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    ratings: list[dict[str, Any]] | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    expected: dict[tuple[str, str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for scenario in scenarios:
        if "story" not in scenario:
            continue
        if not scenario.get("project_id"):
            raise ValueError(f"story scenario {scenario['scenario_id']!r} requires project_id")
        if not scenario["story"].get("causal_edges"):
            raise ValueError(f"story scenario {scenario['scenario_id']!r} requires causal_edges")
        conclusion = scenario["story"].get("current_conclusion", {})
        if not conclusion.get("checks"):
            raise ValueError(
                f"story scenario {scenario['scenario_id']!r} requires current_conclusion.checks"
            )
        roles = scenario.get("required_roles", list(DEFAULT_ROLES))
        if (
            not isinstance(roles, list)
            or any(not isinstance(role, str) for role in roles)
            or len(roles) != len(DEFAULT_ROLES)
            or set(roles) != set(DEFAULT_ROLES)
        ):
            raise ValueError(
                f"story scenario {scenario['scenario_id']!r} has invalid required_roles"
            )
        for variant in scenario["query_variants"]:
            for role in roles:
                key = (scenario["scenario_id"], variant["variant_id"], role)
                if key in expected:
                    raise ValueError(f"duplicate corpus key: {':'.join(key)}")
                expected[key] = (scenario, variant)

    supplied: dict[tuple[str, str, str], dict[str, Any]] = {}
    response_sessions: set[str] = set()
    for index, response in enumerate(responses, 1):
        key = _artifact_key(response, "response", index)
        if key not in expected:
            raise ValueError(f"unknown response key: {':'.join(key)}")
        if key in supplied:
            raise ValueError(f"duplicate response key: {':'.join(key)}")
        scenario, variant = expected[key]
        _validate_bound_artifact(response, scenario, variant, "response", key, run_id)
        if response["session_id"] in response_sessions:
            raise ValueError(f"response session_id reused: {response['session_id']}")
        response_sessions.add(response["session_id"])
        trace_owned = {
            "retrieved_entity_ids",
            "resolved_entity_ids",
            "human_scores",
            "response_sha256",
        } & set(response)
        if trace_owned:
            fields = ", ".join(sorted(trace_owned))
            raise ValueError(
                f"response contains independently owned fields ({fields}): {':'.join(key)}"
            )
        _validate_response_id_arrays(response, key)
        supplied[key] = response

    missing = sorted(set(expected) - set(supplied))
    if missing:
        rendered = ", ".join(":".join(key) for key in missing)
        raise ValueError(f"missing responses: {rendered}")

    supplied_traces: dict[tuple[str, str, str], dict[str, Any]] = {}
    for index, trace in enumerate(traces, 1):
        key = _artifact_key(trace, "trace", index)
        if key not in expected:
            raise ValueError(f"unknown trace key: {':'.join(key)}")
        if key in supplied_traces:
            raise ValueError(f"duplicate trace key: {':'.join(key)}")
        scenario, variant = expected[key]
        _validate_bound_artifact(trace, scenario, variant, "trace", key, run_id)
        if trace["session_id"] != supplied[key]["session_id"]:
            raise ValueError(f"trace session mismatch: {':'.join(key)}")
        if trace.get("response_sha256") != canonical_record_sha256(supplied[key]):
            raise ValueError(f"trace response hash mismatch: {':'.join(key)}")
        if {"retrieved_entity_ids", "resolved_entity_ids"} & set(trace):
            raise ValueError(f"trace must contain raw calls, not claimed id lists: {':'.join(key)}")
        collector_id = trace.get("collector_id")
        if not isinstance(collector_id, str) or not collector_id.strip():
            raise ValueError(f"trace requires collector_id: {':'.join(key)}")
        if collector_id == trace["session_id"]:
            raise ValueError(f"trace collector must be independent: {':'.join(key)}")
        calls = trace.get("calls")
        if not isinstance(calls, list) or not calls:
            raise ValueError(f"trace requires raw calls: {':'.join(key)}")

        retrieved_ids: set[str] = set()
        resolved_ids: set[str] = set()
        attested_preview_ids: set[str] = set()
        ordinals: list[int] = []
        for call_index, call in enumerate(calls, 1):
            if not isinstance(call, dict):
                raise ValueError(f"trace call {call_index} must be an object: {':'.join(key)}")
            ordinal = call.get("ordinal")
            if not isinstance(ordinal, int):
                raise ValueError(f"trace call requires integer ordinal: {':'.join(key)}")
            ordinals.append(ordinal)
            if call.get("project_id") != scenario["project_id"]:
                raise ValueError(f"trace call project mismatch: {':'.join(key)}")
            request = call.get("request")
            if not isinstance(request, dict) or request.get("project_id") != scenario["project_id"]:
                raise ValueError(f"trace call request is not project-bound: {':'.join(key)}")
            operation = call.get("operation")
            if not isinstance(operation, str) or not operation:
                raise ValueError(f"trace call requires operation: {':'.join(key)}")
            if call.get("outcome") != "ok":
                continue
            response_payload = _normalize_trace_response(
                call.get("response"),
                context=f"trace call {call_index} response ({':'.join(key)})",
            )
            retrieved_ids.update(extract_entity_ids(response_payload))
            attested_preview_ids.update(
                _attested_preview_record_ids(
                    operation,
                    response_payload,
                    scenario["project_id"],
                )
            )
            if operation == "resolve_entities":
                if not isinstance(response_payload, dict):
                    raise ValueError(
                        "resolver response must be an object, an exact JSON string, or a "
                        f"single MCP text-content JSON envelope: {':'.join(key)}"
                    )
                resolved_ids.update(resolved_entity_ids(response_payload, scenario["project_id"]))
        if ordinals != list(range(1, len(calls) + 1)):
            raise ValueError(f"trace call ordinals must be contiguous: {':'.join(key)}")

        missing_preview = sorted(
            set(supplied[key].get("preview_evidence_ids", [])) - attested_preview_ids
        )
        if missing_preview:
            raise ValueError(
                "response preview evidence is not attested by a matching "
                "same-project typed experiment record "
                f"({', '.join(missing_preview)}): {':'.join(key)}"
            )

        supplied_traces[key] = {
            **trace,
            "retrieved_entity_ids": sorted(retrieved_ids),
            "resolved_entity_ids": sorted(resolved_ids),
        }

    missing_traces = sorted(set(expected) - set(supplied_traces))
    if missing_traces:
        rendered = ", ".join(":".join(key) for key in missing_traces)
        raise ValueError(f"missing traces: {rendered}")

    supplied_ratings: dict[tuple[str, str, str], dict[str, Any]] = {}
    for index, rating in enumerate(ratings or [], 1):
        key = _artifact_key(rating, "rating", index)
        if key not in expected:
            raise ValueError(f"unknown rating key: {':'.join(key)}")
        if key in supplied_ratings:
            raise ValueError(f"duplicate rating key: {':'.join(key)}")
        scenario, variant = expected[key]
        _validate_bound_artifact(rating, scenario, variant, "rating", key, run_id)
        if rating["session_id"] != supplied[key]["session_id"]:
            raise ValueError(f"rating session mismatch: {':'.join(key)}")
        if not rating.get("reviewer_id"):
            raise ValueError(f"rating requires reviewer_id: {':'.join(key)}")
        if rating["reviewer_id"] == rating["session_id"]:
            raise ValueError(f"rating reviewer must be independent: {':'.join(key)}")
        expected_hash = canonical_record_sha256(supplied[key])
        if rating.get("response_sha256") != expected_hash:
            raise ValueError(f"rating response hash mismatch: {':'.join(key)}")
        supplied_ratings[key] = rating

    scores = []
    for key in sorted(expected):
        scenario, variant = expected[key]
        trace = supplied_traces[key]
        response_hash = canonical_record_sha256(supplied[key])
        response = {
            **supplied[key],
            "style": variant.get("style", key[1]),
            "retrieved_entity_ids": trace["retrieved_entity_ids"],
            "resolved_entity_ids": trace["resolved_entity_ids"],
            "response_sha256": response_hash,
        }
        rating = supplied_ratings.get(key)
        if rating is not None:
            response["human_scores"] = rating.get("human_scores")
            response["human_reviewer_id"] = rating["reviewer_id"]
        scores.append(score_story_response(scenario, response))
    return {
        "aggregate": aggregate_story_responses(scores),
        "responses": scores,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", required=True, help="frozen story JSONL corpus")
    parser.add_argument("--run-id", required=True, help="frozen id shared by all run artifacts")
    parser.add_argument("--responses", required=True, help="cold-session response JSONL")
    parser.add_argument("--traces", required=True, help="independently captured RKA trace JSONL")
    parser.add_argument("--ratings", help="optional independent human-rating JSONL")
    parser.add_argument("--out", help="write metrics JSON here; defaults to stdout")
    args = parser.parse_args(argv)

    corpus_path = Path(args.corpus)
    responses_path = Path(args.responses)
    traces_path = Path(args.traces)
    ratings_path = Path(args.ratings) if args.ratings else None
    try:
        result = score_response_set(
            load_corpus(corpus_path),
            load_jsonl(responses_path),
            load_jsonl(traces_path),
            load_jsonl(ratings_path) if ratings_path else None,
            run_id=args.run_id,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result["meta"] = {
        "run_id": args.run_id,
        "corpus": str(corpus_path),
        "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
        "responses": str(responses_path),
        "responses_sha256": hashlib.sha256(responses_path.read_bytes()).hexdigest(),
        "traces": str(traces_path),
        "traces_sha256": hashlib.sha256(traces_path.read_bytes()).hexdigest(),
        "ratings": str(ratings_path) if ratings_path else None,
        "ratings_sha256": hashlib.sha256(ratings_path.read_bytes()).hexdigest()
        if ratings_path
        else None,
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
