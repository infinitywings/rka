"""REST compatibility for historical reference-validation jobs."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig
from rka.services.jobs import JobQueue


@pytest_asyncio.fixture
async def api_context(tmp_path: Path):
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
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-RKA-Project": "proj_default"},
        ) as client:
            yield client, app
    finally:
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_validation_initiation_route_is_removed(api_context) -> None:
    client, _app = api_context
    manuscript = await client.post(
        "/api/manuscripts/native",
        json={"title": "No Core validation"},
    )
    response = await client.post(
        f"/api/manuscripts/{manuscript.json()['id']}/validate-reference",
        json={"title": "A paper"},
    )
    assert response.status_code in {404, 405}


@pytest.mark.asyncio
async def test_status_route_reads_historical_job_and_hides_other_manuscript(
    api_context,
) -> None:
    client, app = api_context
    first = await client.post("/api/manuscripts/native", json={"title": "First"})
    second = await client.post("/api/manuscripts/native", json={"title": "Second"})
    first_id = first.json()["id"]
    job_id = await JobQueue(app.state.db).enqueue(
        "reference_validate",
        project_id="proj_default",
        entity_type="manuscript",
        entity_id=first_id,
        payload={"requested_manuscript_id": first_id},
    )

    status = await client.get(
        f"/api/manuscripts/{first_id}/reference-validations/{job_id}"
    )
    assert status.status_code == 200
    assert status.json()["status"] == "pending"
    assert status.json()["job_id"] == job_id

    hidden = await client.get(
        f"/api/manuscripts/{second.json()['id']}/reference-validations/{job_id}"
    )
    assert hidden.status_code == 404
