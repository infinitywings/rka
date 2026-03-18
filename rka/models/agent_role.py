"""Agent role models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentRoleCreate(BaseModel):
    """Register a new agent role."""

    name: str
    description: str | None = None
    system_prompt_template: str | None = None
    subscriptions: list[str] = Field(default_factory=list)
    subscription_filters: dict | None = None
    role_state: dict | None = None
    learnings_digest: str | None = None
    autonomy_profile: dict | None = None
    model: str | None = None
    model_tier: str | None = None
    tools_config: dict | None = None


class AgentRoleUpdate(BaseModel):
    """Update an existing agent role."""

    name: str | None = None
    description: str | None = None
    system_prompt_template: str | None = None
    subscriptions: list[str] | None = None
    subscription_filters: dict | None = None
    role_state: dict | None = None
    learnings_digest: str | None = None
    autonomy_profile: dict | None = None
    model: str | None = None
    model_tier: str | None = None
    tools_config: dict | None = None


class AgentRoleBind(BaseModel):
    """Bind a role to a session."""

    session_id: str


class AgentRoleStateUpdate(BaseModel):
    """Update role state."""

    role_state: dict


class AgentRole(BaseModel):
    """Full agent role record from database."""

    id: str
    project_id: str
    name: str
    description: str | None = None
    system_prompt_template: str | None = None
    subscriptions: list[str] = Field(default_factory=list)
    subscription_filters: dict | None = None
    role_state: dict | None = None
    learnings_digest: str | None = None
    autonomy_profile: dict | None = None
    model: str | None = None
    model_tier: str | None = None
    tools_config: dict | None = None
    active_session_id: str | None = None
    last_active_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
