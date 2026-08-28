"""REST project isolation for journal provenance writes."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


@pytest_asyncio.fixture
async def api_client(tmp_path: Path):
    app = create_app(
        RKAConfig(
            project_dir=tmp_path,
            db_path=Path("core-reliability-api.db"),
            llm_enabled=False,
            embeddings_enabled=False,
        )
    )
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_rest_rejects_foreign_provenance_without_partial_write(
    api_client: httpx.AsyncClient,
) -> None:
    created = await api_client.post(
        "/api/projects",
        json={"id": "prj_foreign", "name": "Foreign"},
    )
    assert created.status_code == 200, created.text
    foreign_decision = await api_client.post(
        "/api/decisions",
        headers={"X-RKA-Project": "prj_foreign"},
        json={
            "question": "Foreign decision?",
            "phase": "design",
            "decided_by": "brain",
        },
    )
    assert foreign_decision.status_code == 201, foreign_decision.text

    response = await api_client.post(
        "/api/notes",
        headers={"X-RKA-Project": "proj_default"},
        json={
            "content": "REST write that must roll back.",
            "related_decisions": [foreign_decision.json()["id"]],
        },
    )
    assert response.status_code == 422, response.text
    assert "proj_default" in response.json()["detail"]

    listed = await api_client.get(
        "/api/notes",
        headers={"X-RKA-Project": "proj_default"},
    )
    assert listed.status_code == 200
    assert all(
        note["content"] != "REST write that must roll back."
        for note in listed.json()
    )
