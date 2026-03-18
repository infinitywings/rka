"""Role event queue service."""

from __future__ import annotations

import json
import logging

from rka.infra.ids import generate_id
from rka.models.role_event import RoleEvent, RoleEventCreate
from rka.services.base import BaseService, _now

logger = logging.getLogger(__name__)


class RoleEventService(BaseService):
    """Manages durable role-targeted event inboxes."""

    async def emit(self, data: RoleEventCreate) -> RoleEvent:
        """Emit a role event into a target role's inbox."""
        event_id = generate_id("role_event")
        await self.db.execute(
            """INSERT INTO role_events
               (id, project_id, target_role_id, event_type, source_role_id,
                source_entity_id, source_entity_type, payload, status,
                priority, depends_on)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            [
                event_id, self.project_id, data.target_role_id,
                data.event_type, data.source_role_id,
                data.source_entity_id, data.source_entity_type,
                self._json_dumps(data.payload),
                data.priority, data.depends_on,
            ],
        )
        await self.db.commit()
        return await self.get(event_id)  # type: ignore[return-value]

    async def emit_for_subscribers(
        self,
        event_type: str,
        *,
        source_entity_id: str | None = None,
        source_entity_type: str | None = None,
        source_role_id: str | None = None,
        payload: dict | None = None,
        priority: int = 100,
        agent_role_service: "AgentRoleService | None" = None,
    ) -> list[str]:
        """Fan-out: emit to all roles whose subscriptions match event_type.

        Returns list of created role_event IDs.
        """
        if agent_role_service is None:
            return []
        matched = await agent_role_service.match_subscriptions(event_type)
        created_ids: list[str] = []
        for role in matched:
            evt = await self.emit(RoleEventCreate(
                target_role_id=role.id,
                event_type=event_type,
                source_role_id=source_role_id,
                source_entity_id=source_entity_id,
                source_entity_type=source_entity_type,
                payload=payload,
                priority=priority,
            ))
            created_ids.append(evt.id)
        return created_ids

    async def get(self, event_id: str) -> RoleEvent | None:
        """Get a role event by ID."""
        row = await self.db.fetchone(
            "SELECT * FROM role_events WHERE id = ? AND project_id = ?",
            [event_id, self.project_id],
        )
        if not row:
            return None
        return self._row_to_model(row)

    async def list_for_role(
        self,
        role_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RoleEvent]:
        """List events for a specific role, optionally filtered by status."""
        conditions = ["project_id = ?", "target_role_id = ?"]
        params: list = [self.project_id, role_id]
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = " AND ".join(conditions)
        params.extend([limit, offset])
        rows = await self.db.fetchall(
            f"SELECT * FROM role_events WHERE {where} ORDER BY priority DESC, created_at ASC LIMIT ? OFFSET ?",
            params,
        )
        return [self._row_to_model(r) for r in rows]

    async def mark_processing(self, event_id: str) -> RoleEvent | None:
        """Mark an event as being processed."""
        now = _now()
        await self.db.execute(
            "UPDATE role_events SET status = 'processing', processed_at = ? WHERE id = ? AND project_id = ? AND status = 'pending'",
            [now, event_id, self.project_id],
        )
        await self.db.commit()
        return await self.get(event_id)

    async def ack(self, event_id: str) -> RoleEvent | None:
        """Acknowledge a role event (mark as consumed)."""
        now = _now()
        await self.db.execute(
            "UPDATE role_events SET status = 'acked', acked_at = ? WHERE id = ? AND project_id = ? AND status IN ('pending', 'processing')",
            [now, event_id, self.project_id],
        )
        await self.db.commit()
        return await self.get(event_id)

    async def expire_stale(self, *, older_than_hours: int = 72) -> int:
        """Expire pending events older than the given threshold."""
        cutoff = _now()  # simplified — real cutoff uses timedelta
        # Use SQLite datetime arithmetic
        result = await self.db.execute(
            """UPDATE role_events
               SET status = 'expired'
               WHERE project_id = ? AND status = 'pending'
                 AND created_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ? || ' hours')""",
            [self.project_id, f"-{older_than_hours}"],
        )
        await self.db.commit()
        return result.rowcount if hasattr(result, "rowcount") else 0

    def _row_to_model(self, row) -> RoleEvent:
        """Convert a DB row to a RoleEvent model."""
        d = dict(row)
        d["payload"] = self._json_loads(d.get("payload"))
        return RoleEvent(**d)


# Import for type checking only
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rka.services.agent_roles import AgentRoleService
