"""Phase 2.10 T1 — `RestMCPClient.rka_get_journal` regression tests.

Mission: `mis_01KRYBZ0W4Z9F1GXKP96ERKGKK` (Phase 2.10; PI-handed-off scope
per `dec_01KRYBR8APM187YJXQG2Q455EM` Option A — bundled retry + bug fix).

Discharge of Phase 2.9 T3 debt per `jrn_01KRY908A3RYX1TBH6CKKPJRGC`. These
tests lock the corrected contract:

- Endpoint: `/api/notes` (REST surface), NOT `/api/journal` (web UI HTML)
- Return shape: `list[dict[str, Any]]`, NOT `dict[str, Any]`
- Tags filter: client-side post-fetch (REST endpoint has no `tags` query param)
- Filter semantics: a note matches if it carries ALL requested tags
- Defensive: non-list REST responses (None, dict, str) return empty list

The bulk of behavioral coverage lives next to peer methods in
`test_mcp_client.py`. This dedicated file exists per Phase 2.10 T1 spec
to make the regression locks easy to find when the next caller surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestrator.mcp_client import RestMCPClient


@dataclass
class FakeResp:
    status_code: int = 200
    _json: Any = None
    text: str = ""
    content: bytes = b"{}"

    def json(self):
        return self._json if self._json is not None else {}

    def raise_for_status(self):
        if 400 <= self.status_code < 600:
            raise RuntimeError(f"HTTP {self.status_code}")


@dataclass
class FakeHttp:
    canned: FakeResp = field(default_factory=lambda: FakeResp(_json=[]))
    calls: list[dict] = field(default_factory=list)

    def request(self, method, path, *, json=None, params=None):
        self.calls.append({"method": method, "path": path, "json": json, "params": params})
        return self.canned


def _client(http: FakeHttp) -> RestMCPClient:
    return RestMCPClient(
        base_url="http://x",
        workflow_thread_id="thr_t1_test",
        http_client=http,
    )


# ---------------------------------------------------------------------------
# Phase 2.10 T1 — corrected endpoint contract
# ---------------------------------------------------------------------------


def test_rka_get_journal_hits_notes_not_journal_endpoint():
    """REGRESSION-LOCK (jrn_01KRY908A3RYX1TBH6CKKPJRGC): the upstream bug was
    `rka_get_journal` hitting `/api/journal` which is the web UI HTML route
    (HTTP 200 + `<!doctype html>` body). The corrected endpoint is
    `/api/notes` (REST surface). Phase 2.9 T3's integration probe surfaced
    this; Phase 2.10 T1 discharges the debt."""
    http = FakeHttp(canned=FakeResp(_json=[]))
    c = _client(http)
    c.rka_get_journal()
    assert http.calls[0]["path"] == "/api/notes", (
        f"Phase 2.10 T1 regression-lock: rka_get_journal MUST hit /api/notes, "
        f"not /api/journal. Got path={http.calls[0]['path']!r}."
    )


def test_rka_get_journal_does_not_send_tags_query_param():
    """REST `/api/notes` does not accept a `tags` query param (verified
    via /openapi.json — supported params are type, phase, confidence,
    importance, source, status, since, hide_superseded, limit, offset,
    project_id, X-RKA-Project). Tags filtering happens client-side
    post-fetch."""
    http = FakeHttp(canned=FakeResp(_json=[]))
    c = _client(http)
    c.rka_get_journal(tags=["alpha", "beta"], limit=5)
    assert "tags" not in (http.calls[0]["params"] or {}), (
        "Phase 2.10 T1: tags must NOT be sent as a query param; "
        "filter client-side instead"
    )
    # `limit` IS still a valid query param.
    assert http.calls[0]["params"]["limit"] == 5


def test_rka_get_journal_returns_list_not_dict():
    """Return shape: `list[dict[str, Any]]`. The pre-Phase-2.10 Protocol
    declared `dict[str, Any]` but the real REST surface returns a list;
    the FakeMCP returned `{"entries": []}` masked the mismatch for
    multiple phases."""
    http = FakeHttp(canned=FakeResp(_json=[{"id": "jrn_x", "tags": []}]))
    c = _client(http)
    result = c.rka_get_journal()
    assert isinstance(result, list), (
        f"Phase 2.10 T1: return shape must be list[dict], not "
        f"{type(result).__name__}"
    )
    assert len(result) == 1
    assert result[0]["id"] == "jrn_x"


def test_rka_get_journal_client_side_tag_filter_requires_all_tags():
    """A note matches the filter iff it carries ALL requested tags
    (intersection / set-subset semantics). Two-tag filter: note must
    carry both tags to match."""
    canned = [
        {"id": "jrn_a", "tags": ["alpha", "beta", "gamma"]},
        {"id": "jrn_b", "tags": ["alpha"]},            # missing 'beta'
        {"id": "jrn_c", "tags": ["beta", "delta"]},    # missing 'alpha'
        {"id": "jrn_d", "tags": ["alpha", "beta"]},
    ]
    http = FakeHttp(canned=FakeResp(_json=canned))
    c = _client(http)
    result = c.rka_get_journal(tags=["alpha", "beta"])
    matched_ids = sorted(n["id"] for n in result)
    assert matched_ids == ["jrn_a", "jrn_d"], (
        f"Phase 2.10 T1: client-side filter must require ALL tags; "
        f"got matches={matched_ids!r}"
    )


def test_rka_get_journal_handles_non_list_response_defensively():
    """If the REST endpoint returns None or an unexpected shape (dict /
    string / etc.), return an empty list rather than crashing the
    caller. Defends against future REST surface drift."""
    # None response
    http = FakeHttp(canned=FakeResp(_json=None))
    c = _client(http)
    assert c.rka_get_journal() == []

    # Unexpected dict response (the old shape some callers might still expect)
    http = FakeHttp(canned=FakeResp(_json={"entries": []}))
    c = _client(http)
    assert c.rka_get_journal() == []

    # Unexpected string response (HTML body case — what triggered the
    # original Phase 2.9 T3 failure)
    http = FakeHttp(canned=FakeResp(_json="<!doctype html>"))
    c = _client(http)
    assert c.rka_get_journal() == []


def test_rka_get_journal_empty_tag_list_returns_all_notes():
    """When `tags=[]` (empty list, truthy-False), no client-side filter
    applies — all notes returned. Matches the `tags=None` case."""
    canned = [{"id": "jrn_a", "tags": ["x"]}, {"id": "jrn_b", "tags": ["y"]}]
    http = FakeHttp(canned=FakeResp(_json=canned))
    c = _client(http)
    assert len(c.rka_get_journal(tags=[])) == 2
