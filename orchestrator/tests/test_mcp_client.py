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


def test_rka_get_journal_joins_tags_csv():
    http = FakeHttp(canned=FakeResp(_json={"entries": []}))
    c = _client(http)
    c.rka_get_journal(tags=["a", "b"], limit=10)
    assert http.calls[0]["params"]["tags"] == "a,b"


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


def test_rka_submit_checkpoint_carries_workflow_tag():
    http = FakeHttp(canned=FakeResp(_json={"id": "chk_001"}))
    c = _client(http)
    out = c.rka_submit_checkpoint("reason text", type="decision")
    assert out == "chk_001"
    body = http.calls[0]["json"]
    assert "thr_t9" in body["tags"]


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
    # Spot-check that the 13 documented methods exist on the impl.
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
    ):
        assert hasattr(c, name), f"RestMCPClient is missing {name}"
