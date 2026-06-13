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


# Phase-X² polish — extract the structured FastAPI 422 detail into a
# compact human-readable summary that lands in the CheckpointError
# reason string (and thus in execute_ratified_actions's ErrorRecord
# detail via `repr(exc)`). Falls through to None when the body shape
# doesn't match Pydantic v2's validation-error shape, so legacy
# Affordance-G semantics (custom `{error, detail: str, hint}`) keep
# their existing label downstream.
# Field-name fragments that indicate a secret-bearing value. Expanded
# per adversarial review wf_ed78d6f8 to cover the common credential
# vocabulary (pwd/pin/bearer/passphrase/cookie/session/cert/etc.) — the
# new 422-reason surface crosses three storage layers (workflow_runs →
# parked interrupts → RKA journal), so any field name fragment indicating
# secret content must redact.
_SECRET_LOC_HINTS: frozenset[str] = frozenset({
    "token", "key", "secret", "password", "auth", "api_key", "apikey",
    "credential", "credentials", "passphrase", "bearer", "pwd", "pin",
    "cookie", "session", "cert", "signature", "private",
})
_SUMMARY_MAX_CHARS: int = 500


def _summarize_422_detail(body: Any) -> str | None:
    """Render FastAPI's Pydantic-v2 validation-error list as a one-line
    summary, or return None if the body isn't that shape.

    Pydantic v2 422 shape: `{"detail": [{"type": "...", "loc": [...],
    "msg": "...", "input": ...}]}`. We extract `loc` (dot-joined,
    skipping the leading "body" segment), `input` (the offending
    value, redacted if loc looks like a secret), and `msg`. Multiple
    errors are joined with "; ". Total length is capped; overflow is
    indicated with "… +N more".

    Returns the empty string if the detail list is empty (degenerate
    Pydantic case) so callers can distinguish "no items" from
    "wrong shape entirely".
    """
    if not isinstance(body, dict):
        return None
    items = body.get("detail")
    if not isinstance(items, list):
        return None
    summaries: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            return None
        loc = item.get("loc")
        msg = item.get("msg")
        if not isinstance(loc, list) or not isinstance(msg, str):
            return None
        # Skip the leading "body" segment that FastAPI prepends.
        loc_segments = [str(s) for s in loc if s != "body"]
        field = ".".join(loc_segments) if loc_segments else "<root>"
        value = item.get("input")
        # Redact secrets if the field name looks sensitive.
        loc_lower = field.lower()
        is_secret = any(hint in loc_lower for hint in _SECRET_LOC_HINTS)
        if is_secret:
            value_repr = "<REDACTED>"
        else:
            value_repr = repr(value)
            # Cap individual input length so a giant pasted blob
            # doesn't dominate the summary.
            if len(value_repr) > 80:
                value_repr = value_repr[:77] + "..."
        summaries.append(f"{field}={value_repr} ({msg})")
    if not summaries:
        return ""
    joined = "; ".join(summaries)
    if len(joined) <= _SUMMARY_MAX_CHARS:
        return joined
    # Overflow: keep as many full entries as fit, then indicate
    # truncation.
    kept: list[str] = []
    running = 0
    for s in summaries:
        if running + len(s) + 2 > _SUMMARY_MAX_CHARS:
            break
        kept.append(s)
        running += len(s) + 2
    n_more = len(summaries) - len(kept)
    return "; ".join(kept) + f"… +{n_more} more"


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

    # Phase O O3.1 — hygiene checks. These are READ-side: no
    # workflow_thread_id auto-tagging needed.
    def rka_check_integrity(self) -> dict[str, Any]: ...
    def rka_check_freshness(self, days_threshold: int = 30) -> dict[str, Any]: ...
    def rka_get_pending_maintenance(self) -> dict[str, Any]: ...

    # v2.8.0 KB-wide verification + temporal currency reads (eval-v3).
    # All READ-side; no auto-tagging.
    def rka_collect_report_context(
        self, description: str, *, angle_queries: list[str] | None = None,
        max_nodes: int = 60,
    ) -> dict[str, Any]: ...
    def rka_mission_guard(self, mission_id: str) -> dict[str, Any]: ...
    def rka_staleness_impact(self, entity_id: str, *, max_depth: int = 3) -> dict[str, Any]: ...
    def rka_belief_as_of(self, date: str) -> dict[str, Any]: ...

    # Phase O O3.2 — claims surface (POST /api/claims). WRITE-side
    # (each claim is provenance for the plan that follows at O4).
    def rka_create_claim(
        self,
        *,
        source_entry_id: str,
        claim_type: str,
        content: str,
        confidence: float = 0.5,
    ) -> str: ...
    def rka_list_claims(
        self,
        *,
        source_entry_id: str | None = None,
        claim_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

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
    def rka_submit_checkpoint(self, *args: Any, **kwargs: Any) -> str: ...
    def rka_submit_report(self, *args: Any, **kwargs: Any) -> str: ...
    def rka_create_mission(
        self,
        objective: str,
        *,
        motivated_by_decision: str,
        acceptance_criteria: list[str],
        phase: str | None = None,
        scope_boundaries: str | None = None,
        depends_on: str | None = None,
        tags: list[str] | None = None,
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
    def rka_bulk_update(self, updates: list[dict]) -> str: ...

    # Phase-A2 (agentic) — additions matching the new WRITE_TOOLS entries.
    # Both methods auto-tag the workflow_thread_id into the `tags` list
    # (or set up a tags list if the caller didn't pass one).
    def rka_update_mission_status(
        self,
        id: str,
        *,
        status: str | None = None,
        tasks: list[dict] | None = None,
        report: dict | None = None,
        context: str | None = None,
        acceptance_criteria: str | None = None,
        scope_boundaries: str | None = None,
        checkpoint_triggers: str | None = None,
        depends_on: str | None = None,
        tags: list[str] | None = None,
    ) -> str: ...
    def rka_ingest_document(
        self,
        content: str,
        *,
        source: str = "brain",
        default_type: str = "finding",
        phase: str | None = None,
        tags: list[str] | None = None,
        related_literature: list[str] | None = None,
        related_decisions: list[str] | None = None,
        related_mission: str | None = None,
        split_by_headings: bool = True,
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
            # Phase-X² polish — surface structured FastAPI validation
            # detail in the CheckpointError reason string. Run-5's PA-2
            # failure was opaque ("knowledge-pack integrity"); the
            # actual 422 body carried `body.confidence='confirmed'` +
            # the valid-values list. Enrich the reason so the
            # ErrorRecord (via `repr(exc)` in execute_ratified_actions)
            # surfaces the actionable info. Fall through to the
            # legacy label for Affordance-G shapes (custom `{error,
            # detail: str, hint}`) so that semantic stays preserved.
            summary = _summarize_422_detail(detail)
            if summary:
                reason = (
                    f"RKA returned 422 (validation); path={path}; {summary}"
                )
            else:
                reason = (
                    f"RKA returned 422 (knowledge-pack integrity); "
                    f"path={path}"
                )
            raise CheckpointError(reason, mcp_response=detail)
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

    # Phase O O3.1 — hygiene checks.
    def rka_check_integrity(self) -> dict:
        """GET /api/integrity. Returns {'total_issues': N, 'issues': [...]}."""
        return self._request("GET", "/api/integrity") or {}

    def rka_check_freshness(self, days_threshold: int = 30) -> dict:
        """GET /api/freshness/check?days_threshold=N."""
        return self._request(
            "GET", "/api/freshness/check", params={"days_threshold": days_threshold}
        ) or {}

    def rka_get_pending_maintenance(self) -> dict:
        """GET /api/maintenance — flagged/pending maintenance items."""
        return self._request("GET", "/api/maintenance") or {}

    # v2.8.0 KB-wide verification + temporal currency reads (eval-v3).
    def rka_collect_report_context(
        self, description: str, *, angle_queries: list[str] | None = None,
        max_nodes: int = 60,
    ) -> dict:
        """POST /api/graph/report-context — multi-angle seed + provenance-
        weighted graph expansion. Returns {nodes, queries, seed_count, ...}."""
        body = _drop_none({
            "description": description,
            "angle_queries": angle_queries,
            "max_nodes": max_nodes,
        })
        return self._request("POST", "/api/graph/report-context", json=body) or {}

    def rka_mission_guard(self, mission_id: str) -> dict:
        """GET /api/missions/{id}/guard — negative knowledge (retracted /
        superseded / contradicted) relevant to a mission, for pickup."""
        return self._request("GET", f"/api/missions/{mission_id}/guard") or {}

    def rka_staleness_impact(self, entity_id: str, *, max_depth: int = 3) -> dict:
        """GET /api/graph/staleness-impact/{id} — downstream blast-radius of a
        stale entity (dependent-direction links only)."""
        return self._request(
            "GET", f"/api/graph/staleness-impact/{entity_id}",
            params={"max_depth": max_depth},
        ) or {}

    def rka_belief_as_of(self, date: str) -> dict:
        """GET /api/graph/as-of?date=ISO — believed-current knowledge state at
        a past date, plus what changed since."""
        return self._request("GET", "/api/graph/as-of", params={"date": date}) or {}

    # Phase O O3.2 — claims surface.
    def rka_create_claim(
        self,
        *,
        source_entry_id: str,
        claim_type: str,
        content: str,
        confidence: float = 0.5,
    ) -> str:
        """POST /api/claims — create one claim derived from a journal entry."""
        body = {
            "source_entry_id": source_entry_id,
            "claim_type": claim_type,
            "content": content,
            "confidence": confidence,
        }
        result = self._request("POST", "/api/claims", json=body) or {}
        return result.get("id") or result.get("clm_id") or ""

    def rka_list_claims(
        self,
        *,
        source_entry_id: str | None = None,
        claim_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """GET /api/claims with optional filters."""
        params: dict[str, Any] = {"limit": limit}
        if source_entry_id:
            params["source_entry_id"] = source_entry_id
        if claim_type:
            params["claim_type"] = claim_type
        result = self._request("GET", "/api/claims", params=params)
        return result if isinstance(result, list) else []

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

    def rka_submit_checkpoint(self, *args: Any, **kw: Any) -> str:
        """Submit a checkpoint via POST /api/checkpoints.

        Accepts BOTH the canonical RKA-MCP-tool arg shape (what the
        Brain LLM reads in tool docstrings) AND the legacy adapter shape
        (kept for backward-compat with pre-Phase-D2.4 callers). Common
        Brain-isms (`message` instead of `description`, `data` instead
        of structured context) are tolerated as aliases.

        Canonical RKA shape (rka_submit_checkpoint @ rka/mcp/server.py):
          mission_id (required)
          type ("decision" | "clarification" | "inspection" | "gate")
          description (required — the checkpoint message)
          task_reference, context, options, recommendation, blocking

        Legacy adapter shape (pre-Phase-D2.4):
          reason (positional), related_mission, type
          ^ Still works; `reason`→`description`, `related_mission`→`mission_id`.

        Brain-ism aliases tolerated:
          message → description    (the Brain LLM frequently emits 'message')
          content → description    (Phase-X²' polish — Brain extrapolates
                                    `content` as the universal "body
                                    field" name across WRITE_TOOLS;
                                    surfaced empirically on 2026-06-01
                                    hyperscaler-auditing PA-2 dispatch
                                    failure. Symmetric with
                                    `rka_submit_report` which has
                                    accepted `content` since Phase D2.4.
                                    The asymmetry between sibling
                                    EXECUTION_GATES tools was the bug.)
          data    → context        (Brain often packages structured fields here;
                                    we JSON-encode it into the `context` field
                                    so no data is lost)

        Phase-D2.4 fix (empirical follow-up from
        thr_19e790f90b4f9301179): the prior narrow signature
        `rka_submit_checkpoint(reason, *, type, related_mission)`
        rejected the Brain LLM's `{mission_id, message, blocking, data}`
        emission with TypeError("unexpected keyword argument
        'mission_id'"). This broadened signature accepts the shape Brain
        actually emits (matches the user-facing RKA MCP tool) while
        preserving the legacy entry point for any downstream caller
        that still uses it.
        """
        import json as _json

        # Pull the "description / message / reason / content" body from
        # any of the accepted argument shapes. The `content` alias was
        # added in Phase-X²' polish — symmetric with rka_submit_report.
        description = (
            kw.pop("description", None)
            or kw.pop("message", None)
            or kw.pop("reason", None)
            or kw.pop("content", None)
            or (args[0] if args else None)
        )
        if not description:
            raise ValueError(
                "rka_submit_checkpoint requires a description/message/"
                "reason/content"
            )

        mission_id = kw.pop("mission_id", None) or kw.pop("related_mission", None)
        if not mission_id:
            raise ValueError(
                "rka_submit_checkpoint requires mission_id (canonical) or "
                "related_mission (legacy) — both map to "
                "CheckpointCreate.mission_id, which is required by RKA's schema."
            )

        # Compose context from the workflow_thread_id auto-tag PLUS any
        # explicit context kwarg PLUS any `data` dict Brain bundles. The
        # workflow_thread_id is always prefixed so Affordance-F retrieval
        # works regardless of what shape Brain chose.
        ctx_parts: list[str] = []
        if self.workflow_thread_id:
            ctx_parts.append(f"workflow_thread_id: {self.workflow_thread_id}")
        explicit_ctx = kw.pop("context", None)
        if explicit_ctx:
            ctx_parts.append(str(explicit_ctx))
        data_payload = kw.pop("data", None)
        if data_payload is not None:
            try:
                ctx_parts.append("data:\n" + _json.dumps(data_payload, indent=2))
            except Exception:  # noqa: BLE001 — defensive serialization
                ctx_parts.append(f"data: {data_payload!r}")
        context = "\n\n".join(ctx_parts) if ctx_parts else None

        body = _drop_none(
            {
                "mission_id": mission_id,
                "type": kw.pop("type", None) or "decision",
                "description": description,
                "task_reference": kw.pop("task_reference", None),
                "context": context,
                "options": kw.pop("options", None),
                "recommendation": kw.pop("recommendation", None),
                "blocking": kw.pop("blocking", None),
            }
        )
        # Unknown kwargs are silently dropped — the WRITE_TOOLS surface is
        # already gated by `execute_ratified_actions`, so anything that
        # reached this adapter has been PI-ratified.
        result = self._request("POST", "/api/checkpoints", json=body) or {}
        return result.get("id") or ""

    def rka_submit_report(self, *args: Any, **kw: Any) -> str:
        """POST /api/missions/{mission}/report.

        Accepts BOTH the canonical RKA-MCP-tool arg shape AND the legacy
        adapter shape. The canonical shape (rka_submit_report @
        rka/mcp/server.py) is:
          mission_id (required)
          summary (required — full report body)
          findings, anomalies, questions, codebase_state,
          recommended_next (optional, str — one item per line)

        Legacy adapter shape (pre-Phase-D2.4):
          content (positional), related_mission

        Brain-ism aliases:
          content → summary  (legacy free-form content goes into summary)

        Each free-form field that arrives as a string is preserved as a
        single-element list when the REST schema expects a list, so
        Brain's emission shape lands intact in the report.

        Returns the mission_id under which the report was filed —
        reports are stored inline on missions; there's no separate
        report entity. Retrievable via GET /api/missions/{id}/report.

        Phase-D2.4 fix: the prior `(content, **kw)` signature rejected
        Brain's `{mission_id, summary, findings, anomalies, questions,
        codebase_state, recommended_next}` emission because no
        positional `content` arrived and `related_mission` was missing
        (Brain emitted `mission_id`). The same TypeError class that hit
        rka_submit_checkpoint.
        """
        # Pull the mission_id from canonical or legacy.
        mission = kw.pop("mission_id", None) or kw.pop("related_mission", None)
        if not mission:
            raise ValueError(
                "rka_submit_report requires mission_id (canonical) or "
                "related_mission (legacy)."
            )

        # Pull the summary/content (free-form body) from any accepted shape.
        summary = (
            kw.pop("summary", None)
            or kw.pop("content", None)
            or (args[0] if args else None)
            or ""
        )

        # Coerce each list-shaped field: REST schema accepts list[str] |
        # None for findings/anomalies/questions/recommended_next. The
        # canonical RKA MCP tool sends str (one item per line); the
        # legacy orchestrator path sometimes sends list[str]. Accept both.
        def _coerce_list(v: Any) -> list[str] | None:
            if v is None:
                return None
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()] or None
            if isinstance(v, str):
                lines = [ln.strip() for ln in v.strip().splitlines() if ln.strip()]
                return lines or None
            return [str(v)]

        # tasks_completed: anchor with the summary line so the report has
        # at least one task entry even if the caller didn't supply one.
        tasks_completed = kw.pop("tasks_completed", None)
        if not tasks_completed and summary:
            # Use the first line of the summary as a one-task anchor; the
            # full summary is preserved in findings if no other findings
            # were passed (legacy behavior).
            first_line = summary.strip().splitlines()[0] if summary else ""
            tasks_completed = [first_line] if first_line else [summary]
        if isinstance(tasks_completed, str):
            tasks_completed = _coerce_list(tasks_completed)

        findings = _coerce_list(kw.pop("findings", None))
        if not findings and summary and not kw.get("_summary_only"):
            # Legacy behavior: if no findings were passed, route the
            # free-form summary into findings so it lands somewhere
            # structured.
            findings = [summary]

        body = _drop_none(
            {
                "tasks_completed": tasks_completed,
                "findings": findings,
                "anomalies": _coerce_list(kw.pop("anomalies", None)),
                "questions": _coerce_list(kw.pop("questions", None)),
                "codebase_state": kw.pop("codebase_state", None),
                "recommended_next": kw.pop("recommended_next", None),
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
        phase: str | None = None,
        scope_boundaries: str | None = None,
        depends_on: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """POST /api/missions.

        Phase O4.2 (mis_…onboard-plan): grew optional kwargs to expose
        the full MissionCreate surface (phase, scope_boundaries,
        depends_on) so the auto-materialized milestone chain at
        pi_plan_ratify can express its DAG. Pre-Phase-O callers using
        the original 2-kwarg form (motivated_by_decision +
        acceptance_criteria) continue to work — the new kwargs default
        to None and are dropped from the JSON body via _drop_none.

        acceptance_criteria is passed as a list per the historical
        Phase 2.7 convention; the server's MissionCreate model accepts
        str | None so the list is currently rendered as a one-element
        JSON array. (Not breaking anything that already shipped.)
        """
        merged_tags = list(tags or [])
        if self.workflow_thread_id and self.workflow_thread_id not in merged_tags:
            merged_tags.append(self.workflow_thread_id)
        body = _drop_none(
            {
                "objective": objective,
                "motivated_by_decision": motivated_by_decision,
                "acceptance_criteria": list(acceptance_criteria),
                "phase": phase,
                "scope_boundaries": scope_boundaries,
                "depends_on": depends_on,
                "tags": merged_tags,
            }
        )
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

    def rka_bulk_update(self, updates: list[dict]) -> str:
        """Bulk-update multiple entities; fan out to per-entity REST endpoints.

        Phase 2.13 (mis_01KRYZMEAT01SMNNXQXS3JRC4W T1; per
        dec_01KRYZGF8N1SNJX5TSP0GM77Z7 Option A) — closes the 10th trigger
        surfaced empirically by Phase 2.12 (`mis_01KRYVYZ42H0ETXMYRE7318KM4`):
        the brain LLM methodologically chose `rka_bulk_update` for
        cross-reference hygiene (the target journal's own Provenance section
        documents using it for the same target journals), but the orchestrator
        had no Protocol method and Phase 2.7 Option C correctly rejected the
        ratified action.

        WHY a fanout adapter (not a thin single-endpoint wrapper): RKA does
        NOT expose a single bulk REST endpoint. The MCP tool
        `rka/mcp/server.py:rka_bulk_update` is itself the fanout layer — it
        iterates the `updates` list and dispatches to `PUT /api/notes/{id}`
        (note/journal), `PUT /api/decisions/{id}` (decision), or
        `PUT /api/literature/{id}` (literature). This RestMCPClient method
        mirrors that fanout loop against the same per-entity endpoints. The
        endpoint-map and per-item error-aggregation shape are duplicated
        from `rka/mcp/server.py:938-993`; if RKA extends the fanout (new
        entity_type), both must update in lockstep. Phase 2.15+ may extract
        the shared shape into a utility, but that requires touching `rka/`
        which is outside the agentic branch's scope.

        Args:
            updates: list of `{"entity_type", "id", "data"}` dicts. Each
                `data` is the entity-specific PUT body. `entity_type` is one
                of `note` | `journal` | `decision` | `literature`.

        Returns:
            Multi-line summary string mirroring the MCP tool's return shape
            (e.g. `"Updated 3/3\\n\\nSuccesses:\\n[0] note jrn_... OK"`).
            execute_ratified_actions stores this in the ArtifactRef.rka_id
            field; the `bulk` entity_type label (see
            `_WRITE_TOOL_ENTITY_TYPES` in nodes/executor.py) tags the
            artifact so the run-artifact JSON ledger preserves provenance.

        Workflow-thread-id auto-tagging: when an update's
            `data["tags"]` is provided, the workflow_thread_id is appended;
            when omitted, tags are left untouched (preserves existing tags
            on the entity, mirroring rka_update_note semantics).
        """
        endpoint_map = {
            "note": "/api/notes/{eid}",
            "journal": "/api/notes/{eid}",
            "decision": "/api/decisions/{eid}",
            "literature": "/api/literature/{eid}",
        }
        results: list[str] = []
        errors: list[str] = []
        for i, upd in enumerate(updates):
            etype = upd.get("entity_type")
            eid = upd.get("id")
            data = dict(upd.get("data") or {})

            if not etype or not eid:
                errors.append(f"[{i}] missing entity_type or id")
                continue

            endpoint_template = endpoint_map.get(etype)
            if not endpoint_template:
                errors.append(f"[{i}] unknown entity_type: {etype}")
                continue

            if "tags" in data and data["tags"] is not None:
                data["tags"] = _merge_workflow_tag(
                    data["tags"], self.workflow_thread_id
                )

            endpoint = endpoint_template.format(eid=eid)
            try:
                self._request("PUT", endpoint, json=data)
                results.append(f"[{i}] {etype} {eid} OK")
            except Exception as e:  # noqa: BLE001 — mirror MCP-side per-item aggregation
                errors.append(f"[{i}] {etype} {eid} -> error: {str(e)[:100]}")

        summary = f"Updated {len(results)}/{len(updates)}"
        if errors:
            summary += f" ({len(errors)} errors)"
        lines = [summary, ""]
        if results:
            lines.append("Successes:")
            lines.extend(results[:20])
            if len(results) > 20:
                lines.append(f"  ... and {len(results) - 20} more")
        if errors:
            lines.append("Errors:")
            lines.extend(errors)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Phase-A2 (agentic) — WRITE_TOOLS expansion: mission lifecycle +
    # structured single-call document ingestion. Both surfaced empirically
    # during the IoT-edge-LLM Phase-1 test mission, where the Brain
    # proposed these tools (real, exposed by the rka MCP server) but
    # execute_ratified_actions correctly rejected them because they were
    # not in WRITE_TOOLS. PI-ratified expansion lands them here.
    # ------------------------------------------------------------------

    def rka_update_mission_status(self, id: str, **kw: Any) -> str:
        """PUT /api/missions/{mis_id} — mission lifecycle update.

        Used by the Brain to mark a mission active/complete and to record
        task progress as the workflow advances. Status-only writes have
        no content-risk; full-field writes (objective change, scope
        boundary updates) inherit the PI ratification gate just like any
        WRITE_TOOL.

        Workflow_thread_id auto-tagging: when `tags` is provided, the
        thread id is appended; when omitted, tags are left untouched.
        """
        if not id:
            raise ValueError("rka_update_mission_status requires a non-empty mission id")
        body = _drop_none(
            {
                "status": kw.get("status"),
                "tasks": kw.get("tasks"),
                "report": kw.get("report"),
                "context": kw.get("context"),
                "acceptance_criteria": kw.get("acceptance_criteria"),
                "scope_boundaries": kw.get("scope_boundaries"),
                "checkpoint_triggers": kw.get("checkpoint_triggers"),
                "depends_on": kw.get("depends_on"),
                "tags": (
                    _merge_workflow_tag(kw["tags"], self.workflow_thread_id)
                    if kw.get("tags") is not None
                    else None
                ),
            }
        )
        result = self._request("PUT", f"/api/missions/{id}", json=body) or {}
        return result.get("id") or id

    def rka_ingest_document(self, content: str, **kw: Any) -> str:
        """POST /api/ingest/document — single-call structured document ingest.

        Brain alternative to rka_add_note when the content is a single
        cohesive document (synthesis, gap map, lit review) that should
        land as a journal entry without manual splitting. The rka side
        of this endpoint can optionally split by heading boundaries
        (`split_by_headings=True`, default) — when used through the
        orchestrator we typically want a single unified entry, so the
        Protocol default flips to False at the caller site if needed.

        Returns the created journal id. If split_by_headings produces
        multiple entries, only the primary id is returned (callers
        wanting per-section ids should pre-split and use rka_add_note).

        Workflow_thread_id auto-tagging: applies unconditionally — if
        the caller passes `tags`, the thread id is appended; if not,
        a fresh tag list is created with just the thread id. (Differs
        from rka_update_note's "leave-alone" semantics because this is
        a CREATE operation, not an update.)
        """
        if not content or not content.strip():
            raise ValueError("rka_ingest_document requires non-empty content")
        body = _drop_none(
            {
                "content": content,
                "source": kw.get("source") or "brain",
                "default_type": kw.get("default_type") or "finding",
                "phase": kw.get("phase"),
                "tags": _merge_workflow_tag(
                    kw.get("tags") or [], self.workflow_thread_id
                ),
                "related_literature": kw.get("related_literature"),
                "related_decisions": kw.get("related_decisions"),
                "related_mission": kw.get("related_mission"),
                "split_by_headings": kw.get("split_by_headings", True),
            }
        )
        result = self._request("POST", "/api/ingest/document", json=body) or {}
        # Endpoint returns either {"id": "..."} for single or
        # {"ids": [...]} for split-by-headings. Take the first as the
        # canonical artifact id for the dispatcher's ArtifactRef.
        if "id" in result:
            return result["id"]
        if "ids" in result and result["ids"]:
            return result["ids"][0]
        # Fall back to a synthetic marker the dispatcher can store.
        return "ingest_document_no_id_returned"


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
