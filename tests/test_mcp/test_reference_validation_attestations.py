"""Typed MCP contract for persistent reference-validation attestations."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from rka.mcp import server as mcp_server
from rka.mcp import verb_dispatch
from rka.mcp.operation_args import ValidateReferenceArgs


def test_typed_args_expose_journal_authors_and_literature_binding() -> None:
    args = ValidateReferenceArgs(
        project_id="prj_test",
        manuscript_id="jrn_manuscript",
        doi="10.1234/example",
        author=[{"family": "Smith", "given": "J"}],
        literature_id="lit_example",
    )
    assert args.manuscript_id.startswith("jrn_")
    assert [author.model_dump(exclude_none=True) for author in args.author or []] == [
        {"family": "Smith", "given": "J"}
    ]
    schema = ValidateReferenceArgs.model_json_schema()["properties"]
    assert "author" in schema
    assert "literature_id" in schema
    assert "jrn_" in schema["manuscript_id"]["description"]
    assert "202 pending job envelope" in (
        ValidateReferenceArgs.model_json_schema()["description"]
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": "x" * 2_001, "doi": None},
        {"author": [{"family": "Smith", "credential": "secret"}]},
        {"author": [{"given": "No family or literal"}]},
        {"author": [{"family": "Smith"}] * 101},
    ],
)
def test_typed_args_reject_unbounded_or_open_author_payloads(overrides) -> None:
    payload = {
        "project_id": "prj_test",
        "manuscript_id": "man_test",
        "doi": "10.1234/example",
        **overrides,
    }
    with pytest.raises(ValidationError):
        ValidateReferenceArgs(**payload)


@pytest.mark.asyncio
async def test_mcp_proxy_returns_pending_job_and_forwards_binding(monkeypatch) -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"path": request.url.path, "body": json.loads(request.content)})
        return httpx.Response(
            202,
            json={
                "job_id": "job_mcp",
                "status": "pending",
                "canonical_manuscript_id": "man_mcp",
                "requested_manuscript_id": "jrn_manuscript",
                "attempts": 0,
                "max_attempts": 3,
            },
        )

    transport = httpx.MockTransport(handler)

    def client(project_id=None):
        return httpx.AsyncClient(transport=transport, base_url="http://testserver")

    monkeypatch.setattr(mcp_server, "_client", client)
    result = json.loads(
        await mcp_server.rka_validate_reference(
            manuscript_id="jrn_manuscript",
            doi="10.1234/example",
            author=[{"family": "Smith"}],
            literature_id="lit_example",
            project_id="prj_test",
        )
    )
    assert result["job_id"] == "job_mcp"
    assert result["status"] == "pending"
    validation_calls = [
        call for call in calls if call["path"].endswith("/validate-reference")
    ]
    assert validation_calls == [
        {
            "path": "/api/manuscripts/jrn_manuscript/validate-reference",
            "body": {
                "DOI": "10.1234/example",
                "author": [{"family": "Smith"}],
                "literature_id": "lit_example",
            },
        }
    ]


@pytest.mark.asyncio
async def test_deferred_mcp_tool_revalidates_nested_authors() -> None:
    result = json.loads(
        await mcp_server.rka_validate_reference(
            manuscript_id="man_test",
            title="Bounded",
            author=[{"family": "Smith", "credential": "secret"}],
            project_id="prj_test",
        )
    )
    assert result["status"] == "error"
    assert "extra" in result["message"].lower()


@pytest.mark.asyncio
async def test_dispatch_forwards_author_and_literature_id(monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_validate(**kwargs):
        calls.append(kwargs)
        return "ok"

    monkeypatch.setattr(verb_dispatch, "_legacy", lambda name: fake_validate)
    result = await verb_dispatch.dispatch_record_literature(
        project_id="prj_test",
        title="A paper",
        bibtex=None,
        search_query=None,
        search_source=None,
        doi="10.1234/example",
        authors=None,
        year_min=None,
        venue=None,
        status="to_read",
        abstract=None,
        url=None,
        tags=None,
        related_decisions=None,
        action="validate_reference",
        lit_id=None,
        manuscript_id="jrn_manuscript",
        zotero_key=None,
        pdf_path=None,
        annotations=None,
        summary=None,
        add_to_library=False,
        limit=10,
        author=[{"family": "Smith"}],
        literature_id="lit_example",
    )
    assert result == "ok"
    assert calls == [
        {
            "manuscript_id": "jrn_manuscript",
            "doi": "10.1234/example",
            "title": "A paper",
            "author": [{"family": "Smith"}],
            "literature_id": "lit_example",
            "project_id": "prj_test",
        }
    ]
