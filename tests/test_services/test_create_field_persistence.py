"""Regression tests for the CREATE-path silent-write-failure bug class.

Filed under mis_01KR43RX9KY11GAPTPPGK9XSDE (Mission C). Companion to
test_update_field_persistence.py (Bug A): same bug shape (model-narrowness +
Pydantic extra="ignore" default → silent strip), but on the CREATE path
that Bug A's UPDATE-only audit didn't cover.

Two new defects fixed by this mission, both Bug-A pattern:

  - DecisionCreate.assumptions — silently dropped pre-fix because Bug A's
    commit added `assumptions` to DecisionUpdate but missed DecisionCreate.
    rka_add_decision MCP wrapper has been sending the field; service was
    silently dropping it for the week between Bug A and Mission C.

  - JournalEntryCreate.summary — silently dropped pre-fix because the
    field exists on JournalEntryUpdate but not on JournalEntryCreate, and
    NoteService.create's INSERT projection didn't enumerate it either.

All 12 *Create models lacking it gained `extra="forbid"` defense-in-depth
mirroring Bug A's commit on the *Update side. Behavior change for clients:
POST endpoints reject undeclared fields with 422 instead of silent strip.

Test pattern, applied to every (service, field) pair under audit:

    1. Build the *Create payload with the field set.
    2. Call service.create.
    3. Re-read via service.get.
    4. Assert the field has the written value.

Tests that only check the create-call's return-object echo are exactly the
tests this bug evades; round-trip via get is required.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from pydantic import ValidationError

from rka.infra.database import Database
from rka.models.checkpoint import CheckpointCreate
from rka.models.claim import (
    ClaimCreate, ClaimEdgeCreate,
    EvidenceClusterCreate,
)
from rka.models.decision import DecisionCreate
from rka.models.journal import JournalEntryCreate
from rka.models.literature import LiteratureCreate
from rka.models.mission import MissionCreate, MissionReportCreate, MissionTask
from rka.models.project import ProjectCreate
from rka.models.review_queue import ReviewItemCreate
from rka.models.topic import TopicCreate
from rka.services.checkpoints import CheckpointService
from rka.services.claims import ClaimService
from rka.services.clusters import ClusterService
from rka.services.decisions import DecisionService
from rka.services.literature import LiteratureService
from rka.services.missions import MissionService
from rka.services.notes import NoteService
from rka.services.project import ProjectService
from rka.services.topics import TopicService


PROJECT_ID = "proj_test_create_persistence"


@pytest_asyncio.fixture
async def project_db(db: Database):
    """Database with a project row created for PROJECT_ID."""
    psvc = ProjectService(db)
    await psvc.create_project(
        ProjectCreate(id=PROJECT_ID, name="Test Create Persistence", description="t"),
        actor="system",
    )
    return db


# ── Decisions: the new CREATE-path defect (assumptions) ────────────────


class TestDecisionCreatePersistence:
    """Mission C primary defect: DecisionCreate.assumptions silently stripped pre-fix."""

    @pytest_asyncio.fixture
    async def svc(self, project_db: Database) -> DecisionService:
        return DecisionService(project_db, project_id=PROJECT_ID)

    async def test_assumptions_persists(self, svc: DecisionService):
        """REGRESSION: assumptions was silently stripped at create-time pre-fix.

        Round-trips via svc.get() to catch the bug class — checking the
        create-call's return-object alone would have passed against the
        buggy code (because Pydantic stripped it before the service even
        saw it).
        """
        rec = await svc.create(DecisionCreate(
            question="What architecture should we adopt?",
            phase="design",
            decided_by="executor",
            assumptions=["latency dominates", "single tenant", "read-heavy"],
        ))
        after = await svc.get(rec.id)
        assert after.assumptions == ["latency dominates", "single tenant", "read-heavy"]

    async def test_rationale_persists_working_anchor(self, svc: DecisionService):
        """Working anchor: rationale always round-tripped correctly."""
        rec = await svc.create(DecisionCreate(
            question="t",
            phase="design",
            decided_by="executor",
            rationale="because the data says so",
        ))
        after = await svc.get(rec.id)
        assert after.rationale == "because the data says so"

    async def test_motivated_by_decision_via_grep_gate_anchor(self, svc: DecisionService):
        """The decision created here will be referenced by the Mission test below."""
        rec = await svc.create(DecisionCreate(
            question="anchor for mission test",
            phase="design",
            decided_by="executor",
        ))
        assert rec.id is not None

    async def test_extra_field_rejected(self):
        """DecisionCreate now sets extra='forbid'; undeclared fields raise."""
        with pytest.raises(ValidationError):
            DecisionCreate(  # type: ignore[call-arg]
                question="t", phase="design", decided_by="executor",
                some_undeclared_field="x",
            )


# ── Journal entries: the new CREATE-path defect (summary) ──────────────


class TestJournalEntryCreatePersistence:
    """Mission C secondary defect: JournalEntryCreate.summary silently dropped pre-fix."""

    @pytest_asyncio.fixture
    async def svc(self, project_db: Database) -> NoteService:
        return NoteService(project_db, project_id=PROJECT_ID)

    async def test_summary_persists(self, svc: NoteService):
        """REGRESSION: summary was silently stripped at create-time pre-fix.

        JournalEntryCreate didn't declare the field; NoteService.create's
        INSERT didn't enumerate the column. JournalEntryUpdate has the
        field, so post-create UPDATE worked — exactly Bug A's CREATE/UPDATE
        divergence shape.
        """
        rec = await svc.create(JournalEntryCreate(
            content="long-form content goes here",
            summary="t2 summary",
            type="note",
            source="executor",
        ))
        after = await svc.get(rec.id)
        assert after.summary == "t2 summary"
        # And content (working anchor) still persists.
        assert after.content == "long-form content goes here"

    async def test_extra_field_rejected(self):
        """JournalEntryCreate now sets extra='forbid'."""
        with pytest.raises(ValidationError):
            JournalEntryCreate(  # type: ignore[call-arg]
                content="t", some_undeclared_field="x",
            )


# ── Missions: T1's working anchor (motivated_by_decision) ──────────────


class TestMissionCreatePersistence:
    """T1 reproducer: MissionService.create.motivated_by_decision works correctly.

    The original Group-B failure (mis_01KQMWJ5EA9GKMQKQ8JT4M4FJE.motivated_by_decision
    landed as NULL) was intermittent — 2 of 3 identical-shape calls succeeded — and
    most consistent with client-side LLM tool-call malformation rather than a
    deterministic service-layer bug. This test pins the deterministic round-trip
    behavior so any future regression on the service path is caught.
    """

    @pytest_asyncio.fixture
    async def svc(self, project_db: Database) -> MissionService:
        return MissionService(project_db, project_id=PROJECT_ID)

    @pytest_asyncio.fixture
    async def parent_decision_id(self, project_db: Database) -> str:
        dsvc = DecisionService(project_db, project_id=PROJECT_ID)
        rec = await dsvc.create(DecisionCreate(
            question="parent decision for mission link",
            phase="design", decided_by="executor",
        ))
        return rec.id

    async def test_motivated_by_decision_persists(
        self, svc: MissionService, parent_decision_id: str,
    ):
        rec = await svc.create(MissionCreate(
            phase="design",
            objective="t mission",
            motivated_by_decision=parent_decision_id,
        ), actor="executor")
        after = await svc.get(rec.id)
        assert after.motivated_by_decision == parent_decision_id

    async def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            MissionCreate(  # type: ignore[call-arg]
                phase="design", objective="t", some_undeclared_field="x",
            )


# ── Other *Create models: extra="forbid" smoke tests ───────────────────


class TestExtraForbidCoverage:
    """Smoke-coverage of extra='forbid' on every *Create model that gained it
    in Mission C T5. Each test verifies that an undeclared field raises
    ValidationError instead of being silently stripped.

    Skipped: DecisionOptionCreate, HookCreate, CalibrationOutcomeCreate
    (already had extra='forbid' before Mission C).
    """

    def test_decision_create(self):
        with pytest.raises(ValidationError):
            DecisionCreate(  # type: ignore[call-arg]
                question="t", phase="design", decided_by="executor", extra_x="x",
            )

    def test_mission_create(self):
        with pytest.raises(ValidationError):
            MissionCreate(  # type: ignore[call-arg]
                phase="design", objective="t", extra_x="x",
            )

    def test_mission_report_create(self):
        with pytest.raises(ValidationError):
            MissionReportCreate(extra_x="x")  # type: ignore[call-arg]

    def test_journal_entry_create(self):
        with pytest.raises(ValidationError):
            JournalEntryCreate(content="t", extra_x="x")  # type: ignore[call-arg]

    def test_checkpoint_create(self):
        with pytest.raises(ValidationError):
            CheckpointCreate(  # type: ignore[call-arg]
                mission_id="mis_x", type="decision", description="t", extra_x="x",
            )

    def test_literature_create(self):
        with pytest.raises(ValidationError):
            LiteratureCreate(title="t", extra_x="x")  # type: ignore[call-arg]

    def test_claim_create(self):
        with pytest.raises(ValidationError):
            ClaimCreate(  # type: ignore[call-arg]
                source_entry_id="jrn_x", claim_type="observation", content="t",
                extra_x="x",
            )

    def test_evidence_cluster_create(self):
        with pytest.raises(ValidationError):
            EvidenceClusterCreate(label="t", extra_x="x")  # type: ignore[call-arg]

    def test_claim_edge_create(self):
        with pytest.raises(ValidationError):
            ClaimEdgeCreate(  # type: ignore[call-arg]
                source_claim_id="clm_x", relation="member_of", extra_x="x",
            )

    def test_topic_create(self):
        with pytest.raises(ValidationError):
            TopicCreate(name="t", extra_x="x")  # type: ignore[call-arg]

    def test_project_create(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="t", extra_x="x")  # type: ignore[call-arg]

    def test_review_item_create(self):
        with pytest.raises(ValidationError):
            ReviewItemCreate(  # type: ignore[call-arg]
                item_type="claim", item_id="clm_x", flag="low_confidence_cluster",
                extra_x="x",
            )


# ── Working anchors for the other audited services ─────────────────────


class TestOtherServicesCreateAnchors:
    """Lightweight working-anchor coverage for the all-green services in
    the T2 audit. Confirms each *Service.create round-trips a representative
    field via get(), establishing a regression catch-all for the bug class."""

    async def test_literature_title_persists(self, project_db: Database):
        svc = LiteratureService(project_db, project_id=PROJECT_ID)
        rec = await svc.create(LiteratureCreate(
            title="Test Paper", abstract="t", added_by="executor",
        ))
        after = await svc.get(rec.id)
        assert after.title == "Test Paper"
        assert after.abstract == "t"

    async def test_claim_content_persists(self, project_db: Database):
        # Need a journal source_entry_id.
        nsvc = NoteService(project_db, project_id=PROJECT_ID)
        seed = await nsvc.create(JournalEntryCreate(
            content="seed for claim", type="note", source="executor",
        ))
        csvc = ClaimService(project_db, project_id=PROJECT_ID)
        rec = await csvc.create(ClaimCreate(
            source_entry_id=seed.id,
            claim_type="observation",
            content="latency improves under tuning",
            confidence=0.8,
        ))
        after = await csvc.get(rec.id)
        assert after.content == "latency improves under tuning"
        assert after.confidence == 0.8

    async def test_evidence_cluster_label_persists(self, project_db: Database):
        clsvc = ClusterService(project_db, project_id=PROJECT_ID)
        rec = await clsvc.create(EvidenceClusterCreate(
            label="Latency cluster",
            synthesis="tuned configuration consistently lowers tail latency.",
            confidence="emerging",
        ))
        after = await clsvc.get(rec.id)
        assert after.label == "Latency cluster"
        assert after.synthesis.startswith("tuned configuration")

    async def test_topic_name_persists(self, project_db: Database):
        tsvc = TopicService(project_db, project_id=PROJECT_ID)
        rec = await tsvc.create(TopicCreate(
            name="test-topic", description="round-trip anchor",
        ))
        after = await tsvc.get(rec.id)
        assert after.name == "test-topic"
        assert after.description == "round-trip anchor"

    async def test_checkpoint_description_persists(self, project_db: Database):
        # Need a mission_id.
        msvc = MissionService(project_db, project_id=PROJECT_ID)
        m = await msvc.create(MissionCreate(phase="design", objective="t"), actor="executor")
        chsvc = CheckpointService(project_db, project_id=PROJECT_ID)
        rec = await chsvc.create(CheckpointCreate(
            mission_id=m.id, type="decision", description="t checkpoint",
        ))
        after = await chsvc.get(rec.id)
        assert after.description == "t checkpoint"
