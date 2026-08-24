"""Hermetic runner tests via httpx.MockTransport (Eval-v2 pattern).

Locks: entity-id extraction from nested payloads, the union scoring path,
and — critically — that a 4xx from a traversal surface (the v2.5.x
multi-hop 422) is recorded as a divergence instead of crashing the run.
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

from v3.tracing.runner import TraceRunner, extract_entity_ids, load_corpus  # noqa: E402

ANCHOR = "dec_000059REDACTED"
DIRECTIVE = "jrn_000060REDACTED"
EVIDENCE = "clm_000061REDACTED"
PAPER = "lit_000062REDACTED"

SCENARIO = {
    "scenario_id": "scaffold-pivot",
    "nl_query": "why agentless over swe-agent",
    "anchor_decision": ANCHOR,
    "expected_trace": [
        {"entity_id": DIRECTIVE, "entity_type": "journal", "relation": "directive", "importance": "critical"},
        {"entity_id": EVIDENCE, "entity_type": "claim", "relation": "evidence", "importance": "critical"},
        {"entity_id": PAPER, "entity_type": "literature", "relation": "literature", "importance": "useful"},
    ],
}


def _transport(multi_hop_status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/search":
            return httpx.Response(
                200, json=[{"id": "dec_000063REDACTED"}, {"id": ANCHOR}]
            )
        if path.startswith("/api/graph/ego/"):
            return httpx.Response(
                200,
                json={
                    "nodes": [
                        {"id": ANCHOR},
                        {"id": DIRECTIVE, "label": "PI directive"},
                    ],
                    "edges": [{"source": ANCHOR, "target": DIRECTIVE}],
                },
            )
        if path == "/api/graph/multi-hop":
            if multi_hop_status != 200:
                return httpx.Response(multi_hop_status, json={"detail": "boom"})
            body = json.loads(request.content)
            assert body["seeds"] == [ANCHOR]
            return httpx.Response(
                200, json={"results": [{"entity_id": EVIDENCE}, {"entity_id": PAPER}]}
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_extract_entity_ids_nested_and_deduped() -> None:
    payload = {
        "nodes": [{"id": ANCHOR}, {"text": f"see {DIRECTIVE} and {ANCHOR}"}],
        "extra": [[{"ref": EVIDENCE}]],
    }
    assert extract_entity_ids(payload) == [ANCHOR, DIRECTIVE, EVIDENCE]


async def test_runner_scores_union_across_surfaces() -> None:
    runner = TraceRunner("http://rka.test", transport=_transport())
    try:
        result = await runner.run_000055REDACTED(SCENARIO)
    finally:
        await runner.close()

    assert result["divergences"] == []
    assert result["union"]["trace_recall"] == 1.0
    assert result["per_surface"]["ego"]["trace_recall"] == 0.5
    assert result["per_surface"]["multi_hop"]["trace_recall"] == 0.5
    assert result["anchor_reciprocal_rank"] == 0.5
    assert result["raw"]["multi_hop_ids"] == [EVIDENCE, PAPER]


async def test_multi_hop_422_is_divergence_not_crash() -> None:
    runner = TraceRunner("http://rka.test", transport=_transport(multi_hop_status=422))
    try:
        result = await runner.run_000055REDACTED(SCENARIO)
    finally:
        await runner.close()

    assert result["divergences"] == ["multi_hop: HTTP 422"]
    # ego still contributes, so the run degrades instead of dying
    assert result["union"]["trace_recall"] == 0.5


def test_load_corpus_validates_and_skips_comments(tmp_path: Path) -> None:
    corpus = tmp_path / "scenarios.jsonl"
    corpus.write_text(
        "# comment line\n" + json.dumps(SCENARIO) + "\n", encoding="utf-8"
    )
    assert [s["scenario_id"] for s in load_corpus(corpus)] == ["scaffold-pivot"]

    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"scenario_id": "x"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="anchor_decision"):
        load_corpus(bad)


def test_example_corpus_parses() -> None:
    example = Path(__file__).parent.parent / "tracing" / "scenarios.example.jsonl"
    scenarios = load_corpus(example)
    assert len(scenarios) == 2
    assert scenarios[0]["pivot"]["superseding_decision_id"] == scenarios[0]["anchor_decision"]
