"""Project state service."""

from __future__ import annotations

import json

from rka.infra.ids import generate_id
from rka.models.project import ProjectCreate, ProjectInfo, ProjectState, ProjectStateUpdate
from rka.services.base import BaseService, _now


class ProjectService(BaseService):
    """Manages projects and per-project state."""

    DEFAULT_PROJECT_ID = "proj_default"

    async def list_projects(self) -> list[ProjectInfo]:
        rows = await self.db.fetchall(
            "SELECT id, name, description, created_by, created_at, updated_at "
            "FROM projects ORDER BY created_at"
        )
        return [ProjectInfo(**dict(row)) for row in rows]

    async def create_project(self, data: ProjectCreate, actor: str = "system") -> ProjectInfo:
        project_id = (data.id or generate_id("project")).strip()
        existing_id = await self.db.fetchone("SELECT id FROM projects WHERE id = ?", [project_id])
        if existing_id:
            raise ValueError(f"Project '{project_id}' already exists")

        existing_name = await self.db.fetchone("SELECT id FROM projects WHERE name = ?", [data.name])
        if existing_name:
            raise ValueError(f"Project name '{data.name}' already exists")

        now = _now()
        await self.db.execute(
            """INSERT INTO projects (id, name, description, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [project_id, data.name, data.description, actor, now, now],
        )

        phases = data.phases_config or [
            "literature", "planning", "data_collection", "implementation", "evaluation", "paper_writing",
        ]
        await self.db.execute(
            """INSERT OR IGNORE INTO project_states
               (project_id, project_name, project_description, current_phase, phases_config, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [project_id, data.name, data.description, phases[0], json.dumps(phases), now, now],
        )
        await self.db.commit()
        await self.audit("create", "project", project_id, actor, {"name": data.name}, project_id=project_id)
        row = await self.db.fetchone("SELECT * FROM projects WHERE id = ?", [project_id])
        return ProjectInfo(**dict(row))

    async def get(self, project_id: str = DEFAULT_PROJECT_ID) -> ProjectState | None:
        """Get state for a project."""
        row = await self.db.fetchone(
            "SELECT * FROM project_states WHERE project_id = ?",
            [project_id],
        )
        if row is None and project_id == self.DEFAULT_PROJECT_ID:
            # Legacy fallback for pre-migration DBs
            row = await self.db.fetchone("SELECT * FROM project_state WHERE id = 1")
        if row is None:
            return None
        return self._row_to_model(row)

    async def initialize(
        self,
        name: str,
        description: str | None = None,
        phases: list[str] | None = None,
        project_id: str = DEFAULT_PROJECT_ID,
    ) -> ProjectState:
        """Initialize project state (called by `rka init`)."""
        default_phases = phases or [
            "literature", "planning", "data_collection",
            "implementation", "evaluation", "paper_writing",
        ]
        await self.db.execute(
            """INSERT OR IGNORE INTO projects (id, name, description, created_by)
               VALUES (?, ?, ?, 'system')""",
            [project_id, name, description],
        )
        await self.db.execute(
            """INSERT OR REPLACE INTO project_states
               (project_id, project_name, project_description, current_phase, phases_config, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM project_states WHERE project_id = ?), ?), ?)""",
            [project_id, name, description, default_phases[0], json.dumps(default_phases), project_id, _now(), _now()],
        )
        await self.db.commit()
        await self.audit("create", "project", project_id, "system", {"name": name}, project_id=project_id)
        return await self.get(project_id=project_id)

    async def update(
        self,
        data: ProjectStateUpdate,
        actor: str = "system",
        project_id: str = DEFAULT_PROJECT_ID,
    ) -> ProjectState:
        """Update project state with partial data."""
        current = await self.get(project_id=project_id)
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
            f"UPDATE project_states SET {set_clause} WHERE project_id = ?",
            values + [project_id],
        )
        await self.db.commit()

        # Emit phase change event if phase changed
        if data.current_phase and data.current_phase != current.current_phase:
            await self.emit_event(
                event_type="phase_changed",
                entity_type="project",
                entity_id=project_id,
                actor=actor,
                summary=f"Phase changed: {current.current_phase} → {data.current_phase}",
                phase=data.current_phase,
                project_id=project_id,
            )

        await self.audit("update", "project", project_id, actor, {"fields": list(updates.keys())}, project_id=project_id)
        return await self.get(project_id=project_id)

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
