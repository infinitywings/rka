"""MCP provenance direction and depth contract regressions."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import TypeAdapter

from rka.mcp import server
from rka.mcp.operation_args import QueryArgsUnion


@pytest.fixture
def captured_requests(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "path": request.url.path,
                "query": dict(request.url.params),
            }
        )
        return httpx.Response(
            200,
            json={
                "nodes": [
                    {"id": "jrn_basis", "type": "journal", "label": "Basis"},
                    {"id": "dec_prior", "type": "decision", "label": "Prior"},
                    {"id": "dec_center", "type": "decision", "label": "Center"},
                    {"id": "mis_run", "type": "mission", "label": "Run"},
                    {"id": "jrn_result", "type": "journal", "label": "Result"},
                    {
                        "id": "clm_conclusion",
                        "type": "claim",
                        "label": "Conclusion",
                    },
                ],
                "edges": [
                    {
                        # Stored orientation: the decision (source) depends on
                        # its justifying journal (target).
                        "source": "dec_prior",
                        "target": "jrn_basis",
                        "link_type": "justified_by",
                    },
                    {
                        # Same physical orientation as motivated below, but
                        # opposite causal direction from the center.
                        "source": "dec_center",
                        "target": "dec_prior",
                        "link_type": "supersedes",
                    },
                    {
                        "source": "dec_center",
                        "target": "mis_run",
                        "link_type": "motivated",
                    },
                    {
                        "source": "mis_run",
                        "target": "jrn_result",
                        "link_type": "produced",
                    },
                    {
                        # A claim depends on its source journal, so forward
                        # traversal from the journal reaches this third hop.
                        "source": "clm_conclusion",
                        "target": "jrn_result",
                        "link_type": "derived_from",
                    },
                ],
            },
        )

    def client(_project_id: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://testserver",
        )

    monkeypatch.setattr(server, "_client", client)
    return captured


@pytest.mark.parametrize(
    ("direction", "shows_upstream", "shows_downstream"),
    [
        ("backward", True, False),
        ("upstream", True, False),
        ("forward", False, True),
        ("downstream", False, True),
        ("both", True, True),
    ],
)
@pytest.mark.asyncio
async def test_direct_provenance_accepts_public_and_legacy_directions(
    captured_requests: list[dict[str, Any]],
    direction: str,
    shows_upstream: bool,
    shows_downstream: bool,
) -> None:
    result = await server.rka_trace_provenance(
        entity_id="dec_center",
        direction=direction,
        project_id="prj_test",
    )

    assert ("Upstream (what led to this)" in result) is shows_upstream
    assert ("Downstream (what this led to)" in result) is shows_downstream
    upstream_section = result.partition("Upstream (what led to this):")[2].partition(
        "Downstream (what this led to):"
    )[0]
    downstream_section = result.partition("Downstream (what this led to):")[2]
    if shows_upstream:
        assert "dec_prior" in upstream_section
        assert "jrn_basis" in upstream_section
        assert "mis_run" not in upstream_section
        assert "depth=2, from=dec_prior" in upstream_section
    if shows_downstream:
        assert "mis_run" in downstream_section
        assert "jrn_result" in downstream_section
        assert "clm_conclusion" in downstream_section
        assert "dec_prior" not in downstream_section
        assert "depth=3, from=jrn_result" in downstream_section
    graph_request = next(
        request
        for request in captured_requests
        if request["path"] == "/api/graph/ego/dec_center"
    )
    assert graph_request == {
        "path": "/api/graph/ego/dec_center",
        "query": {"depth": "3"},
    }


@pytest.mark.asyncio
async def test_provenance_depth_limits_rendered_causal_traversal(
    captured_requests: list[dict[str, Any]],
) -> None:
    result = await server.rka_trace_provenance(
        entity_id="dec_center",
        direction="both",
        max_depth=1,
        project_id="prj_test",
    )

    assert "dec_prior" in result
    assert "mis_run" in result
    assert "jrn_basis" not in result
    assert "jrn_result" not in result
    assert "clm_conclusion" not in result
    assert captured_requests[-1]["query"] == {"depth": "1"}


@pytest.mark.asyncio
async def test_single_provenance_link_never_claims_no_links(
    captured_requests: list[dict[str, Any]],
) -> None:
    result = await server.rka_trace_provenance(
        entity_id="dec_prior",
        direction="backward",
        max_depth=1,
        project_id="prj_test",
    )

    assert "jrn_basis" in result
    assert "(none)" not in result
    assert "no links found" not in result


@pytest.mark.asyncio
async def test_typed_provenance_rejects_unknown_direction_before_http(
    captured_requests: list[dict[str, Any]],
) -> None:
    args = TypeAdapter(QueryArgsUnion).validate_python(
        {
            "operation": "provenance",
            "project_id": "prj_test",
            "id": "dec_center",
            "filters": {"direction": "sideways"},
        }
    )

    with pytest.raises(ValueError, match="direction must be one of"):
        await server.rka_query(args)
    assert captured_requests == []


@pytest.mark.parametrize("max_depth", [0, 4, True, 1.5])
@pytest.mark.asyncio
async def test_direct_provenance_rejects_depth_outside_endpoint_contract(
    captured_requests: list[dict[str, Any]],
    max_depth: Any,
) -> None:
    with pytest.raises(ValueError, match="between 1 and 3"):
        await server.rka_trace_provenance(
            entity_id="dec_center",
            max_depth=max_depth,
            project_id="prj_test",
        )
    assert captured_requests == []


@pytest.mark.asyncio
async def test_provenance_describe_documents_canonical_contract() -> None:
    schema = json.loads(await server.rka_describe(operation="provenance"))

    assert schema["enums"]["direction"] == [
        "forward",
        "backward",
        "both",
        "downstream",
        "upstream",
    ]
    assert "defaults to 3" in schema["notes"]
    assert "between 1 and 3" in schema["notes"]
    assert "Unknown directions are rejected" in schema["notes"]
    assert "non-causal context" in schema["notes"]


def test_informed_by_uses_endpoint_types_for_both_stored_shapes() -> None:
    nodes = {
        "lit_basis": {"type": "literature"},
        "dec_choice": {"type": "decision"},
        "jrn_notes": {"type": "journal"},
    }
    canonical = [
        {
            "source": "lit_basis",
            "target": "dec_choice",
            "link_type": "informed_by",
        }
    ]
    reading_notes = [
        {
            "source": "jrn_notes",
            "target": "lit_basis",
            "link_type": "informed_by",
        }
    ]

    assert server._walk_provenance_edges(
        "dec_choice",
        canonical,
        direction="backward",
        max_depth=1,
        nodes=nodes,
    ) == [
        {
            "entity_id": "lit_basis",
            "from_id": "dec_choice",
            "link_type": "informed_by",
            "depth": 1,
        }
    ]
    assert server._walk_provenance_edges(
        "jrn_notes",
        reading_notes,
        direction="backward",
        max_depth=1,
        nodes=nodes,
    ) == [
        {
            "entity_id": "lit_basis",
            "from_id": "jrn_notes",
            "link_type": "informed_by",
            "depth": 1,
        }
    ]
    assert server._walk_provenance_edges(
        "lit_basis",
        reading_notes,
        direction="forward",
        max_depth=1,
        nodes=nodes,
    )[0]["entity_id"] == "jrn_notes"


def test_provenance_walk_preserves_parallel_converging_and_cycle_edges() -> None:
    edges = [
        {
            "source": "dec_root",
            "target": "jrn_a",
            "link_type": "justified_by",
        },
        {
            "source": "dec_root",
            "target": "jrn_b",
            "link_type": "justified_by",
        },
        {"source": "jrn_a", "target": "lit_x", "link_type": "cites"},
        {
            "source": "jrn_a",
            "target": "lit_x",
            "link_type": "references",
        },
        {"source": "jrn_b", "target": "lit_x", "link_type": "cites"},
        # Backward traversal reaches the root again at depth three. The edge
        # must remain visible, but the root must not be expanded a second time.
        {"source": "lit_x", "target": "dec_root", "link_type": "cites"},
    ]

    steps = server._walk_provenance_edges(
        "dec_root",
        edges,
        direction="backward",
        max_depth=3,
    )

    assert len(steps) == 6
    assert {
        (step["from_id"], step["entity_id"], step["link_type"], step["depth"])
        for step in steps
    } == {
        ("dec_root", "jrn_a", "justified_by", 1),
        ("dec_root", "jrn_b", "justified_by", 1),
        ("jrn_a", "lit_x", "cites", 2),
        ("jrn_a", "lit_x", "references", 2),
        ("jrn_b", "lit_x", "cites", 2),
        ("lit_x", "dec_root", "cites", 3),
    }


@pytest.mark.asyncio
async def test_contradictions_render_only_as_non_causal_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "nodes": [
                    {"id": "clm_center", "type": "claim", "label": "Center"},
                    {"id": "clm_dispute", "type": "claim", "label": "Dispute"},
                ],
                "edges": [
                    {
                        "source": "clm_center",
                        "target": "clm_dispute",
                        "link_type": "contradicts",
                    }
                ],
            },
        )

    def client(_project_id: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://testserver",
        )

    monkeypatch.setattr(server, "_client", client)
    result = await server.rka_trace_provenance(
        entity_id="clm_center",
        direction="both",
        project_id="prj_test",
    )

    upstream = result.partition("Upstream (what led to this):")[2].partition(
        "Downstream (what this led to):"
    )[0]
    downstream = result.partition("Downstream (what this led to):")[2].partition(
        "Contextual disagreements (non-causal):"
    )[0]
    disagreement = result.partition("Contextual disagreements (non-causal):")[2]
    assert "clm_dispute" not in upstream
    assert "clm_dispute" not in downstream
    assert "clm_dispute" in disagreement
    assert "↔ contradicts" in disagreement
