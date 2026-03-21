"""Tests for v2.1 Phase 6: Sequential review loop.

Covers:
- Fan-out of synthesis.created, critique.no_issues, disagreement.detected events
- Reviewer routing to synthesis.created (not decision.* / claim.*)
- Researcher routing to critique.no_issues
- Auto next-mission creation flow on critique.no_issues
- Role subscription update validation
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from pathlib import Path

from rka.infra.database import Database
from rka.models.agent_role import AgentRoleCreate, AgentRoleUpdate
from rka.models.role_event import RoleEventCreate
from rka.models.journal import JournalEntryCreate
from rka.models.mission import MissionCreate, MissionReportCreate
from rka.services.agent_roles import AgentRoleService
from rka.services.role_events import RoleEventService
from rka.services.notes import NoteService
from rka.services.missions import MissionService


async def _ensure_project(db: Database, project_id: str = "proj_default") -> None:
    await db.execute(
        "INSERT OR IGNORE INTO projects (id, name, description, created_by) VALUES (?, ?, ?, ?)",
        [project_id, "Test", "Test project", "system"],
    )
    await db.execute(
        """INSERT OR IGNORE INTO project_states
           (project_id, project_name, project_description, phases_config, created_at, updated_at)
           VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'), strftime('%Y-%m-%dT%H:%M:%SZ','now'))""",
        [project_id, "Test", "Test project", "[]"],
    )
    await db.commit()


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    db_path = str(tmp_path / "test_sequential_review.db")
    database = Database(db_path)
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    await _ensure_project(database)
    yield database
    await database.close()


@pytest_asyncio.fixture
async def role_svc(db: Database):
    return AgentRoleService(db)


@pytest_asyncio.fixture
async def evt_svc(db: Database):
    return RoleEventService(db)


# ── Role Subscription Updates ─────────────────────────────


@pytest.mark.asyncio
async def test_reviewer_subscribes_to_synthesis_created(role_svc: AgentRoleService):
    """Reviewer role should match synthesis.created events."""
    reviewer = await role_svc.register(AgentRoleCreate(
        name="reviewer",
        subscriptions=["synthesis.created", "report.*"],
    ))
    matched = await role_svc.match_subscriptions("synthesis.created")
    assert any(r.id == reviewer.id for r in matched)


@pytest.mark.asyncio
async def test_reviewer_no_longer_matches_decision_events(role_svc: AgentRoleService):
    """Reviewer with updated subscriptions should NOT match decision.* events."""
    reviewer = await role_svc.register(AgentRoleCreate(
        name="reviewer_v2",
        subscriptions=["synthesis.created", "report.*"],
    ))
    matched = await role_svc.match_subscriptions("decision.created")
    assert not any(r.id == reviewer.id for r in matched)


@pytest.mark.asyncio
async def test_researcher_subscribes_to_critique(role_svc: AgentRoleService):
    """Researcher role should match critique.* events."""
    researcher = await role_svc.register(AgentRoleCreate(
        name="researcher",
        subscriptions=["report.*", "checkpoint.created.*", "literature.*", "decision.*", "critique.*"],
    ))
    matched = await role_svc.match_subscriptions("critique.no_issues")
    assert any(r.id == researcher.id for r in matched)

    matched2 = await role_svc.match_subscriptions("critique.disagreement")
    assert any(r.id == researcher.id for r in matched2)


# ── synthesis.created Fan-Out ─────────────────────────────


@pytest.mark.asyncio
async def test_synthesis_created_fanout(
    role_svc: AgentRoleService, evt_svc: RoleEventService
):
    """synthesis.created should fan out to reviewer (subscribed) but not executor."""
    reviewer = await role_svc.register(AgentRoleCreate(
        name="reviewer_synth",
        subscriptions=["synthesis.created"],
    ))
    await role_svc.register(AgentRoleCreate(
        name="executor_synth",
        subscriptions=["mission.*"],
    ))

    # Create a researcher role to use as source
    researcher = await role_svc.register(AgentRoleCreate(
        name="researcher_synth",
        subscriptions=["report.*"],
    ))

    ids = await evt_svc.emit_for_subscribers(
        "synthesis.created",
        source_entity_id="jrn_synth_001",
        source_entity_type="journal",
        source_role_id=researcher.id,
        payload={"mission_id": "mis_001", "summary": "Synthesis of findings"},
        agent_role_service=role_svc,
    )
    assert len(ids) == 1

    events = await evt_svc.list_for_role(reviewer.id, status="pending")
    assert len(events) == 1
    assert events[0].event_type == "synthesis.created"
    assert events[0].payload["mission_id"] == "mis_001"


# ── critique.no_issues Fan-Out ────────────────────────────


@pytest.mark.asyncio
async def test_critique_no_issues_fanout(
    role_svc: AgentRoleService, evt_svc: RoleEventService
):
    """critique.no_issues should fan out to researcher (subscribed to critique.*)."""
    researcher = await role_svc.register(AgentRoleCreate(
        name="researcher_crit",
        subscriptions=["report.*", "critique.*"],
    ))
    reviewer = await role_svc.register(AgentRoleCreate(
        name="reviewer_crit",
        subscriptions=["synthesis.created"],
    ))

    ids = await evt_svc.emit_for_subscribers(
        "critique.no_issues",
        source_entity_id="jrn_synth_002",
        source_entity_type="journal",
        source_role_id=reviewer.id,
        payload={"mission_id": "mis_002", "verdict": "approved"},
        agent_role_service=role_svc,
    )
    assert len(ids) == 1

    events = await evt_svc.list_for_role(researcher.id, status="pending")
    assert len(events) == 1
    assert events[0].event_type == "critique.no_issues"
    assert events[0].payload["verdict"] == "approved"

    # Reviewer should NOT get this event
    reviewer_events = await evt_svc.list_for_role(reviewer.id, status="pending")
    assert len(reviewer_events) == 0


# ── disagreement.detected Fan-Out ─────────────────────────


@pytest.mark.asyncio
async def test_disagreement_detected_fanout(
    role_svc: AgentRoleService, evt_svc: RoleEventService
):
    """disagreement.detected should fan out to roles subscribed to disagreement.*."""
    # In the current setup, no role subscribes to disagreement.*
    # PI notification is handled separately. Test that it doesn't fan-out unexpectedly.
    await role_svc.register(AgentRoleCreate(
        name="researcher_disagr",
        subscriptions=["report.*", "critique.*"],
    ))
    await role_svc.register(AgentRoleCreate(
        name="reviewer_disagr",
        subscriptions=["synthesis.created"],
    ))

    ids = await evt_svc.emit_for_subscribers(
        "disagreement.detected",
        source_entity_id="jrn_synth_003",
        source_entity_type="journal",
        source_role_id=None,
        payload={"mission_id": "mis_003", "issues": ["unsupported claim"], "severity": "major"},
        agent_role_service=role_svc,
    )
    # Neither researcher (critique.*) nor reviewer (synthesis.created) match disagreement.*
    assert len(ids) == 0


# ── End-to-End: Report → Synthesis → Critique → Next Mission ──


@pytest.mark.asyncio
async def test_full_sequential_review_loop(db: Database):
    """Simulate the full Phase 6 loop: report → synthesis event → critique event → next mission."""
    role_svc = AgentRoleService(db)
    evt_svc = RoleEventService(db)
    note_svc = NoteService(db, role_event_service=evt_svc, agent_role_service=role_svc)
    mis_svc = MissionService(db, role_event_service=evt_svc, agent_role_service=role_svc)

    # Setup roles
    researcher = await role_svc.register(AgentRoleCreate(
        name="researcher_e2e",
        subscriptions=["report.*", "critique.*"],
    ))
    reviewer = await role_svc.register(AgentRoleCreate(
        name="reviewer_e2e",
        subscriptions=["synthesis.created"],
    ))
    executor = await role_svc.register(AgentRoleCreate(
        name="executor_e2e",
        subscriptions=["mission.*"],
    ))

    # Step 1: Create and complete a mission (simulates executor work)
    mission = await mis_svc.create(MissionCreate(
        phase="p1",
        objective="Investigate data patterns",
        role_id=executor.id,
    ))

    # Executor submits report → report.submitted fans out to researcher
    await mis_svc.submit_report(mission.id, MissionReportCreate(
        findings=["Found pattern A", "Found pattern B"],
        recommended_next="Investigate pattern A deeper",
    ))

    # Researcher should have a report.submitted event
    researcher_events = await evt_svc.list_for_role(researcher.id, status="pending")
    report_events = [e for e in researcher_events if e.event_type == "report.submitted"]
    assert len(report_events) >= 1

    # Step 2: Researcher writes synthesis and emits synthesis.created
    synthesis = await note_svc.create(JournalEntryCreate(
        type="note",
        content="Synthesis: Patterns A and B suggest a systematic trend worth deeper investigation.",
        source="brain",
        related_mission=mission.id,
        role_id=researcher.id,
    ))

    # Emit synthesis.created via emit_for_subscribers
    synth_ids = await evt_svc.emit_for_subscribers(
        "synthesis.created",
        source_entity_id=synthesis.id,
        source_entity_type="journal",
        source_role_id=researcher.id,
        payload={"mission_id": mission.id, "summary": "Patterns A and B trend"},
        agent_role_service=role_svc,
    )
    assert len(synth_ids) == 1  # reviewer gets it

    # Reviewer should have the synthesis.created event
    reviewer_events = await evt_svc.list_for_role(reviewer.id, status="pending")
    assert any(e.event_type == "synthesis.created" for e in reviewer_events)

    # Step 3: Reviewer writes critique and emits critique.no_issues
    critique = await note_svc.create(JournalEntryCreate(
        type="note",
        content="Critique: Synthesis is well-supported. Patterns are consistent with prior findings.",
        source="brain",
        related_mission=mission.id,
        role_id=reviewer.id,
    ))

    crit_ids = await evt_svc.emit_for_subscribers(
        "critique.no_issues",
        source_entity_id=synthesis.id,
        source_entity_type="journal",
        source_role_id=reviewer.id,
        payload={"mission_id": mission.id, "critique_note_id": critique.id, "verdict": "approved"},
        agent_role_service=role_svc,
    )
    assert len(crit_ids) == 1  # researcher gets it

    # Researcher should have the critique.no_issues event
    researcher_events2 = await evt_svc.list_for_role(researcher.id, status="pending")
    assert any(e.event_type == "critique.no_issues" for e in researcher_events2)

    # Step 4: Researcher creates next mission → executor picks it up
    next_mission = await mis_svc.create(MissionCreate(
        phase="p1",
        objective="Investigate pattern A in depth",
        context="Follow-up from synthesis of mission " + mission.id,
        role_id=executor.id,
    ))

    # Executor should have a mission.created event
    executor_events = await evt_svc.list_for_role(executor.id, status="pending")
    mission_events = [e for e in executor_events if e.event_type == "mission.created"]
    assert len(mission_events) >= 2  # original + follow-up


# ── Subscription Update Validation ────────────────────────


@pytest.mark.asyncio
async def test_update_subscriptions_preserves_other_fields(role_svc: AgentRoleService):
    """Updating subscriptions should not clobber other role fields."""
    role = await role_svc.register(AgentRoleCreate(
        name="sub_update_test",
        description="Original description",
        subscriptions=["old.event"],
        model="test-model",
    ))
    updated = await role_svc.update(role.id, AgentRoleUpdate(
        subscriptions=["new.event", "another.*"],
    ))
    assert updated.subscriptions == ["new.event", "another.*"]
    assert updated.description == "Original description"
    assert updated.model == "test-model"
