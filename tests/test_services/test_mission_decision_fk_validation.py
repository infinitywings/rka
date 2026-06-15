"""Mission creation validates motivated_by_decision instead of 500ing.

Regression for the FK-violation -> 500 bug surfaced by an end-to-end test:
POST /api/missions (service-layer create) with a non-existent or empty
motivated_by_decision tripped a raw `sqlite3.IntegrityError: FOREIGN KEY
constraint failed` inside the INSERT, surfacing as an opaque 500. The service
now validates the reference up front (clean ValueError -> HTTP 400) and treats a
blank reference as "unset" (NULL).
"""

from __future__ import annotations

import pytest

from rka.infra.database import Database
from rka.models.decision import DecisionCreate
from rka.models.mission import MissionCreate
from rka.models.project import ProjectCreate
from rka.services.decisions import DecisionService
from rka.services.missions import MissionService
from rka.services.project import ProjectService

PROJECT_ID = "proj_test_mission_fk_validation"


@pytest.fixture
async def services(db: Database):
    psvc = ProjectService(db)
    await psvc.create_project(
        ProjectCreate(id=PROJECT_ID, name="Mission FK test", description="t"),
        actor="system",
    )
    return (
        DecisionService(db, project_id=PROJECT_ID),
        MissionService(db, project_id=PROJECT_ID),
    )


async def test_nonexistent_decision_raises_valueerror_not_integrityerror(services):
    _, msvc = services
    with pytest.raises(ValueError, match="not found"):
        await msvc.create(
            MissionCreate(
                phase="design",
                objective="mission with a bogus decision link",
                motivated_by_decision="dec_does_not_exist",
            ),
            actor="executor",
        )


async def test_empty_decision_reference_is_treated_as_unset(services):
    _, msvc = services
    mission = await msvc.create(
        MissionCreate(
            phase="design",
            objective="mission with blank motivation",
            motivated_by_decision="   ",  # whitespace -> NULL, no FK attempt
        ),
        actor="executor",
    )
    assert mission.id
    assert not (mission.motivated_by_decision or "")  # stored as unset


async def test_valid_decision_reference_succeeds_and_links(services):
    dsvc, msvc = services
    decision = await dsvc.create(
        DecisionCreate(question="anchor decision", phase="design", decided_by="executor")
    )
    mission = await msvc.create(
        MissionCreate(
            phase="design",
            objective="mission with a real decision link",
            motivated_by_decision=decision.id,
        ),
        actor="executor",
    )
    assert mission.motivated_by_decision == decision.id
    # the 'motivated' entity_link materializes
    links = await msvc.db.fetchall(
        """SELECT id FROM entity_links
           WHERE source_id = ? AND target_id = ? AND link_type = 'motivated'""",
        [decision.id, mission.id],
    )
    assert len(links) == 1
