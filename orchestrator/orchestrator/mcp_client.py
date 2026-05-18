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
    def rka_get_journal(
        self, *, tags: list[str] | None = None, limit: int = 20
    ) -> list[dict[str, Any]]: ...
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
    def rka_update_note(
        self,
        id: str,
        *,
        content: str | None = None,
        type: str | None = None,
        confidence: str | None = None,
        importance: str | None = None,
        verbatim_input: str | None = None,
        related_decisions: list[str] | None = None,
        related_literature: list[str] | None = None,
        related_mission: str | None = None,
        tags: list[str] | None = None,
        phase: str | None = None,
        source: str | None = None,
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
        body: dict = {"limit": limit}
        if topic:
            body["topic"] = topic
        return self._request("POST", "/api/context", json=body) or {}

    def rka_get_journal(
        self, *, tags: list[str] | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """GET /api/notes (REST endpoint per /openapi.json).

        Phase 2.10 T1 (mis_01KRYBZ0W4Z9F1GXKP96ERKGKK; discharge of Phase 2.9
        T3 debt per `jrn_01KRY908A3RYX1TBH6CKKPJRGC`):
        - URL: was `/api/journal` (web UI HTML route, HTTP 200 but body is
          `<!doctype html>` — fails callers expecting JSON); now `/api/notes`
          which is the actual REST surface returning a list of note objects.
        - Return shape: was `dict[str, Any]` per the (incorrect) Protocol; now
          `list[dict[str, Any]]` matching the live REST surface.
        - Tags filter: REST `/api/notes` does NOT accept a `tags` query param
          (verified via /openapi.json — supported params are type, phase,
          confidence, importance, source, status, since, hide_superseded,
          limit, offset, project_id, X-RKA-Project). Filter client-side
          post-fetch: a note matches if it carries ALL requested tags.
        """
        params: dict = {"limit": limit}
        result = self._request("GET", "/api/notes", params=params)
        # Real REST returns a list; tolerate `None` (empty response).
        notes: list[dict[str, Any]] = result if isinstance(result, list) else []
        if not tags:
            return notes
        wanted = set(tags)
        return [
            n for n in notes
            if wanted.issubset(set(n.get("tags") or []))
        ]

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
        self,
        content: str,
        *,
        related_journal: list[str],
        tags: list[str] | None = None,
        decided_by: str = "pi",
        phase: str = "design",
        rationale: str | None = None,
    ) -> str:
        """POST /api/decisions.

        The REST `DecisionCreate` schema requires `question + decided_by +
        phase`. Free-form `content` is mapped to `question` (truncated to
        keep the title-line readable; full text goes to `rationale`).
        """
        question = content.strip().split("\n", 1)[0][:280]
        body = _drop_none(
            {
                "question": question or content[:280] or "Decision drafted by orchestrator",
                "rationale": rationale or content,
                "decided_by": decided_by,
                "phase": phase,
                "related_journal": list(related_journal),
                "tags": _merge_workflow_tag(tags, self.workflow_thread_id),
            }
        )
        result = self._request("POST", "/api/decisions", json=body) or {}
        return result.get("id") or ""

    def rka_submit_checkpoint(
        self,
        reason: str,
        *,
        type: str = "decision",
        related_mission: str | None = None,
    ) -> str:
        """Submit a checkpoint via POST /api/checkpoints.

        Phase 2.1 (mis_01KRSTZVCTFGF91QZXTYK7ZGDD T2): payload aligned with
        RKA's current `CheckpointCreate` schema (rka/models/checkpoint.py).
        Mission C (mis_01KR43RX9KY11GAPTPPGK9XSDE, v2.3.4) added
        `extra="forbid"` as defense-in-depth; the orchestrator's pre-v2.4
        field names (`reason`, `related_mission`, `tags`) were rejected,
        causing the v2.5.3+agentic-rc1 422 cascade.

        Schema-correct mapping:
          - orchestrator `reason`           → RKA `description` (required)
          - orchestrator `related_mission`  → RKA `mission_id`   (required)
          - orchestrator `type`             → RKA `type`         (already aligned)
          - orchestrator `tags`             → RKA has no `tags` on CheckpointCreate;
            the workflow_thread_id survives via `context` as a structured prefix
            (checkpoints are indexed by mission_id, not by tag, so Affordance-F
            retrieval still works through the mission linkage).
        """
        if not related_mission:
            raise ValueError(
                "rka_submit_checkpoint requires related_mission (maps to "
                "CheckpointCreate.mission_id which is required by RKA's schema)."
            )
        context = (
            f"workflow_thread_id: {self.workflow_thread_id}"
            if self.workflow_thread_id
            else None
        )
        body = _drop_none(
            {
                "mission_id": related_mission,
                "type": type,
                "description": reason,
                "context": context,
            }
        )
        result = self._request("POST", "/api/checkpoints", json=body) or {}
        return result.get("id") or ""

    def rka_submit_report(self, content: str, **kw: Any) -> str:
        """POST /api/missions/{mission}/report.

        The REST schema (`MissionReportCreate`) accepts only structured
        fields: tasks_completed, findings, anomalies, questions,
        codebase_state, recommended_next. We map the free-form `content`
        argument to `findings=[content]` when no structured findings were
        passed, so the LLM-shaped output the executor node produces still
        lands somewhere useful.

        Return value: the mission_id under which the report was filed.
        Phase 2.7 T5 triage (`jrn_01KRXQJJXKRAH1GB6FTZEQDAXQ`) confirmed RKA's
        data model stores reports inline on missions — there is no separate
        `Report` entity with a `rep_*` prefix. The Phase 2.6 finding
        "returned mission_id as report_id" was an orchestrator-side
        contract mismatch (incorrect assumption that a fresh `rep_*` id
        would be minted), not a REST bug. The returned mission_id is the
        canonical identity for retrieving the report via
        `GET /api/missions/{id}/report`.
        """
        mission = kw.get("related_mission")
        if not mission:
            raise ValueError("rka_submit_report requires related_mission")
        findings = kw.get("findings")
        if not findings and content:
            findings = [content]
        body = _drop_none(
            {
                "tasks_completed": kw.get("tasks_completed"),
                "findings": findings,
                "anomalies": kw.get("anomalies"),
                "questions": kw.get("questions"),
                "codebase_state": kw.get("codebase_state"),
                "recommended_next": kw.get("recommended_next"),
            }
        )
        result = self._request(
            "POST", f"/api/missions/{mission}/report", json=body
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

    def rka_update_note(self, id: str, **kw: Any) -> str:
        """PUT /api/notes/{note_id}.

        Phase 2.7 (mis_01KRXNAJDM2DQ3K1VH6CXAPK8R T3): added to support the
        Phase 2.4 → 2.6 acceptance criterion ("1+ items complete the cycle
        with rka_update_note write"). PI ratified inclusion in MCPClient
        Protocol at T1 mid-mission gate (jrn_01KRXP96THHEAKCGB0P0KGV7Y9).

        Workflow_thread_id auto-tagging applies — if `tags` is provided,
        the thread id is appended via `_merge_workflow_tag`; if `tags` is
        None, no tag mutation (the endpoint preserves existing tags).
        """
        if not id:
            raise ValueError("rka_update_note requires a non-empty note id")
        body = _drop_none(
            {
                "content": kw.get("content"),
                "type": kw.get("type"),
                "confidence": kw.get("confidence"),
                "importance": kw.get("importance"),
                "verbatim_input": kw.get("verbatim_input"),
                "related_decisions": kw.get("related_decisions"),
                "related_literature": kw.get("related_literature"),
                "related_mission": kw.get("related_mission"),
                "tags": (
                    _merge_workflow_tag(kw["tags"], self.workflow_thread_id)
                    if kw.get("tags") is not None
                    else None
                ),
                "phase": kw.get("phase"),
                "source": kw.get("source"),
            }
        )
        result = self._request("PUT", f"/api/notes/{id}", json=body) or {}
        # PUT typically returns the updated entity; fall back to input id
        # so callers can confirm the write succeeded.
        return result.get("id") or id


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
