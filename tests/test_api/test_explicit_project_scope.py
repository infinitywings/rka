"""Scoped endpoints must refuse a request that names no project.

`get_project_id` used to fall back to `DEFAULT_PROJECT_ID` when a request
carried neither the `X-RKA-Project` header nor a `project_id` query parameter.
The fallback was silent: a scoped write with no project did not fail, it filed
the row under the default project. Thirty entities reached `proj_default` that
way — journal entries, claims, decisions and clusters whose typed links all
point into other projects.

Writes matter most, but reads are covered too: an export or a search that
silently answers about the wrong project is its own failure, and was how this
was noticed.

Unscoped endpoints must keep working without a project, or creating the first
project becomes impossible.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


@pytest_asyncio.fixture
async def client(tmp_path: Path):
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("explicit_scope.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        # Deliberately no default headers: absence is what is under test.
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


NOTE = {"content": "a note that must not be filed by guesswork"}


class TestScopedWritesRefuseWithoutAProject:
    @pytest.mark.asyncio
    async def test_create_note_is_refused(self, client: httpx.AsyncClient):
        response = await client.post("/api/notes", json=NOTE)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_the_refusal_names_both_ways_to_supply_scope(self, client):
        detail = (await client.post("/api/notes", json=NOTE)).json()["detail"]
        assert "X-RKA-Project" in detail
        assert "project_id" in detail

    @pytest.mark.asyncio
    async def test_nothing_is_written_to_the_default_project(self, client):
        await client.post("/api/notes", json=NOTE)
        listed = await client.get("/api/notes", headers={"X-RKA-Project": "proj_default"})
        assert listed.status_code == 200
        body = listed.json()
        rows = body if isinstance(body, list) else body.get("entries", body.get("items", []))
        assert all(NOTE["content"] not in str(row) for row in rows)

    @pytest.mark.asyncio
    async def test_a_blank_header_is_absence_not_a_project(self, client):
        response = await client.post("/api/notes", json=NOTE, headers={"X-RKA-Project": "   "})
        assert response.status_code == 422


class TestExplicitScopeStillWorks:
    @pytest.mark.asyncio
    async def test_header_is_accepted(self, client: httpx.AsyncClient):
        response = await client.post(
            "/api/notes", json=NOTE, headers={"X-RKA-Project": "proj_default"}
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_query_parameter_is_accepted(self, client: httpx.AsyncClient):
        response = await client.post(
            "/api/notes", json=NOTE, params={"project_id": "proj_default"}
        )
        assert response.status_code == 201


class TestUnscopedEndpointsAreUnaffected:
    """Creating the first project cannot itself require a project."""

    @pytest.mark.asyncio
    async def test_health(self, client: httpx.AsyncClient):
        assert (await client.get("/api/health")).status_code == 200

    @pytest.mark.asyncio
    async def test_list_projects(self, client: httpx.AsyncClient):
        assert (await client.get("/api/projects")).status_code == 200

    @pytest.mark.asyncio
    async def test_create_project(self, client: httpx.AsyncClient):
        response = await client.post("/api/projects", json={"name": "scope test"})
        assert response.status_code == 200, response.text
