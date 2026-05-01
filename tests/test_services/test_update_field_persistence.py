"""Regression tests for the silent-write-failure bug class.

Filed under mis_01KQJH9MB65AR0GSVPQBT8707X. The bug: fields not declared in
*Update Pydantic models were silently stripped during request deserialization
(Pydantic's extra="ignore" default), so writes returned 200 but had no effect.

Test pattern, applied to every (service, field) pair:

    1. Read the entity's `updated_at` (or `created_at` for missions, which
       lack updated_at).
    2. Perform the write via the service layer.
    3. Re-read the entity via the service layer's `get` method.
    4. Assert the field has the written value.
    5. Assert `updated_at` advanced (where the entity has one).

Tests that only check the response body's `fields=...` list are exactly
the tests this bug evades; do not write tests that stop at the response.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from pydantic import ValidationError

from rka.infra.database import Database
from rka.models.claim import (
    ClaimCreate, ClaimUpdate,
    EvidenceClusterCreate, EvidenceClusterUpdate,
)
from rka.models.decision import DecisionCreate, DecisionUpdate
from rka.models.journal import JournalEntryCreate, JournalEntryUpdate
from rka.models.literature import LiteratureCreate, LiteratureUpdate
from rka.models.mission import MissionCreate, MissionUpdate, MissionTask
from rka.models.project import ProjectCreate
from rka.models.topic import TopicCreate, TopicUpdate
from rka.services.claims import ClaimService
from rka.services.clusters import ClusterService
from rka.services.decisions import DecisionService
from rka.services.literature import LiteratureService
from rka.services.missions import MissionService
from rka.services.notes import NoteService
from rka.services.project import ProjectService
from rka.services.topics import TopicService


PROJECT_ID = "proj_test_persistence"


@pytest_asyncio.fixture
async def project_db(db: Database):
    """Database with a project row created for PROJECT_ID."""
    project_svc = ProjectService(db)
    await project_svc.create_project(
        ProjectCreate(id=PROJECT_ID, name="Test Persistence", description="test"),
        actor="system",
    )
    return db


# ── Decisions ────────────────────────────────────────────────────────


class TestDecisionUpdatePersistence:
    """Bug A's original failure case: DecisionService.update.assumptions."""

    @pytest_asyncio.fixture
    async def svc(self, project_db: Database) -> DecisionService:
        return DecisionService(project_db, project_id=PROJECT_ID)

    @pytest_asyncio.fixture
    async def decision_id(self, svc: DecisionService) -> str:
        rec = await svc.create(DecisionCreate(
            question="test", phase="design", decided_by="executor",
        ))
        return rec.id

    async def test_assumptions_persists(self, svc: DecisionService, decision_id: str):
        """REGRESSION: assumptions was silently stripped pre-fix.

        Round-trips via svc.get() to catch the bug class — checking the
        response body of the update call alone would still pass against
        the buggy code.
        """
        before = await svc.get(decision_id)
        assert before.assumptions is None
        before_updated = before.updated_at

        # Force at least 1s clock advance for updated_at comparison.
        await asyncio.sleep(1.05)

        await svc.update(
            decision_id,
            DecisionUpdate(assumptions=["a1", "a2", "a3"]),
        )

        after = await svc.get(decision_id)
        assert after.assumptions == ["a1", "a2", "a3"]
        assert after.updated_at > before_updated

    async def test_rationale_persists_working_anchor(
        self, svc: DecisionService, decision_id: str,
    ):
        """Working-anchor regression: rationale was always working."""
        await asyncio.sleep(1.05)
        await svc.update(decision_id, DecisionUpdate(rationale="because"))
        after = await svc.get(decision_id)
        assert after.rationale == "because"

    async def test_extra_field_rejected(self, decision_id: str):
        """DecisionUpdate now sets extra='forbid'; undeclared fields raise."""
        with pytest.raises(ValidationError):
            DecisionUpdate(some_undeclared_field="x")  # type: ignore[call-arg]


# ── Missions ─────────────────────────────────────────────────────────


class TestMissionUpdatePersistence:
    """Bug A's parallel case: MissionService.update with 9 previously-stripped fields."""

    @pytest_asyncio.fixture
    async def svc(self, project_db: Database) -> MissionService:
        return MissionService(project_db, project_id=PROJECT_ID)

    @pytest_asyncio.fixture
    async def mission_id(self, svc: MissionService) -> str:
        rec = await svc.create(MissionCreate(
            phase="design", objective="test mission",
        ))
        return rec.id

    @pytest_asyncio.fixture
    async def decision_id(self, project_db: Database) -> str:
        """A decision to use as motivated_by_decision target."""
        dec_svc = DecisionService(project_db, project_id=PROJECT_ID)
        rec = await dec_svc.create(DecisionCreate(
            question="motivating", phase="design", decided_by="executor",
        ))
        return rec.id

    async def test_motivated_by_decision_persists(
        self, svc: MissionService, mission_id: str, decision_id: str,
    ):
        """REGRESSION: motivated_by_decision was silently stripped pre-fix."""
        before = await svc.get(mission_id)
        assert before.motivated_by_decision is None

        await svc.update(
            mission_id,
            MissionUpdate(motivated_by_decision=decision_id),
        )

        after = await svc.get(mission_id)
        assert after.motivated_by_decision == decision_id

    async def test_context_persists(self, svc: MissionService, mission_id: str):
        await svc.update(mission_id, MissionUpdate(context="bg context"))
        after = await svc.get(mission_id)
        assert after.context == "bg context"

    async def test_acceptance_criteria_persists(
        self, svc: MissionService, mission_id: str,
    ):
        await svc.update(mission_id, MissionUpdate(acceptance_criteria="ac"))
        after = await svc.get(mission_id)
        assert after.acceptance_criteria == "ac"

    async def test_scope_boundaries_persists(
        self, svc: MissionService, mission_id: str,
    ):
        await svc.update(mission_id, MissionUpdate(scope_boundaries="sb"))
        after = await svc.get(mission_id)
        assert after.scope_boundaries == "sb"

    async def test_checkpoint_triggers_persists(
        self, svc: MissionService, mission_id: str,
    ):
        await svc.update(mission_id, MissionUpdate(checkpoint_triggers="ct"))
        after = await svc.get(mission_id)
        assert after.checkpoint_triggers == "ct"

    async def test_phase_persists(self, svc: MissionService, mission_id: str):
        await svc.update(mission_id, MissionUpdate(phase="experiment"))
        after = await svc.get(mission_id)
        assert after.phase == "experiment"

    async def test_tags_persists(self, svc: MissionService, mission_id: str):
        await svc.update(mission_id, MissionUpdate(tags=["alpha", "beta"]))
        after = await svc.get(mission_id)
        assert set(after.tags) == {"alpha", "beta"}

    async def test_objective_persists_working_anchor(
        self, svc: MissionService, mission_id: str,
    ):
        """Working-anchor regression: objective was always working."""
        await svc.update(mission_id, MissionUpdate(objective="new obj"))
        after = await svc.get(mission_id)
        assert after.objective == "new obj"

    async def test_tasks_persists_working_anchor(
        self, svc: MissionService, mission_id: str,
    ):
        """Working-anchor regression: tasks was always working."""
        await svc.update(
            mission_id,
            MissionUpdate(tasks=[MissionTask(description="t1")]),
        )
        after = await svc.get(mission_id)
        assert after.tasks is not None
        assert len(after.tasks) == 1
        assert after.tasks[0].description == "t1"

    async def test_extra_field_rejected(self):
        """MissionUpdate now sets extra='forbid'; undeclared fields raise."""
        with pytest.raises(ValidationError):
            MissionUpdate(undeclared="x")  # type: ignore[call-arg]


# ── Notes / Journal ──────────────────────────────────────────────────


class TestJournalEntryUpdatePersistence:
    """Working-anchor service: NoteService was already correct pre-fix."""

    @pytest_asyncio.fixture
    async def svc(self, project_db: Database) -> NoteService:
        return NoteService(project_db, project_id=PROJECT_ID)

    @pytest_asyncio.fixture
    async def entry_id(self, svc: NoteService) -> str:
        rec = await svc.create(JournalEntryCreate(content="seed"))
        return rec.id

    async def test_related_mission_persists_working_anchor(
        self, svc: NoteService, entry_id: str, project_db: Database,
    ):
        """Confirmed working in the audit; protect against regression."""
        # Seed a mission to point at.
        ms = MissionService(project_db, project_id=PROJECT_ID)
        m = await ms.create(MissionCreate(phase="design", objective="x"))

        before = await svc.get(entry_id)
        before_updated = before.updated_at
        await asyncio.sleep(1.05)

        await svc.update(entry_id, JournalEntryUpdate(related_mission=m.id))

        after = await svc.get(entry_id)
        assert after.related_mission == m.id
        assert after.updated_at > before_updated

    async def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            JournalEntryUpdate(undeclared="x")  # type: ignore[call-arg]


# ── Literature ───────────────────────────────────────────────────────


class TestLiteratureUpdatePersistence:
    """Working-anchor service: Pattern A coverage."""

    @pytest_asyncio.fixture
    async def svc(self, project_db: Database) -> LiteratureService:
        return LiteratureService(project_db, project_id=PROJECT_ID)

    @pytest_asyncio.fixture
    async def lit_id(self, svc: LiteratureService) -> str:
        rec = await svc.create(LiteratureCreate(title="seed paper"))
        return rec.id

    async def test_title_persists(self, svc: LiteratureService, lit_id: str):
        await svc.update(lit_id, LiteratureUpdate(title="updated"))
        after = await svc.get(lit_id)
        assert after.title == "updated"

    async def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            LiteratureUpdate(undeclared="x")  # type: ignore[call-arg]


# ── Topics / Claims / Clusters ───────────────────────────────────────


class TestSmallerEntityUpdates:
    """Working-anchor coverage for the rest: claims, clusters, topics."""

    async def test_topic_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            TopicUpdate(undeclared="x")  # type: ignore[call-arg]

    async def test_claim_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ClaimUpdate(undeclared="x")  # type: ignore[call-arg]

    async def test_cluster_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            EvidenceClusterUpdate(undeclared="x")  # type: ignore[call-arg]
