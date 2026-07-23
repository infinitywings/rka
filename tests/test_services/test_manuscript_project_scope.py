"""ManuscriptService project-scope output and lookup tests."""

from __future__ import annotations

import pytest

from rka.infra.database import Database
from rka.models.project import ProjectCreate
from rka.services.manuscript import ManuscriptService
from rka.services.notes import NoteService
from rka.services.project import ProjectService


@pytest.mark.asyncio
async def test_manuscript_get_attests_scope_and_rejects_cross_project_lookup(
    db: Database,
) -> None:
    other_project_id = "proj_manuscript_other"
    await ProjectService(db).create_project(
        ProjectCreate(id=other_project_id, name="Other Manuscript Scope"),
    )

    default_service = ManuscriptService(
        db,
        notes=NoteService(db, project_id="proj_default"),
        project_id="proj_default",
    )
    other_service = ManuscriptService(
        db,
        notes=NoteService(db, project_id=other_project_id),
        project_id=other_project_id,
    )

    entry = await default_service.register(
        venue="USENIX",
        title="A Project-Scoped Manuscript",
    )
    manuscript = await default_service.get(entry.id)

    assert manuscript is not None
    assert manuscript["project_id"] == "proj_default"
    assert await other_service.get(entry.id) is None
