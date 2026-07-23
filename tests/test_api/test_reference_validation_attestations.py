"""REST request contract for reference-validation attestations."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


@pytest_asyncio.fixture
async def api_client(tmp_path: Path):
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("reference-validation.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_route_queues_authors_and_literature_id(api_client) -> None:
    registered = await api_client.post(
        "/api/manuscripts",
        json={"venue": "CHI", "title": "Route test"},
    )
    assert registered.status_code == 201
    manuscript_id = registered.json()["id"]
    literature = await api_client.post(
        "/api/literature",
        json={"title": "A paper", "doi": "10.1234/route"},
    )
    assert literature.status_code == 201
    response = await api_client.post(
        f"/api/manuscripts/{manuscript_id}/validate-reference",
        json={
            "DOI": "10.1234/route",
            "title": "A paper",
            "author": [{"family": "Smith", "given": "J"}],
            "literature_id": literature.json()["id"],
        },
    )
    assert response.status_code == 202
    pending = response.json()
    assert pending["status"] == "pending"
    assert pending["job_id"].startswith("job_")
    assert pending["requested_manuscript_id"] == manuscript_id
    assert pending["canonical_manuscript_id"] == registered.json()["canonical_id"]

    status = await api_client.get(
        f"/api/manuscripts/{manuscript_id}/reference-validations/"
        f"{pending['job_id']}"
    )
    assert status.status_code == 200
    assert status.json() == pending


@pytest.mark.asyncio
async def test_status_route_hides_job_from_other_manuscript(api_client) -> None:
    first = await api_client.post(
        "/api/manuscripts/native",
        json={"title": "First"},
    )
    second = await api_client.post(
        "/api/manuscripts/native",
        json={"title": "Second"},
    )
    queued = await api_client.post(
        f"/api/manuscripts/{first.json()['id']}/validate-reference",
        json={"title": "Scoped paper"},
    )
    hidden = await api_client.get(
        f"/api/manuscripts/{second.json()['id']}/reference-validations/"
        f"{queued.json()['job_id']}"
    )
    assert hidden.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"title": "x" * 2_001},
        {"title": "Bounded", "unexpected": {"provider": "blob"}},
        {
            "title": "Bounded",
            "author": [{"family": "Smith", "credential": "secret"}],
        },
        {"title": "Bounded", "author": [{"given": "Missing identity"}]},
        {"title": "Bounded", "author": [{"family": "Smith"}] * 101},
        {"DOI": "   ", "title": "   "},
    ],
)
async def test_route_rejects_unbounded_or_open_reference_payloads(
    api_client,
    payload,
) -> None:
    manuscript = await api_client.post(
        "/api/manuscripts/native",
        json={"title": "Input bounds"},
    )
    response = await api_client.post(
        f"/api/manuscripts/{manuscript.json()['id']}/validate-reference",
        json=payload,
    )
    assert response.status_code == 422
