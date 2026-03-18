"""Agent role routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.models.agent_role import AgentRole, AgentRoleCreate, AgentRoleUpdate, AgentRoleBind, AgentRoleStateUpdate
from rka.services.agent_roles import AgentRoleService
from rka.api.deps import get_scoped_agent_role_service

router = APIRouter()


@router.post("/roles", response_model=AgentRole, status_code=201)
async def register_role(
    data: AgentRoleCreate,
    svc: AgentRoleService = Depends(get_scoped_agent_role_service),
):
    return await svc.register(data)


@router.get("/roles", response_model=list[AgentRole])
async def list_roles(
    limit: int = Query(50, le=200),
    offset: int = 0,
    svc: AgentRoleService = Depends(get_scoped_agent_role_service),
):
    return await svc.list(limit=limit, offset=offset)


@router.get("/roles/{role_id}", response_model=AgentRole)
async def get_role(
    role_id: str,
    svc: AgentRoleService = Depends(get_scoped_agent_role_service),
):
    role = await svc.get(role_id)
    if role is None:
        raise HTTPException(404, f"Role {role_id} not found")
    return role


@router.put("/roles/{role_id}", response_model=AgentRole)
async def update_role(
    role_id: str,
    data: AgentRoleUpdate,
    svc: AgentRoleService = Depends(get_scoped_agent_role_service),
):
    role = await svc.get(role_id)
    if role is None:
        raise HTTPException(404, f"Role {role_id} not found")
    return await svc.update(role_id, data)


@router.post("/roles/{role_id}/bind", response_model=AgentRole)
async def bind_role(
    role_id: str,
    data: AgentRoleBind,
    svc: AgentRoleService = Depends(get_scoped_agent_role_service),
):
    role = await svc.get(role_id)
    if role is None:
        raise HTTPException(404, f"Role {role_id} not found")
    return await svc.bind(role_id, data.session_id)


@router.put("/roles/{role_id}/state", response_model=AgentRole)
async def save_role_state(
    role_id: str,
    data: AgentRoleStateUpdate,
    svc: AgentRoleService = Depends(get_scoped_agent_role_service),
):
    role = await svc.get(role_id)
    if role is None:
        raise HTTPException(404, f"Role {role_id} not found")
    return await svc.save_state(role_id, data.role_state)
