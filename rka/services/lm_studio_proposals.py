"""Loopback-only LM Studio adapter for semantic patch suggestions."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from rka.config import RKAConfig
from rka.infra.ids import generate_id
from rka.models.semantic_patch import (
    ContextManifestCreate,
    GeneratedProposalDraft,
    LMStudioProposalRequest,
    SemanticPatchProposalCreate,
)
from rka.services.semantic_patch import SemanticPatchService


class LMStudioResponseError(RuntimeError):
    """The configured local provider returned an unusable response."""


def _local_base_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if (
        parsed.scheme != "http"
        or parsed.hostname
        not in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "LM Studio base URL must be an uncredentialed local-machine http URL"
        )
    return value.rstrip("/")


class LMStudioProposalAdapter:
    """Generate one candidate, then validate it through SemanticPatchService."""

    def __init__(self, service: SemanticPatchService, config: RKAConfig):
        self.service = service
        self.config = config

    async def generate(self, request: LMStudioProposalRequest) -> dict[str, Any]:
        base_url = _local_base_url(self.config.workbench_lm_studio_base_url)
        model = (request.model or self.config.workbench_lm_studio_model).strip()
        if not model:
            raise ValueError(
                "LM Studio model is required; set RKA_WORKBENCH_LM_STUDIO_MODEL or request.model"
            )
        manifest = await self.service.create_context_manifest(
            ContextManifestCreate(
                origin="lm_studio",
                provider="lm_studio",
                model=model,
                boundary="local_loopback",
                selected_context=request.selected_context,
                include_source_closure=request.include_source_closure,
                targets=request.targets,
                constraints=request.constraints,
                omissions=request.omissions,
                truncation_notes=request.truncation_notes,
            )
        )
        call_id = generate_id("semantic_patch_provider_call")
        await self.service.record_provider_event(
            call_id=call_id,
            manifest_id=manifest["id"],
            event="started",
            provider="lm_studio",
            model=model,
            boundary="local_loopback",
            details={"endpoint": "/chat/completions"},
        )
        try:
            draft = await self._request_draft(
                base_url=base_url,
                model=model,
                instruction=request.instruction,
                manifest=manifest,
            )
            proposal = await self.service.create_proposal(
                SemanticPatchProposalCreate(
                    origin="lm_studio",
                    intent=draft.intent,
                    reason=draft.reason,
                    created_by=request.created_by,
                    operations=draft.operations,
                    provider="lm_studio",
                    model=model,
                    boundary="local_loopback",
                    context_manifest_id=manifest["id"],
                )
            )
        except Exception as exc:
            await self.service.record_provider_event(
                call_id=call_id,
                manifest_id=manifest["id"],
                event="failed",
                provider="lm_studio",
                model=model,
                boundary="local_loopback",
                details={"error_type": type(exc).__name__, "message": str(exc)[:2000]},
            )
            raise
        proposal["provider_call_id"] = call_id
        return proposal

    async def _request_draft(
        self,
        *,
        base_url: str,
        model: str,
        instruction: str,
        manifest: dict[str, Any],
    ) -> GeneratedProposalDraft:
        system = (
            "You propose edits to an auditable research manuscript workbench. "
            "Return only an object matching the supplied schema. Do not invent entity IDs, "
            "remove qualifiers or counterevidence silently, claim ratification, or imply that "
            "the proposal has been applied. Use only the supplied context manifest."
        )
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": _bounded_prompt(instruction, manifest),
                },
            ],
            "temperature": 0.2,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "rka_semantic_patch_draft",
                    "strict": True,
                    "schema": GeneratedProposalDraft.model_json_schema(),
                },
            },
        }
        async with httpx.AsyncClient(
            timeout=self.config.workbench_lm_studio_timeout,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = await client.post(f"{base_url}/chat/completions", json=body)
            response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise LMStudioResponseError("LM Studio returned a non-JSON response") from exc
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LMStudioResponseError(
                "LM Studio response did not contain message content"
            ) from exc
        try:
            parsed = json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError as exc:
            raise LMStudioResponseError("LM Studio returned invalid JSON") from exc
        try:
            return GeneratedProposalDraft.model_validate(parsed)
        except ValidationError as exc:
            raise LMStudioResponseError(
                "LM Studio response did not match the semantic proposal schema"
            ) from exc


def _bounded_prompt(instruction: str, manifest: dict[str, Any]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
    # The caller must disclose intentional omissions. An accidental unbounded
    # payload fails closed instead of silently sending a partial manifest.
    if len(encoded) > 1_000_000:
        raise ValueError(
            "context manifest exceeds 1,000,000 characters; select less context and record omissions"
        )
    return f"Researcher instruction:\n{instruction}\n\nExact context manifest:\n{encoded}"
