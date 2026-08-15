"""REST contracts for experiment/run/observation evidence records."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from rka.api.app import create_app
from rka.config import RKAConfig


@pytest.mark.asyncio
async def test_experiment_rest_lifecycle_and_conflict_mapping(tmp_path: Path) -> None:
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("experiment-api.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-RKA-Project": "proj_default"},
        ) as client:
            created_response = await client.post(
                "/api/experiments",
                json={
                    "title": "API experiment",
                    "objective": "Measure one bounded effect.",
                    "protocol": "Execute the frozen benchmark.",
                    "created_by": "brain",
                    "reason": "Exercise the REST contract.",
                },
            )
            assert created_response.status_code == 201, created_response.text
            experiment = created_response.json()
            assert experiment["current_plan"]["version"] == 1

            stale_response = await client.post(
                f"/api/experiments/{experiment['id']}/transition",
                json={
                    "expected_revision": 2,
                    "target_status": "active",
                    "actor": "pi",
                    "reason": "Stale request.",
                },
            )
            assert stale_response.status_code == 409

            active_response = await client.post(
                f"/api/experiments/{experiment['id']}/transition",
                json={
                    "expected_revision": 1,
                    "target_status": "active",
                    "actor": "pi",
                    "reason": "Approved.",
                },
            )
            assert active_response.status_code == 200

            run_response = await client.post(
                "/api/experiment-runs",
                json={
                    "experiment_id": experiment["id"],
                    "plan_version": 1,
                    "label": "api-run",
                    "runner": "local",
                    "created_by": "executor",
                    "reason": "Execute plan version 1.",
                },
            )
            assert run_response.status_code == 201, run_response.text
            run = run_response.json()

            started_response = await client.post(
                f"/api/experiment-runs/{run['id']}/transition",
                json={
                    "expected_revision": 1,
                    "action": "start",
                    "actor": "executor",
                    "reason": "Started.",
                },
            )
            assert started_response.status_code == 200

            observation_response = await client.post(
                "/api/experiment-observations",
                json={
                    "run_id": run["id"],
                    "name": "accuracy delta",
                    "kind": "comparison",
                    "direction": "inconclusive",
                    "summary": "The interval crosses zero.",
                    "value_text": "95% CI [-0.02, 0.03]",
                    "observed_at": "2026-08-15T12:00:00Z",
                    "recorded_by": "executor",
                },
            )
            assert observation_response.status_code == 201, observation_response.text
            observation = observation_response.json()
            assert observation["direction"] == "inconclusive"

            locator_response = await client.post(
                "/api/evidence-locators",
                json={
                    "observation_id": observation["id"],
                    "source_kind": "repository",
                    "repository_url": "https://github.com/example/evaluation",
                    "commit_sha": "0123456789abcdef0123456789abcdef01234567",
                    "relative_path": "results/accuracy.json",
                    "locator_kind": "json_pointer",
                    "locator_value": "/accuracy/delta",
                    "content_hash": "a" * 64,
                    "created_by": "executor",
                },
            )
            assert locator_response.status_code == 201, locator_response.text

            detail_response = await client.get(
                f"/api/experiment-observations/{observation['id']}"
            )
            assert detail_response.status_code == 200
            assert detail_response.json()["locators"][0]["id"].startswith("elc_")

            filtered_response = await client.get(
                "/api/experiment-observations",
                params={"direction": "inconclusive"},
            )
            assert filtered_response.status_code == 200
            assert [item["id"] for item in filtered_response.json()] == [
                observation["id"]
            ]
    finally:
        await lifespan.__aexit__(None, None, None)
