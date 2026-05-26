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
    # Phase 2.10 T1 (mis_01KRYBZ0W4Z9F1GXKP96ERKGKK): aligned with real
    # RestMCPClient.rka_get_journal shape. Was `dict={"entries": []}`
    # (wrong shape that masked the upstream bug for multiple phases);
    # now `list[dict]` matching the live REST `/api/notes` surface.
    journal_response: list = field(default_factory=list)
    mission_response: dict = field(default_factory=lambda: {"id": "mis_test", "status": "active"})
    checkpoints_response: list = field(default_factory=list)
    # Phase O O3.1 — hygiene-check responses. Default to clean (no issues).
    integrity_response: dict = field(
        default_factory=lambda: {"total_issues": 0, "issues": []}
    )
    freshness_response: dict = field(default_factory=lambda: {"stale_entries": []})
    pending_maintenance_response: dict = field(
        default_factory=lambda: {"items": []}
    )
    # Phase O O3.2 — claims surface.
    claim_counter: int = 0
    claims_response: list = field(default_factory=list)

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

    def rka_get_journal(
        self, *, tags: list[str] | None = None, limit: int = 20
    ) -> list[dict]:
        """Phase 2.10 T1: return type aligned with real RestMCPClient.
        Client-side tag filter applied to match real REST behavior (REST
        `/api/notes` doesn't accept a `tags` query param). Tests can
        populate `journal_response` with a list of note dicts; tag filter
        applies before return."""
        self._record("rka_get_journal", tags=tags, limit=limit)
        if not tags:
            return self.journal_response
        wanted = set(tags)
        return [
            n for n in self.journal_response
            if wanted.issubset(set(n.get("tags") or []))
        ]

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

    # Phase O O3.1 — hygiene checks.
    def rka_check_integrity(self) -> dict:
        self._record("rka_check_integrity")
        return self.integrity_response

    def rka_check_freshness(self, days_threshold: int = 30) -> dict:
        self._record("rka_check_freshness", days_threshold=days_threshold)
        return self.freshness_response

    def rka_get_pending_maintenance(self) -> dict:
        self._record("rka_get_pending_maintenance")
        return self.pending_maintenance_response

    # Phase O O3.2 — claims surface.
    def rka_create_claim(
        self,
        *,
        source_entry_id: str,
        claim_type: str,
        content: str,
        confidence: float = 0.5,
    ) -> str:
        self.claim_counter += 1
        rid = f"clm_fake_{self.claim_counter:03d}"
        self._record(
            "rka_create_claim",
            source_entry_id=source_entry_id,
            claim_type=claim_type,
            content=content,
            confidence=confidence,
            claim_id=rid,
        )
        return rid

    def rka_list_claims(
        self,
        *,
        source_entry_id: str | None = None,
        claim_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        self._record(
            "rka_list_claims",
            source_entry_id=source_entry_id,
            claim_type=claim_type,
            limit=limit,
        )
        return self.claims_response

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
        """Phase 2.7 T5 (jrn_01KRXQJJXKRAH1GB6FTZEQDAXQ): aligned with the real
        RestMCPClient contract. RKA stores reports inline on missions —
        there is no separate `Report` entity. The return value is the
        mission_id under which the report was filed, mirroring what the
        live `POST /api/missions/{id}/report` endpoint returns. Phase 2.5
        FakeMCP used a `rep_fake_NNN` prefix that was never accurate."""
        self.report_counter += 1
        mission_id = kwargs.get("related_mission") or f"mis_fake_unknown_{self.report_counter:03d}"
        self._record("rka_submit_report", content=content, report_id=mission_id, **kwargs)
        return mission_id

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

    def rka_bulk_update(self, updates: list[dict]) -> str:
        """Phase 2.13 T1 (mis_01KRYZMEAT01SMNNXQXS3JRC4W): matches the Protocol
        addition for the bulk-update fanout. Records the call (with the full
        updates list under `updates`) so tests can assert which entity IDs
        received which updates. Returns a summary string mirroring the real
        RestMCPClient.rka_bulk_update shape."""
        self._record("rka_bulk_update", updates=updates)
        n = len(updates)
        return f"Updated {n}/{n}"
