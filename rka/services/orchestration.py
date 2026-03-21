"""Orchestration control plane service.

Manages autonomy modes, circuit breaker, cost tracking, PI overrides,
and stuck-event detection for the v2.1 orchestration layer.
"""

from __future__ import annotations

import logging

from rka.infra.database import Database
from rka.models.orchestration import (
    AutonomyMode,
    CostLogCreate,
    CostLogEntry,
    CostSummary,
    OrchestrationConfig,
    OrchestrationConfigUpdate,
    OrchestrationStatus,
    RoleCostSummary,
)
from rka.services.base import _now

logger = logging.getLogger(__name__)


class OrchestrationService:
    """Orchestration control plane for a single project."""

    def __init__(self, db: Database, project_id: str):
        self.db = db
        self.project_id = project_id

    # ── Config Management ──────────────────────────────────────

    async def get_config(self) -> OrchestrationConfig:
        """Get or create the orchestration config for this project."""
        row = await self.db.fetchone(
            "SELECT * FROM orchestration_config WHERE project_id = ?",
            [self.project_id],
        )
        if row:
            d = dict(row)
            d["circuit_breaker_enabled"] = bool(d.get("circuit_breaker_enabled", 1))
            d["circuit_breaker_tripped"] = bool(d.get("circuit_breaker_tripped", 0))
            return OrchestrationConfig(**d)

        # Auto-create default config
        now = _now()
        await self.db.execute(
            """INSERT OR IGNORE INTO orchestration_config (project_id, updated_at)
               VALUES (?, ?)""",
            [self.project_id, now],
        )
        await self.db.commit()
        return OrchestrationConfig(project_id=self.project_id, updated_at=now)

    async def update_config(
        self, data: OrchestrationConfigUpdate, actor: str = "pi"
    ) -> OrchestrationConfig:
        """Update orchestration config fields."""
        # Ensure row exists
        await self.get_config()

        updates: dict = {}
        if data.autonomy_mode is not None:
            updates["autonomy_mode"] = data.autonomy_mode
        if data.circuit_breaker_enabled is not None:
            updates["circuit_breaker_enabled"] = int(data.circuit_breaker_enabled)
        if data.cost_limit_usd is not None:
            updates["cost_limit_usd"] = data.cost_limit_usd
        if data.cost_window_hours is not None:
            updates["cost_window_hours"] = data.cost_window_hours

        if updates:
            updates["updated_at"] = _now()
            updates["updated_by"] = actor
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [self.project_id]
            await self.db.execute(
                f"UPDATE orchestration_config SET {set_clause} WHERE project_id = ?",
                values,
            )
            await self.db.commit()

        return await self.get_config()

    # ── Autonomy Mode ──────────────────────────────────────────

    async def get_autonomy_mode(self) -> AutonomyMode:
        config = await self.get_config()
        return config.autonomy_mode

    async def set_autonomy_mode(
        self, mode: AutonomyMode, actor: str = "pi"
    ) -> OrchestrationConfig:
        return await self.update_config(
            OrchestrationConfigUpdate(autonomy_mode=mode), actor=actor
        )

    async def is_processing_allowed(self) -> bool:
        """Check if event processing is allowed given current mode and circuit breaker."""
        config = await self.get_config()
        if config.autonomy_mode == "paused":
            return False
        if config.circuit_breaker_tripped:
            return False
        return True

    # ── Circuit Breaker ────────────────────────────────────────

    async def check_circuit_breaker(self) -> bool:
        """Check if the circuit breaker should trip. Returns True if tripped."""
        config = await self.get_config()
        if not config.circuit_breaker_enabled:
            return False
        if config.circuit_breaker_tripped:
            return True

        # Check cost in the window
        summary = await self.get_cost_summary(window_hours=config.cost_window_hours)
        if summary.total_cost_usd >= config.cost_limit_usd:
            await self._trip_circuit_breaker()
            return True
        return False

    async def _trip_circuit_breaker(self) -> None:
        """Trip the circuit breaker."""
        now = _now()
        await self.db.execute(
            """UPDATE orchestration_config
               SET circuit_breaker_tripped = 1, circuit_breaker_tripped_at = ?, updated_at = ?
               WHERE project_id = ?""",
            [now, now, self.project_id],
        )
        await self.db.commit()
        logger.warning("Circuit breaker TRIPPED for project %s", self.project_id)

    async def reset_circuit_breaker(self, actor: str = "pi") -> OrchestrationConfig:
        """Reset a tripped circuit breaker (PI action)."""
        now = _now()
        await self.db.execute(
            """UPDATE orchestration_config
               SET circuit_breaker_tripped = 0, circuit_breaker_tripped_at = NULL,
                   updated_at = ?, updated_by = ?
               WHERE project_id = ?""",
            [now, actor, self.project_id],
        )
        await self.db.commit()
        logger.info("Circuit breaker reset by %s for project %s", actor, self.project_id)
        return await self.get_config()

    # ── Cost Tracking ──────────────────────────────────────────

    async def log_cost(self, data: CostLogCreate) -> CostLogEntry:
        """Record a cost log entry and check circuit breaker."""
        await self.db.execute(
            """INSERT INTO role_cost_log
               (project_id, role_id, mission_id, input_tokens, output_tokens,
                model, estimated_cost_usd, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                self.project_id, data.role_id, data.mission_id,
                data.input_tokens, data.output_tokens,
                data.model, data.estimated_cost_usd, data.description,
            ],
        )
        await self.db.commit()

        # Auto-check circuit breaker after each cost entry
        await self.check_circuit_breaker()

        row = await self.db.fetchone(
            "SELECT * FROM role_cost_log WHERE project_id = ? ORDER BY id DESC LIMIT 1",
            [self.project_id],
        )
        return CostLogEntry(**dict(row)) if row else CostLogEntry(
            project_id=self.project_id, role_id=data.role_id
        )

    async def get_cost_summary(
        self, *, window_hours: int | None = None
    ) -> CostSummary:
        """Get aggregated cost summary, optionally within a time window."""
        if window_hours:
            row = await self.db.fetchone(
                """SELECT
                     COALESCE(SUM(input_tokens), 0) as total_input,
                     COALESCE(SUM(output_tokens), 0) as total_output,
                     COALESCE(SUM(estimated_cost_usd), 0.0) as total_cost,
                     COUNT(*) as cnt
                   FROM role_cost_log
                   WHERE project_id = ?
                     AND created_at > strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours')""",
                [self.project_id, f"-{window_hours}"],
            )
        else:
            row = await self.db.fetchone(
                """SELECT
                     COALESCE(SUM(input_tokens), 0) as total_input,
                     COALESCE(SUM(output_tokens), 0) as total_output,
                     COALESCE(SUM(estimated_cost_usd), 0.0) as total_cost,
                     COUNT(*) as cnt
                   FROM role_cost_log
                   WHERE project_id = ?""",
                [self.project_id],
            )

        if row:
            d = dict(row)
            return CostSummary(
                total_input_tokens=d["total_input"],
                total_output_tokens=d["total_output"],
                total_cost_usd=d["total_cost"],
                entry_count=d["cnt"],
                window_hours=window_hours,
            )
        return CostSummary(window_hours=window_hours)

    async def get_cost_by_role(
        self, *, window_hours: int | None = None
    ) -> list[RoleCostSummary]:
        """Get cost breakdown per role."""
        if window_hours:
            rows = await self.db.fetchall(
                """SELECT
                     rcl.role_id,
                     ar.name as role_name,
                     COALESCE(SUM(rcl.input_tokens), 0) as total_input,
                     COALESCE(SUM(rcl.output_tokens), 0) as total_output,
                     COALESCE(SUM(rcl.estimated_cost_usd), 0.0) as total_cost,
                     COUNT(*) as cnt
                   FROM role_cost_log rcl
                   LEFT JOIN agent_roles ar ON ar.id = rcl.role_id
                   WHERE rcl.project_id = ?
                     AND rcl.created_at > strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours')
                   GROUP BY rcl.role_id
                   ORDER BY total_cost DESC""",
                [self.project_id, f"-{window_hours}"],
            )
        else:
            rows = await self.db.fetchall(
                """SELECT
                     rcl.role_id,
                     ar.name as role_name,
                     COALESCE(SUM(rcl.input_tokens), 0) as total_input,
                     COALESCE(SUM(rcl.output_tokens), 0) as total_output,
                     COALESCE(SUM(rcl.estimated_cost_usd), 0.0) as total_cost,
                     COUNT(*) as cnt
                   FROM role_cost_log rcl
                   LEFT JOIN agent_roles ar ON ar.id = rcl.role_id
                   WHERE rcl.project_id = ?
                   GROUP BY rcl.role_id
                   ORDER BY total_cost DESC""",
                [self.project_id],
            )

        return [
            RoleCostSummary(
                role_id=dict(r)["role_id"],
                role_name=dict(r).get("role_name"),
                total_input_tokens=dict(r)["total_input"],
                total_output_tokens=dict(r)["total_output"],
                total_cost_usd=dict(r)["total_cost"],
                entry_count=dict(r)["cnt"],
            )
            for r in rows
        ]

    # ── PI Override ────────────────────────────────────────────

    async def pi_override(
        self,
        directive: str,
        *,
        target_role_id: str | None = None,
        target_role_name: str | None = None,
        halt_current: bool = False,
    ) -> dict:
        """Inject a PI override directive as a high-priority event.

        If target_role_id or target_role_name is given, the directive goes to
        that role. Otherwise it's broadcast to all roles.
        """
        from rka.services.agent_roles import AgentRoleService
        from rka.services.role_events import RoleEventService

        role_svc = AgentRoleService(self.db, project_id=self.project_id)
        event_svc = RoleEventService(self.db, project_id=self.project_id)

        # Resolve target
        target_roles = []
        if target_role_id:
            role = await role_svc.get(target_role_id)
            if role:
                target_roles = [role]
        elif target_role_name:
            role = await role_svc.get_by_name(target_role_name)
            if role:
                target_roles = [role]
        else:
            target_roles = await role_svc.list(limit=200)

        if not target_roles:
            return {"status": "no_targets", "events_created": 0}

        created_ids = []
        for role in target_roles:
            from rka.models.role_event import RoleEventCreate

            evt = await event_svc.emit(RoleEventCreate(
                target_role_id=role.id,
                event_type="pi.override",
                payload={
                    "directive": directive,
                    "halt_current": halt_current,
                    "override_by": "pi",
                },
                priority=999,  # Maximum priority
            ))
            created_ids.append(evt.id)

            if halt_current:
                # Expire any pending/processing events for this role
                await self.db.execute(
                    """UPDATE role_events
                       SET status = 'expired'
                       WHERE target_role_id = ? AND project_id = ?
                         AND status IN ('pending', 'processing')
                         AND id != ?""",
                    [role.id, self.project_id, evt.id],
                )
                await self.db.commit()

        return {
            "status": "override_sent",
            "events_created": len(created_ids),
            "event_ids": created_ids,
            "targets": [r.name for r in target_roles],
        }

    # ── Stuck Event Detection ──────────────────────────────────

    async def get_stuck_events(
        self, *, processing_timeout_hours: int = 2, pending_timeout_hours: int = 24
    ) -> list[dict]:
        """Find events that appear stuck (processing too long or pending too long)."""
        rows = await self.db.fetchall(
            """SELECT re.*, ar.name as role_name
               FROM role_events re
               LEFT JOIN agent_roles ar ON ar.id = re.target_role_id
               WHERE re.project_id = ?
                 AND (
                   (re.status = 'processing'
                    AND re.processed_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours'))
                   OR
                   (re.status = 'pending'
                    AND re.created_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours'))
                 )
               ORDER BY re.created_at ASC
               LIMIT 50""",
            [self.project_id, f"-{processing_timeout_hours}", f"-{pending_timeout_hours}"],
        )
        return [dict(r) for r in rows]

    async def retry_stuck_event(self, event_id: str) -> dict:
        """Reset a stuck event back to pending status."""
        row = await self.db.fetchone(
            "SELECT * FROM role_events WHERE id = ? AND project_id = ?",
            [event_id, self.project_id],
        )
        if not row:
            return {"status": "not_found"}

        await self.db.execute(
            """UPDATE role_events
               SET status = 'pending', processed_at = NULL
               WHERE id = ? AND project_id = ?
                 AND status IN ('processing', 'expired')""",
            [event_id, self.project_id],
        )
        await self.db.commit()
        return {"status": "retried", "event_id": event_id}

    # ── Full Status ────────────────────────────────────────────

    async def get_status(self) -> OrchestrationStatus:
        """Get full orchestration status for the dashboard."""
        from rka.services.agent_roles import AgentRoleService

        config = await self.get_config()
        role_svc = AgentRoleService(self.db, project_id=self.project_id)

        # Roles with event queue depth
        roles = await role_svc.list(limit=200)
        role_data = []
        for role in roles:
            pending_row = await self.db.fetchone(
                """SELECT COUNT(*) as cnt FROM role_events
                   WHERE target_role_id = ? AND project_id = ? AND status = 'pending'""",
                [role.id, self.project_id],
            )
            processing_row = await self.db.fetchone(
                """SELECT COUNT(*) as cnt FROM role_events
                   WHERE target_role_id = ? AND project_id = ? AND status = 'processing'""",
                [role.id, self.project_id],
            )
            role_data.append({
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "model": role.model,
                "model_tier": role.model_tier,
                "subscriptions": role.subscriptions,
                "last_active_at": role.last_active_at,
                "active_session_id": role.active_session_id,
                "pending_events": dict(pending_row)["cnt"] if pending_row else 0,
                "processing_events": dict(processing_row)["cnt"] if processing_row else 0,
                "autonomy_profile": role.autonomy_profile,
            })

        cost_summary = await self.get_cost_summary(
            window_hours=config.cost_window_hours
        )
        cost_by_role = await self.get_cost_by_role(
            window_hours=config.cost_window_hours
        )
        stuck_events = await self.get_stuck_events()

        # Recent overrides
        override_rows = await self.db.fetchall(
            """SELECT re.*, ar.name as target_role_name
               FROM role_events re
               LEFT JOIN agent_roles ar ON ar.id = re.target_role_id
               WHERE re.project_id = ? AND re.event_type = 'pi.override'
               ORDER BY re.created_at DESC LIMIT 10""",
            [self.project_id],
        )
        recent_overrides = [dict(r) for r in override_rows]

        return OrchestrationStatus(
            config=config,
            roles=role_data,
            cost_summary=cost_summary,
            cost_by_role=cost_by_role,
            stuck_events=stuck_events,
            recent_overrides=recent_overrides,
        )
