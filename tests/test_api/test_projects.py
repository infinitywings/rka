"""Project API tests."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from rka.api.app import create_app
from rka.config import RKAConfig


@pytest.mark.asyncio
async def test_create_project_is_not_scoped_by_active_project_header(tmp_path: Path):
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("projects.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)

    await lifespan.__aenter__()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            seed_response = await client.post(
                "/api/projects",
                json={"id": "proj_existing", "name": "Existing Project"},
            )
            assert seed_response.status_code == 200

            response = await client.post(
                "/api/projects",
                json={"name": "Created While Scoped"},
                headers={"X-RKA-Project": "proj_existing"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] != "proj_existing"
        assert body["name"] == "Created While Scoped"
    finally:
        await lifespan.__aexit__(None, None, None)
