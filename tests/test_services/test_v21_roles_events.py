"""Tests for v2.1 Phase 1: role registry, role events, subscription matching, fan-out."""

from __future__ import annotations

import pytest
import pytest_asyncio
from pathlib import Path

from rka.infra.database import Database
from rka.models.agent_role import AgentRoleCreate, AgentRoleUpdate, AgentRoleStateUpdate
from rka.models.role_event import RoleEventCreate
from rka.models.journal import JournalEntryCreate
from rka.models.mission import MissionCreate
from rka.models.checkpoint import CheckpointCreate
from rka.models.decision import DecisionCreate
from rka.services.agent_roles import AgentRoleService
from rka.services.role_events import RoleEventService
from rka.services.notes import NoteService
from rka.services.missions import MissionService
from rka.services.checkpoints import CheckpointService
from rka.services.decisions import DecisionService


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
    db_path = str(tmp_path / "test_v21_roles.db")
    database = Database(db_path)
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    await _ensure_project(database)
    yield database
    await database.close()


# ---- Migration correctness ----

@pytest.mark.asyncio
async def test_migration_creates_agent_roles_table(db: Database):
    """Migration 013 should create agent_roles table."""
    row = await db.fetchone(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_roles'"
    )
    assert row is not None


@pytest.mark.asyncio
async def test_migration_creates_role_events_table(db: Database):
    """Migration 013 should create role_events table."""
    row = await db.fetchone(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='role_events'"
    )
    assert row is not None


@pytest.mark.asyncio
async def test_migration_idempotent(db: Database):
    """Running migrations again should not fail."""
    count = await db.run_migrations()
    assert count == 0  # Already applied


# ---- Role registration ----

@pytest.mark.asyncio
async def test_register_role(db: Database):
    svc = AgentRoleService(db)
    role = await svc.register(AgentRoleCreate(
        name="researcher_brain",
        description="Deep research agent",
        subscriptions=["report.*", "checkpoint.created.*"],
        model="claude-sonnet-4-5-20250514",
        model_tier="standard",
    ))
    assert role.id.startswith("arl_")
    assert role.name == "researcher_brain"
    assert role.subscriptions == ["report.*", "checkpoint.created.*"]
    assert role.model == "claude-sonnet-4-5-20250514"
    assert role.model_tier == "standard"


@pytest.mark.asyncio
async def test_register_role_unique_constraint(db: Database):
    """Duplicate (project_id, name) should fail."""
    svc = AgentRoleService(db)
    await svc.register(AgentRoleCreate(name="unique_role"))
    with pytest.raises(Exception):  # IntegrityError
        await svc.register(AgentRoleCreate(name="unique_role"))


# ---- Role listing ----

@pytest.mark.asyncio
async def test_list_roles(db: Database):
    svc = AgentRoleService(db)
    await svc.register(AgentRoleCreate(name="role_a"))
    await svc.register(AgentRoleCreate(name="role_b"))
    roles = await svc.list()
    assert len(roles) >= 2
    names = {r.name for r in roles}
    assert "role_a" in names
    assert "role_b" in names


# ---- Role update ----

@pytest.mark.asyncio
async def test_update_role(db: Database):
    svc = AgentRoleService(db)
    role = await svc.register(AgentRoleCreate(name="updatable"))
    updated = await svc.update(role.id, AgentRoleUpdate(
        description="Updated description",
        subscriptions=["note.created"],
    ))
    assert updated.description == "Updated description"
    assert updated.subscriptions == ["note.created"]


# ---- Role bind ----

@pytest.mark.asyncio
async def test_bind_role(db: Database):
    svc = AgentRoleService(db)
    role = await svc.register(AgentRoleCreate(name="bindable"))
    bound = await svc.bind(role.id, "session_abc123")
    assert bound.active_session_id == "session_abc123"
    assert bound.last_active_at is not None


# ---- Role state ----

@pytest.mark.asyncio
async def test_save_role_state(db: Database):
    svc = AgentRoleService(db)
    role = await svc.register(AgentRoleCreate(name="stateful"))
    updated = await svc.save_state(role.id, {"focus": "literature review", "progress": 0.5})
    assert updated.role_state == {"focus": "literature review", "progress": 0.5}


# ---- Subscription matching ----

@pytest.mark.asyncio
async def test_match_subscriptions_glob(db: Database):
    svc = AgentRoleService(db)
    await svc.register(AgentRoleCreate(
        name="report_watcher",
        subscriptions=["report.*"],
    ))
    await svc.register(AgentRoleCreate(
        name="checkpoint_watcher",
        subscriptions=["checkpoint.*"],
    ))
    await svc.register(AgentRoleCreate(
        name="all_watcher",
        subscriptions=["*"],
    ))

    matched = await svc.match_subscriptions("report.submitted")
    names = {r.name for r in matched}
    assert "report_watcher" in names
    assert "all_watcher" in names
    assert "checkpoint_watcher" not in names


@pytest.mark.asyncio
async def test_match_subscriptions_no_match(db: Database):
    svc = AgentRoleService(db)
    await svc.register(AgentRoleCreate(
        name="narrow_watcher",
        subscriptions=["very.specific.event"],
    ))
    matched = await svc.match_subscriptions("note.created")
    assert len(matched) == 0


# ---- Role event emit ----

@pytest.mark.asyncio
async def test_emit_role_event(db: Database):
    role_svc = AgentRoleService(db)
    role = await role_svc.register(AgentRoleCreate(name="target_role"))

    evt_svc = RoleEventService(db)
    event = await evt_svc.emit(RoleEventCreate(
        target_role_id=role.id,
        event_type="note.created",
        source_entity_id="jrn_test123",
        source_entity_type="journal",
        payload={"summary": "Test note"},
    ))
    assert event.id.startswith("rve_")
    assert event.status == "pending"
    assert event.event_type == "note.created"
    assert event.payload == {"summary": "Test note"}


# ---- Role event list for role ----

@pytest.mark.asyncio
async def test_list_events_for_role(db: Database):
    role_svc = AgentRoleService(db)
    role = await role_svc.register(AgentRoleCreate(name="inbox_role"))

    evt_svc = RoleEventService(db)
    await evt_svc.emit(RoleEventCreate(target_role_id=role.id, event_type="a"))
    await evt_svc.emit(RoleEventCreate(target_role_id=role.id, event_type="b"))

    events = await evt_svc.list_for_role(role.id)
    assert len(events) == 2


@pytest.mark.asyncio
async def test_list_events_filter_by_status(db: Database):
    role_svc = AgentRoleService(db)
    role = await role_svc.register(AgentRoleCreate(name="filter_role"))

    evt_svc = RoleEventService(db)
    evt = await evt_svc.emit(RoleEventCreate(target_role_id=role.id, event_type="x"))
    await evt_svc.ack(evt.id)

    pending = await evt_svc.list_for_role(role.id, status="pending")
    assert len(pending) == 0
    acked = await evt_svc.list_for_role(role.id, status="acked")
    assert len(acked) == 1


# ---- Event acknowledge ----

@pytest.mark.asyncio
async def test_ack_event(db: Database):
    role_svc = AgentRoleService(db)
    role = await role_svc.register(AgentRoleCreate(name="ack_role"))

    evt_svc = RoleEventService(db)
    event = await evt_svc.emit(RoleEventCreate(target_role_id=role.id, event_type="test"))
    acked = await evt_svc.ack(event.id)
    assert acked.status == "acked"
    assert acked.acked_at is not None


# ---- Event mark processing ----

@pytest.mark.asyncio
async def test_mark_processing(db: Database):
    role_svc = AgentRoleService(db)
    role = await role_svc.register(AgentRoleCreate(name="proc_role"))

    evt_svc = RoleEventService(db)
    event = await evt_svc.emit(RoleEventCreate(target_role_id=role.id, event_type="test"))
    processing = await evt_svc.mark_processing(event.id)
    assert processing.status == "processing"
    assert processing.processed_at is not None


# ---- Fan-out: emit_for_subscribers ----

@pytest.mark.asyncio
async def test_emit_for_subscribers(db: Database):
    role_svc = AgentRoleService(db)
    await role_svc.register(AgentRoleCreate(name="sub_a", subscriptions=["note.*"]))
    await role_svc.register(AgentRoleCreate(name="sub_b", subscriptions=["note.created"]))
    await role_svc.register(AgentRoleCreate(name="sub_c", subscriptions=["mission.*"]))

    evt_svc = RoleEventService(db)
    ids = await evt_svc.emit_for_subscribers(
        "note.created",
        source_entity_id="jrn_123",
        source_entity_type="journal",
        payload={"test": True},
        agent_role_service=role_svc,
    )
    assert len(ids) == 2  # sub_a and sub_b match, sub_c does not


# ---- Post-write hook integration ----

@pytest.mark.asyncio
async def test_note_create_fans_out_role_event(db: Database):
    """Creating a note should fan out role events to subscribers of 'note.created'."""
    role_svc = AgentRoleService(db)
    await role_svc.register(AgentRoleCreate(name="note_watcher", subscriptions=["note.*"]))

    evt_svc = RoleEventService(db)
    note_svc = NoteService(db, role_event_service=evt_svc, agent_role_service=role_svc)

    entry = await note_svc.create(JournalEntryCreate(content="Test content", source="brain"))
    events = await evt_svc.list_for_role(
        (await role_svc.get_by_name("note_watcher")).id,
        status="pending",
    )
    assert len(events) >= 1
    assert events[0].event_type == "note.created"


@pytest.mark.asyncio
async def test_mission_create_fans_out_role_event(db: Database):
    role_svc = AgentRoleService(db)
    await role_svc.register(AgentRoleCreate(name="mission_watcher", subscriptions=["mission.*"]))

    evt_svc = RoleEventService(db)
    msvc = MissionService(db, role_event_service=evt_svc, agent_role_service=role_svc)

    await msvc.create(MissionCreate(phase="p1", objective="Test mission"))
    events = await evt_svc.list_for_role(
        (await role_svc.get_by_name("mission_watcher")).id,
    )
    assert any(e.event_type == "mission.created" for e in events)


@pytest.mark.asyncio
async def test_decision_create_fans_out_role_event(db: Database):
    role_svc = AgentRoleService(db)
    await role_svc.register(AgentRoleCreate(name="decision_watcher", subscriptions=["decision.*"]))

    evt_svc = RoleEventService(db)
    dsvc = DecisionService(db, role_event_service=evt_svc, agent_role_service=role_svc)

    await dsvc.create(DecisionCreate(question="Q?", phase="p1", decided_by="brain"))
    events = await evt_svc.list_for_role(
        (await role_svc.get_by_name("decision_watcher")).id,
    )
    assert any(e.event_type == "decision.created" for e in events)


@pytest.mark.asyncio
async def test_checkpoint_create_fans_out_role_event(db: Database):
    role_svc = AgentRoleService(db)
    await role_svc.register(AgentRoleCreate(name="chk_watcher", subscriptions=["checkpoint.*"]))

    evt_svc = RoleEventService(db)
    msvc = MissionService(db)
    mission = await msvc.create(MissionCreate(phase="p1", objective="For checkpoint"))

    csvc = CheckpointService(db, role_event_service=evt_svc, agent_role_service=role_svc)
    await csvc.create(CheckpointCreate(
        mission_id=mission.id, type="decision", description="Need help",
    ))

    events = await evt_svc.list_for_role(
        (await role_svc.get_by_name("chk_watcher")).id,
    )
    assert any(e.event_type == "checkpoint.created" for e in events)


# ---- Optional injection compatibility ----

@pytest.mark.asyncio
async def test_note_create_without_role_services(db: Database):
    """Services should work fine without role_event_service injected."""
    svc = NoteService(db)
    entry = await svc.create(JournalEntryCreate(content="No fan-out", source="executor"))
    assert entry.id.startswith("jrn_")


@pytest.mark.asyncio
async def test_mission_create_without_role_services(db: Database):
    svc = MissionService(db)
    mission = await svc.create(MissionCreate(phase="p1", objective="No fan-out"))
    assert mission.id.startswith("mis_")
