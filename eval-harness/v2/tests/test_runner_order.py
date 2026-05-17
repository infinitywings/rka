"""Unit tests for the Eval-v2 runner's tool-invocation-order policy
(Mission v2.5.5-D2-runner-reorder, mis_01KRSQ4GCRWPSXCWZHGZ2ZR830).

Vector II hypothesis: the bundle's ``combined_ranking`` head is
dominated by which tool fires first. Anchor-aware tools (ego_graph,
multi_hop, assemble_evidence) carry the most-relevant entities for
anchored scenarios; firing them BEFORE ``get_context`` puts their
outputs at the head of the combined ranking. These tests lock the
reorder predicate + the deterministic prefix order.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_V2_DIR = Path(__file__).resolve().parent.parent
if str(_V2_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_V2_DIR.parent))

from v2.runner import EvalV2Runner


def _scenario(tools: list[str], *, critical_count: int = 1) -> dict:
    """Build a minimal scenario fixture for the reorder predicate."""
    return {
        "scenario_id": "test-fixture",
        "actor": "brain",
        "tools_invoked": tools,
        "expected_entities": [
            {
                "entity_id": f"dec_TEST_{i}",
                "entity_type": "decision",
                "importance": "critical",
            }
            for i in range(critical_count)
        ],
    }


class TestRunnerReorder:
    def test_anchored_scenario_fires_ego_graph_before_get_context(self):
        """Canonical anchored scenario: ego_graph + multi_hop appear after
        get_context in the corpus, but the reorder must pull them to the
        front because the scenario has critical expected entities."""
        tools = [
            "rka_get_context",
            "rka_get_ego_graph",
            "rka_multi_hop_retrieval",
            "rka_get_status",
        ]
        scenario = _scenario(tools)
        ordered = EvalV2Runner._reorder_tools_for_scenario(scenario, tools)
        # Anchor-aware tools first, in deterministic order.
        assert ordered.index("rka_get_ego_graph") < ordered.index("rka_get_context")
        assert ordered.index("rka_multi_hop_retrieval") < ordered.index("rka_get_context")
        # Deterministic prefix order: ego_graph before multi_hop.
        assert ordered.index("rka_get_ego_graph") < ordered.index(
            "rka_multi_hop_retrieval"
        )
        # Non-anchor-aware tools preserve their relative order from the corpus.
        assert ordered.index("rka_get_context") < ordered.index("rka_get_status")
        # No tools added or dropped — set equality.
        assert set(ordered) == set(tools)
        assert len(ordered) == len(tools)

    def test_no_anchor_aware_tools_returns_list_unchanged(self):
        """Scenarios whose tools_invoked have NO anchor-aware tools must
        be returned unchanged (the 7/16 un-anchored corpus cases). Even
        if the scenario has critical expected entities, with no anchor-
        aware tools to pull there's nothing to reorder."""
        tools = [
            "rka_get_context",
            "rka_get_status",
            "rka_get_pending_maintenance",
            "rka_get_checkpoints",
        ]
        scenario = _scenario(tools, critical_count=3)
        ordered = EvalV2Runner._reorder_tools_for_scenario(scenario, tools)
        assert ordered == tools

    def test_no_critical_entities_returns_list_unchanged(self):
        """Defensive: if a scenario has zero critical entities (would
        violate the corpus ≥3-critical-floor rule but covers the edge
        case), the reorder is a no-op regardless of tool composition."""
        tools = [
            "rka_get_ego_graph",
            "rka_get_context",
            "rka_multi_hop_retrieval",
        ]
        scenario = _scenario(tools, critical_count=0)
        ordered = EvalV2Runner._reorder_tools_for_scenario(scenario, tools)
        assert ordered == tools

    def test_deterministic_anchor_prefix_order(self):
        """When all 3 anchor-aware tools are present, they must come
        out in the canonical order: ego_graph → multi_hop → assemble_
        evidence. This is what the bundle's combined_ranking head will
        carry; downstream NDCG depends on it."""
        # Corpus order intentionally scrambled.
        tools = [
            "rka_assemble_evidence",
            "rka_get_context",
            "rka_multi_hop_retrieval",
            "rka_get_ego_graph",
            "rka_get_status",
        ]
        scenario = _scenario(tools)
        ordered = EvalV2Runner._reorder_tools_for_scenario(scenario, tools)
        # Anchor-aware prefix is the class constant's order.
        assert ordered[:3] == [
            "rka_get_ego_graph",
            "rka_multi_hop_retrieval",
            "rka_assemble_evidence",
        ]
        # Remaining tools keep their corpus order.
        assert ordered[3:] == ["rka_get_context", "rka_get_status"]

    def test_partial_anchor_aware_subset_still_reorders(self):
        """When only SOME anchor-aware tools are present, just those
        get pulled to the front in canonical order. Mirrors the most
        common corpus shape (8/9 affected scenarios have 1-2, not 3)."""
        tools = [
            "rka_get_context",
            "rka_multi_hop_retrieval",  # the only anchor-aware tool present
            "rka_get_journal",
        ]
        scenario = _scenario(tools)
        ordered = EvalV2Runner._reorder_tools_for_scenario(scenario, tools)
        assert ordered == [
            "rka_multi_hop_retrieval",
            "rka_get_context",
            "rka_get_journal",
        ]


class TestAnchorAwareToolOrderConstant:
    """Lock the class-level anchor-aware tool tuple — its identity is
    load-bearing for the bundle's combined_ranking head."""

    def test_canonical_anchor_aware_order(self):
        assert EvalV2Runner._ANCHOR_AWARE_TOOL_ORDER == (
            "rka_get_ego_graph",
            "rka_multi_hop_retrieval",
            "rka_assemble_evidence",
        )


class TestRunSceneriaWiresReorderPolicy:
    """T4 (mis_01KRSQ4GCRWPSXCWZHGZ2ZR830): lock the runner reorder as
    the eval-v2 default by asserting `run_scenario` actually invokes
    the reorder before iterating over tools. A behavioral test on the
    bundle's recorded invocation order is more robust than asserting
    on the method's existence — it locks the integration, not just the
    API surface."""

    @pytest.mark.asyncio
    async def test_run_scenario_records_invocations_in_reordered_order(self):
        """Construct a scenario whose corpus tools_invoked puts an
        anchor-aware tool AFTER get_context; assert the bundle's
        recorded invocations have the anchor-aware tool BEFORE
        get_context. This locks the run_scenario → _reorder wiring."""
        import httpx

        from v2.runner import EvalV2Runner

        # Hand a stub transport that 200s every relevant endpoint.
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"entities": []})

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_handler), base_url="http://test"
        )
        r = EvalV2Runner(rka_url="http://test", project_id="prj_test", http_client=client)

        scenario = {
            "scenario_id": "test-lock-reorder-wiring",
            "actor": "brain",
            "trigger": "lock-policy-assertion",
            "tools_invoked": [
                "rka_get_context",       # corpus position 0
                "rka_get_ego_graph",     # corpus position 1 — should be pulled to 0
                "rka_multi_hop_retrieval",  # corpus position 2 — should be pulled to 1
                "rka_get_status",        # corpus position 3 — should stay after the anchors
            ],
            "expected_entities": [
                {
                    "entity_id": "dec_TEST_LOCK",
                    "entity_type": "decision",
                    "importance": "critical",
                },
                {
                    "entity_id": "dec_TEST_LOCK_2",
                    "entity_type": "decision",
                    "importance": "critical",
                },
                {
                    "entity_id": "dec_TEST_LOCK_3",
                    "entity_type": "decision",
                    "importance": "critical",
                },
            ],
        }
        bundle = await r.run_scenario(scenario)
        invocation_order = [inv.tool for inv in bundle.invocations]
        assert invocation_order == [
            "rka_get_ego_graph",
            "rka_multi_hop_retrieval",
            "rka_get_context",
            "rka_get_status",
        ], (
            "run_scenario must apply the anchor-aware reorder policy before "
            "iterating; the bundle's invocation order is the canonical "
            "evidence the policy is wired in. If this fails, T1's reorder "
            "exists but isn't being called."
        )
