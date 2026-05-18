"""Unit tests for the RestMCPClient (T9).

These exercise the URL + body construction for all 13 RKA tools and the
Affordance-G 422 → CheckpointError path. The HTTP layer is mocked via
a small Fake httpx.Client so tests run offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from orchestrator.mcp_client import (
    CheckpointError,
    RestMCPClient,
    _drop_none,
    _merge_workflow_tag,
    make_client,
)


@dataclass
class FakeResp:
    status_code: int = 200
    _json: Any = None
    text: str = ""
    content: bytes = b"{}"

    def json(self):
        if self._json is None:
            return {}
        return self._json

    def raise_for_status(self):
        if 400 <= self.status_code < 600:
            raise RuntimeError(f"HTTP {self.status_code}")


@dataclass
class FakeHttp:
    """Captures (method, path, json, params) per call; returns a canned resp."""

    canned: FakeResp = field(default_factory=lambda: FakeResp(_json={"id": "jrn_fake_001"}))
    calls: list[dict] = field(default_factory=list)

    def request(self, method, path, *, json=None, params=None):
        self.calls.append({"method": method, "path": path, "json": json, "params": params})
        return self.canned


def _client(http: FakeHttp | None = None, **kw) -> RestMCPClient:
    return RestMCPClient(
        base_url="http://x",
        workflow_thread_id="thr_t9",
        http_client=http or FakeHttp(),
        **kw,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_merge_workflow_tag_appends_when_missing():
    out = _merge_workflow_tag(["a", "b"], "thr_x")
    assert out == ["a", "b", "thr_x"]


def test_merge_workflow_tag_dedupes():
    out = _merge_workflow_tag(["a", "thr_x"], "thr_x")
    assert out == ["a", "thr_x"]


def test_merge_workflow_tag_handles_none():
    out = _merge_workflow_tag(None, "thr_x")
    assert out == ["thr_x"]


def test_drop_none_removes_none_values():
    assert _drop_none({"a": 1, "b": None, "c": 0}) == {"a": 1, "c": 0}


# ---------------------------------------------------------------------------
# Read methods
# ---------------------------------------------------------------------------


def test_rka_get_status_issues_get():
    http = FakeHttp(canned=FakeResp(_json={"phase": "design"}))
    c = _client(http)
    out = c.rka_get_status()
    assert out == {"phase": "design"}
    assert http.calls[0]["method"] == "GET"
    assert http.calls[0]["path"] == "/api/status"


def test_rka_get_context_posts_with_body():
    # The /api/context route is POST with topic+limit in the JSON body
    # (discovered during T12 pilot — fixed in mcp_client.py).
    http = FakeHttp(canned=FakeResp(_json={"recent": []}))
    c = _client(http)
    c.rka_get_context(topic="orchestrator", limit=5)
    call = http.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/api/context"
    assert call["json"] == {"topic": "orchestrator", "limit": 5}


def test_rka_get_journal_hits_notes_endpoint_with_client_side_tag_filter():
    """Phase 2.10 T1 (mis_01KRYBZ0W4Z9F1GXKP96ERKGKK; discharge of Phase 2.9
    T3 debt per jrn_01KRY908A3RYX1TBH6CKKPJRGC):

    - The endpoint is `/api/notes` (REST surface), NOT `/api/journal` (web
      UI HTML route).
    - REST `/api/notes` does NOT accept a `tags` query param — filtering
      happens CLIENT-SIDE post-fetch. The request `params` should NOT
      contain `tags`.
    - Return shape is `list[dict]` (matching the REST surface), not
      `dict[str, Any]`.

    The pre-Phase-2.10 test asserted CSV-joined tags get sent in params;
    that assumed the (broken) endpoint behavior. The new test locks the
    corrected contract."""
    # Two notes; one carries the tag, one doesn't. Client-side filter
    # should return only the tagged one.
    canned_response = [
        {"id": "jrn_a", "type": "log", "tags": ["target-tag", "other"]},
        {"id": "jrn_b", "type": "log", "tags": ["unrelated"]},
    ]
    http = FakeHttp(canned=FakeResp(_json=canned_response))
    c = _client(http)
    result = c.rka_get_journal(tags=["target-tag"], limit=10)

    # Endpoint check: hits /api/notes, NOT /api/journal.
    assert http.calls[0]["path"] == "/api/notes", (
        f"Phase 2.10 T1: rka_get_journal must hit /api/notes (REST surface), "
        f"not /api/journal (web UI HTML); got path={http.calls[0]['path']!r}"
    )
    # Tags NOT in request params — filtered client-side.
    assert "tags" not in (http.calls[0]["params"] or {}), (
        "Phase 2.10 T1: REST /api/notes doesn't accept tags query param; "
        "filter must be client-side post-fetch"
    )
    # Limit IS still sent.
    assert http.calls[0]["params"]["limit"] == 10
    # Return shape: list filtered to matching entries.
    assert isinstance(result, list), (
        f"Phase 2.10 T1: return shape must be list[dict] not {type(result).__name__}"
    )
    assert len(result) == 1
    assert result[0]["id"] == "jrn_a"


def test_rka_get_journal_no_tags_returns_all_notes():
    """When `tags=None` (or empty), return the full list with no client-side filter."""
    canned_response = [
        {"id": "jrn_a", "tags": ["x"]},
        {"id": "jrn_b", "tags": ["y"]},
    ]
    http = FakeHttp(canned=FakeResp(_json=canned_response))
    c = _client(http)
    result = c.rka_get_journal(limit=20)
    assert isinstance(result, list)
    assert len(result) == 2


def test_rka_get_journal_handles_non_list_response_gracefully():
    """Defensive: if the REST endpoint returns a non-list (None, dict, str),
    return an empty list rather than crashing the caller."""
    # None response
    http = FakeHttp(canned=FakeResp(_json=None))
    c = _client(http)
    result = c.rka_get_journal()
    assert result == []

    # Unexpected dict response
    http = FakeHttp(canned=FakeResp(_json={"unexpected": "shape"}))
    c = _client(http)
    result = c.rka_get_journal()
    assert result == []


def test_rka_get_mission_default_active():
    http = FakeHttp()
    c = _client(http)
    c.rka_get_mission()
    assert http.calls[0]["path"] == "/api/missions/active"


def test_rka_get_mission_by_id():
    http = FakeHttp()
    c = _client(http)
    c.rka_get_mission(id="mis_xyz")
    assert http.calls[0]["path"] == "/api/missions/mis_xyz"


def test_rka_search_posts_query_body():
    http = FakeHttp(canned=FakeResp(_json=[]))
    c = _client(http)
    c.rka_search("provenance trail", limit=5)
    call = http.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/api/search"
    assert call["json"] == {"query": "provenance trail", "limit": 5}


def test_rka_get_checkpoints_passes_status():
    http = FakeHttp(canned=FakeResp(_json=[]))
    c = _client(http)
    c.rka_get_checkpoints(status="open")
    assert http.calls[0]["params"]["status"] == "open"


# ---------------------------------------------------------------------------
# Write methods — workflow_thread_id auto-tagging
# ---------------------------------------------------------------------------


def test_rka_add_note_auto_tags_workflow_thread_id():
    http = FakeHttp(canned=FakeResp(_json={"id": "jrn_001"}))
    c = _client(http)
    note_id = c.rka_add_note("hello", tags=["custom"])
    assert note_id == "jrn_001"
    body = http.calls[0]["json"]
    assert "thr_t9" in body["tags"]
    assert "custom" in body["tags"]


def test_rka_add_note_default_tags_just_workflow_id():
    http = FakeHttp(canned=FakeResp(_json={"id": "jrn_002"}))
    c = _client(http)
    c.rka_add_note("hello")
    body = http.calls[0]["json"]
    assert body["tags"] == ["thr_t9"]


def test_rka_add_decision_carries_workflow_tag():
    http = FakeHttp(canned=FakeResp(_json={"id": "dec_001"}))
    c = _client(http)
    out = c.rka_add_decision("draft content", related_journal=["jrn_a"])
    assert out == "dec_001"
    body = http.calls[0]["json"]
    assert body["related_journal"] == ["jrn_a"]
    assert "thr_t9" in body["tags"]
    # T12-discovered: REST DecisionCreate requires question/decided_by/phase
    assert body["question"]
    assert body["decided_by"] == "pi"
    assert body["phase"] == "design"


def test_rka_add_decision_maps_content_to_question_and_rationale():
    http = FakeHttp(canned=FakeResp(_json={"id": "dec_002"}))
    c = _client(http)
    c.rka_add_decision(
        "Q: Should Phase 2 proceed?\nDetails: ...",
        related_journal=["jrn_x"],
    )
    body = http.calls[0]["json"]
    # First-line → question (truncated to 280)
    assert body["question"].startswith("Q: Should Phase 2 proceed?")
    # Full text → rationale
    assert "Details" in body["rationale"]


def test_rka_submit_checkpoint_payload_matches_current_rka_schema():
    """Phase 2.1 (mis_01KRSTZVCTFGF91QZXTYK7ZGDD T2): the orchestrator's
    payload must match RKA's CheckpointCreate schema (Mission C v2.3.4
    added `extra="forbid"`). Pre-fix it sent {reason, related_mission,
    tags} which were all rejected — the v2.5.3+agentic-rc1 422 cascade.
    Post-fix it sends {description, mission_id, type, context}.
    """
    http = FakeHttp(canned=FakeResp(_json={"id": "chk_001"}))
    c = _client(http)
    out = c.rka_submit_checkpoint(
        "reason text",
        type="decision",
        related_mission="mis_xyz",
    )
    assert out == "chk_001"
    body = http.calls[0]["json"]
    # Schema-correct keys present:
    assert body["mission_id"] == "mis_xyz"
    assert body["description"] == "reason text"
    assert body["type"] == "decision"
    # Workflow tag folded into context (CheckpointCreate has no `tags`):
    assert "thr_t9" in (body.get("context") or "")
    # Pre-v2.5.3+agentic-rc1 field names MUST NOT appear (extra="forbid"
    # would reject them):
    assert "reason" not in body
    assert "related_mission" not in body
    assert "tags" not in body


def test_rka_submit_checkpoint_requires_related_mission():
    """`related_mission` maps to RKA's required `mission_id`. Caller-side
    validation surfaces the missing-arg cleanly rather than letting RKA
    return a 422."""
    c = _client()
    with pytest.raises(ValueError, match="related_mission"):
        c.rka_submit_checkpoint("reason text", type="decision")


def test_rka_submit_checkpoint_surfaces_422_with_structured_detail():
    """If RKA returns a 422 (Affordance-G body), the CheckpointError must
    carry the structured detail in `mcp_response` for downstream debugging.
    Confirms the existing `_request` 422 handling stays wired."""
    affordance_g_body = {
        "error": "checkpoint_invalid_payload",
        "detail": "field `mission_id` is required",
        "hint": "send {'mission_id': 'mis_...', 'type': '...', 'description': '...'}",
    }
    http = FakeHttp(
        canned=FakeResp(status_code=422, _json=affordance_g_body, content=b"x"),
    )
    c = _client(http)
    with pytest.raises(CheckpointError) as exc_info:
        c.rka_submit_checkpoint(
            "reason text", type="decision", related_mission="mis_xyz"
        )
    err = exc_info.value
    assert "422" in str(err)
    # The body is preserved on .mcp_response for the escalation_router /
    # debugging to inspect.
    assert err.mcp_response == affordance_g_body


def test_rka_submit_report_requires_mission():
    c = _client()
    with pytest.raises(ValueError):
        c.rka_submit_report("x")


def test_rka_submit_report_targets_mission_path():
    http = FakeHttp(canned=FakeResp(_json={"id": "rep_001"}))
    c = _client(http)
    c.rka_submit_report("report content", related_mission="mis_xyz")
    call = http.calls[0]
    # Discovered during T12 pilot: /report is singular in the REST surface;
    # request body uses structured fields only (no `content`, `summary`,
    # `tags` per MissionReportCreate schema). Free-form `content` is
    # remapped to findings[0] for compatibility.
    assert call["path"] == "/api/missions/mis_xyz/report"
    assert call["json"]["findings"] == ["report content"]
    assert "content" not in call["json"]
    assert "summary" not in call["json"]
    assert "tags" not in call["json"]


def test_rka_create_mission_carries_decision_link():
    http = FakeHttp(canned=FakeResp(_json={"id": "mis_001"}))
    c = _client(http)
    out = c.rka_create_mission(
        "objective",
        motivated_by_decision="dec_abc",
        acceptance_criteria=["A1", "A2"],
    )
    assert out == "mis_001"
    body = http.calls[0]["json"]
    assert body["motivated_by_decision"] == "dec_abc"
    assert body["acceptance_criteria"] == ["A1", "A2"]


# ---------------------------------------------------------------------------
# project_id propagation
# ---------------------------------------------------------------------------


def test_project_id_appears_in_every_call():
    http = FakeHttp(canned=FakeResp(_json={"id": "jrn_001"}))
    c = _client(http, project_id="prj_abc")
    c.rka_get_status()
    c.rka_add_note("x")
    for call in http.calls:
        assert call["params"]["project_id"] == "prj_abc"


def test_no_project_id_means_no_project_id_param():
    http = FakeHttp(canned=FakeResp(_json={"id": "jrn_001"}))
    c = _client(http)  # no project_id
    c.rka_get_status()
    # params dict should be empty
    assert "project_id" not in (http.calls[0]["params"] or {})


# ---------------------------------------------------------------------------
# Affordance G — 422 KnowledgePackIntegrityError → CheckpointError
# ---------------------------------------------------------------------------


def test_422_maps_to_checkpoint_error():
    http = FakeHttp(canned=FakeResp(status_code=422, _json={"detail": "integrity"}, content=b"{}"))
    c = _client(http)
    with pytest.raises(CheckpointError) as exc_info:
        c.rka_add_note("x")
    assert "422" in str(exc_info.value)
    assert exc_info.value.mcp_response == {"detail": "integrity"}


def test_500_does_not_map_to_checkpoint_error():
    # Other errors raise the generic HTTPStatusError-like exception.
    http = FakeHttp(canned=FakeResp(status_code=500, _json={}, content=b"{}"))
    c = _client(http)
    with pytest.raises(RuntimeError):
        c.rka_add_note("x")


# ---------------------------------------------------------------------------
# Factory + Protocol compliance
# ---------------------------------------------------------------------------


def test_make_client_returns_rest_implementation():
    client = make_client(workflow_thread_id="thr_test")
    assert isinstance(client, RestMCPClient)
    assert client.workflow_thread_id == "thr_test"


def test_rest_mcp_client_satisfies_protocol_surface():
    # Spot-check that the documented methods exist on the impl. Phase 2.7 T3a
    # added `rka_update_note` to the Protocol (14 methods now; was 13 in Phase 1).
    c = _client()
    for name in (
        "rka_search",
        "rka_get",
        "rka_get_context",
        "rka_get_journal",
        "rka_get_research_map",
        "rka_get_mission",
        "rka_add_note",
        "rka_add_decision",
        "rka_create_mission",
        "rka_submit_checkpoint",
        "rka_submit_report",
        "rka_get_checkpoints",
        "rka_trace_provenance",
        "rka_update_note",   # Phase 2.7 T3a addition
    ):
        assert hasattr(c, name), f"RestMCPClient is missing {name}"


# ---------------------------------------------------------------------------
# Phase 2.7 T3a — `rka_update_note` REST contract
# ---------------------------------------------------------------------------


def test_rka_update_note_issues_put_to_correct_path():
    """The endpoint discovered via /openapi.json is PUT /api/notes/{note_id}."""
    http = FakeHttp(canned=FakeResp(_json={"id": "jrn_fake_001"}))
    c = _client(http)
    returned_id = c.rka_update_note(
        "jrn_target_001",
        related_decisions=["dec_a", "dec_b"],
    )
    # PUT to the correct path.
    assert len(http.calls) == 1
    call = http.calls[0]
    assert call["method"] == "PUT"
    assert call["path"] == "/api/notes/jrn_target_001"
    # Body carries the structured update fields; None-valued kwargs elided.
    body = call["json"] or {}
    assert body.get("related_decisions") == ["dec_a", "dec_b"]
    # workflow_thread_id was merged onto tags ONLY if tags is provided (None preserves).
    assert "tags" not in body
    # Returns the REST response id, falling back to input id if missing.
    assert returned_id == "jrn_fake_001"


def test_rka_update_note_falls_back_to_input_id_when_response_empty():
    """If the REST response is empty, return the input id so callers can
    still confirm via a follow-up rka_get."""
    http = FakeHttp(canned=FakeResp(_json={}))
    c = _client(http)
    returned_id = c.rka_update_note("jrn_target_002", content="updated")
    assert returned_id == "jrn_target_002"


def test_rka_update_note_merges_workflow_tag_when_tags_provided():
    http = FakeHttp(canned=FakeResp(_json={"id": "jrn_x"}))
    c = _client(http)
    c.rka_update_note("jrn_target_003", tags=["existing-tag"])
    body = http.calls[0]["json"] or {}
    # Both the original tag and the workflow_thread_id are present.
    assert "existing-tag" in body["tags"]
    assert "thr_t9" in body["tags"]


def test_rka_update_note_rejects_empty_id():
    c = _client()
    with pytest.raises(ValueError, match="non-empty note id"):
        c.rka_update_note("")


# ---------------------------------------------------------------------------
# Phase 2.7 T5 — rka_submit_report return-value contract (mission_id, NOT rep_*)
# (jrn_01KRXQJJXKRAH1GB6FTZEQDAXQ triage — RKA stores reports inline on
#  missions; no separate Report entity exists in the data model)
# ---------------------------------------------------------------------------


def test_rka_submit_report_returns_mission_id_not_rep_prefix():
    """The REST endpoint `POST /api/missions/{mis_id}/report` returns the
    mission object (schema=Mission) with `id=mission_id`. There is no
    `rep_*` prefix in the RKA data model. Phase 2.7 T5 locks the
    orchestrator's understanding of this contract — `final_report_id` is
    the mission_id under which the report was filed, NOT a fresh entity
    id with `rep_` prefix."""
    http = FakeHttp(canned=FakeResp(_json={"id": "mis_target_01ABC"}))
    c = _client(http)
    returned = c.rka_submit_report(
        "report body text",
        related_mission="mis_target_01ABC",
    )
    # The mission_id is echoed back — this IS the contract.
    assert returned == "mis_target_01ABC"
    assert not returned.startswith("rep_"), (
        "Phase 2.7 T5: RKA's data model does not mint rep_* IDs for "
        "reports. They live inline on missions. The `final_report_id` "
        "field carries the mission_id under which the report was filed."
    )
