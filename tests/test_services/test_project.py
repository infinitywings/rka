"""Project service tests."""

from __future__ import annotations

import pytest

from rka.models.project import ProjectCreate
from rka.services.project import ProjectService


@pytest.mark.asyncio
async def test_create_project_rejects_duplicate_name(db):
    svc = ProjectService(db)

    await svc.create_project(
        ProjectCreate(id="proj_one", name="Duplicate Name", description="one"),
        actor="system",
    )

    with pytest.raises(ValueError, match="Project name 'Duplicate Name' already exists"):
        await svc.create_project(
            ProjectCreate(id="proj_two", name="Duplicate Name", description="two"),
            actor="system",
        )
