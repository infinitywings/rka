"""Locks for the back-tracing metric math (pure functions, no HTTP)."""

from __future__ import annotations

import sys
from pathlib import Path

_EVAL_HARNESS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_EVAL_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_HARNESS_DIR))

from v3.tracing.metrics import (  # noqa: E402
    aggregate,
    aggregate_story,
    aggregate_story_responses,
    anchor_reciprocal_rank,
    causal_order_score,
    pivot_score,
    score_scenario,
    score_story_response,
    score_story_variant,
    story_scores,
    trace_scores,
)

TRACE = [
    {
        "entity_id": "jrn_dir",
        "entity_type": "journal",
        "relation": "directive",
        "importance": "critical",
    },
    {
        "entity_id": "clm_ev",
        "entity_type": "claim",
        "relation": "evidence",
        "importance": "critical",
    },
    {
        "entity_id": "lit_a",
        "entity_type": "literature",
        "relation": "literature",
        "importance": "useful",
    },
]


def test_anchor_reciprocal_rank() -> None:
    assert anchor_reciprocal_rank(["dec_x", "dec_a"], "dec_a") == 0.5
    assert anchor_reciprocal_rank(["dec_a"], "dec_a") == 1.0
    assert anchor_reciprocal_rank(["dec_x"], "dec_a") == 0.0
    assert anchor_reciprocal_rank([], "dec_a") == 0.0


def test_trace_scores_partial_recall() -> None:
    scores = trace_scores(TRACE, {"jrn_dir", "lit_a", "noise_1", "noise_2"})
    assert scores["trace_recall"] == 0.5  # 1 of 2 critical
    assert scores["expanded_recall"] == 2 / 3
    assert scores["per_relation"]["directive"] == {"expected": 1, "found": 1}
    assert scores["per_relation"]["evidence"] == {"expected": 1, "found": 0}
    assert scores["precision"] == 0.5  # 2 relevant of 4 returned


def test_trace_scores_empty_returns() -> None:
    scores = trace_scores(TRACE, set())
    assert scores["trace_recall"] == 0.0
    assert scores["precision"] == 0.0


def test_pivot_score_stale_surfacing() -> None:
    pivot = {"superseded_decision_id": "dec_old", "superseding_decision_id": "dec_new"}
    assert pivot_score(None, {"dec_old"}) == {"applicable": False}
    ok = pivot_score(pivot, {"dec_new", "dec_old"})
    assert ok["superseding_found"] and not ok["stale_surfacing"]
    stale = pivot_score(pivot, {"dec_old"})
    assert stale["stale_surfacing"] is True


def test_score_scenario_union_beats_single_surface() -> None:
    scenario = {
        "scenario_id": "s1",
        "anchor_decision": "dec_a",
        "expected_trace": TRACE,
        "pivot": {"superseded_decision_id": "dec_old", "superseding_decision_id": "dec_a"},
    }
    result = score_scenario(
        scenario,
        {"ego": ["jrn_dir"], "multi_hop": ["clm_ev", "lit_a", "dec_a"]},
        ["dec_x", "dec_a"],
        [],
    )
    assert result["union"]["trace_recall"] == 1.0
    assert result["per_surface"]["ego"]["trace_recall"] == 0.5
    assert result["anchor_reciprocal_rank"] == 0.5
    assert result["pivot"]["superseding_found"] is True


def test_aggregate_rolls_up_relations_and_pivots() -> None:
    scenario = {
        "scenario_id": "s1",
        "anchor_decision": "dec_a",
        "expected_trace": TRACE,
        "pivot": {"superseded_decision_id": "dec_old", "superseding_decision_id": "dec_a"},
    }
    r1 = score_scenario(scenario, {"ego": ["jrn_dir", "clm_ev", "lit_a", "dec_a"]}, ["dec_a"], [])
    r2 = score_scenario(
        {**scenario, "scenario_id": "s2", "pivot": None},
        {"ego": []},
        None,
        ["multi_hop: HTTP 422"],
    )
    rollup = aggregate([r1, r2])
    assert rollup["n_scenarios"] == 2
    assert rollup["trace_recall_mean"] == 0.5
    assert rollup["anchor_mrr"] == 1.0  # only s1 had an NL query
    assert rollup["per_relation"]["directive"]["recall"] == 0.5
    assert rollup["pivot_scenarios"] == 1 and rollup["pivot_correct"] == 1
    assert rollup["scenarios_with_divergences"] == ["s2"]


STORY = {
    "roles": {
        "literature_basis": {"any_of": ["lit_basis"], "required": True},
        "rationale_journal": {"any_of": ["jrn_why"], "required": True},
        "current_decision": {"any_of": ["dec_new"], "required": True},
        "old_decision": {"any_of": ["dec_old"], "required": True},
        "execution_mission": {"any_of": ["mis_run"], "required": True},
        "result_journal": {"any_of": ["jrn_result"], "required": True},
    },
    "required_edges": [
        {"source": "lit_basis", "target": "dec_new", "link_type": "informed_by"},
        {"source": "dec_new", "target": "jrn_why", "link_type": "justified_by"},
        {"source": "dec_new", "target": "mis_run", "link_type": "motivated"},
        {"source": "mis_run", "target": "jrn_result", "link_type": "produced"},
    ],
    "required_facts": [
        {
            "fact_id": "choice",
            "any_of_entities": ["dec_new"],
            "contains": ["Dilithium2", "60 ms"],
        }
    ],
    "current_entities": ["dec_new"],
    "historical_entities": ["dec_old"],
    "forbidden_current_entities": ["jrn_draft_only"],
    "currentness": {
        "must_be_current": ["dec_new"],
        "must_be_not_current": ["dec_old"],
    },
    "optional_entities": ["jrn_extra"],
    "distractors": ["jrn_noise"],
    "forbidden_entities": ["dec_forbidden"],
    "foreign_must_exclude": ["dec_foreign"],
    "causal_edges": [
        ["dec_old", "jrn_why"],
        ["lit_basis", "jrn_why"],
        ["jrn_why", "dec_new"],
        ["dec_new", "mis_run"],
        ["mis_run", "jrn_result"],
    ],
    "current_conclusion": {
        "verdict": "supported",
        "checks": [
            {"must_include": ["Dilithium2"]},
            {"numeric": {"value": 60, "tolerance": 0}},
        ],
    },
}

STORY_IDS = {"lit_basis", "jrn_why", "dec_new", "dec_old", "mis_run", "jrn_result"}
STORY_EDGES = [
    {"source": edge["source"], "target": edge["target"], "link_type": edge["link_type"]}
    for edge in STORY["required_edges"]
]
STORY_PACKET = {
    "project_id": "prj_story",
    "entities": {
        "dec_new": {
            "found": True,
            "outcome": "resolved",
            "project_id": "prj_story",
            "rationale": "Dilithium2 verification takes about 60 ms.",
            "currentness": {"is_current": True},
        },
        "dec_old": {
            "found": True,
            "outcome": "resolved",
            "project_id": "prj_story",
            "currentness": {"is_current": False},
        },
    },
}


def test_story_scores_complete_causal_story() -> None:
    score = story_scores(STORY, STORY_IDS, STORY_EDGES, STORY_PACKET)
    assert score["story_success"] is True
    assert score["role_coverage"] == 1.0
    assert score["required_edge_coverage"] == 1.0
    assert score["fact_coverage"] == 1.0
    assert score["currentness_accuracy"] == 1.0
    assert not any(score["hard_failures"].values())


def test_story_scores_rejects_fragment_and_stale_only_answers() -> None:
    fragmented = story_scores(
        STORY,
        STORY_IDS - {"dec_new", "mis_run"} | {"dec_old", "dec_foreign"},
        STORY_EDGES[:1],
        STORY_PACKET,
    )
    assert fragmented["story_success"] is False
    assert fragmented["role_coverage"] < 1.0
    assert fragmented["required_edge_coverage"] == 0.25
    assert fragmented["hard_failures"]["foreign_project"] == ["dec_foreign"]
    assert fragmented["hard_failures"]["stale_only"] is True


def test_story_scores_fails_closed_when_resolution_is_missing() -> None:
    score = story_scores(STORY, STORY_IDS, STORY_EDGES, entity_packet=None)
    assert score["story_success"] is False
    assert score["fact_coverage"] == 0.0
    assert score["currentness_accuracy"] == 0.0
    assert score["hard_failures"]["resolution_missing"] is True


def test_story_scores_rejects_project_dump_by_precision() -> None:
    noisy_ids = STORY_IDS | {f"noise_{index}" for index in range(100)}
    score = story_scores(STORY, noisy_ids, STORY_EDGES, STORY_PACKET)
    assert score["role_coverage"] == 1.0
    assert score["precision"] < score["min_precision"]
    assert score["hard_failures"]["precision"] is True
    assert score["story_success"] is False


def test_story_variant_and_aggregate_group_query_styles() -> None:
    scenario = {
        "scenario_id": "signature-story",
        "anchor_decision": "dec_new",
        "story": STORY,
    }
    exact = score_story_variant(
        scenario,
        {"variant_id": "exact", "style": "exact", "query": "signature decision"},
        {"search": ["dec_new"], "graph": sorted(STORY_IDS)},
        {"search": [], "graph": STORY_EDGES},
        ["dec_new"],
        STORY_PACKET,
        [],
    )
    vague = score_story_variant(
        scenario,
        {"variant_id": "vague", "style": "underspecified", "query": "what happened"},
        {"search": ["dec_old"]},
        {"search": []},
        ["dec_old"],
        STORY_PACKET,
        [],
    )
    rollup = aggregate_story([exact, vague])
    assert exact["headline"]["story_success"] is True
    assert rollup["n_variants"] == 2
    assert rollup["story_success_rate"] == 0.5
    assert rollup["by_style"]["exact"]["story_success_rate"] == 1.0
    assert rollup["by_style"]["underspecified"]["story_success_rate"] == 0.0


def _good_story_response(**overrides) -> dict:
    response = {
        "scenario_id": "signature-story",
        "query_variant": "exact",
        "role": "brain",
        "answer": "The evidence supports Dilithium2; verification took 60 ms.",
        "verdict": "supported",
        "cited_entity_ids": sorted(STORY_IDS),
        "retrieved_entity_ids": sorted(STORY_IDS | {"jrn_noise"}),
        "resolved_entity_ids": sorted(STORY_IDS | {"jrn_noise"}),
        "current_entity_ids": ["dec_new"],
        "causal_chain": [
            "dec_old",
            "lit_basis",
            "jrn_why",
            "dec_new",
            "mis_run",
            "jrn_result",
        ],
    }
    response.update(overrides)
    return response


def _human_scores(score: int = 4) -> dict[str, int]:
    return {
        "current_conclusion": score,
        "mandatory_coverage": score,
        "causal_reconstruction": score,
        "provenance_currentness": score,
        "distractor_rejection": score,
    }


def _story_scenario() -> dict:
    return {
        "scenario_id": "signature-story",
        "anchor_decision": "dec_new",
        "story": STORY,
    }


def test_causal_order_full_reverse_and_missing() -> None:
    edges = [["dec_old", "jrn_why"], ["jrn_why", "dec_new"]]
    full = causal_order_score(edges, ["dec_old", "jrn_why", "dec_new"])
    reverse = causal_order_score(edges, ["dec_new", "jrn_why", "dec_old"])
    missing = causal_order_score(edges, ["dec_old", "dec_new"])
    assert full["accuracy"] == 1.0
    assert reverse["accuracy"] == 0.0
    assert missing["accuracy"] == 0.0


def test_story_response_scores_complete_cold_session_answer() -> None:
    score = score_story_response(_story_scenario(), _good_story_response())
    assert score["mechanical_pass"] is True
    assert score["overall_status"] == "pending_human_review"
    assert score["role_coverage"] == 1.0
    assert score["causal_order"]["accuracy"] == 1.0
    assert score["verdict_match"] is True
    assert score["conclusion_passed"] is True
    assert score["human_total"] is None


def test_story_response_requires_complete_independent_human_rubric_for_overall_pass() -> None:
    passed = score_story_response(
        _story_scenario(),
        _good_story_response(human_scores=_human_scores()),
    )
    assert passed["mechanical_pass"] is True
    assert passed["human_pass"] is True
    assert passed["human_total"] == 20
    assert passed["overall_status"] == "pass"

    invalid = score_story_response(
        _story_scenario(),
        _good_story_response(human_scores={"current_conclusion": 4}),
    )
    assert invalid["mechanical_pass"] is True
    assert invalid["human_scores_valid"] is False
    assert invalid["overall_status"] == "invalid_human_review"


def test_story_response_hard_failures_override_high_human_score() -> None:
    response = _good_story_response(
        cited_entity_ids=sorted(STORY_IDS | {"dec_foreign", "dec_forbidden"}),
        current_entity_ids=["dec_old", "jrn_draft_only"],
        verdict="rejected",
        human_scores=_human_scores(),
    )
    score = score_story_response(_story_scenario(), response)
    assert score["human_total"] == 20
    assert score["hard_fail"] is True
    assert score["mechanical_pass"] is False
    assert score["overall_status"] == "mechanical_fail"
    assert score["hard_failures"]["foreign_project"] == ["dec_foreign"]
    assert score["hard_failures"]["forbidden_entity"] == ["dec_forbidden"]
    assert score["hard_failures"]["stale_as_current"] == [
        "dec_old",
        "jrn_draft_only",
    ]
    assert score["hard_failures"]["current_missing"] == ["dec_new"]
    assert score["hard_failures"]["verdict_mismatch"] is True


def test_story_response_checks_answer_terms_numbers_and_causal_order() -> None:
    response = _good_story_response(
        answer="The scheme was selected, but the latency was not recorded.",
        causal_chain=list(reversed(_good_story_response()["causal_chain"])),
    )
    score = score_story_response(_story_scenario(), response)
    assert score["conclusion_passed"] is False
    assert score["causal_order"]["accuracy"] == 0.0
    assert score["mechanical_pass"] is False


def test_story_response_rejects_empty_contract_distractor_and_bad_chain() -> None:
    incomplete_story = {
        **STORY,
        "causal_edges": [],
        "current_conclusion": {},
    }
    incomplete = score_story_response(
        {**_story_scenario(), "story": incomplete_story},
        _good_story_response(answer=""),
    )
    assert incomplete["hard_failures"]["missing_conclusion_contract"] is True
    assert incomplete["hard_failures"]["missing_causal_contract"] is True
    assert incomplete["mechanical_pass"] is False

    unattested = score_story_response(
        _story_scenario(),
        _good_story_response(retrieved_entity_ids=[], resolved_entity_ids=[]),
    )
    assert unattested["hard_failures"]["missing_retrieval_trace"] is True
    assert unattested["hard_failures"]["citation_not_attested"]
    assert unattested["mechanical_pass"] is False

    bad_chain = score_story_response(
        _story_scenario(),
        _good_story_response(
            cited_entity_ids=sorted(STORY_IDS | {"jrn_noise"}),
            causal_chain=[
                "dec_old",
                "lit_basis",
                "jrn_why",
                "dec_new",
                "mis_run",
                "jrn_result",
                "jrn_result",
                "jrn_uncited",
            ],
        ),
    )
    assert bad_chain["hard_failures"]["distractor_as_support"] == ["jrn_noise"]
    assert bad_chain["hard_failures"]["causal_duplicates"] == ["jrn_result"]
    assert bad_chain["hard_failures"]["causal_not_cited"] == ["jrn_uncited"]
    assert bad_chain["mechanical_pass"] is False


def test_story_response_allows_distractor_only_in_rejected_list() -> None:
    score = score_story_response(
        _story_scenario(),
        _good_story_response(rejected_entity_ids=["jrn_noise"]),
    )
    assert score["mechanical_pass"] is True
    assert score["overall_status"] == "pending_human_review"
    assert score["distractors_rejected"] == ["jrn_noise"]


def test_story_response_rejects_citation_dump() -> None:
    noise = {f"noise_{index}" for index in range(100)}
    all_ids = sorted(STORY_IDS | noise)
    score = score_story_response(
        _story_scenario(),
        _good_story_response(
            cited_entity_ids=all_ids,
            retrieved_entity_ids=all_ids,
            resolved_entity_ids=all_ids,
        ),
    )
    assert score["hard_failures"]["citation_precision"] is True
    assert score["mechanical_pass"] is False


def test_negated_conclusion_cannot_pass_independent_human_review() -> None:
    score = score_story_response(
        _story_scenario(),
        _good_story_response(
            answer="Dilithium2 was not adopted, and verification did not take 60 ms.",
            human_scores=_human_scores(0),
        ),
    )
    assert score["mechanical_pass"] is True
    assert score["human_pass"] is False
    assert score["overall_status"] == "human_fail"


def test_aggregate_story_responses_groups_query_styles() -> None:
    exact = score_story_response(_story_scenario(), _good_story_response())
    colloquial = score_story_response(
        _story_scenario(),
        _good_story_response(
            query_variant="colloquial",
            style="colloquial",
            cited_entity_ids=["dec_new"],
        ),
    )
    rollup = aggregate_story_responses([exact, colloquial])
    assert rollup["n_responses"] == 2
    assert rollup["mechanical_pass_rate"] == 0.5
    assert rollup["overall_pass_rate"] == 0.0
    assert rollup["pending_human_review"] == 1
    assert rollup["by_role"]["brain"]["mechanical_pass_rate"] == 0.5
    assert rollup["by_style"]["exact"]["mechanical_pass_rate"] == 1.0
    assert rollup["by_style"]["colloquial"]["mechanical_pass_rate"] == 0.0
