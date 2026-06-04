"""Phase O, O1.2 — idea_polish + PolishedIdea tests.

Covers:
  - PolishedIdea schema: from_dict validation, round-trip, missing-field errors
  - extract_json_block: fenced + balanced-brace fallback, last-wins
  - idea_polish_node: happy path emits polished_idea + journal artifact
  - idea_polish_node: pulls ingested-source summaries into the prompt
  - idea_polish_node: PI's brain_position text feeds the prompt
  - idea_polish_node: one-retry on parse failure; ErrorRecord on second
  - idea_polish_node: backfills empty ingested_sources from state
  - idea_polish_node: handles MCP write failure cleanly
  - idea_polish_node: graph.ONBOARDING_NODE_NAMES contains 'idea_polish'
"""

from __future__ import annotations

import json

import pytest

from orchestrator import graph
from orchestrator.nodes import onboarding
from orchestrator.onboarding_schemas import PolishedIdea, extract_json_block

from tests._fakes import FakeMCP, FakeSDK


# ---------------------------------------------------------------------------
# PolishedIdea schema
# ---------------------------------------------------------------------------


def test_polished_idea_round_trip():
    pi = PolishedIdea(
        research_question="Can edge LLMs hit 5 tok/s on a Pi 5?",
        motivation="On-device LLMs unlock private personalization.",
        scope="In: 1-3B params + Pi 5. Out: server-class GPUs.",
        novelty_hypothesis="No prior work has measured INT4 quant on Pi 5.",
        target_venue="MLSys 2026",
        ingested_sources=["jrn_a", "jrn_b"],
        open_assumptions=["thermal headroom is the bottleneck"],
    )
    d = pi.to_dict()
    pi2 = PolishedIdea.from_dict(d)
    assert pi2.research_question == pi.research_question
    assert pi2.ingested_sources == ["jrn_a", "jrn_b"]
    assert pi2.target_venue == "MLSys 2026"


def test_polished_idea_missing_required_field_raises():
    with pytest.raises(ValueError, match="missing required"):
        PolishedIdea.from_dict({"research_question": "x", "motivation": "y"})


def test_polished_idea_empty_required_field_raises():
    with pytest.raises(ValueError, match="missing required"):
        PolishedIdea.from_dict(
            {
                "research_question": "x",
                "motivation": "y",
                "scope": "",  # empty string
                "novelty_hypothesis": "z",
            }
        )


def test_polished_idea_optional_venue_omitted():
    pi = PolishedIdea.from_dict(
        {
            "research_question": "x",
            "motivation": "y",
            "scope": "in: foo; out: bar",
            "novelty_hypothesis": "z",
        }
    )
    assert pi.target_venue is None
    assert pi.ingested_sources == []
    assert pi.open_assumptions == []


def test_polished_idea_rejects_non_list_ingested_sources():
    with pytest.raises(ValueError, match="must be a list"):
        PolishedIdea.from_dict(
            {
                "research_question": "x",
                "motivation": "y",
                "scope": "z",
                "novelty_hypothesis": "n",
                "ingested_sources": "jrn_a",  # string, not list
            }
        )


# ---------------------------------------------------------------------------
# extract_json_block
# ---------------------------------------------------------------------------


def test_extract_json_block_fenced():
    txt = 'Thinking out loud...\n```json\n{"foo": 1}\n```\nbye'
    assert extract_json_block(txt) == {"foo": 1}


def test_extract_json_block_balanced_fallback():
    """No fenced block, but trailing balanced object → parse it."""
    txt = "no fence here\n{\"foo\": 2, \"bar\": [1, 2]}"
    assert extract_json_block(txt) == {"foo": 2, "bar": [1, 2]}


def test_extract_json_block_last_wins():
    """Multiple fenced blocks → last one wins (Brain re-emitting on retry)."""
    txt = '```json\n{"old": 1}\n```\n\n```json\n{"new": 2}\n```'
    assert extract_json_block(txt) == {"new": 2}


def test_extract_json_block_returns_none_on_empty():
    assert extract_json_block("") is None
    assert extract_json_block("no json here at all") is None


def test_extract_json_block_malformed_returns_none():
    assert extract_json_block("```json\n{not valid}\n```") is None


def test_extract_json_block_handles_nested_objects():
    txt = '```json\n{"top": {"inner": [1, {"deep": true}]}}\n```'
    parsed = extract_json_block(txt)
    assert parsed["top"]["inner"][1]["deep"] is True


# ---------------------------------------------------------------------------
# idea_polish_node — happy path
# ---------------------------------------------------------------------------


def _good_brain_reply(target_venue: str = "MLSys 2026") -> str:
    return (
        "Thinking through this...\n\n"
        "```json\n"
        + json.dumps(
            {
                "research_question": "Can edge LLMs hit 5 tok/s on Pi 5?",
                "motivation": "On-device LLMs unlock private personalization.",
                "scope": "In: 1-3B + Pi 5. Out: GPUs.",
                "novelty_hypothesis": "INT4 quant on Pi 5 not measured before.",
                "target_venue": target_venue,
                "open_assumptions": ["thermal headroom matters"],
                "ingested_sources": ["jrn_AA", "jrn_BB"],
            }
        )
        + "\n```"
    )


def test_idea_polish_happy_path_writes_polished_idea_and_artifact():
    sdk = FakeSDK(canned_reply=_good_brain_reply())
    mcp = FakeMCP()
    mcp.journal_response = [
        {"id": "jrn_AA", "tags": ["prj_test", "ingested-source"], "content": "sum 1"},
        {"id": "jrn_BB", "tags": ["prj_test", "ingested-source"], "content": "sum 2"},
    ]
    state = {
        "project_id": "prj_test",
        "brain_position": "I want to build edge LLM hosting.",
        "ingested_source_ids": ["jrn_AA", "jrn_BB"],
    }

    out = onboarding.idea_polish_node(state, sdk, mcp)

    assert out["current_node"] == "idea_polish"
    polished = out["polished_idea"]
    assert "Pi 5" in polished["research_question"]
    assert polished["target_venue"] == "MLSys 2026"
    assert polished["ingested_sources"] == ["jrn_AA", "jrn_BB"]
    # Artifact emitted for the polished-idea journal.
    assert len(out["artifacts"]) == 1
    art = out["artifacts"][0]
    assert art["entity_type"] == "journal"
    assert art["node_name"] == "idea_polish"
    # MCP call: rka_add_note with the right tags.
    notes = [c for c in mcp.calls if c["op"] == "rka_add_note"]
    assert len(notes) == 1
    assert "polished-idea" in notes[0]["tags"]
    assert "prj_test" in notes[0]["tags"]
    assert notes[0].get("source") == "brain"


def test_idea_polish_prompt_includes_pi_description_and_summaries():
    sdk = FakeSDK(canned_reply=_good_brain_reply())
    mcp = FakeMCP()
    mcp.journal_response = [
        {
            "id": "jrn_AA",
            "tags": ["prj_test", "ingested-source"],
            "content": "Summary of paper X about edge LLM quantization.",
        },
    ]
    state = {
        "project_id": "prj_test",
        "brain_position": "I want quantization on Pi 5.",
        "ingested_source_ids": ["jrn_AA"],
    }
    onboarding.idea_polish_node(state, sdk, mcp)

    assert len(sdk.calls) == 1
    prompt = sdk.calls[0]["prompt"]
    assert "quantization on Pi 5" in prompt
    assert "Summary of paper X" in prompt
    assert "jrn_AA" in prompt
    # Schema documentation present in the prompt.
    assert '"research_question"' in prompt
    assert '"novelty_hypothesis"' in prompt


def test_idea_polish_backfills_ingested_sources_from_state():
    """If Brain emits empty ingested_sources but state has them, splice in."""
    reply = (
        "```json\n"
        + json.dumps(
            {
                "research_question": "x?",
                "motivation": "y.",
                "scope": "z.",
                "novelty_hypothesis": "w.",
                "ingested_sources": [],  # Brain forgot
            }
        )
        + "\n```"
    )
    out = onboarding.idea_polish_node(
        {
            "project_id": "prj_x",
            "brain_position": "foo",
            "ingested_source_ids": ["jrn_X", "jrn_Y"],
        },
        FakeSDK(canned_reply=reply),
        FakeMCP(),
    )
    assert out["polished_idea"]["ingested_sources"] == ["jrn_X", "jrn_Y"]


# ---------------------------------------------------------------------------
# idea_polish_node — parse retry
# ---------------------------------------------------------------------------


class _SeqSDK:
    """FakeSDK variant that returns different replies per call."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        system=None,
        timeout_s: float | None = None,  # Phase S4 — accepted, ignored
    ) -> str:
        self.calls.append({"prompt": prompt, "system": system})
        if not self.replies:
            return ""
        return self.replies.pop(0)


def test_idea_polish_retries_once_on_parse_failure_then_succeeds():
    sdk = _SeqSDK(
        replies=[
            "no JSON block at all",  # parse fail
            _good_brain_reply(),     # succeeds on retry
        ]
    )
    out = onboarding.idea_polish_node(
        {
            "project_id": "prj_x",
            "brain_position": "foo",
            "ingested_source_ids": [],
        },
        sdk,
        FakeMCP(),
    )
    assert "polished_idea" in out
    assert "errors" not in out
    assert len(sdk.calls) == 2
    # The retry prompt should carry the corrective-feedback addendum.
    assert "Parse-retry feedback" in sdk.calls[1]["prompt"]


def test_idea_polish_records_error_on_second_parse_failure():
    sdk = _SeqSDK(replies=["no json", "still no json"])
    out = onboarding.idea_polish_node(
        {
            "project_id": "prj_x",
            "brain_position": "foo",
            "ingested_source_ids": [],
        },
        sdk,
        FakeMCP(),
    )
    assert "polished_idea" not in out
    assert "errors" in out
    err = out["errors"][0]
    assert err["error_type"] == "idea_polish_parse_failure"
    assert err["node_name"] == "idea_polish"


def test_idea_polish_records_error_on_missing_field():
    """A JSON object missing required fields counts as a parse failure
    (PolishedIdea.from_dict raises). Should retry once."""
    reply = '```json\n{"research_question": "x"}\n```'
    sdk = _SeqSDK(replies=[reply, reply])  # both attempts equally bad
    out = onboarding.idea_polish_node(
        {"project_id": "prj_x", "ingested_source_ids": []}, sdk, FakeMCP()
    )
    assert "errors" in out
    assert "missing required" in out["errors"][0]["detail"]


# ---------------------------------------------------------------------------
# idea_polish_node — MCP write failure
# ---------------------------------------------------------------------------


def test_idea_polish_handles_journal_write_failure():
    class _WriteFailMCP(FakeMCP):
        def rka_add_note(self, content: str, **kw):
            raise RuntimeError("RKA write blocked")

    sdk = FakeSDK(canned_reply=_good_brain_reply())
    mcp = _WriteFailMCP()
    out = onboarding.idea_polish_node(
        {"project_id": "prj_x", "brain_position": "foo", "ingested_source_ids": []},
        sdk,
        mcp,
    )
    # polished_idea still in state so we can render it for retry / debug.
    assert "polished_idea" in out
    # But the error is recorded.
    assert out["errors"][0]["error_type"] == "idea_polish_journal_write_failed"


# ---------------------------------------------------------------------------
# Graph registry wiring
# ---------------------------------------------------------------------------


def test_graph_onboarding_node_names_include_idea_polish():
    assert "idea_polish" in graph.ONBOARDING_NODE_NAMES
