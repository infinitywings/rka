"""MCP parity tests for E2.1 Core capability discovery."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka import __version__
from rka.api.app import create_app
from rka.config import RKAConfig
from rka.mcp.operation_args import QueryCapabilitiesArgs


def _capability_document(*, core_version: str) -> dict:
    return {
        "schema_version": "rka.core-capabilities/v1",
        "core": {
            "name": "rka-core",
            "version": core_version,
            "contract": "rka-core/v1",
            "supported_contracts": ["rka-core/v1"],
        },
        "interfaces": {
            "rest": {
                "status": "stable",
                "contract": "rka-rest/v1",
                "discovery": "/openapi.json",
            },
            "mcp": {
                "status": "stable",
                "contract": "rka-mcp/v1",
                "discovery": "rka_describe",
                "operation_maturity_basis": "usage-readiness",
                "default_operation_count": 1,
                "usage_stable_operation_count": 1,
                "usage_preview_operation_count": 0,
                "deprecated_operation_count": 0,
                "supported_operation_count": 1,
                "supported_usage_stable_operation_count": 1,
                "supported_usage_preview_operation_count": 0,
                "unsupported_operation_count": 0,
                "legacy_operation_count": 0,
            },
        },
        "supported_capabilities": ["rest", "mcp", "embedding"],
        "available_capabilities": ["rest", "mcp"],
        "embedding": {"available": False, "reason_unavailable": "disabled"},
    }


@pytest_asyncio.fixture
async def capability_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import rka.mcp.server as mcp_server

    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("capability_discovery.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:

        def fake_client(project_id: str | None = None) -> httpx.AsyncClient:
            assert project_id is None
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            )

        monkeypatch.setattr(mcp_server, "_client", fake_client)
        yield mcp_server
    finally:
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_capabilities_query_is_unscoped_and_reports_connector_backend(
    capability_backend,
):
    body = json.loads(await capability_backend.rka_query(QueryCapabilitiesArgs()))
    assert body["schema_version"] == "rka.core-capabilities/v1"
    assert body["core"]["version"] == __version__
    assert body["connector"] == {
        "name": "rka-mcp",
        "version": __version__,
        "backend_version": __version__,
        "version_match": True,
        "compatible": True,
    }


@pytest.mark.asyncio
async def test_capabilities_query_preserves_actionable_requirement_error(
    capability_backend,
):
    body = json.loads(
        await capability_backend.rka_query(QueryCapabilitiesArgs(required_contract="rka-core/v99"))
    )
    assert body["error"] == "unsupported_core_contract"
    assert body["supported_contracts"] == ["rka-core/v1"]
    assert body["connector"]["version"] == __version__
    assert "rka-core/v1" in body["hint"]


@pytest.mark.asyncio
async def test_capabilities_query_preserves_capability_requirement_error(
    capability_backend,
):
    body = json.loads(
        await capability_backend.rka_query(
            QueryCapabilitiesArgs(required_capabilities=["embedding"])
        )
    )
    assert body["error"] == "unsupported_capability_combination"
    assert body["issues"][0]["status"] == "unavailable"
    assert body["connector"]["compatible"] is True


@pytest.mark.asyncio
async def test_pre_e2_backend_returns_incompatible_backend(monkeypatch: pytest.MonkeyPatch):
    import rka.mcp.server as mcp_server

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/capabilities"
        return httpx.Response(
            200,
            json={
                "embedding": {
                    "available": False,
                    "reason_unavailable": "legacy response",
                }
            },
        )

    def fake_client(project_id: str | None = None) -> httpx.AsyncClient:
        assert project_id is None
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://legacy",
        )

    monkeypatch.setattr(mcp_server, "_client", fake_client)
    body = json.loads(await mcp_server.rka_query(QueryCapabilitiesArgs()))
    assert body["error"] == "incompatible_backend"
    assert body["connector"]["version"] == __version__
    assert body["observed_payload"]["embedding"]["reason_unavailable"] == ("legacy response")
    assert "upgrade" in body["hint"].lower()


@pytest.mark.asyncio
async def test_version_skew_is_visible_but_contract_compatible(
    monkeypatch: pytest.MonkeyPatch,
):
    import rka.mcp.server as mcp_server

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_capability_document(core_version="2.9.0"))

    def fake_client(project_id: str | None = None) -> httpx.AsyncClient:
        assert project_id is None
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://skewed",
        )

    monkeypatch.setattr(mcp_server, "_client", fake_client)
    body = json.loads(await mcp_server.rka_query(QueryCapabilitiesArgs()))
    assert body["connector"]["backend_version"] == "2.9.0"
    assert body["connector"]["version_match"] is False
    assert body["connector"]["compatible"] is True


@pytest.mark.asyncio
async def test_valid_manifest_without_required_contract_uses_uniform_error_shape(
    monkeypatch: pytest.MonkeyPatch,
):
    import rka.mcp.server as mcp_server

    manifest = _capability_document(core_version="4.0.0")
    manifest["core"]["contract"] = "rka-core/v2"
    manifest["core"]["supported_contracts"] = ["rka-core/v2"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=manifest)

    def fake_client(project_id: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://future",
        )

    monkeypatch.setattr(mcp_server, "_client", fake_client)
    body = json.loads(await mcp_server.rka_query(QueryCapabilitiesArgs()))
    assert body["error"] == "incompatible_backend"
    assert body["required_contract"] == "rka-core/v1"
    assert body["connector"]["compatible"] is False
    assert body["backend_capabilities"]["core"]["contract"] == "rka-core/v2"
    assert "synchronize" in body["hint"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [404, 405])
async def test_missing_capability_endpoint_is_actionable_incompatibility(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
):
    import rka.mcp.server as mcp_server

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="not available")

    def fake_client(project_id: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://legacy",
        )

    monkeypatch.setattr(mcp_server, "_client", fake_client)
    body = json.loads(await mcp_server.rka_query(QueryCapabilitiesArgs()))
    assert body["error"] == "incompatible_backend"
    assert body["rest_status_code"] == status_code
    assert "upgrade" in body["hint"].lower()


@pytest.mark.asyncio
async def test_unreachable_backend_returns_recovery_hint(monkeypatch: pytest.MonkeyPatch):
    import rka.mcp.server as mcp_server

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    def fake_client(project_id: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://offline",
        )

    monkeypatch.setattr(mcp_server, "_client", fake_client)
    body = json.loads(await mcp_server.rka_query(QueryCapabilitiesArgs()))
    assert body["error"] == "backend_unavailable"
    assert body["connector_version"] == __version__
    assert "RKA_API_URL" in body["hint"]


def test_mcp_initialize_identifies_the_rka_connector_version():
    import rka.mcp.server as mcp_server

    assert mcp_server.mcp._mcp_server.version == __version__
