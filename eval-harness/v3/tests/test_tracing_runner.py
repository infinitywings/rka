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

from v3.tracing.runner import (  # noqa: E402
    TraceRunner,
    extract_entity_ids,
    extract_graph_edges,
    load_corpus,
)

ANCHOR = "dec_00000000000000000000000011"
DIRECTIVE = "jrn_00000000000000000000000012"
EVIDENCE = "clm_00000000000000000000000013"
PAPER = "lit_00000000000000000000000014"

SCENARIO = {
    "scenario_id": "scaffold-pivot",
    "nl_query": "why agentless over swe-agent",
    "anchor_decision": ANCHOR,
    "expected_trace": [
        {
            "entity_id": DIRECTIVE,
            "entity_type": "journal",
            "relation": "directive",
            "importance": "critical",
        },
        {
            "entity_id": EVIDENCE,
            "entity_type": "claim",
            "relation": "evidence",
            "importance": "critical",
        },
        {
            "entity_id": PAPER,
            "entity_type": "literature",
            "relation": "literature",
            "importance": "useful",
        },
    ],
}


def _transport(multi_hop_status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/search":
            return httpx.Response(
                200,
                json=[{"id": "dec_00000000000000000000000015"}, {"id": ANCHOR}],
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


def test_extract_entity_ids_includes_experiment_chain_prefixes() -> None:
    ids = [
        "exp_00000000000000000000000001",
        "run_00000000000000000000000002",
        "obs_00000000000000000000000003",
        "elc_00000000000000000000000004",
        "art_00000000000000000000000005",
        "csc_00000000000000000000000006",
        "evr_00000000000000000000000007",
    ]
    assert extract_entity_ids({"story": ids}) == ids


def test_extract_entity_ids_ignores_truncated_ulids() -> None:
    payload = {
        "preview": "mis_01KPRB8JW9QXX7B",
        "full": "mis_01KPRB8JW9QXX7B7H4KNYJ3GMV",
    }

    assert extract_entity_ids(payload) == ["mis_01KPRB8JW9QXX7B7H4KNYJ3GMV"]


def test_extract_graph_edges_nested_and_deduped() -> None:
    payload = {
        "edges": [
            {"source": ANCHOR, "target": DIRECTIVE, "link_type": "justified_by"},
            {"source": ANCHOR, "target": DIRECTIVE, "link_type": "justified_by"},
        ]
    }
    assert extract_graph_edges(payload) == [
        {"source": ANCHOR, "target": DIRECTIVE, "link_type": "justified_by"}
    ]


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
    corpus.write_text("# comment line\n" + json.dumps(SCENARIO) + "\n", encoding="utf-8")
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

    story_example = Path(__file__).parent.parent / "tracing" / "scenarios.story.example.jsonl"
    story_scenarios = load_corpus(story_example)
    assert len(story_scenarios) == 1
    assert len(story_scenarios[0]["query_variants"]) == 4


def _story_transport(resolve_mode: str = "complete") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("project_id") == "prj_00000000000000000000000000"
        path = request.url.path
        if path == "/api/search":
            return httpx.Response(200, json=[{"entity_id": ANCHOR}])
        if path == "/api/graph/report-context":
            body = json.loads(request.content)
            assert "angle_queries" not in body
            return httpx.Response(200, json={"nodes": [{"id": DIRECTIVE}]})
        if path == "/api/graph/multi-hop":
            body = json.loads(request.content)
            nodes = [{"id": ANCHOR}, {"id": DIRECTIVE}, {"id": EVIDENCE}]
            edges = [
                {"source": ANCHOR, "target": DIRECTIVE, "link_type": "justified_by"},
                {"source": ANCHOR, "target": EVIDENCE, "link_type": "motivated"},
            ]
            if body.get("seeds"):
                nodes.append({"id": PAPER})
                edges.append({"source": PAPER, "target": ANCHOR, "link_type": "informed_by"})
            return httpx.Response(200, json={"nodes": nodes, "edges": edges})
        if path.startswith("/api/graph/ego/"):
            return httpx.Response(
                200,
                json={
                    "nodes": [{"id": ANCHOR}, {"id": PAPER}],
                    "edges": [{"source": PAPER, "target": ANCHOR, "link_type": "informed_by"}],
                },
            )
        if path == "/api/entities/resolve":
            if resolve_mode == "absent":
                return httpx.Response(503, json={"detail": "resolver unavailable"})
            body = json.loads(request.content)
            entities = {
                entity_id: {
                    "found": True,
                    "outcome": "resolved",
                    "project_id": "prj_00000000000000000000000000",
                    "currentness": {"is_current": True},
                    "record": {"content": "grounded result"},
                }
                for entity_id in body["ids"]
            }
            if resolve_mode == "partial" and EVIDENCE in entities:
                entities[EVIDENCE] = {
                    "found": False,
                    "outcome": "missing",
                    "currentness": {"is_current": False},
                    "record": None,
                }
            if resolve_mode == "wrong-entity-project" and EVIDENCE in entities:
                entities[EVIDENCE]["project_id"] = "prj_00000000000000000000000099"
            if resolve_mode == "missing-entity-project" and EVIDENCE in entities:
                entities[EVIDENCE].pop("project_id")
            packet_project = (
                "prj_00000000000000000000000099"
                if resolve_mode == "wrong-project"
                else "prj_00000000000000000000000000"
            )
            return httpx.Response(
                200,
                json={
                    "project_id": packet_project,
                    "entities": entities,
                    "entity_links": [
                        {
                            "source_id": ANCHOR,
                            "target_id": DIRECTIVE,
                            "link_type": "justified_by",
                        },
                        {
                            "source_id": ANCHOR,
                            "target_id": EVIDENCE,
                            "link_type": "motivated",
                        },
                    ],
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


STORY_SCENARIO = {
    "scenario_id": "signature-story",
    "project_id": "prj_00000000000000000000000000",
    "anchor_decision": ANCHOR,
    "query_variants": [
        {"variant_id": "exact", "style": "exact", "query": "signature decision"},
        {
            "variant_id": "colloquial",
            "style": "colloquial",
            "query": "what happened with signatures",
            "angle_queries": ["signature direction"],
        },
    ],
    "story": {
        "roles": {
            "current_decision": {"any_of": [ANCHOR], "required": True},
            "rationale": {"any_of": [DIRECTIVE], "required": True},
            "mission": {"any_of": [EVIDENCE], "required": True},
        },
        "required_edges": [
            {"source": ANCHOR, "target": DIRECTIVE, "link_type": "justified_by"},
            {"source": ANCHOR, "target": EVIDENCE, "link_type": "motivated"},
        ],
        "current_entities": [ANCHOR],
        "currentness": {"must_be_current": [ANCHOR]},
    },
}


async def test_story_runner_uses_query_only_and_runs_each_variant() -> None:
    runner = TraceRunner(
        "http://rka.test",
        project_id="prj_00000000000000000000000000",
        transport=_story_transport(),
    )
    try:
        result = await runner.run_story_scenario(STORY_SCENARIO)
    finally:
        await runner.close()

    assert [variant["variant_id"] for variant in result["variants"]] == ["exact", "colloquial"]
    assert all(variant["headline"]["story_success"] for variant in result["variants"])
    assert result["oracle_diagnostic"]["scores"]["role_coverage"] == 1.0


async def test_story_headline_uses_only_resolver_confirmed_ids() -> None:
    runner = TraceRunner(
        "http://rka.test",
        project_id="prj_00000000000000000000000000",
        transport=_story_transport(resolve_mode="partial"),
    )
    try:
        result = await runner.run_story_variant(STORY_SCENARIO, STORY_SCENARIO["query_variants"][0])
    finally:
        await runner.close()

    assert result["raw_candidate_recall"]["role_coverage"] == 1.0
    assert result["headline"]["role_coverage"] == pytest.approx(2 / 3, abs=1e-4)
    assert result["headline"]["missing_roles"] == ["mission"]
    assert result["headline"]["hard_failures"]["resolution_incomplete"] == [EVIDENCE]
    assert result["headline"]["story_success"] is False


async def test_story_headline_fails_closed_when_resolver_is_absent() -> None:
    runner = TraceRunner(
        "http://rka.test",
        project_id="prj_00000000000000000000000000",
        transport=_story_transport(resolve_mode="absent"),
    )
    try:
        result = await runner.run_story_variant(STORY_SCENARIO, STORY_SCENARIO["query_variants"][0])
    finally:
        await runner.close()

    assert result["raw_candidate_recall"]["role_coverage"] == 1.0
    assert result["headline"]["role_coverage"] == 0.0
    assert result["headline"]["hard_failures"]["resolution_missing"] is True
    assert result["headline"]["story_success"] is False
    assert result["divergences"] == ["resolve: HTTP 503"]


async def test_story_headline_rejects_resolver_packet_for_another_project() -> None:
    runner = TraceRunner(
        "http://rka.test",
        project_id="prj_00000000000000000000000000",
        transport=_story_transport(resolve_mode="wrong-project"),
    )
    try:
        result = await runner.run_story_variant(STORY_SCENARIO, STORY_SCENARIO["query_variants"][0])
    finally:
        await runner.close()

    assert result["raw_candidate_recall"]["role_coverage"] == 1.0
    assert result["headline"]["role_coverage"] == 0.0
    assert result["headline"]["hard_failures"]["resolution_project_scope"] is True
    assert result["headline"]["story_success"] is False


@pytest.mark.parametrize(
    "resolve_mode",
    ["wrong-entity-project", "missing-entity-project"],
)
async def test_story_headline_rejects_unattested_entity_project(resolve_mode: str) -> None:
    runner = TraceRunner(
        "http://rka.test",
        project_id="prj_00000000000000000000000000",
        transport=_story_transport(resolve_mode=resolve_mode),
    )
    try:
        result = await runner.run_story_variant(STORY_SCENARIO, STORY_SCENARIO["query_variants"][0])
    finally:
        await runner.close()

    assert result["raw_candidate_recall"]["role_coverage"] == 1.0
    assert result["headline"]["role_coverage"] == pytest.approx(2 / 3, abs=1e-4)
    assert result["headline"]["missing_roles"] == ["mission"]
    assert result["headline"]["hard_failures"]["resolution_incomplete"] == [EVIDENCE]
    assert result["headline"]["story_success"] is False


def test_load_corpus_accepts_story_and_rejects_missing_variants(tmp_path: Path) -> None:
    corpus = tmp_path / "story.jsonl"
    corpus.write_text(json.dumps(STORY_SCENARIO) + "\n", encoding="utf-8")
    assert load_corpus(corpus)[0]["story"]["roles"]

    bad = tmp_path / "bad-story.jsonl"
    payload = {key: value for key, value in STORY_SCENARIO.items() if key != "query_variants"}
    bad.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="query_variants"):
        load_corpus(bad)

    missing_project = tmp_path / "missing-project.jsonl"
    payload = {key: value for key, value in STORY_SCENARIO.items() if key != "project_id"}
    missing_project.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="requires project_id"):
        load_corpus(missing_project)


def test_load_corpus_rejects_invalid_and_duplicate_slugs(tmp_path: Path) -> None:
    invalid_scenario = tmp_path / "invalid-scenario.jsonl"
    invalid_scenario.write_text(
        json.dumps({**SCENARIO, "scenario_id": "Not_Kebab"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="scenario_id must be a kebab-case slug"):
        load_corpus(invalid_scenario)

    duplicate_scenario = tmp_path / "duplicate-scenario.jsonl"
    duplicate_scenario.write_text(
        json.dumps(SCENARIO) + "\n" + json.dumps(SCENARIO) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate scenario_id"):
        load_corpus(duplicate_scenario)

    invalid_variant = tmp_path / "invalid-variant.jsonl"
    payload = {
        **STORY_SCENARIO,
        "query_variants": [{"variant_id": "Not_Kebab", "query": "why"}],
    }
    invalid_variant.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="variant_id must be a kebab-case slug"):
        load_corpus(invalid_variant)

    duplicate_variant = tmp_path / "duplicate-variant.jsonl"
    payload = {
        **STORY_SCENARIO,
        "query_variants": [
            {"variant_id": "exact", "query": "why"},
            {"variant_id": "exact", "query": "why again"},
        ],
    }
    duplicate_variant.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate variant_id"):
        load_corpus(duplicate_variant)
