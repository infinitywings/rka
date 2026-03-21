"""Orchestration control plane models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


AutonomyMode = Literal["manual", "supervised", "autonomous", "paused"]


class OrchestrationConfig(BaseModel):
    """Project-level orchestration configuration."""

    project_id: str
    autonomy_mode: AutonomyMode = "manual"
    circuit_breaker_enabled: bool = True
    cost_limit_usd: float = 10.0
    cost_window_hours: int = 24
    circuit_breaker_tripped: bool = False
    circuit_breaker_tripped_at: str | None = None
    updated_at: str | None = None
    updated_by: str | None = None


class OrchestrationConfigUpdate(BaseModel):
    """Update orchestration settings."""

    autonomy_mode: AutonomyMode | None = None
    circuit_breaker_enabled: bool | None = None
    cost_limit_usd: float | None = None
    cost_window_hours: int | None = None


class CircuitBreakerReset(BaseModel):
    """Reset a tripped circuit breaker."""

    actor: str = "pi"


class PIOverride(BaseModel):
    """PI override: inject a high-priority directive to a role."""

    target_role_id: str | None = None
    target_role_name: str | None = None
    directive: str
    halt_current: bool = False


class CostLogEntry(BaseModel):
    """A single cost log entry."""

    id: int | None = None
    project_id: str
    role_id: str
    mission_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
    estimated_cost_usd: float = 0.0
    description: str | None = None
    created_at: str | None = None


class CostLogCreate(BaseModel):
    """Record token usage."""

    role_id: str
    mission_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
    estimated_cost_usd: float = 0.0
    description: str | None = None


class CostSummary(BaseModel):
    """Aggregated cost summary."""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    entry_count: int = 0
    window_hours: int | None = None


class RoleCostSummary(BaseModel):
    """Cost summary for a specific role."""

    role_id: str
    role_name: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    entry_count: int = 0


class OrchestrationStatus(BaseModel):
    """Full orchestration status for the dashboard."""

    config: OrchestrationConfig
    roles: list[dict] = Field(default_factory=list)
    cost_summary: CostSummary = Field(default_factory=CostSummary)
    cost_by_role: list[RoleCostSummary] = Field(default_factory=list)
    stuck_events: list[dict] = Field(default_factory=list)
    recent_overrides: list[dict] = Field(default_factory=list)
