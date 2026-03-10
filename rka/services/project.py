"""Project state service."""

from __future__ import annotations

import json

from rka.models.project import ProjectState, ProjectStateUpdate
from rka.services.base import BaseService, _now


class ProjectService(BaseService):
    """Manages the singleton project state."""

    async def get(self) -> ProjectState | None:
        """Get current project state."""
        row = await self.db.fetchone("SELECT * FROM project_state WHERE id = 1")
        if row is None:
            return None
        return self._row_to_model(row)

    async def initialize(self, name: str, description: str | None = None, phases: list[str] | None = None) -> ProjectState:
        """Initialize project state (called by `rka init`)."""
        default_phases = phases or [
            "literature", "planning", "data_collection",
            "implementation", "evaluation", "paper_writing",
        ]
        await self.db.execute(
            """INSERT OR REPLACE INTO project_state
               (id, project_name, project_description, current_phase, phases_config)
               VALUES (1, ?, ?, ?, ?)""",
            [name, description, default_phases[0], json.dumps(default_phases)],
        )
        await self.db.commit()
        await self.audit("create", "project", "1", "system", {"name": name})
        return await self.get()

    async def update(self, data: ProjectStateUpdate, actor: str = "system") -> ProjectState:
        """Update project state with partial data."""
        current = await self.get()
        if current is None:
            raise ValueError("Project not initialized. Run `rka init` first.")

        updates = {}
        for field, value in data.model_dump(exclude_none=True).items():
            if field == "phases_config":
                updates[field] = json.dumps(value)
            elif field == "metrics":
                updates[field] = json.dumps(value)
            else:
                updates[field] = value

        if not updates:
            return current

        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values())

        await self.db.execute(
            f"UPDATE project_state SET {set_clause} WHERE id = 1",
            values,
        )
        await self.db.commit()

        # Emit phase change event if phase changed
        if data.current_phase and data.current_phase != current.current_phase:
            await self.emit_event(
                event_type="phase_changed",
                entity_type="project",
                entity_id="1",
                actor=actor,
                summary=f"Phase changed: {current.current_phase} → {data.current_phase}",
                phase=data.current_phase,
            )

        await self.audit("update", "project", "1", actor, {"fields": list(updates.keys())})
        return await self.get()

    def _row_to_model(self, row: dict) -> ProjectState:
        return ProjectState(
            project_name=row["project_name"],
            project_description=row.get("project_description"),
            current_phase=row.get("current_phase"),
            phases_config=self._json_loads(row.get("phases_config"), []),
            summary=row.get("summary"),
            blockers=row.get("blockers"),
            metrics=self._json_loads(row.get("metrics"), {}),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
