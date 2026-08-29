"""E2.4 contract tests for frozen Writer REST compatibility surfaces."""

from __future__ import annotations

import httpx
import pytest

from rka.api.app import create_app


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
WRITER_PATH_PREFIXES = (
    "/api/manuscripts",
    "/api/manuscript-source-proposals",
    "/api/planning",
    "/api/semantic-patches",
)


def _path_operations(schema: dict, path: str) -> list[dict]:
    return [
        operation
        for method, operation in schema["paths"][path].items()
        if method in HTTP_METHODS
    ]


def test_writer_routes_are_deprecated_but_remain_in_openapi() -> None:
    schema = create_app().openapi()
    writer_operations = [
        operation
        for path, path_item in schema["paths"].items()
        if path.startswith(WRITER_PATH_PREFIXES)
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    ]

    assert len(writer_operations) == 53
    assert all(operation.get("deprecated") is True for operation in writer_operations)


def test_mixed_changes_router_keeps_core_cursor_stable() -> None:
    schema = create_app().openapi()

    core_changes = _path_operations(schema, "/api/changes")
    writer_impact = _path_operations(
        schema,
        "/api/manuscripts/{manuscript_id}/impact",
    )

    assert len(core_changes) == 1
    assert core_changes[0].get("deprecated") is not True
    assert len(writer_impact) == 1
    assert writer_impact[0]["deprecated"] is True


def test_representative_core_routes_are_not_deprecated() -> None:
    schema = create_app().openapi()

    for path in ("/api/capabilities", "/api/projects", "/api/claims"):
        operations = _path_operations(schema, path)
        assert operations, path
        assert all(operation.get("deprecated") is not True for operation in operations)


@pytest.mark.asyncio
async def test_writer_call_gets_headers_without_body_wrapping() -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/semantic-patches/schema",
            headers={"Origin": "http://localhost:5173"},
        )
        core_response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.headers["X-RKA-Compatibility-Status"] == "deprecated"
    assert response.headers["X-RKA-Removal-Milestone"] == "E5"
    assert "rka-project/rka-writer" in response.headers["Link"]
    exposed = response.headers["Access-Control-Expose-Headers"].lower()
    assert "x-rka-compatibility-status" in exposed
    assert "x-rka-removal-milestone" in exposed
    assert "link" in exposed
    assert isinstance(response.json(), dict)
    assert "compatibility_notice" not in response.json()

    assert core_response.status_code == 200
    assert "X-RKA-Compatibility-Status" not in core_response.headers


def test_writer_path_matching_requires_a_complete_prefix_segment() -> None:
    from rka.api.app import _is_writer_compatibility_path

    assert _is_writer_compatibility_path("/api/manuscripts") is True
    assert _is_writer_compatibility_path("/api/manuscripts/man_legacy") is True
    assert _is_writer_compatibility_path("/api/manuscripts-core") is False
