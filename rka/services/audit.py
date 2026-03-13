"""Audit log service."""

from __future__ import annotations

from rka.models.audit import AuditEntry
from rka.services.base import BaseService


class AuditService(BaseService):
    """Query the audit log."""

    async def list(
        self,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        actor: str | None = None,
        since: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEntry]:
        """List audit log entries with filters."""
        conditions = ["project_id = ?"]
        params: list = [self.project_id]

        if action:
            conditions.append("action = ?")
            params.append(action)
        if entity_type:
            conditions.append("entity_type = ?")
            params.append(entity_type)
        if entity_id:
            conditions.append("entity_id = ?")
            params.append(entity_id)
        if actor:
            conditions.append("actor = ?")
            params.append(actor)
        if since:
            conditions.append("created_at >= ?")
            params.append(since)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        rows = await self.db.fetchall(
            f"SELECT * FROM audit_log WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [self._row_to_model(row) for row in rows]

    async def count(self) -> dict[str, int]:
        """Get counts by action type."""
        rows = await self.db.fetchall(
            "SELECT action, COUNT(*) as cnt FROM audit_log WHERE project_id = ? GROUP BY action ORDER BY cnt DESC",
            [self.project_id],
        )
        return {row["action"]: row["cnt"] for row in rows}

    def _row_to_model(self, row: dict) -> AuditEntry:
        return AuditEntry(
            id=row["id"],
            action=row["action"],
            entity_type=row["entity_type"],
            entity_id=row.get("entity_id"),
            actor=row.get("actor"),
            details=self._json_loads(row.get("details")),
            created_at=row.get("created_at"),
        )
