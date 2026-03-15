"""Onboarding routes — generate project-specific CLAUDE.md."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from rka.services.onboarding import OnboardingService
from rka.api.deps import get_scoped_onboarding_service

router = APIRouter()


@router.get("/generate-claude-md")
async def generate_claude_md(
    role: str = "executor",
    svc: OnboardingService = Depends(get_scoped_onboarding_service),
) -> dict:
    md = await svc.generate_claude_md(role=role)
    return {"markdown": md, "role": role}
