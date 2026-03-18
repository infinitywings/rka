"""Agent role registry service."""

from __future__ import annotations

import fnmatch
import json
import logging

from rka.infra.ids import generate_id
from rka.models.agent_role import AgentRole, AgentRoleCreate, AgentRoleUpdate
from rka.services.base import BaseService, _now

logger = logging.getLogger(__name__)


class AgentRoleService(BaseService):
    """Manages persistent agent role definitions."""

    async def register(self, data: AgentRoleCreate) -> AgentRole:
        """Register a new agent role."""
        role_id = generate_id("agent_role")
        now = _now()
        await self.db.execute(
            """INSERT INTO agent_roles
               (id, project_id, name, description, system_prompt_template,
                subscriptions, subscription_filters, role_state, learnings_digest,
                autonomy_profile, model, model_tier, tools_config, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                role_id, self.project_id, data.name, data.description,
                data.system_prompt_template,
                self._json_dumps(data.subscriptions),
                self._json_dumps(data.subscription_filters),
                self._json_dumps(data.role_state),
                data.learnings_digest,
                self._json_dumps(data.autonomy_profile),
                data.model, data.model_tier,
                self._json_dumps(data.tools_config),
                now, now,
            ],
        )
        await self.db.commit()
        await self.audit("create", "agent_role", role_id, "system")
        return await self.get(role_id)  # type: ignore[return-value]

    async def get(self, role_id: str) -> AgentRole | None:
        """Get a role by ID."""
        row = await self.db.fetchone(
            "SELECT * FROM agent_roles WHERE id = ? AND project_id = ?",
            [role_id, self.project_id],
        )
        if not row:
            return None
        return self._row_to_model(row)

    async def get_by_name(self, name: str) -> AgentRole | None:
        """Get a role by name within the current project."""
        row = await self.db.fetchone(
            "SELECT * FROM agent_roles WHERE name = ? AND project_id = ?",
            [name, self.project_id],
        )
        if not row:
            return None
        return self._row_to_model(row)

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[AgentRole]:
        """List roles for the current project."""
        rows = await self.db.fetchall(
            "SELECT * FROM agent_roles WHERE project_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            [self.project_id, limit, offset],
        )
        return [self._row_to_model(r) for r in rows]

    async def update(self, role_id: str, data: AgentRoleUpdate) -> AgentRole:
        """Update a role."""
        updates: dict = {}
        if data.name is not None:
            updates["name"] = data.name
        if data.description is not None:
            updates["description"] = data.description
        if data.system_prompt_template is not None:
            updates["system_prompt_template"] = data.system_prompt_template
        if data.subscriptions is not None:
            updates["subscriptions"] = self._json_dumps(data.subscriptions)
        if data.subscription_filters is not None:
            updates["subscription_filters"] = self._json_dumps(data.subscription_filters)
        if data.role_state is not None:
            updates["role_state"] = self._json_dumps(data.role_state)
        if data.learnings_digest is not None:
            updates["learnings_digest"] = data.learnings_digest
        if data.autonomy_profile is not None:
            updates["autonomy_profile"] = self._json_dumps(data.autonomy_profile)
        if data.model is not None:
            updates["model"] = data.model
        if data.model_tier is not None:
            updates["model_tier"] = data.model_tier
        if data.tools_config is not None:
            updates["tools_config"] = self._json_dumps(data.tools_config)

        if updates:
            updates["updated_at"] = _now()
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [role_id, self.project_id]
            await self.db.execute(
                f"UPDATE agent_roles SET {set_clause} WHERE id = ? AND project_id = ?",
                values,
            )
            await self.db.commit()
            await self.audit("update", "agent_role", role_id, "system", {"fields": list(updates.keys())})
        return await self.get(role_id)  # type: ignore[return-value]

    async def bind(self, role_id: str, session_id: str) -> AgentRole:
        """Bind a role to a session (DB-backed session-role binding)."""
        now = _now()
        await self.db.execute(
            "UPDATE agent_roles SET active_session_id = ?, last_active_at = ?, updated_at = ? WHERE id = ? AND project_id = ?",
            [session_id, now, now, role_id, self.project_id],
        )
        await self.db.commit()
        return await self.get(role_id)  # type: ignore[return-value]

    async def save_state(self, role_id: str, role_state: dict) -> AgentRole:
        """Save role state."""
        now = _now()
        await self.db.execute(
            "UPDATE agent_roles SET role_state = ?, updated_at = ? WHERE id = ? AND project_id = ?",
            [self._json_dumps(role_state), now, role_id, self.project_id],
        )
        await self.db.commit()
        return await self.get(role_id)  # type: ignore[return-value]

    async def match_subscriptions(self, event_type: str) -> list[AgentRole]:
        """Find all roles whose subscriptions match the given event_type.

        Uses fnmatch-style glob matching against each role's subscription patterns.
        """
        roles = await self.list(limit=200)
        matched: list[AgentRole] = []
        for role in roles:
            for pattern in role.subscriptions:
                if fnmatch.fnmatch(event_type, pattern):
                    matched.append(role)
                    break
        return matched

    def _row_to_model(self, row) -> AgentRole:
        """Convert a DB row to an AgentRole model."""
        d = dict(row)
        d["subscriptions"] = self._json_loads(d.get("subscriptions"), default=[])
        d["subscription_filters"] = self._json_loads(d.get("subscription_filters"))
        d["role_state"] = self._json_loads(d.get("role_state"))
        d["autonomy_profile"] = self._json_loads(d.get("autonomy_profile"))
        d["tools_config"] = self._json_loads(d.get("tools_config"))
        return AgentRole(**d)
