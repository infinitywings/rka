"""Phase O, O3.2 — claim_extraction + pi_claims_review tests.

Covers:
  - claim_extraction iterates journals tagged for the 4 categories
    (polished-idea, ingested-source, literature, deep-research-finding)
  - Dedup across categories: a journal tagged for multiple categories
    counts once
  - Brain reply parsing: valid claim_types accepted, malformed entries
    filtered, case-insensitive claim_type accepted
  - Confidence: out-of-range values clamped to 0.5; non-numeric → 0.5
  - Empty-claim-list Brain reply is treated as success (no error)
  - LLM failure per-journal is recorded as ErrorRecord but pipeline
    proceeds for the remaining journals
  - rka_create_claim failure per-claim is recorded; node still returns
    successfully-created IDs
  - Missing project_id returns an ErrorRecord, no MCP calls
  - pi_claims_review payload shape (items, two_tap, claim_ids)
  - pi_claims_review accept: claim_ids preserved
  - pi_claims_review reject/correct: claim_ids cleared
  - pi_claims_review correct: brain_position carries the redirect
  - parked_store + runner registry wiring
"""

from __future__ import annotations

import json

import pytest

from orchestrator import graph
from orchestrator.nodes import onboarding, pi
from orchestrator.parked_store import ParkedStore
from orchestrator.runner import _ACCEPT_TOKEN_BY_TYPE, OrchestratorRunner

from tests._fakes import FakeMCP, FakeSDK


# ---------------------------------------------------------------------------
# Brain reply parsing
# ---------------------------------------------------------------------------


def _claims_reply(claims: list[dict]) -> str:
    return "```json\n" + json.dumps({"claims": claims}) + "\n```"


def test_parse_claims_valid_entries():
    reply = _claims_reply(
        [
            {"claim_type": "evidence", "content": "Pi 5 can run 1B INT4.", "confidence": 0.8},
            {"claim_type": "hypothesis", "content": "Thermal limits dominate.", "confidence": 0.5},
        ]
    )
    out = onboarding._parse_claims_reply(reply)
    assert len(out) == 2
    assert out[0]["claim_type"] == "evidence"
    assert out[1]["confidence"] == 0.5


def test_parse_claims_filters_malformed_entries():
    reply = _claims_reply(
        [
            {"claim_type": "evidence", "content": "good claim"},  # missing confidence → 0.5 default
            {"claim_type": "evidence"},                            # missing content → filtered
            {"content": "no type"},                                # missing claim_type → filtered
            {"claim_type": "unknown_type", "content": "bad type"},  # unknown type → filtered
            {"claim_type": "hypothesis", "content": ""},           # empty content → filtered
        ]
    )
    out = onboarding._parse_claims_reply(reply)
    assert len(out) == 1
    assert out[0]["content"] == "good claim"
    assert out[0]["confidence"] == 0.5


def test_parse_claims_accepts_case_insensitive_claim_type():
    reply = _claims_reply(
        [{"claim_type": "Evidence", "content": "case insensitive", "confidence": 0.7}]
    )
    out = onboarding._parse_claims_reply(reply)
    assert len(out) == 1
    assert out[0]["claim_type"] == "evidence"


def test_parse_claims_clamps_confidence_out_of_range():
    reply = _claims_reply(
        [
            {"claim_type": "evidence", "content": "c1", "confidence": 1.5},  # > 1 → 0.5
            {"claim_type": "evidence", "content": "c2", "confidence": -0.3},  # < 0 → 0.5
            {"claim_type": "evidence", "content": "c3", "confidence": "bad"},  # non-numeric → 0.5
        ]
    )
    out = onboarding._parse_claims_reply(reply)
    assert all(c["confidence"] == 0.5 for c in out)


def test_parse_claims_empty_list_is_valid():
    out = onboarding._parse_claims_reply(_claims_reply([]))
    assert out == []


def test_parse_claims_unparseable_reply_returns_empty():
    assert onboarding._parse_claims_reply("no json here") == []
    assert onboarding._parse_claims_reply("") == []


# ---------------------------------------------------------------------------
# claim_extraction_node happy path
# ---------------------------------------------------------------------------


def _mk_mcp_with_journals(*entries: dict) -> FakeMCP:
    mcp = FakeMCP()
    mcp.journal_response = list(entries)
    return mcp


def test_claim_extraction_iterates_all_four_tag_categories():
    mcp = _mk_mcp_with_journals(
        {"id": "jrn_pol", "tags": ["prj_x", "polished-idea"], "content": "polish."},
        {"id": "jrn_src", "tags": ["prj_x", "ingested-source"], "content": "source."},
        {"id": "jrn_lit", "tags": ["prj_x", "literature"], "content": "paper."},
        {"id": "jrn_drf", "tags": ["prj_x", "deep-research-finding"], "content": "finding."},
    )
    sdk = FakeSDK(canned_reply=_claims_reply(
        [{"claim_type": "evidence", "content": "x", "confidence": 0.5}]
    ))

    out = onboarding.claim_extraction_node({"project_id": "prj_x"}, sdk, mcp)

    # Each category should have been queried (one rka_get_journal call per).
    journal_calls = [c for c in mcp.calls if c["op"] == "rka_get_journal"]
    assert len(journal_calls) == 4
    tags_seen = [tuple(c["tags"]) for c in journal_calls]
    assert ("prj_x", "polished-idea") in tags_seen
    assert ("prj_x", "ingested-source") in tags_seen
    assert ("prj_x", "literature") in tags_seen
    assert ("prj_x", "deep-research-finding") in tags_seen
    # 4 journals × 1 claim each = 4 claim_ids.
    assert len(out["claim_ids"]) == 4


def test_claim_extraction_dedupes_journals_across_categories():
    """A journal tagged with both 'polished-idea' and 'literature' should
    only be processed once."""
    shared = {
        "id": "jrn_shared",
        "tags": ["prj_x", "polished-idea", "literature"],
        "content": "shared.",
    }
    mcp = _mk_mcp_with_journals(shared)
    sdk = FakeSDK(canned_reply=_claims_reply(
        [{"claim_type": "evidence", "content": "x"}]
    ))
    out = onboarding.claim_extraction_node({"project_id": "prj_x"}, sdk, mcp)
    # Brain was called only once even though the journal would match
    # two of the four tag categories.
    assert len(sdk.calls) == 1
    assert len(out["claim_ids"]) == 1


def test_claim_extraction_submits_via_rka_create_claim():
    mcp = _mk_mcp_with_journals(
        {"id": "jrn_a", "tags": ["prj_x", "literature"], "content": "x"},
    )
    sdk = FakeSDK(canned_reply=_claims_reply([
        {"claim_type": "evidence", "content": "claim 1", "confidence": 0.7},
        {"claim_type": "hypothesis", "content": "claim 2", "confidence": 0.4},
    ]))
    out = onboarding.claim_extraction_node({"project_id": "prj_x"}, sdk, mcp)
    assert len(out["claim_ids"]) == 2
    creates = [c for c in mcp.calls if c["op"] == "rka_create_claim"]
    assert len(creates) == 2
    assert creates[0]["source_entry_id"] == "jrn_a"
    assert creates[0]["claim_type"] == "evidence"
    assert creates[0]["confidence"] == 0.7


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_claim_extraction_missing_project_id_returns_error():
    out = onboarding.claim_extraction_node({}, FakeSDK(), FakeMCP())
    assert out["claim_ids"] == []
    assert out["errors"][0]["error_type"] == "claim_extraction_no_project_id"


def test_claim_extraction_records_llm_failure_keeps_going():
    """If Brain raises on one journal, pipeline records ErrorRecord but
    proceeds for the remaining journals."""

    class _PartialFailSDK:
        def __init__(self):
            self.calls = []

        def complete(
            self,
            prompt: str,
            *,
            max_tokens: int = 4096,
            system=None,
            timeout_s: float | None = None,  # Phase S4 — accepted, ignored
        ) -> str:
            self.calls.append(prompt)
            if "jrn_bad" in prompt:
                raise RuntimeError("Brain blew up")
            return _claims_reply(
                [{"claim_type": "evidence", "content": "ok", "confidence": 0.5}]
            )

    mcp = _mk_mcp_with_journals(
        {"id": "jrn_bad", "tags": ["prj_x", "literature"], "content": "x"},
        {"id": "jrn_ok",  "tags": ["prj_x", "literature"], "content": "y"},
    )
    out = onboarding.claim_extraction_node(
        {"project_id": "prj_x"}, _PartialFailSDK(), mcp
    )
    # Good journal yielded a claim.
    assert len(out["claim_ids"]) == 1
    # Failed journal recorded.
    assert any(
        e["error_type"] == "claim_extraction_llm_failed"
        for e in out["errors"]
    )


def test_claim_extraction_records_create_failure():
    class _CreateFailMCP(FakeMCP):
        def rka_create_claim(self, **kw):
            raise RuntimeError("RKA blocked")

    mcp = _CreateFailMCP()
    mcp.journal_response = [
        {"id": "jrn_x", "tags": ["prj_x", "literature"], "content": "x"}
    ]
    sdk = FakeSDK(canned_reply=_claims_reply(
        [{"claim_type": "evidence", "content": "x"}]
    ))
    out = onboarding.claim_extraction_node({"project_id": "prj_x"}, sdk, mcp)
    assert out["claim_ids"] == []
    assert out["errors"][0]["error_type"] == "claim_extraction_write_failed"


def test_claim_extraction_empty_claims_reply_no_error():
    """Brain emitting {claims: []} is valid (entry has nothing
    extractable). Pipeline records nothing."""
    mcp = _mk_mcp_with_journals(
        {"id": "jrn_x", "tags": ["prj_x", "literature"], "content": "x"}
    )
    sdk = FakeSDK(canned_reply=_claims_reply([]))
    out = onboarding.claim_extraction_node({"project_id": "prj_x"}, sdk, mcp)
    assert out["claim_ids"] == []
    assert "errors" not in out


# ---------------------------------------------------------------------------
# pi_claims_review payload + routing
# ---------------------------------------------------------------------------


def _state_with_claims(*claim_ids: str) -> dict:
    return {"project_id": "prj_x", "claim_ids": list(claim_ids)}


def test_pi_claims_review_payload_shape():
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return "accept"

    mcp = FakeMCP()
    mcp.claims_response = [
        {"id": "clm_aa", "claim_type": "evidence", "content": "x"},
        {"id": "clm_bb", "claim_type": "hypothesis", "content": "y"},
    ]
    pi.pi_claims_review(
        _state_with_claims("clm_aa", "clm_bb"), FakeSDK(), mcp, fake_interrupt
    )

    p = captured["payload"]
    assert p["type"] == "pi_claims_review"
    assert "TWO-TAP" in p["title"]
    assert p["two_tap_required"] is True
    assert "2 extracted" in p["two_tap_label"]
    assert p["claim_ids"] == ["clm_aa", "clm_bb"]
    # Items hydrated from rka_list_claims.
    assert len(p["items"]) == 2
    assert p["items"][0]["content"] == "x"


def test_pi_claims_review_accept_preserves_claim_ids():
    out = pi.pi_claims_review(
        _state_with_claims("clm_a", "clm_b"),
        FakeSDK(),
        FakeMCP(),
        lambda _p: "accept",
    )
    # state didn't get cleared on accept.
    assert "claim_ids" not in out  # not overwritten — state's existing IDs survive
    assert out["current_node"] == "pi_claims_review"


def test_pi_claims_review_reject_clears_claim_ids():
    out = pi.pi_claims_review(
        _state_with_claims("clm_a"),
        FakeSDK(),
        FakeMCP(),
        lambda _p: "reject",
    )
    assert out["claim_ids"] == []
    assert "brain_position" not in out


def test_pi_claims_review_correct_carries_redirect_and_clears():
    feedback = "Drop the methodology claims; focus on evidence + hypotheses."
    out = pi.pi_claims_review(
        _state_with_claims("clm_a"),
        FakeSDK(),
        FakeMCP(),
        lambda _p: feedback,
    )
    assert out["claim_ids"] == []
    assert out["brain_position"] == feedback


def test_pi_claims_review_fetch_falls_back_to_rka_get():
    """When rka_list_claims returns empty (or raises), per-ID rka_get
    is used as fallback."""

    class _ListEmptyMCP(FakeMCP):
        def rka_list_claims(self, **kw):
            return []

        def rka_get(self, id: str) -> dict:
            self._record("rka_get", id=id)
            return {"id": id, "claim_type": "evidence", "content": "fallback"}

    mcp = _ListEmptyMCP()
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return "accept"

    pi.pi_claims_review(
        _state_with_claims("clm_X"), FakeSDK(), mcp, fake_interrupt
    )
    # rka_get fallback fired.
    assert any(c["op"] == "rka_get" for c in mcp.calls)
    assert captured["payload"]["items"][0]["content"] == "fallback"


# ---------------------------------------------------------------------------
# Schema + registry wiring
# ---------------------------------------------------------------------------


def test_parked_store_accepts_pi_claims_review():
    store = ParkedStore(":memory:")
    thread_id = store.create_run(mission_id="prj_x", project_id="prj_x")
    iid = store.park_interrupt(
        workflow_thread_id=thread_id,
        mission_id="prj_x",
        interrupt_type="pi_claims_review",
        payload={"type": "pi_claims_review", "title": "x"},
    )
    assert iid.startswith("int_")
    store.close()


def test_runner_accept_token_for_claims_review_is_accept():
    assert _ACCEPT_TOKEN_BY_TYPE["pi_claims_review"] == "accept"


def test_runner_recognizes_pi_claims_review_as_onboarding():
    assert "pi_claims_review" in OrchestratorRunner._PHASE_O_INTERRUPT_TYPES


def test_graph_onboarding_node_names_include_claim_extraction_and_review():
    assert "claim_extraction" in graph.ONBOARDING_NODE_NAMES
    assert "pi_claims_review" in graph.ONBOARDING_NODE_NAMES
