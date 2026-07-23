"""API contract tests for server-attested project scope."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


DEFAULT_HEADERS = {"X-RKA-Project": "proj_default"}
OTHER_HEADERS = {"X-RKA-Project": "proj_scope_other"}


@pytest_asyncio.fixture
async def api_client(tmp_path: Path):
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("scope-outputs.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/projects",
                json={"id": "proj_scope_other", "name": "Other Scope"},
            )
            assert response.status_code == 200
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_note_outputs_attested_project_and_rejects_cross_project_lookup(
    api_client: httpx.AsyncClient,
) -> None:
    created = await api_client.post(
        "/api/notes",
        headers=DEFAULT_HEADERS,
        json={"content": "Project-scoped note.", "source": "executor"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["project_id"] == "proj_default"

    fetched = await api_client.get(
        f"/api/notes/{body['id']}",
        headers=DEFAULT_HEADERS,
    )
    assert fetched.status_code == 200
    assert fetched.json()["project_id"] == "proj_default"

    wrong_scope = await api_client.get(
        f"/api/notes/{body['id']}",
        headers=OTHER_HEADERS,
    )
    assert wrong_scope.status_code == 404


@pytest.mark.asyncio
async def test_decision_outputs_attested_project_and_rejects_cross_project_lookup(
    api_client: httpx.AsyncClient,
) -> None:
    created = await api_client.post(
        "/api/decisions",
        headers=DEFAULT_HEADERS,
        json={
            "question": "Which claim belongs to this project?",
            "phase": "planning",
            "decided_by": "pi",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["project_id"] == "proj_default"

    fetched = await api_client.get(
        f"/api/decisions/{body['id']}",
        headers=DEFAULT_HEADERS,
    )
    assert fetched.status_code == 200
    assert fetched.json()["project_id"] == "proj_default"

    wrong_scope = await api_client.get(
        f"/api/decisions/{body['id']}",
        headers=OTHER_HEADERS,
    )
    assert wrong_scope.status_code == 404


@pytest.mark.asyncio
async def test_manuscript_registration_outputs_attested_project(
    api_client: httpx.AsyncClient,
) -> None:
    created = await api_client.post(
        "/api/manuscripts",
        headers=DEFAULT_HEADERS,
        json={"venue": "CHI", "title": "Scoped manuscript"},
    )
    assert created.status_code == 201
    assert created.json()["project_id"] == "proj_default"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("collection", "payload"),
    [
        ("literature", {"title": "Scoped source"}),
        ("missions", {"phase": "execution", "objective": "Scoped mission"}),
        ("clusters", {"label": "Scoped evidence"}),
    ],
)
async def test_remaining_writer_entities_attest_project_and_reject_wrong_scope(
    api_client: httpx.AsyncClient,
    collection: str,
    payload: dict,
) -> None:
    created = await api_client.post(
        f"/api/{collection}",
        headers=DEFAULT_HEADERS,
        json=payload,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["project_id"] == "proj_default"

    fetched = await api_client.get(
        f"/api/{collection}/{body['id']}",
        headers=DEFAULT_HEADERS,
    )
    assert fetched.status_code == 200
    assert fetched.json()["project_id"] == "proj_default"

    wrong_scope = await api_client.get(
        f"/api/{collection}/{body['id']}",
        headers=OTHER_HEADERS,
    )
    assert wrong_scope.status_code == 404
