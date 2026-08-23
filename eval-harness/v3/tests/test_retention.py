"""Locks for the retention (fade) benchmark scoring and runner.

The runner tests use an echo completer — the response is the assembled
prompt itself — so pass/fail becomes a pure function of the context
policy: an arm passes a probe exactly when its assembled context still
contains the seeded material.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

_EVAL_HARNESS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_EVAL_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_HARNESS_DIR))

from v3.retention.runner import (  # noqa: E402
    RetentionRunner,
    lexical_top_chunks,
    load_corpus,
)
from v3.retention.scoring import retention_curve, score_probe  # noqa: E402

CLAIM_ID = "clm_01EXAMPLEAUCRESULT000000"

SCENARIO = {
    "scenario_id": "fade-1",
    "seeded_items": [
        {
            "item_id": "dir-ci",
            "kind": "directive",
            "text": "Directive: always report the confidence interval; never cite DelayNet-v1.",
        },
        {
            "item_id": "ev-auc",
            "kind": "evidence",
            "text": f"Finding {CLAIM_ID}: detector achieves 0.73 AUC at the 25ms window.",
        },
    ],
    "filler_tasks": [
        {"prompt": "unrelated filler", "canned_response": "x " * 400},
    ],
    "probes": [
        {
            "probe_id": "p1",
            "target_item": "ev-auc",
            "after_tokens": 10,
            "prompt": "What AUC at the 25ms window? Cite the source.",
            "expect": {
                "numeric": {"value": 0.73, "tolerance": 0.001},
                "expected_citations": [CLAIM_ID],
            },
        }
    ],
}


# ------------------------------------------------------------------ scoring


def test_score_probe_all_check_kinds() -> None:
    expect = {
        "must_include": ["confidence interval"],
        "must_not_include": ["DelayNet-v1"],
        "expected_citations": [CLAIM_ID],
        "numeric": {"value": 0.73, "tolerance": 0.001},
    }
    good = f"AUC 0.73 (95% Confidence Interval reported), per {CLAIM_ID}."
    assert score_probe(expect, good)["passed"] is True

    stale = f"AUC 0.73 with confidence interval, per DelayNet-v1 and {CLAIM_ID}."
    result = score_probe(expect, stale)
    assert result["passed"] is False
    assert result["checks"]["must_not_include"]["leaked"] == ["DelayNet-v1"]

    wrong_number = f"AUC 0.61, confidence interval included, per {CLAIM_ID}."
    assert score_probe(expect, wrong_number)["checks"]["numeric"]["passed"] is False


def test_score_probe_empty_expectation_fails() -> None:
    assert score_probe({}, "anything")["passed"] is False


def test_retention_curve_buckets_and_kinds() -> None:
    results = [
        {"arm": "rka", "distance_tokens": 1_000, "passed": True, "kind": "directive"},
        {"arm": "rka", "distance_tokens": 60_000, "passed": True, "kind": "evidence"},
        {"arm": "full_context", "distance_tokens": 1_000, "passed": True, "kind": "directive"},
        {"arm": "full_context", "distance_tokens": 60_000, "passed": False, "kind": "evidence"},
    ]
    curve = retention_curve(results)
    assert curve["by_arm"]["rka"]["overall_pass_rate"] == 1.0
    assert curve["by_arm"]["full_context"]["by_distance"]["<=150000"]["pass_rate"] == 0.0
    assert curve["by_arm"]["full_context"]["by_kind"]["directive"]["pass_rate"] == 1.0


def test_lexical_top_chunks_prefers_overlap() -> None:
    transcript = ("noise " * 300) + "the detector AUC threshold discussion " + ("pad " * 300)
    chunks = lexical_top_chunks(transcript, "detector AUC threshold", k=2)
    assert chunks and "AUC" in chunks[0]


# ------------------------------------------------------------------- runner


def _echo(system: str, prompt: str) -> str:
    return prompt


def _rka_transport(status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/search"
        if status != 200:
            return httpx.Response(status, json={"detail": "down"})
        return httpx.Response(
            200,
            json=[{"id": CLAIM_ID, "snippet": "detector achieves 0.73 AUC at 25ms"}],
        )

    return httpx.MockTransport(handler)


async def test_full_context_and_rka_pass_rag_configurable() -> None:
    runner = RetentionRunner(
        _echo, rka_url="http://rka.test", transport=_rka_transport()
    )
    try:
        results = await runner.run_scenario(SCENARIO, ["full_context", "rag", "rka"])
    finally:
        await runner.close()

    by_arm = {r["arm"]: r for r in results}
    assert len(results) == 3
    # seeds are in the full context -> echo completer reproduces them
    assert by_arm["full_context"]["passed"] is True
    # rka context comes from retrieval, not from pasted seeds
    assert by_arm["rka"]["passed"] is True
    assert by_arm["rka"]["divergences"] == []
    # every result carries the distance at firing (seeds + filler)
    assert by_arm["rka"]["distance_tokens"] > 100
    assert by_arm["rka"]["kind"] == "evidence"


async def test_rka_arm_outage_is_divergence_and_failure() -> None:
    runner = RetentionRunner(
        _echo, rka_url="http://rka.test", transport=_rka_transport(status=500)
    )
    try:
        results = await runner.run_scenario(SCENARIO, ["rka"])
    finally:
        await runner.close()
    assert results[0]["passed"] is False
    assert results[0]["divergences"] == ["rka search: HTTP 500"]


async def test_rka_arm_without_url_degrades() -> None:
    runner = RetentionRunner(_echo)
    results = await runner.run_scenario(SCENARIO, ["rka"])
    assert results[0]["divergences"] == ["rka: no --rka-url configured"]


async def test_probe_fires_even_when_filler_too_short() -> None:
    scenario = {**SCENARIO, "filler_tasks": [], "probes": [
        {**SCENARIO["probes"][0], "after_tokens": 10_000_000}
    ]}
    runner = RetentionRunner(_echo)
    results = await runner.run_scenario(scenario, ["full_context"])
    assert len(results) == 1  # end-of-scenario flush


def test_load_corpus_and_example_parse(tmp_path: Path) -> None:
    example = Path(__file__).parent.parent / "retention" / "scenarios.example.jsonl"
    scenarios = load_corpus(example)
    assert scenarios[0]["scenario_id"] == "example-detector-thresholds"
    assert {i["kind"] for i in scenarios[0]["seeded_items"]} == {"directive", "evidence"}

    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"scenario_id": "x"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="seeded_items"):
        load_corpus(bad)
