"""REST contracts for semantic cursor and Writer impact reads."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from rka.api.app import create_app
from rka.config import RKAConfig


@pytest.mark.asyncio
async def test_change_and_manuscript_impact_routes_are_project_scoped(
    tmp_path: Path,
) -> None:
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("change-routes.db"),
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
            created_response = await client.post(
                "/api/manuscripts/native",
                json={"title": "Impact API paper", "venue": "IEEE S&P"},
            )
            assert created_response.status_code == 201
            manuscript = created_response.json()

            spine_response = await client.put(
                f"/api/manuscripts/{manuscript['id']}/argument-spine",
                json={
                    "expected_revision": 1,
                    "spine": {
                        "claims": [{
                            "claim_id": "C1",
                            "claim_type": "methodological",
                            "status": "active",
                            "text": "The method isolates the evaluated factor.",
                            "allowed_wording": "The evaluated factor is isolated.",
                            "prohibited_wording": [
                                "The method proves universal isolation."
                            ],
                            "manuscript_units": ["M1"],
                        }],
                        "units": [{
                            "unit_id": "M1",
                            "kind": "method",
                            "location": "sections/method.tex#factor",
                            "status": "drafted",
                        }],
                    },
                },
            )
            assert spine_response.status_code == 200

            baseline_response = await client.get(
                "/api/changes",
                params={"cursor": 0, "limit": 100},
            )
            assert baseline_response.status_code == 200
            baseline = baseline_response.json()
            assert baseline["schema_version"] == "rka-change-cursor/v1"
            assert baseline["project_id"] == "proj_default"

            updated_response = await client.patch(
                f"/api/manuscripts/{manuscript['id']}",
                json={
                    "expected_revision": 2,
                    "abstract": "A bounded, evidence-backed abstract.",
                },
            )
            assert updated_response.status_code == 200

            change_response = await client.get(
                "/api/changes",
                params={"cursor": baseline["next_cursor"], "limit": 1},
            )
            assert change_response.status_code == 200
            change_page = change_response.json()
            assert change_page["changes"][0]["source_table"] == "manuscripts"

            impact_response = await client.get(
                f"/api/manuscripts/{manuscript['id']}/impact",
                params={"since_cursor": baseline["next_cursor"]},
            )
            assert impact_response.status_code == 200
            impact = impact_response.json()
            assert impact["schema_version"] == "rka-manuscript-impact/v1"
            assert impact["impact_state"] == "relevant_changes"
            assert [
                item["local_key"]
                for item in impact["affected_manuscript_claims"]
            ] == ["C1"]
            assert impact["file_locations"] == ["sections/method.tex#factor"]

            missing = await client.get(
                "/api/manuscripts/man_missing/impact",
                params={"since_cursor": 0},
            )
            assert missing.status_code == 404
    finally:
        await lifespan.__aexit__(None, None, None)
