"""Test for Affordance D (Mission B / mis_01KR209WY4M6WQFEXRH79KC2ZF):
the service-layer round-trip that the new rka_update_mission MCP wrapper
relies on.

The MCP wrapper itself is a thin pass-through to PUT /api/missions/{id},
which Bug A's commit (02d7348) already covered for round-trip persistence
via test_update_field_persistence.py. This test adds the specific case
that motivated the Affordance D — updating motivated_by_decision via the
service-layer update path materializes the corresponding 'motivated'
entity_link, parallel to the create-path behavior.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.models.decision import DecisionCreate
from rka.models.mission import MissionCreate, MissionUpdate
from rka.models.project import ProjectCreate
from rka.services.decisions import DecisionService
from rka.services.missions import MissionService
from rka.services.project import ProjectService

PROJECT_ID = "proj_test_update_mission_affordance_d"


@pytest_asyncio.fixture
async def setup(db: Database):
    psvc = ProjectService(db)
    await psvc.create_project(
        ProjectCreate(id=PROJECT_ID, name="Affordance D Test", description="t"),
        actor="system",
    )
    dsvc = DecisionService(db, project_id=PROJECT_ID)
    msvc = MissionService(db, project_id=PROJECT_ID)
    decision = await dsvc.create(DecisionCreate(
        question="anchor decision for affordance D",
        phase="design",
        decided_by="executor",
    ))
    mission = await msvc.create(
        MissionCreate(phase="design", objective="affordance D test mission"),
        actor="executor",
    )
    return db, msvc, decision.id, mission.id


class TestAffordanceDServiceLayer:
    """The MCP wrapper rka_update_mission proxies these service-layer calls."""

    async def test_motivated_by_decision_updates_and_materializes_link(self, setup):
        db, msvc, dec_id, mis_id = setup

        # Pre-state: no motivated entity_link yet.
        pre_links = await db.fetchall(
            """SELECT id FROM entity_links
               WHERE source_id = ? AND target_id = ? AND link_type = 'motivated'""",
            [dec_id, mis_id],
        )
        assert pre_links == []

        # Update via service.
        await msvc.update(mis_id, MissionUpdate(motivated_by_decision=dec_id))

        # Post: field persisted (round-trip via get).
        after = await msvc.get(mis_id)
        assert after.motivated_by_decision == dec_id

        # Post: motivated entity_link materialized (Bug A's fix carries here).
        post_links = await db.fetchall(
            """SELECT id, source_type, source_id, link_type, target_type, target_id
               FROM entity_links
               WHERE source_id = ? AND target_id = ? AND link_type = 'motivated'""",
            [dec_id, mis_id],
        )
        assert len(post_links) == 1, "expected exactly one materialized 'motivated' edge"
        link = post_links[0]
        assert link["source_type"] == "decision"
        assert link["target_type"] == "mission"

    async def test_context_field_round_trips(self, setup):
        """Working anchor: context (one of MissionUpdate's fields added in Bug A)."""
        _db, msvc, _dec_id, mis_id = setup
        await msvc.update(mis_id, MissionUpdate(context="affordance D context body"))
        after = await msvc.get(mis_id)
        assert after.context == "affordance D context body"

    async def test_extra_field_rejected(self):
        """MissionUpdate has extra='forbid' (Bug A defense-in-depth);
        rka_update_mission's signature doesn't expose undeclared fields,
        but if a future caller bypasses the MCP wrapper and POSTs JSON
        directly with an undeclared field, Pydantic still rejects."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            MissionUpdate(undeclared_xyz="x")  # type: ignore[call-arg]
