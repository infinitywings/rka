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
    # RKA's MissionCreate model is `acceptance_criteria: str | None`; a raw list
    # 422s against a live server. The adapter newline-joins the list to conform.
    assert body["acceptance_criteria"] == "A1\nA2"
    assert isinstance(body["acceptance_criteria"], str)


def test_rka_create_mission_accepts_prejoined_string():
    http = FakeHttp(canned=FakeResp(_json={"id": "mis_002"}))
    c = _client(http)
    c.rka_create_mission(
        "objective",
        motivated_by_decision="dec_abc",
        acceptance_criteria="already a string",
    )
    assert http.calls[0]["json"]["acceptance_criteria"] == "already a string"


def test_rka_update_mission_status_coerces_acceptance_criteria_list():
    http = FakeHttp(canned=FakeResp(_json={"id": "mis_003"}))
    c = _client(http)
    c.rka_update_mission_status("mis_003", acceptance_criteria=["C1", "C2"])
    body = http.calls[0]["json"]
    assert body["acceptance_criteria"] == "C1\nC2"


def test_rka_update_mission_status_routes_report_to_report_endpoint():
    # MissionUpdate is extra="forbid" and has no `report` field; forwarding it
    # in the PUT body 422s. The adapter must route it to POST .../report.
    http = FakeHttp(canned=FakeResp(_json={"id": "mis_x"}))
    c = _client(http)
    c.rka_update_mission_status("mis_x", status="complete", report="final report body")
    put = http.calls[0]
    assert put["method"] == "PUT" and put["path"] == "/api/missions/mis_x"
    assert "report" not in put["json"]            # not in the MissionUpdate body
    rep = http.calls[1]
    assert rep["method"] == "POST" and rep["path"] == "/api/missions/mis_x/report"


def test_rka_update_mission_status_no_report_endpoint_call_when_absent():
    http = FakeHttp(canned=FakeResp(_json={"id": "mis_x"}))
    c = _client(http)
    c.rka_update_mission_status("mis_x", status="active")
    assert len(http.calls) == 1                   # only the PUT, no report call


def test_rka_ingest_document_parses_created_id():
    # The endpoint returns {"created":[{"id":...}], "errors":[], "total_sections":N}
    # — not {"id"}/{"ids"}. The adapter must read created[0].id.
    http = FakeHttp(canned=FakeResp(_json={
        "created": [{"id": "jrn_new", "type": "finding"}], "errors": [], "total_sections": 1,
    }))
    c = _client(http)
    assert c.rka_ingest_document("a document body", source="brain") == "jrn_new"


def test_rka_ingest_document_raises_on_errors_only():
    http = FakeHttp(canned=FakeResp(_json={
        "created": [], "errors": [{"section": "S1", "error": "source invalid"}],
        "total_sections": 1,
    }))
    c = _client(http)
    with pytest.raises(ValueError, match="created no entries"):
        c.rka_ingest_document("body", source="brain")


def test_rka_get_dispatches_by_id_prefix():
    # There is no /api/entities/{id}; the adapter must route by the id prefix to
    # the per-type collection. (Hitting a bad path returns the SPA index.html.)
    http = FakeHttp(canned=FakeResp(_json={"id": "x"}))
    c = _client(http)
    c.rka_get("jrn_abc")
    c.rka_get("chk_abc")
    c.rka_get("dec_abc")
    assert [call["path"] for call in http.calls] == [
        "/api/notes/jrn_abc", "/api/checkpoints/chk_abc", "/api/decisions/dec_abc",
    ]


def test_rka_get_unrecognized_prefix_raises_not_html():
    c = _client()
    with pytest.raises(ValueError, match="unrecognized id prefix"):
        c.rka_get("zzz_abc")


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
# Phase-X² polish — FastAPI Pydantic 422 detail enrichment in reason string
# ---------------------------------------------------------------------------


def test_422_pydantic_detail_landed_in_reason():
    """Run-5 PA-2 exact regression: confidence='confirmed' was rejected
    with a Pydantic literal_error. The reason string MUST now include
    the field name + the offending value, so the downstream
    ErrorRecord surfaces actionable info instead of the generic
    'knowledge-pack integrity' label."""
    pydantic_body = {
        "detail": [
            {
                "type": "literal_error",
                "loc": ["body", "confidence"],
                "msg": (
                    "Input should be 'hypothesis', 'tested', 'verified', "
                    "'superseded' or 'retracted'"
                ),
                "input": "confirmed",
            }
        ]
    }
    http = FakeHttp(
        canned=FakeResp(status_code=422, _json=pydantic_body, content=b"x")
    )
    c = _client(http)
    with pytest.raises(CheckpointError) as exc_info:
        c.rka_add_note("x")
    err = exc_info.value
    # New behavior: "validation" label (not the legacy "knowledge-pack
    # integrity" label) AND the field name + invalid value surface.
    assert "422" in str(err)
    assert "validation" in str(err)
    assert "confidence" in str(err)
    assert "confirmed" in str(err)
    # mcp_response still carries the full parsed body for programmatic
    # inspection by downstream tooling.
    assert err.mcp_response == pydantic_body


def test_422_multiple_validation_errors_joined_in_reason():
    """A 422 with two field violations renders both in the reason
    string, joined by '; '."""
    body = {
        "detail": [
            {
                "type": "literal_error",
                "loc": ["body", "confidence"],
                "msg": "Input should be 'verified' | ...",
                "input": "confirmed",
            },
            {
                "type": "literal_error",
                "loc": ["body", "importance"],
                "msg": "Input should be 'high' | ...",
                "input": "very-high",
            },
        ]
    }
    http = FakeHttp(
        canned=FakeResp(status_code=422, _json=body, content=b"x")
    )
    c = _client(http)
    with pytest.raises(CheckpointError) as exc_info:
        c.rka_add_note("x")
    msg = str(exc_info.value)
    assert "confidence" in msg
    assert "confirmed" in msg
    assert "importance" in msg
    assert "very-high" in msg


def test_422_malformed_body_falls_through_to_generic_label():
    """If the response body isn't JSON, we still raise CheckpointError
    with the legacy 'knowledge-pack integrity' label, mcp_response
    carries the raw text."""

    class _NonJsonResp(FakeResp):
        def json(self):
            raise ValueError("not json")

    http = FakeHttp(
        canned=_NonJsonResp(status_code=422, content=b"plain text body")
    )
    http.canned.text = "plain text body"
    c = _client(http)
    with pytest.raises(CheckpointError) as exc_info:
        c.rka_add_note("x")
    err = exc_info.value
    assert "422" in str(err)
    assert "knowledge-pack integrity" in str(err)
    assert err.mcp_response == {"text": "plain text body"}


def test_422_non_list_detail_falls_through_to_generic_label():
    """Affordance-G shape `{error, detail: str, hint}` must continue to
    surface as 'knowledge-pack integrity' — its semantic is preserved
    even though we now special-case the Pydantic list shape."""
    affordance_g_body = {
        "error": "checkpoint_invalid_payload",
        "detail": "field required",
        "hint": "send mission_id",
    }
    http = FakeHttp(
        canned=FakeResp(status_code=422, _json=affordance_g_body, content=b"x"),
    )
    c = _client(http)
    with pytest.raises(CheckpointError) as exc_info:
        c.rka_add_note("x")
    err = exc_info.value
    assert "knowledge-pack integrity" in str(err)
    assert "validation" not in str(err)
    assert err.mcp_response == affordance_g_body


def test_422_redacts_secret_in_loc():
    """If loc path contains a secret-shaped name (token/key/secret/
    password/auth), the input value MUST be redacted before landing
    in the reason string — secrets shouldn't be journaled."""
    body = {
        "detail": [
            {
                "type": "string_too_short",
                "loc": ["body", "api_key"],
                "msg": "String should have at least 16 characters",
                "input": "sk-leaked-secret-value",
            }
        ]
    }
    http = FakeHttp(canned=FakeResp(status_code=422, _json=body, content=b"x"))
    c = _client(http)
    with pytest.raises(CheckpointError) as exc_info:
        c.rka_add_note("x")
    msg = str(exc_info.value)
    assert "api_key" in msg
    assert "REDACTED" in msg
    # The actual secret MUST NOT appear in the reason string.
    assert "sk-leaked-secret-value" not in msg


@pytest.mark.parametrize(
    "loc_name,leaked_value",
    [
        # Adversarial-review wf_ed78d6f8 must-fix #3: extend secret
        # vocabulary beyond token/key/secret/password/auth to cover the
        # common credential fields that would otherwise leak through
        # the new 422 reason-string surface.
        ("credential", "cred-leak-123"),
        ("credentials", "creds-leak-456"),
        ("passphrase", "correct-horse-battery-staple"),
        ("bearer", "Bearer ey-leak-789"),
        ("pwd", "hunter2"),
        ("pin", "123456"),
        ("cookie", "sessionid=leak-abc"),
        ("session", "sess-leak-def"),
        ("cert", "MIIB-leak-cert"),
        ("signature", "sha256:leak-sig"),
        ("private", "-----BEGIN PRIVATE KEY-----"),
    ],
)
def test_422_redacts_extended_secret_field_names(loc_name, leaked_value):
    """Run-5 demonstrated that the 422 reason crosses three storage
    tiers (workflow_runs → parked_interrupts → RKA journal). The hint
    set must cover the common credential vocabulary, not just
    token/key/secret/password/auth."""
    body = {
        "detail": [
            {
                "type": "string_too_short",
                "loc": ["body", loc_name],
                "msg": "validation failed",
                "input": leaked_value,
            }
        ]
    }
    http = FakeHttp(canned=FakeResp(status_code=422, _json=body, content=b"x"))
    c = _client(http)
    with pytest.raises(CheckpointError) as exc_info:
        c.rka_add_note("x")
    msg = str(exc_info.value)
    assert loc_name in msg
    assert "REDACTED" in msg
    assert leaked_value not in msg, (
        f"secret value for loc={loc_name!r} leaked into reason string"
    )


def test_422_caps_long_input_value():
    """Individual input values longer than 80 chars are truncated with
    '...' so a giant pasted blob doesn't dominate the summary."""
    long_input = "x" * 200
    body = {
        "detail": [
            {
                "type": "value_error",
                "loc": ["body", "content"],
                "msg": "too long",
                "input": long_input,
            }
        ]
    }
    http = FakeHttp(canned=FakeResp(status_code=422, _json=body, content=b"x"))
    c = _client(http)
    with pytest.raises(CheckpointError) as exc_info:
        c.rka_add_note("x")
    msg = str(exc_info.value)
    # Original 200 chars must not appear verbatim
    assert long_input not in msg
    # Truncation marker present
    assert "..." in msg


def test_422_summary_caps_total_length_with_overflow_marker():
    """Many validation errors get capped at ~500 chars with '+N more'
    overflow marker so the PI cockpit rendering isn't overwhelmed."""
    body = {
        "detail": [
            {
                "type": "literal_error",
                "loc": ["body", f"field_{i}"],
                "msg": "A reasonably long error message that adds up across multiple entries",
                "input": f"invalid-value-{i}",
            }
            for i in range(20)
        ]
    }
    http = FakeHttp(canned=FakeResp(status_code=422, _json=body, content=b"x"))
    c = _client(http)
    with pytest.raises(CheckpointError) as exc_info:
        c.rka_add_note("x")
    msg = str(exc_info.value)
    assert "+" in msg and "more" in msg
    # mcp_response still carries the FULL 20-item body for programmatic
    # inspection.
    assert len(exc_info.value.mcp_response["detail"]) == 20


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


# ---------------------------------------------------------------------------
# Phase D2.4 — canonical RKA shape support on submit_checkpoint + submit_report
#
# Empirical fix from live run thr_19e790f90b4f9301179: Brain emitted args
# matching the canonical RKA MCP tool signatures, the adapter raised
# TypeError. Adapter now accepts both shapes.
# ---------------------------------------------------------------------------


def test_rka_submit_checkpoint_accepts_canonical_brain_shape():
    """Brain emits {mission_id, message, blocking, data} matching the RKA
    MCP tool. Adapter must accept it and route to /api/checkpoints."""
    http = FakeHttp(canned=FakeResp(_json={"id": "chk_brain"}))
    c = _client(http)
    out = c.rka_submit_checkpoint(
        mission_id="mis_brain",
        message="MANDATORY T4 GATE — review the partial-pass state.",
        blocking=True,
        data={"task": "T4", "probes_passed": 6, "probes_failed_erofs": 2},
    )
    assert out == "chk_brain"
    body = http.calls[0]["json"]
    assert body["mission_id"] == "mis_brain"
    assert body["description"].startswith("MANDATORY T4 GATE")
    assert body["blocking"] is True
    # `data` is JSON-encoded into context so no info is lost.
    assert "data:" in body["context"]
    assert "probes_passed" in body["context"]
    # Workflow tag preserved.
    assert "thr_t9" in body["context"]


def test_rka_submit_checkpoint_accepts_canonical_description_kwarg():
    """Direct canonical shape: {mission_id, type, description}."""
    http = FakeHttp(canned=FakeResp(_json={"id": "chk_canon"}))
    c = _client(http)
    c.rka_submit_checkpoint(
        mission_id="mis_canon",
        type="gate",
        description="Pre-flight gate before T3 extraction.",
    )
    body = http.calls[0]["json"]
    assert body["mission_id"] == "mis_canon"
    assert body["description"] == "Pre-flight gate before T3 extraction."
    assert body["type"] == "gate"


def test_rka_submit_checkpoint_legacy_positional_reason_still_works():
    """Backward-compat: pre-Phase-D2.4 callers passing `reason` positional
    and `related_mission` kwarg must still work."""
    http = FakeHttp(canned=FakeResp(_json={"id": "chk_legacy"}))
    c = _client(http)
    c.rka_submit_checkpoint(
        "legacy reason text",
        type="decision",
        related_mission="mis_legacy",
    )
    body = http.calls[0]["json"]
    assert body["mission_id"] == "mis_legacy"
    assert body["description"] == "legacy reason text"


def test_rka_submit_checkpoint_accepts_content_alias_phase_x_prime():
    """Phase-X²' polish (Layer 1) — Brain emits `content=` extrapolating
    from rka_add_note's worked example in EXECUTOR_SYSTEM. The adapter
    now accepts `content` as a fourth alias for `description`, symmetric
    with rka_submit_report which has accepted `content` since Phase D2.4.
    The asymmetry between sibling EXECUTION_GATES tools was the bug
    surfaced on 2026-06-01 hyperscaler-auditing PA-2 dispatch failure.
    """
    http = FakeHttp(canned=FakeResp(_json={"id": "chk_content"}))
    c = _client(http)
    out = c.rka_submit_checkpoint(
        mission_id="mis_test",
        type="gate",
        content="checkpoint body via content kwarg",
        blocking=True,
    )
    assert out == "chk_content"
    body = http.calls[0]["json"]
    assert body["description"] == "checkpoint body via content kwarg"
    assert body["type"] == "gate"
    assert body["blocking"] is True


def test_rka_submit_checkpoint_description_wins_when_both_supplied():
    """Phase-X²' polish — collision rule: when BOTH description= and
    content= are passed, description= wins (it's first in the pop
    chain). Pin this to prevent silent drift."""
    http = FakeHttp(canned=FakeResp(_json={"id": "chk_both"}))
    c = _client(http)
    c.rka_submit_checkpoint(
        mission_id="mis_test",
        type="decision",
        description="canonical wins",
        content="alias loses",
    )
    body = http.calls[0]["json"]
    assert body["description"] == "canonical wins"


def test_rka_submit_checkpoint_missing_body_raises():
    """All four body-aliases absent → ValueError mentions every accepted
    alias so the operator sees what shape would have worked."""
    http = FakeHttp(canned=FakeResp(_json={"id": "chk_x"}))
    c = _client(http)
    with pytest.raises(ValueError) as exc:
        c.rka_submit_checkpoint(mission_id="mis_x", type="decision")
    msg = str(exc.value)
    assert "description" in msg
    assert "message" in msg
    assert "reason" in msg
    assert "content" in msg


def test_rka_submit_report_accepts_canonical_brain_shape():
    """Brain emits {mission_id, summary, findings, anomalies, questions,
    codebase_state, recommended_next} matching the RKA MCP tool. Adapter
    must accept it and route to /api/missions/{mission}/report."""
    http = FakeHttp(canned=FakeResp(_json={"id": "rep_brain"}))
    c = _client(http)
    out = c.rka_submit_report(
        mission_id="mis_brain_report",
        summary="Mission ended at G1 with 6/8 T1 probes PASS via Read/Write.",
        findings="T1: 6/8 PASS\nT8 code extension complete\n9032 corpus rows",
        anomalies="Bash EROFS-blocked 3x\nT6 outputs pre-exist",
        questions="Q1: Is T6 pre-approved?\nQ2: krippendorff installed?",
        codebase_state="score_human_audit.py extended",
        recommended_next="PI confirm T6 pre-approval",
    )
    assert out == "rep_brain"
    # Routed to the singular /report path on the canonical mission_id.
    assert http.calls[0]["path"] == "/api/missions/mis_brain_report/report"
    body = http.calls[0]["json"]
    # str inputs were split into list[str] (one item per line per the
    # canonical MCP tool's per-line convention).
    assert body["findings"] == [
        "T1: 6/8 PASS",
        "T8 code extension complete",
        "9032 corpus rows",
    ]
    assert body["anomalies"] == [
        "Bash EROFS-blocked 3x",
        "T6 outputs pre-exist",
    ]
    assert body["questions"] == [
        "Q1: Is T6 pre-approved?",
        "Q2: krippendorff installed?",
    ]
    assert body["codebase_state"] == "score_human_audit.py extended"
    assert body["recommended_next"] == "PI confirm T6 pre-approval"


def test_rka_submit_report_legacy_positional_content_still_works():
    """Backward-compat: pre-Phase-D2.4 callers passing `content` positional
    + `related_mission` kwarg must still work; the content goes into both
    tasks_completed (as anchor) and findings (legacy fallback behavior)."""
    http = FakeHttp(canned=FakeResp(_json={"id": "rep_legacy"}))
    c = _client(http)
    c.rka_submit_report(
        "Legacy free-form report content here.",
        related_mission="mis_legacy_report",
    )
    body = http.calls[0]["json"]
    # findings carries the free-form summary when no structured findings
    # were passed.
    assert body["findings"] == ["Legacy free-form report content here."]


def test_rka_submit_checkpoint_brain_data_dict_serializes_to_context():
    """The `data` kwarg Brain often emits is a structured dict that
    doesn't fit any single CheckpointCreate field — it gets serialized
    into context as JSON so the audit trail preserves the structure."""
    http = FakeHttp(canned=FakeResp(_json={"id": "chk_data"}))
    c = _client(http)
    c.rka_submit_checkpoint(
        mission_id="mis_data",
        message="Decision needed.",
        data={
            "task": "T4",
            "tasks_completed": ["T1", "T2"],
            "tasks_blocked": ["T3"],
            "llm_spend_usd": 0.0,
        },
    )
    body = http.calls[0]["json"]
    ctx = body["context"]
    # Verify the data dict made it into context as JSON.
    assert "data:" in ctx
    assert "T1" in ctx
    assert "T2" in ctx
    assert "T3" in ctx
    assert "llm_spend_usd" in ctx


# ---------------------------------------------------------------------------
# v2.8.0 KB-wide verification + temporal currency reads (eval-v3)
# ---------------------------------------------------------------------------


def test_rka_mission_guard_gets_guard_endpoint():
    http = FakeHttp(canned=FakeResp(_json={"warnings": [{"kind": "retracted"}]}))
    c = _client(http)
    out = c.rka_mission_guard("mis_123")
    call = http.calls[-1]
    assert call["method"] == "GET" and call["path"] == "/api/missions/mis_123/guard"
    assert out["warnings"][0]["kind"] == "retracted"


def test_rka_collect_report_context_posts_description_and_angles():
    http = FakeHttp(canned=FakeResp(_json={"nodes": [], "seed_count": 0}))
    c = _client(http)
    c.rka_collect_report_context("a report on X", angle_queries=["x", "y"], max_nodes=40)
    call = http.calls[-1]
    assert call["method"] == "POST" and call["path"] == "/api/graph/report-context"
    assert call["json"]["description"] == "a report on X"
    assert call["json"]["angle_queries"] == ["x", "y"]
    assert call["json"]["max_nodes"] == 40


def test_rka_collect_report_context_drops_none_angles():
    http = FakeHttp(canned=FakeResp(_json={"nodes": []}))
    c = _client(http)
    c.rka_collect_report_context("desc")
    assert "angle_queries" not in http.calls[-1]["json"]


def test_rka_staleness_impact_gets_with_max_depth_param():
    http = FakeHttp(canned=FakeResp(_json={"impacted": []}))
    c = _client(http)
    c.rka_staleness_impact("dec_9", max_depth=2)
    call = http.calls[-1]
    assert call["method"] == "GET"
    assert call["path"] == "/api/graph/staleness-impact/dec_9"
    assert call["params"] == {"max_depth": 2}


def test_rka_belief_as_of_gets_with_date_param():
    http = FakeHttp(canned=FakeResp(_json={"then_current": {"decisions": []}}))
    c = _client(http)
    c.rka_belief_as_of("2026-03-15")
    call = http.calls[-1]
    assert call["method"] == "GET" and call["path"] == "/api/graph/as-of"
    assert call["params"] == {"date": "2026-03-15"}


def test_v280_methods_on_protocol_surface():
    c = _client()
    for name in ("rka_collect_report_context", "rka_mission_guard",
                 "rka_staleness_impact", "rka_belief_as_of"):
        assert hasattr(c, name), f"RestMCPClient missing {name}"
