"""Tests for v2.1 Phase 5: Orchestration control plane.

Covers: autonomy mode, circuit breaker, cost tracking, PI override, stuck events.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from pathlib import Path

from rka.infra.database import Database
from rka.models.agent_role import AgentRoleCreate
from rka.models.orchestration import (
    CostLogCreate,
    OrchestrationConfigUpdate,
)
from rka.services.agent_roles import AgentRoleService
from rka.services.orchestration import OrchestrationService


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
    db_path = str(tmp_path / "test_orchestration.db")
    database = Database(db_path)
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    await _ensure_project(database)
    yield database
    await database.close()


@pytest_asyncio.fixture
async def orch_svc(db: Database):
    return OrchestrationService(db, project_id="proj_default")


@pytest_asyncio.fixture
async def role_svc(db: Database):
    return AgentRoleService(db, project_id="proj_default")


# ── Migration ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_migration_creates_orchestration_tables(db: Database):
    """Migration 014 should create orchestration_config and role_cost_log tables."""
    row1 = await db.fetchone(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='orchestration_config'"
    )
    row2 = await db.fetchone(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='role_cost_log'"
    )
    assert row1 is not None, "orchestration_config table should exist"
    assert row2 is not None, "role_cost_log table should exist"


# ── Config Defaults ────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_config_creates_default(orch_svc: OrchestrationService):
    """get_config should auto-create a default config row."""
    config = await orch_svc.get_config()
    assert config.project_id == "proj_default"
    assert config.autonomy_mode == "manual"
    assert config.circuit_breaker_enabled is True
    assert config.cost_limit_usd == 10.0
    assert config.cost_window_hours == 24
    assert config.circuit_breaker_tripped is False


# ── Autonomy Mode ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_autonomy_mode(orch_svc: OrchestrationService):
    cfg = await orch_svc.set_autonomy_mode("supervised", actor="pi")
    assert cfg.autonomy_mode == "supervised"

    cfg = await orch_svc.set_autonomy_mode("paused", actor="pi")
    assert cfg.autonomy_mode == "paused"


@pytest.mark.asyncio
async def test_processing_allowed_manual(orch_svc: OrchestrationService):
    await orch_svc.set_autonomy_mode("manual")
    assert await orch_svc.is_processing_allowed() is True


@pytest.mark.asyncio
async def test_processing_not_allowed_paused(orch_svc: OrchestrationService):
    await orch_svc.set_autonomy_mode("paused")
    assert await orch_svc.is_processing_allowed() is False


# ── Circuit Breaker ────────────────────────────────────────

@pytest.mark.asyncio
async def test_circuit_breaker_not_tripped_initially(orch_svc: OrchestrationService):
    tripped = await orch_svc.check_circuit_breaker()
    assert tripped is False


@pytest.mark.asyncio
async def test_circuit_breaker_trips_on_cost_limit(
    orch_svc: OrchestrationService, role_svc: AgentRoleService
):
    # Set a very low cost limit
    await orch_svc.update_config(
        OrchestrationConfigUpdate(cost_limit_usd=0.01, cost_window_hours=24)
    )

    # Create a role for cost logging
    role = await role_svc.register(AgentRoleCreate(name="test-brain"))

    # Log cost that exceeds the limit
    await orch_svc.log_cost(CostLogCreate(
        role_id=role.id,
        input_tokens=10000,
        output_tokens=5000,
        estimated_cost_usd=0.05,
        model="test-model",
    ))

    # Check that the breaker tripped
    config = await orch_svc.get_config()
    assert config.circuit_breaker_tripped is True

    # Processing should not be allowed
    assert await orch_svc.is_processing_allowed() is False


@pytest.mark.asyncio
async def test_circuit_breaker_reset(
    orch_svc: OrchestrationService, role_svc: AgentRoleService
):
    # Trip the breaker
    await orch_svc.update_config(
        OrchestrationConfigUpdate(cost_limit_usd=0.001)
    )
    role = await role_svc.register(AgentRoleCreate(name="test-brain-2"))
    await orch_svc.log_cost(CostLogCreate(
        role_id=role.id, estimated_cost_usd=0.01
    ))
    config = await orch_svc.get_config()
    assert config.circuit_breaker_tripped is True

    # Reset
    config = await orch_svc.reset_circuit_breaker(actor="pi")
    assert config.circuit_breaker_tripped is False
    assert await orch_svc.is_processing_allowed() is True


@pytest.mark.asyncio
async def test_circuit_breaker_disabled(orch_svc: OrchestrationService):
    await orch_svc.update_config(
        OrchestrationConfigUpdate(circuit_breaker_enabled=False)
    )
    tripped = await orch_svc.check_circuit_breaker()
    assert tripped is False


# ── Cost Tracking ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_cost_and_summary(
    orch_svc: OrchestrationService, role_svc: AgentRoleService
):
    role = await role_svc.register(AgentRoleCreate(name="cost-test-role"))

    # Log a few cost entries
    await orch_svc.log_cost(CostLogCreate(
        role_id=role.id, input_tokens=1000, output_tokens=500,
        estimated_cost_usd=0.01, model="test-model", description="test entry 1"
    ))
    await orch_svc.log_cost(CostLogCreate(
        role_id=role.id, input_tokens=2000, output_tokens=1000,
        estimated_cost_usd=0.02, model="test-model", description="test entry 2"
    ))

    # Check summary
    summary = await orch_svc.get_cost_summary()
    assert summary.total_input_tokens == 3000
    assert summary.total_output_tokens == 1500
    assert abs(summary.total_cost_usd - 0.03) < 0.001
    assert summary.entry_count == 2


@pytest.mark.asyncio
async def test_cost_by_role(
    orch_svc: OrchestrationService, role_svc: AgentRoleService
):
    role1 = await role_svc.register(AgentRoleCreate(name="role-a"))
    role2 = await role_svc.register(AgentRoleCreate(name="role-b"))

    await orch_svc.log_cost(CostLogCreate(
        role_id=role1.id, estimated_cost_usd=0.01
    ))
    await orch_svc.log_cost(CostLogCreate(
        role_id=role2.id, estimated_cost_usd=0.02
    ))

    by_role = await orch_svc.get_cost_by_role()
    assert len(by_role) == 2
    # Sorted by cost desc
    assert by_role[0].role_name == "role-b"
    assert abs(by_role[0].total_cost_usd - 0.02) < 0.001


# ── PI Override ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pi_override_to_specific_role(
    orch_svc: OrchestrationService, role_svc: AgentRoleService
):
    role = await role_svc.register(AgentRoleCreate(name="target-role"))

    result = await orch_svc.pi_override(
        directive="Stop current work and focus on analysis",
        target_role_name="target-role",
    )
    assert result["status"] == "override_sent"
    assert result["events_created"] == 1
    assert "target-role" in result["targets"]


@pytest.mark.asyncio
async def test_pi_override_broadcast(
    orch_svc: OrchestrationService, role_svc: AgentRoleService
):
    await role_svc.register(AgentRoleCreate(name="brain-1"))
    await role_svc.register(AgentRoleCreate(name="executor-1"))

    result = await orch_svc.pi_override(
        directive="All agents halt — merge freeze in effect",
    )
    assert result["status"] == "override_sent"
    assert result["events_created"] == 2


@pytest.mark.asyncio
async def test_pi_override_with_halt(
    orch_svc: OrchestrationService, role_svc: AgentRoleService, db: Database
):
    from rka.services.role_events import RoleEventService
    from rka.models.role_event import RoleEventCreate

    role = await role_svc.register(AgentRoleCreate(
        name="halt-target", subscriptions=["journal.*"]
    ))
    event_svc = RoleEventService(db, project_id="proj_default")

    # Create a pending event
    await event_svc.emit(RoleEventCreate(
        target_role_id=role.id,
        event_type="journal.created",
        payload={"test": True},
    ))

    # Override with halt
    result = await orch_svc.pi_override(
        directive="Emergency halt",
        target_role_name="halt-target",
        halt_current=True,
    )
    assert result["events_created"] == 1

    # The pending event should be expired, only the override should be pending
    events = await event_svc.list_for_role(role.id, status="pending")
    assert len(events) == 1
    assert events[0].event_type == "pi.override"
    assert events[0].priority == 999


@pytest.mark.asyncio
async def test_pi_override_no_targets(orch_svc: OrchestrationService):
    result = await orch_svc.pi_override(
        directive="Hello",
        target_role_name="nonexistent-role",
    )
    assert result["status"] == "no_targets"


# ── Stuck Events ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_stuck_events_initially_empty(orch_svc: OrchestrationService):
    stuck = await orch_svc.get_stuck_events()
    assert stuck == []


@pytest.mark.asyncio
async def test_retry_stuck_event_not_found(orch_svc: OrchestrationService):
    result = await orch_svc.retry_stuck_event("nonexistent")
    assert result["status"] == "not_found"


# ── Full Status ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_status(
    orch_svc: OrchestrationService, role_svc: AgentRoleService
):
    await role_svc.register(AgentRoleCreate(name="status-test-role"))

    status = await orch_svc.get_status()
    assert status.config.autonomy_mode == "manual"
    assert len(status.roles) >= 1
    assert status.cost_summary.entry_count == 0
    assert isinstance(status.stuck_events, list)
    assert isinstance(status.recent_overrides, list)


# ── Config Update ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_config_multiple_fields(orch_svc: OrchestrationService):
    config = await orch_svc.update_config(
        OrchestrationConfigUpdate(
            autonomy_mode="autonomous",
            cost_limit_usd=50.0,
            cost_window_hours=48,
        ),
        actor="pi",
    )
    assert config.autonomy_mode == "autonomous"
    assert config.cost_limit_usd == 50.0
    assert config.cost_window_hours == 48
    assert config.updated_by == "pi"
