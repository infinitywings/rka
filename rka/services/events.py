"""Event stream service."""

from __future__ import annotations

from rka.models.event import Event
from rka.services.base import BaseService


class EventService(BaseService):
    """Query the event stream for timeline and graph visualization."""

    async def list(
        self,
        phase: str | None = None,
        event_type: str | None = None,
        entity_type: str | None = None,
        actor: str | None = None,
        since: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Event]:
        """List events with filters."""
        conditions = []
        params = [self.project_id]

        conditions.append("project_id = ?")

        if phase:
            conditions.append("phase = ?")
            params.append(phase)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if entity_type:
            conditions.append("entity_type = ?")
            params.append(entity_type)
        if actor:
            conditions.append("actor = ?")
            params.append(actor)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        rows = await self.db.fetchall(
            f"SELECT * FROM events WHERE {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params,
        )
        return [self._row_to_model(row) for row in rows]

    def _row_to_model(self, row: dict) -> Event:
        return Event(
            id=row["id"],
            timestamp=row.get("timestamp"),
            event_type=row["event_type"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            actor=row["actor"],
            summary=row["summary"],
            caused_by_event=row.get("caused_by_event"),
            caused_by_entity=row.get("caused_by_entity"),
            phase=row.get("phase"),
            details=self._json_loads(row.get("details")),
        )
