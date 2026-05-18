"""Shared test doubles for node tests (T3-T6).

These honor the SDKClient + MCPClient Protocols. Fakes record every call
so tests can assert prompt content, RKA write sequence, tag floors, and
workflow_thread_id propagation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeSDK:
    """Records every `complete()` call; returns the canned reply."""

    canned_reply: str = "fake LLM reply"
    calls: list[dict] = field(default_factory=list)

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> str:
        self.calls.append({"prompt": prompt, "max_tokens": max_tokens, "system": system})
        return self.canned_reply


@dataclass
class FakeMCP:
    """In-memory MCP double supporting the 13-tool surface."""

    workflow_thread_id: str = "thr_test_abc"
    note_counter: int = 0
    decision_counter: int = 0
    report_counter: int = 0
    mission_counter: int = 0
    checkpoint_counter: int = 0
    calls: list[dict] = field(default_factory=list)
    status_response: dict = field(default_factory=lambda: {"phase": "design"})
    context_response: dict = field(default_factory=lambda: {"recent": []})
    research_map_response: dict = field(default_factory=lambda: {"clusters": []})
    journal_response: dict = field(default_factory=lambda: {"entries": []})
    mission_response: dict = field(default_factory=lambda: {"id": "mis_test", "status": "active"})
    checkpoints_response: list = field(default_factory=list)

    def _record(self, op: str, **kw: Any) -> None:
        self.calls.append({"op": op, **kw})

    # --- reads ---
    def rka_get_status(self) -> dict:
        self._record("rka_get_status")
        return self.status_response

    def rka_get_context(self, topic: str | None = None, limit: int = 10) -> dict:
        self._record("rka_get_context", topic=topic, limit=limit)
        return self.context_response

    def rka_get_research_map(self) -> dict:
        self._record("rka_get_research_map")
        return self.research_map_response

    def rka_get_journal(self, *, tags: list[str] | None = None, limit: int = 20) -> dict:
        self._record("rka_get_journal", tags=tags, limit=limit)
        return self.journal_response

    def rka_get_mission(self, id: str | None = None) -> dict:
        self._record("rka_get_mission", id=id)
        return self.mission_response

    def rka_get_checkpoints(self, status: str = "open") -> list:
        self._record("rka_get_checkpoints", status=status)
        return self.checkpoints_response

    def rka_search(self, query: str, *, limit: int = 10) -> list:
        self._record("rka_search", query=query, limit=limit)
        return []

    def rka_get(self, id: str) -> dict:
        self._record("rka_get", id=id)
        return {"id": id}

    def rka_trace_provenance(self, id: str) -> dict:
        self._record("rka_trace_provenance", id=id)
        return {"id": id, "ancestors": []}

    # --- writes ---
    def rka_add_note(self, content: str, **kwargs: Any) -> str:
        self.note_counter += 1
        rid = f"jrn_fake_{self.note_counter:03d}"
        self._record("rka_add_note", content=content, note_id=rid, **kwargs)
        return rid

    def rka_add_decision(self, content: str, **kwargs: Any) -> str:
        self.decision_counter += 1
        rid = f"dec_fake_{self.decision_counter:03d}"
        self._record("rka_add_decision", content=content, decision_id=rid, **kwargs)
        return rid

    def rka_submit_checkpoint(self, reason: str, **kwargs: Any) -> str:
        self.checkpoint_counter += 1
        rid = f"chk_fake_{self.checkpoint_counter:03d}"
        self._record("rka_submit_checkpoint", reason=reason, checkpoint_id=rid, **kwargs)
        return rid

    def rka_submit_report(self, content: str, **kwargs: Any) -> str:
        self.report_counter += 1
        rid = f"rep_fake_{self.report_counter:03d}"
        self._record("rka_submit_report", content=content, report_id=rid, **kwargs)
        return rid

    def rka_create_mission(self, objective: str, **kwargs: Any) -> str:
        self.mission_counter += 1
        rid = f"mis_fake_{self.mission_counter:03d}"
        self._record("rka_create_mission", objective=objective, mission_id=rid, **kwargs)
        return rid

    def rka_update_note(self, id: str, **kwargs: Any) -> str:
        """Phase 2.7 T3a: matches the Protocol addition. Records the call so
        tests can assert which note IDs received which updates."""
        self._record("rka_update_note", id=id, **kwargs)
        return id
