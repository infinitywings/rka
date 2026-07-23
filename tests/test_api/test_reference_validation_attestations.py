"""REST request contract for reference-validation attestations."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig
from rka.services.manuscript import ManuscriptService


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
async def test_route_forwards_authors_and_literature_id(api_client, monkeypatch) -> None:
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
    captured: dict = {}

    async def fake_validate(self, reference, *, manuscript_id, literature_id=None):
        captured.update({
            "reference": reference,
            "manuscript_id": manuscript_id,
            "literature_id": literature_id,
        })
        return {
            "status": "VERIFIED",
            "validation_id": "rvd_route",
            "retraction_checked": True,
        }

    monkeypatch.setattr(ManuscriptService, "validate_reference", fake_validate)
    response = await api_client.post(
        f"/api/manuscripts/{manuscript_id}/validate-reference",
        json={
            "DOI": "10.1234/route",
            "title": "A paper",
            "author": [{"family": "Smith", "given": "J"}],
            "literature_id": literature.json()["id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["validation_id"] == "rvd_route"
    assert captured == {
        "reference": {
            "DOI": "10.1234/route",
            "title": "A paper",
            "author": [{"family": "Smith", "given": "J"}],
        },
        "manuscript_id": manuscript_id,
        "literature_id": literature.json()["id"],
    }
