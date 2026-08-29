"""Minimal downstream client for ``rka-rest/v1``.

This module intentionally imports no RKA package code.  It models what an
independent client can do with only the documented HTTP contract.
"""

from __future__ import annotations

from typing import Any

import httpx


STABLE_REST_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/capabilities"),
        ("POST", "/api/projects"),
        ("POST", "/api/notes"),
        ("GET", "/api/notes/{note_id}"),
        ("POST", "/api/decisions"),
        ("POST", "/api/claims"),
        ("POST", "/api/clusters"),
        ("POST", "/api/claims/edges"),
        ("GET", "/api/assemble-evidence"),
        ("GET", "/api/research-map"),
        ("GET", "/api/changes"),
    }
)


class PublicCoreClient:
    """Small async client used to prove the public contract is sufficient."""

    def __init__(self, http: httpx.AsyncClient, project_id: str | None = None):
        self.http = http
        self.project_id = project_id

    def for_project(self, project_id: str) -> "PublicCoreClient":
        return PublicCoreClient(self.http, project_id=project_id)

    def _scope_headers(self) -> dict[str, str]:
        if not self.project_id:
            raise ValueError("project_id is required for this scoped operation")
        return {"X-RKA-Project": self.project_id}

    async def _json(
        self,
        method: str,
        path: str,
        *,
        scoped: bool = True,
        contract_path: str | None = None,
        **kwargs: Any,
    ) -> Any:
        operation = (method.upper(), contract_path or path)
        if operation not in STABLE_REST_OPERATIONS:
            raise ValueError(f"fixture call is outside rka-rest/v1: {operation!r}")
        headers = dict(kwargs.pop("headers", {}))
        if scoped:
            headers.update(self._scope_headers())
        response = await self.http.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()

    async def capabilities(self) -> dict[str, Any]:
        return await self._json(
            "GET",
            "/api/capabilities",
            scoped=False,
            params={"required_contract": "rka-core/v1"},
        )

    async def create_project(
        self,
        *,
        project_id: str,
        name: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": project_id, "name": name}
        if description is not None:
            payload["description"] = description
        return await self._json("POST", "/api/projects", scoped=False, json=payload)

    async def create_note(self, *, content: str) -> dict[str, Any]:
        return await self._json(
            "POST",
            "/api/notes",
            json={"content": content, "type": "note", "source": "executor"},
        )

    async def get_note(self, note_id: str) -> dict[str, Any]:
        return await self._json(
            "GET",
            f"/api/notes/{note_id}",
            contract_path="/api/notes/{note_id}",
        )

    async def create_research_question(
        self,
        *,
        question: str,
        related_journal: list[str],
    ) -> dict[str, Any]:
        return await self._json(
            "POST",
            "/api/decisions",
            json={
                "question": question,
                "phase": "framing",
                "decided_by": "brain",
                "kind": "research_question",
                "status": "active",
                "related_journal": related_journal,
            },
        )

    async def create_claim(
        self,
        *,
        source_entry_id: str,
        content: str,
    ) -> dict[str, Any]:
        return await self._json(
            "POST",
            "/api/claims",
            json={
                "source_entry_id": source_entry_id,
                "claim_type": "evidence",
                "content": content,
                "confidence": 0.85,
                "verified": True,
                "evidence_status": "supported",
            },
        )

    async def create_cluster(
        self,
        *,
        research_question_id: str,
        label: str,
    ) -> dict[str, Any]:
        return await self._json(
            "POST",
            "/api/clusters",
            json={
                "research_question_id": research_question_id,
                "label": label,
                "confidence": "moderate",
            },
        )

    async def assign_claim_to_cluster(
        self,
        *,
        claim_id: str,
        cluster_id: str,
    ) -> dict[str, Any]:
        return await self._json(
            "POST",
            "/api/claims/edges",
            json={
                "source_claim_id": claim_id,
                "cluster_id": cluster_id,
                "relation": "member_of",
                "confidence": 1.0,
            },
        )

    async def assemble_evidence(self, research_question_id: str) -> dict[str, Any]:
        return await self._json(
            "GET",
            "/api/assemble-evidence",
            params={
                "research_question_id": research_question_id,
                "format": "progress_report",
            },
        )

    async def research_map(self) -> dict[str, Any]:
        return await self._json("GET", "/api/research-map")

    async def changes_since(self, cursor: int = 0) -> dict[str, Any]:
        return await self._json("GET", "/api/changes", params={"cursor": cursor, "limit": 100})
