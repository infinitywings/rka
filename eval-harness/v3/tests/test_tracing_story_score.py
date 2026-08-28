"""Locks for the thin cold-session story-response scoring CLI."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_EVAL_HARNESS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_EVAL_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_HARNESS_DIR))

from v3.tracing.score_story_responses import (  # noqa: E402
    canonical_record_sha256,
    main,
    score_response_set,
)

RUN_ID = "run-story-pilot-001"
ROLES = ("pi", "brain", "executor")


SCENARIO = {
    "scenario_id": "nine-to-three-story",
    "project_id": "prj_00000000000000000000000001",
    "anchor_decision": "dec_00000000000000000000000001",
    "query_variants": [
        {
            "variant_id": "exact",
            "style": "exact",
            "query": "Why map nine types to three?",
        },
        {
            "variant_id": "colloquial",
            "style": "colloquial",
            "query": "Why did we simplify those types?",
        },
    ],
    "story": {
        "roles": {
            "rationale": {
                "any_of": ["jrn_00000000000000000000000001"],
                "required": True,
            },
            "decision": {
                "any_of": ["dec_00000000000000000000000001"],
                "required": True,
            },
        },
        "causal_edges": [
            [
                "jrn_00000000000000000000000001",
                "dec_00000000000000000000000001",
            ]
        ],
        "current_entities": ["dec_00000000000000000000000001"],
        "historical_entities": [],
        "forbidden_entities": [],
        "foreign_must_exclude": [],
        "current_conclusion": {
            "verdict": "adopted",
            "checks": [{"must_include": ["three record types"]}],
        },
    },
}


def _response(variant: str, role: str = "brain") -> dict:
    query = next(
        (item["query"] for item in SCENARIO["query_variants"] if item["variant_id"] == variant),
        "unknown query",
    )
    return {
        "scenario_id": SCENARIO["scenario_id"],
        "query_variant": variant,
        "role": role,
        "run_id": RUN_ID,
        "session_id": f"session-{role}-{variant}",
        "project_id": SCENARIO["project_id"],
        "query": query,
        "answer": "The project adopted three record types to keep the core model small.",
        "verdict": "adopted",
        "cited_entity_ids": [
            "jrn_00000000000000000000000001",
            "dec_00000000000000000000000001",
        ],
        "current_entity_ids": ["dec_00000000000000000000000001"],
        "causal_chain": [
            "jrn_00000000000000000000000001",
            "dec_00000000000000000000000001",
        ],
    }


def _trace(
    variant: str,
    role: str = "brain",
    *,
    resolved: list[str] | None = None,
) -> dict:
    response = _response(variant, role)
    query = next(
        item["query"] for item in SCENARIO["query_variants"] if item["variant_id"] == variant
    )
    retrieved = [
        "jrn_00000000000000000000000001",
        "dec_00000000000000000000000001",
    ]
    resolved_ids = set(retrieved if resolved is None else resolved)
    entities = {
        entity_id: {
            "found": entity_id in resolved_ids,
            "outcome": "resolved" if entity_id in resolved_ids else "missing",
            "project_id": SCENARIO["project_id"] if entity_id in resolved_ids else None,
        }
        for entity_id in retrieved
    }
    return {
        "scenario_id": SCENARIO["scenario_id"],
        "query_variant": variant,
        "role": role,
        "run_id": RUN_ID,
        "session_id": f"session-{role}-{variant}",
        "response_sha256": canonical_record_sha256(response),
        "project_id": SCENARIO["project_id"],
        "query": query,
        "collector_id": "trusted-test-collector",
        "calls": [
            {
                "ordinal": 1,
                "operation": "search",
                "project_id": SCENARIO["project_id"],
                "request": {"project_id": SCENARIO["project_id"], "query": query},
                "outcome": "ok",
                "response": [{"entity_id": entity_id} for entity_id in retrieved],
            },
            {
                "ordinal": 2,
                "operation": "resolve_entities",
                "project_id": SCENARIO["project_id"],
                "request": {"project_id": SCENARIO["project_id"], "ids": retrieved},
                "outcome": "ok",
                "response": {
                    "project_id": SCENARIO["project_id"],
                    "entities": entities,
                },
            },
        ],
    }


def _rating(variant: str, role: str = "brain", score: int = 4) -> dict:
    response = _response(variant, role)
    return {
        "scenario_id": SCENARIO["scenario_id"],
        "query_variant": variant,
        "role": role,
        "run_id": RUN_ID,
        "session_id": response["session_id"],
        "project_id": SCENARIO["project_id"],
        "query": response["query"],
        "reviewer_id": "independent-reviewer-1",
        "response_sha256": canonical_record_sha256(response),
        "human_scores": {
            "current_conclusion": score,
            "mandatory_coverage": score,
            "causal_reconstruction": score,
            "provenance_currentness": score,
            "distractor_rejection": score,
        },
    }


def _all_responses() -> list[dict]:
    return [_response(variant, role) for variant in ("exact", "colloquial") for role in ROLES]


def _all_traces() -> list[dict]:
    return [_trace(variant, role) for variant in ("exact", "colloquial") for role in ROLES]


def _all_ratings() -> list[dict]:
    return [_rating(variant, role) for variant in ("exact", "colloquial") for role in ROLES]


def test_score_response_set_matches_every_variant() -> None:
    result = score_response_set(
        [SCENARIO],
        _all_responses(),
        _all_traces(),
        _all_ratings(),
        run_id=RUN_ID,
    )
    assert result["aggregate"]["n_responses"] == 6
    assert result["aggregate"]["mechanical_pass_rate"] == 1.0
    assert result["aggregate"]["overall_pass_rate"] == 1.0
    assert set(result["aggregate"]["by_role"]) == set(ROLES)
    assert all(result["aggregate"]["by_role"][role]["overall_pass_rate"] == 1.0 for role in ROLES)


def test_score_response_set_rejects_missing_duplicate_and_unknown() -> None:
    with pytest.raises(ValueError, match="missing responses:.*colloquial:executor"):
        score_response_set(
            [SCENARIO],
            _all_responses()[:-1],
            _all_traces(),
            run_id=RUN_ID,
        )

    with pytest.raises(ValueError, match="duplicate response key"):
        score_response_set(
            [SCENARIO],
            _all_responses() + [_response("exact", "pi")],
            _all_traces(),
            run_id=RUN_ID,
        )

    with pytest.raises(ValueError, match="unknown response key"):
        score_response_set(
            [SCENARIO],
            _all_responses() + [_response("exact", "writer")],
            _all_traces(),
            run_id=RUN_ID,
        )

    reused_session = _all_responses()
    reused_session[1] = {
        **reused_session[1],
        "session_id": reused_session[0]["session_id"],
    }
    with pytest.raises(ValueError, match="response session_id reused"):
        score_response_set(
            [SCENARIO],
            reused_session,
            _all_traces(),
            run_id=RUN_ID,
        )


def test_score_response_set_rejects_wrong_project_query_and_incomplete_contract() -> None:
    wrong_project = _all_responses()
    wrong_project[0] = {**wrong_project[0], "project_id": "prj_wrong"}
    with pytest.raises(ValueError, match="response project mismatch"):
        score_response_set(
            [SCENARIO],
            wrong_project,
            _all_traces(),
            run_id=RUN_ID,
        )

    wrong_query = _all_responses()
    wrong_query[0] = {**wrong_query[0], "query": "a different frozen probe"}
    with pytest.raises(ValueError, match="response query mismatch"):
        score_response_set(
            [SCENARIO],
            wrong_query,
            _all_traces(),
            run_id=RUN_ID,
        )

    no_causal = {
        **SCENARIO,
        "story": {**SCENARIO["story"], "causal_edges": []},
    }
    with pytest.raises(ValueError, match="requires causal_edges"):
        score_response_set(
            [no_causal],
            _all_responses(),
            _all_traces(),
            run_id=RUN_ID,
        )

    incomplete_roles = {**SCENARIO, "required_roles": ["pi", "brain"]}
    with pytest.raises(ValueError, match="invalid required_roles"):
        score_response_set(
            [incomplete_roles],
            _all_responses(),
            _all_traces(),
            run_id=RUN_ID,
        )


def test_response_cannot_self_attest_and_trace_controls_citation_attestation() -> None:
    self_attested = _all_responses()
    self_attested[0] = {**self_attested[0], "resolved_entity_ids": ["invented"]}
    with pytest.raises(ValueError, match="independently owned fields"):
        score_response_set(
            [SCENARIO],
            self_attested,
            _all_traces(),
            run_id=RUN_ID,
        )

    traces = _all_traces()
    traces[0] = _trace(
        "exact",
        "pi",
        resolved=["dec_00000000000000000000000001"],
    )
    result = score_response_set(
        [SCENARIO],
        _all_responses(),
        traces,
        run_id=RUN_ID,
    )
    exact = next(
        item
        for item in result["responses"]
        if item["query_variant"] == "exact" and item["role"] == "pi"
    )
    assert exact["hard_failures"]["citation_not_attested"] == ["jrn_00000000000000000000000001"]
    assert exact["mechanical_pass"] is False


def test_missing_rating_remains_pending_human_review() -> None:
    result = score_response_set(
        [SCENARIO],
        _all_responses(),
        _all_traces(),
        run_id=RUN_ID,
    )
    assert result["aggregate"]["mechanical_pass_rate"] == 1.0
    assert result["aggregate"]["overall_pass_rate"] == 0.0
    assert result["aggregate"]["pending_human_review"] == 6


def test_trace_requires_raw_project_bound_calls_and_matching_session() -> None:
    claimed = _all_traces()
    claimed[0] = {key: value for key, value in claimed[0].items() if key != "calls"}
    claimed[0]["retrieved_entity_ids"] = ["invented"]
    claimed[0]["resolved_entity_ids"] = ["invented"]
    with pytest.raises(ValueError, match="raw calls, not claimed id lists"):
        score_response_set(
            [SCENARIO],
            _all_responses(),
            claimed,
            run_id=RUN_ID,
        )

    wrong_session = _all_traces()
    wrong_session[0] = {**wrong_session[0], "session_id": "stale-session"}
    with pytest.raises(ValueError, match="trace session mismatch"):
        score_response_set(
            [SCENARIO],
            _all_responses(),
            wrong_session,
            run_id=RUN_ID,
        )

    wrong_hash = _all_traces()
    wrong_hash[0] = {**wrong_hash[0], "response_sha256": "0" * 64}
    with pytest.raises(ValueError, match="trace response hash mismatch"):
        score_response_set(
            [SCENARIO],
            _all_responses(),
            wrong_hash,
            run_id=RUN_ID,
        )

    wrong_call_project = _all_traces()
    calls = [dict(call) for call in wrong_call_project[0]["calls"]]
    calls[0] = {**calls[0], "project_id": "prj_wrong"}
    wrong_call_project[0] = {**wrong_call_project[0], "calls": calls}
    with pytest.raises(ValueError, match="trace call project mismatch"):
        score_response_set(
            [SCENARIO],
            _all_responses(),
            wrong_call_project,
            run_id=RUN_ID,
        )

    journal_id = "jrn_00000000000000000000000001"
    for entity_project in ("prj_wrong", None):
        entity_unattested = _all_traces()
        entity = entity_unattested[0]["calls"][1]["response"]["entities"][journal_id]
        if entity_project is None:
            entity.pop("project_id")
        else:
            entity["project_id"] = entity_project
        result = score_response_set(
            [SCENARIO],
            _all_responses(),
            entity_unattested,
            run_id=RUN_ID,
        )
        scored = next(
            item
            for item in result["responses"]
            if item["query_variant"] == "exact" and item["role"] == "pi"
        )
        assert scored["hard_failures"]["citation_not_attested"] == [journal_id]
        assert scored["mechanical_pass"] is False


def test_trace_normalizes_exact_json_strings_without_mutating_raw_calls() -> None:
    traces = _all_traces()
    raw_search = json.dumps(traces[0]["calls"][0]["response"])
    raw_resolver = json.dumps(traces[0]["calls"][1]["response"])
    traces[0]["calls"][0]["response"] = raw_search
    traces[0]["calls"][1]["response"] = raw_resolver

    result = score_response_set(
        [SCENARIO],
        _all_responses(),
        traces,
        run_id=RUN_ID,
    )

    scored = next(
        item
        for item in result["responses"]
        if item["query_variant"] == "exact" and item["role"] == "pi"
    )
    assert scored["mechanical_pass"] is True
    assert traces[0]["calls"][0]["response"] == raw_search
    assert traces[0]["calls"][1]["response"] == raw_resolver


def test_trace_normalizes_single_mcp_text_content_envelope() -> None:
    traces = _all_traces()
    for call in traces[0]["calls"]:
        call["response"] = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(call["response"]),
                }
            ]
        }

    result = score_response_set(
        [SCENARIO],
        _all_responses(),
        traces,
        run_id=RUN_ID,
    )

    scored = next(
        item
        for item in result["responses"]
        if item["query_variant"] == "exact" and item["role"] == "pi"
    )
    assert scored["mechanical_pass"] is True


def test_response_rejects_structured_causal_chain_with_actionable_error() -> None:
    responses = _all_responses()
    responses[0] = {
        **responses[0],
        "causal_chain": [
            {
                "source": "jrn_00000000000000000000000001",
                "target": "dec_00000000000000000000000001",
            }
        ],
    }
    traces = _all_traces()
    traces[0]["response_sha256"] = canonical_record_sha256(responses[0])

    with pytest.raises(
        ValueError,
        match=r"causal_chain must be a flat array of entity ID strings",
    ):
        score_response_set(
            [SCENARIO],
            responses,
            traces,
            run_id=RUN_ID,
        )


def test_preview_evidence_is_separate_trace_attested_and_not_scored_as_graph_citation() -> None:
    preview_id = "run_00000000000000000000000001"
    responses = _all_responses()
    responses[0] = {**responses[0], "preview_evidence_ids": [preview_id]}
    traces = _all_traces()
    traces[0]["response_sha256"] = canonical_record_sha256(responses[0])
    traces[0]["calls"].append(
        {
            "ordinal": 3,
            "operation": "experiment_runs",
            "project_id": SCENARIO["project_id"],
            "request": {
                "project_id": SCENARIO["project_id"],
                "id": preview_id,
            },
            "outcome": "ok",
            "response": {
                "id": preview_id,
                "project_id": SCENARIO["project_id"],
                "status": "succeeded",
            },
        }
    )

    result = score_response_set(
        [SCENARIO],
        responses,
        traces,
        run_id=RUN_ID,
    )
    scored = next(
        item
        for item in result["responses"]
        if item["query_variant"] == "exact" and item["role"] == "pi"
    )
    assert scored["mechanical_pass"] is True
    assert scored["preview_evidence_ids"] == [preview_id]

    mixed = _all_responses()
    mixed[0] = {
        **mixed[0],
        "cited_entity_ids": [*mixed[0]["cited_entity_ids"], preview_id],
    }
    mixed_traces = _all_traces()
    mixed_traces[0]["response_sha256"] = canonical_record_sha256(mixed[0])
    with pytest.raises(
        ValueError,
        match=r"move preview IDs to preview_evidence_ids",
    ):
        score_response_set(
            [SCENARIO],
            mixed,
            mixed_traces,
            run_id=RUN_ID,
        )

    unattested = _all_responses()
    unattested[0] = {**unattested[0], "preview_evidence_ids": [preview_id]}
    unattested_traces = _all_traces()
    unattested_traces[0]["response_sha256"] = canonical_record_sha256(unattested[0])
    with pytest.raises(
        ValueError,
        match=r"not attested by a matching same-project typed experiment record",
    ):
        score_response_set(
            [SCENARIO],
            unattested,
            unattested_traces,
            run_id=RUN_ID,
        )


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        (
            "search",
            {
                "summary": (
                    "The journal happens to mention "
                    "run_00000000000000000000000001 in prose."
                )
            },
        ),
        (
            "experiment_observations",
            {
                "id": "run_00000000000000000000000001",
                "project_id": SCENARIO["project_id"],
                "summary": "A run-shaped ID returned by the wrong typed operation.",
            },
        ),
        (
            "experiment_runs",
            {
                "id": "run_00000000000000000000000001",
                "project_id": "prj_00000000000000000000000099",
                "status": "succeeded",
            },
        ),
        (
            "experiment_runs",
            {
                "id": "run_00000000000000000000000002",
                "project_id": SCENARIO["project_id"],
                "status": "succeeded",
                "config": {
                    "id": "run_00000000000000000000000001",
                    "project_id": SCENARIO["project_id"],
                },
            },
        ),
    ],
    ids=("incidental-text", "wrong-operation", "wrong-project", "forged-config"),
)
def test_preview_evidence_rejects_non_authoritative_mentions(
    operation: str,
    payload: dict,
) -> None:
    preview_id = "run_00000000000000000000000001"
    responses = _all_responses()
    responses[0] = {**responses[0], "preview_evidence_ids": [preview_id]}
    traces = _all_traces()
    traces[0]["response_sha256"] = canonical_record_sha256(responses[0])
    traces[0]["calls"].append(
        {
            "ordinal": 3,
            "operation": operation,
            "project_id": SCENARIO["project_id"],
            "request": {"project_id": SCENARIO["project_id"], "id": preview_id},
            "outcome": "ok",
            "response": payload,
        }
    )

    with pytest.raises(
        ValueError,
        match=r"not attested by a matching same-project typed experiment record",
    ):
        score_response_set(
            [SCENARIO],
            responses,
            traces,
            run_id=RUN_ID,
        )


def test_preview_evidence_accepts_only_typed_authoritative_record_locations() -> None:
    preview_ids = [
        "exp_00000000000000000000000001",
        "epv_00000000000000000000000002",
        "run_00000000000000000000000003",
        "rue_00000000000000000000000004",
        "obs_00000000000000000000000005",
        "elc_00000000000000000000000006",
        "evr_00000000000000000000000007",
    ]
    project_id = SCENARIO["project_id"]
    responses = _all_responses()
    responses[0] = {**responses[0], "preview_evidence_ids": preview_ids}
    traces = _all_traces()
    traces[0]["response_sha256"] = canonical_record_sha256(responses[0])
    traces[0]["calls"].extend(
        [
            {
                "ordinal": 3,
                "operation": "experiments",
                "project_id": project_id,
                "request": {"project_id": project_id, "id": preview_ids[0]},
                "outcome": "ok",
                "response": {
                    "id": preview_ids[0],
                    "project_id": project_id,
                    "current_plan": {"id": preview_ids[1], "project_id": project_id},
                    "runs": [{"id": preview_ids[2], "project_id": project_id}],
                },
            },
            {
                "ordinal": 4,
                "operation": "experiment_runs",
                "project_id": project_id,
                "request": {"project_id": project_id, "id": preview_ids[2]},
                "outcome": "ok",
                "response": {
                    "id": preview_ids[2],
                    "project_id": project_id,
                    "events": [{"id": preview_ids[3], "project_id": project_id}],
                    "observations": [
                        {"id": preview_ids[4], "project_id": project_id}
                    ],
                },
            },
            {
                "ordinal": 5,
                "operation": "experiment_observations",
                "project_id": project_id,
                "request": {"project_id": project_id, "id": preview_ids[4]},
                "outcome": "ok",
                "response": {
                    "id": preview_ids[4],
                    "project_id": project_id,
                    "locators": [{"id": preview_ids[5], "project_id": project_id}],
                    "claim_relations": [
                        {"id": preview_ids[6], "project_id": project_id}
                    ],
                },
            },
        ]
    )

    result = score_response_set(
        [SCENARIO],
        responses,
        traces,
        run_id=RUN_ID,
    )
    scored = next(
        item
        for item in result["responses"]
        if item["query_variant"] == "exact" and item["role"] == "pi"
    )
    assert scored["preview_evidence_ids"] == preview_ids
    assert scored["mechanical_pass"] is True


def test_rating_is_bound_to_run_session_project_query_role_and_response_hash() -> None:
    mutations = {
        "run_id": "old-run",
        "session_id": "old-session",
        "project_id": "prj_wrong",
        "query": "a different question",
        "response_sha256": "0" * 64,
    }
    messages = {
        "run_id": "rating run mismatch",
        "session_id": "rating session mismatch",
        "project_id": "rating project mismatch",
        "query": "rating query mismatch",
        "response_sha256": "rating response hash mismatch",
    }
    for field, value in mutations.items():
        ratings = _all_ratings()
        ratings[0] = {**ratings[0], field: value}
        with pytest.raises(ValueError, match=messages[field]):
            score_response_set(
                [SCENARIO],
                _all_responses(),
                _all_traces(),
                ratings,
                run_id=RUN_ID,
            )

    wrong_role = _all_ratings()
    wrong_role[0] = {**wrong_role[0], "role": "writer"}
    with pytest.raises(ValueError, match="unknown rating key"):
        score_response_set(
            [SCENARIO],
            _all_responses(),
            _all_traces(),
            wrong_role,
            run_id=RUN_ID,
        )


def test_cli_writes_hashes_and_aggregate(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.jsonl"
    response_path = tmp_path / "responses.jsonl"
    trace_path = tmp_path / "traces.jsonl"
    rating_path = tmp_path / "ratings.jsonl"
    out_path = tmp_path / "results" / "metrics.json"
    corpus_path.write_text(json.dumps(SCENARIO) + "\n", encoding="utf-8")
    response_path.write_text(
        "\n".join(json.dumps(response) for response in _all_responses()) + "\n",
        encoding="utf-8",
    )
    trace_path.write_text(
        "\n".join(json.dumps(trace) for trace in _all_traces()) + "\n",
        encoding="utf-8",
    )
    rating_path.write_text(
        "\n".join(json.dumps(rating) for rating in _all_ratings()) + "\n",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "--corpus",
                str(corpus_path),
                "--run-id",
                RUN_ID,
                "--responses",
                str(response_path),
                "--traces",
                str(trace_path),
                "--ratings",
                str(rating_path),
                "--out",
                str(out_path),
            ]
        )
        == 0
    )

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["aggregate"]["mechanical_pass_rate"] == 1.0
    assert payload["aggregate"]["overall_pass_rate"] == 1.0
    assert payload["meta"]["run_id"] == RUN_ID
    assert payload["meta"]["corpus_sha256"] == hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    assert (
        payload["meta"]["responses_sha256"]
        == hashlib.sha256(response_path.read_bytes()).hexdigest()
    )
    assert payload["meta"]["traces_sha256"] == hashlib.sha256(trace_path.read_bytes()).hexdigest()
    assert payload["meta"]["ratings_sha256"] == hashlib.sha256(rating_path.read_bytes()).hexdigest()
