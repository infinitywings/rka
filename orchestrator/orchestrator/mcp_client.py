"""MCP client wrapper.

T3-T6 nodes write against the `MCPClient` Protocol. This module exposes
both the Protocol surface AND a concrete `RestMCPClient` that talks to
the RKA REST API directly (which is what the `rka` stdio-MCP binary
internally proxies to anyway, per the repo CLAUDE.md). A future Phase 2
mission can drop a stdio-backed implementation behind the same Protocol
without changing any node code.

The 13 RKA MCP tools (canonical, current as of v2.3.5):

  1. rka_search
  2. rka_get
  3. rka_get_context
  4. rka_get_journal
  5. rka_get_research_map
  6. rka_get_mission
  7. rka_add_note
  8. rka_add_decision
  9. rka_create_mission
 10. rka_submit_checkpoint
 11. rka_submit_report
 12. rka_get_checkpoints
 13. rka_trace_provenance

Error mapping (Affordances G + E from v2.3.5):
  - 422 KnowledgePackIntegrityError → `CheckpointError`
  - motivated-by-explained tag suppression respected on retry

Every write call appends the `workflow_thread_id` to the call's `tags=[…]`
field so the run's RKA artifacts can be recovered via
`rka_get_journal(tags=[workflow_thread_id])` (v2.3.5 Affordance F).
"""

from __future__ import annotations

from typing import Any, Iterable, Protocol


class CheckpointError(Exception):
    """Raised when an MCP call needs the workflow to halt and create a checkpoint.

    The T6 `escalation_router` catches this and emits an
    `rka_submit_checkpoint` of type=decision before routing to PI.
    """

    def __init__(self, reason: str, *, mcp_response: Any = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.mcp_response = mcp_response


class MCPClient(Protocol):
    """Workflow-tagged wrapper over the 13 RKA MCP tools.

    `workflow_thread_id` is set at workflow start and auto-appended to
    every write call's `tags` list.
    """

    workflow_thread_id: str

    # --- reads ---
    def rka_get_status(self) -> dict[str, Any]: ...
    def rka_get_context(self, topic: str | None = None, limit: int = 10) -> dict[str, Any]: ...
    def rka_get_journal(self, *, tags: list[str] | None = None, limit: int = 20) -> dict[str, Any]: ...
    def rka_get_mission(self, id: str | None = None) -> dict[str, Any]: ...
    def rka_get_research_map(self) -> dict[str, Any]: ...
    def rka_get_checkpoints(self, status: str = "open") -> list[dict[str, Any]]: ...
    def rka_search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]: ...
    def rka_get(self, id: str) -> dict[str, Any]: ...
    def rka_trace_provenance(self, id: str) -> dict[str, Any]: ...

    # --- writes (auto-tag workflow_thread_id) ---
    def rka_add_note(
        self,
        content: str,
        *,
        type: str = "note",
        source: str = "brain",
        related_mission: str | None = None,
        related_decisions: list[str] | None = None,
        tags: list[str] | None = None,
        confidence: str = "hypothesis",
        importance: str = "normal",
    ) -> str: ...
    def rka_add_decision(
        self,
        content: str,
        *,
        related_journal: list[str],
        tags: list[str] | None = None,
    ) -> str: ...
    def rka_submit_checkpoint(
        self,
        reason: str,
        *,
        type: str = "decision",
        related_mission: str | None = None,
    ) -> str: ...
    def rka_submit_report(
        self,
        content: str,
        *,
        related_mission: str,
        summary: str | None = None,
        findings: list[str] | None = None,
        anomalies: list[str] | None = None,
        recommended_next: list[str] | None = None,
    ) -> str: ...
    def rka_create_mission(
        self,
        objective: str,
        *,
        motivated_by_decision: str,
        acceptance_criteria: list[str],
    ) -> str: ...


# ---------------------------------------------------------------------------
# Concrete REST-backed implementation
# ---------------------------------------------------------------------------


def _merge_workflow_tag(
    tags: list[str] | None, workflow_thread_id: str
) -> list[str]:
    """Return `tags + [workflow_thread_id]` without duplication."""
    out = list(tags or [])
    if workflow_thread_id and workflow_thread_id not in out:
        out.append(workflow_thread_id)
    return out


def _drop_none(d: dict) -> dict:
    """Skip dict keys whose value is None — keeps REST bodies tidy."""
    return {k: v for k, v in d.items() if v is not None}


class RestMCPClient:
    """HTTP-backed MCPClient implementation.

    Talks to the RKA REST API at `base_url` (default
    `http://localhost:9712`). Mirrors the 13-tool surface that the
    stdio `rka mcp` binary itself proxies into the REST layer.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:9712",
        workflow_thread_id: str,
        project_id: str | None = None,
        http_client: Any = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.workflow_thread_id = workflow_thread_id
        self.project_id = project_id
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._http = http_client  # if None, lazily import httpx on first call

    # ---- low-level helpers ----

    def _client(self):
        if self._http is None:
            import httpx  # local import keeps the package import cheap

            self._http = httpx.Client(base_url=self._base_url, timeout=self._timeout)
        return self._http

    def _params(self, extra: dict | None = None) -> dict:
        out: dict = {}
        if self.project_id:
            out["project_id"] = self.project_id
        if extra:
            out.update(extra)
        return out

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        resp = self._client().request(
            method, path, json=json, params=self._params(params)
        )
        if resp.status_code == 422:
            try:
                detail = resp.json()
            except Exception:  # noqa: BLE001
                detail = {"text": resp.text}
            raise CheckpointError(
                f"RKA returned 422 (knowledge-pack integrity); path={path}",
                mcp_response=detail,
            )
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            return resp.text

    # ---- reads ----

    def rka_get_status(self) -> dict:
        return self._request("GET", "/api/status") or {}

    def rka_get_context(self, topic: str | None = None, limit: int = 10) -> dict:
        params = {"limit": limit}
        if topic:
            params["topic"] = topic
        return self._request("GET", "/api/context", params=params) or {}

    def rka_get_journal(
        self, *, tags: list[str] | None = None, limit: int = 20
    ) -> dict:
        params: dict = {"limit": limit}
        if tags:
            params["tags"] = ",".join(tags)
        return self._request("GET", "/api/journal", params=params) or {}

    def rka_get_mission(self, id: str | None = None) -> dict:
        path = f"/api/missions/{id}" if id else "/api/missions/active"
        return self._request("GET", path) or {}

    def rka_get_research_map(self) -> dict:
        return self._request("GET", "/api/research-map") or {}

    def rka_get_checkpoints(self, status: str = "open") -> list:
        return self._request("GET", "/api/checkpoints", params={"status": status}) or []

    def rka_search(self, query: str, *, limit: int = 10) -> list:
        body = {"query": query, "limit": limit}
        return self._request("POST", "/api/search", json=body) or []

    def rka_get(self, id: str) -> dict:
        return self._request("GET", f"/api/entities/{id}") or {}

    def rka_trace_provenance(self, id: str) -> dict:
        return self._request("GET", f"/api/provenance/{id}") or {}

    # ---- writes ----

    def rka_add_note(self, content: str, **kw: Any) -> str:
        body = _drop_none(
            {
                "content": content,
                "type": kw.get("type", "note"),
                "source": kw.get("source", "brain"),
                "related_mission": kw.get("related_mission"),
                "related_decisions": kw.get("related_decisions"),
                "tags": _merge_workflow_tag(kw.get("tags"), self.workflow_thread_id),
                "confidence": kw.get("confidence", "hypothesis"),
                "importance": kw.get("importance", "normal"),
            }
        )
        result = self._request("POST", "/api/notes", json=body) or {}
        return result.get("id") or result.get("jrn_id") or ""

    def rka_add_decision(
        self, content: str, *, related_journal: list[str], tags: list[str] | None = None
    ) -> str:
        body = {
            "content": content,
            "related_journal": list(related_journal),
            "tags": _merge_workflow_tag(tags, self.workflow_thread_id),
        }
        result = self._request("POST", "/api/decisions", json=body) or {}
        return result.get("id") or ""

    def rka_submit_checkpoint(
        self,
        reason: str,
        *,
        type: str = "decision",
        related_mission: str | None = None,
    ) -> str:
        body = _drop_none(
            {
                "reason": reason,
                "type": type,
                "related_mission": related_mission,
                "tags": [self.workflow_thread_id] if self.workflow_thread_id else [],
            }
        )
        result = self._request("POST", "/api/checkpoints", json=body) or {}
        return result.get("id") or ""

    def rka_submit_report(self, content: str, **kw: Any) -> str:
        mission = kw.get("related_mission")
        if not mission:
            raise ValueError("rka_submit_report requires related_mission")
        body = _drop_none(
            {
                "content": content,
                "summary": kw.get("summary"),
                "findings": kw.get("findings"),
                "anomalies": kw.get("anomalies"),
                "questions": kw.get("questions"),
                "codebase_state": kw.get("codebase_state"),
                "recommended_next": kw.get("recommended_next"),
                "tags": [self.workflow_thread_id] if self.workflow_thread_id else [],
            }
        )
        result = self._request(
            "POST", f"/api/missions/{mission}/reports", json=body
        ) or {}
        return result.get("id") or ""

    def rka_create_mission(
        self,
        objective: str,
        *,
        motivated_by_decision: str,
        acceptance_criteria: list[str],
    ) -> str:
        body = {
            "objective": objective,
            "motivated_by_decision": motivated_by_decision,
            "acceptance_criteria": list(acceptance_criteria),
            "tags": [self.workflow_thread_id] if self.workflow_thread_id else [],
        }
        result = self._request("POST", "/api/missions", json=body) or {}
        return result.get("id") or ""


def make_client(
    *,
    workflow_thread_id: str,
    base_url: str = "http://localhost:9712",
    project_id: str | None = None,
) -> RestMCPClient:
    """Construct the production MCP client (REST-backed)."""
    return RestMCPClient(
        base_url=base_url,
        workflow_thread_id=workflow_thread_id,
        project_id=project_id,
    )
