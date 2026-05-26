"""Phase D, D3a — research_toolkit_node tests.

Covers:
  - Prompt assembly: topic fields + registry domain catalog + per-domain
    shortlists all surface in the LLM prompt
  - Brain JSON parsing: happy path, missing fence, malformed JSON, non-dict
  - Materialization: registry-source preserves canonical metadata,
    user_added stays minimal
  - End-to-end node call: state update has proposed_toolkit + brain_position
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from orchestrator import manifest as M
from orchestrator.nodes import onboarding as O
from orchestrator.state import ResearchWorkflowState


# ---------------------------------------------------------------------------
# Lightweight fakes
# ---------------------------------------------------------------------------


class _FakeSDK:
    """SDK fake that returns a scripted reply, recording the prompt."""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[dict] = []

    def complete(self, prompt: str, *, max_tokens: int = 4096, system: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system, "max_tokens": max_tokens})
        return self.reply


class _StubMCP:
    """MCP stub — research_toolkit_node doesn't touch MCP, so this is
    a trivial placeholder that satisfies the call signature."""

    workflow_thread_id = "thr_test"


def _state_with_topic(
    summary: str = "iot edge llm hosting",
    research_field: str = "ml systems",
    venue: str = "MLSys 2026",
    keywords: list[str] | None = None,
) -> dict:
    return {
        "workflow_thread_id": "thr_t",
        "mission_id": "mis_t",
        "topic_metadata": {
            "summary": summary,
            "research_field": research_field,
            "venue": venue,
            "keywords": keywords or ["edge", "llm", "smart-home"],
        },
    }


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def test_prompt_includes_topic_fields():
    state = _state_with_topic(
        summary="MARKER_SUMMARY", research_field="MARKER_FIELD", venue="MARKER_VENUE",
        keywords=["MARKER_KW1", "MARKER_KW2"],
    )
    sdk = _FakeSDK(reply='```json\n{"selected_domains":[],"scored_tools":[]}\n```')
    O.research_toolkit_node(state, sdk, _StubMCP())  # type: ignore[arg-type]
    prompt = sdk.calls[0]["prompt"]
    assert "MARKER_SUMMARY" in prompt
    assert "MARKER_FIELD" in prompt
    assert "MARKER_VENUE" in prompt
    assert "MARKER_KW1" in prompt
    assert "MARKER_KW2" in prompt


def test_prompt_surfaces_registry_always_on_and_domain_catalog():
    state = _state_with_topic()
    sdk = _FakeSDK(reply='```json\n{"selected_domains":[],"scored_tools":[]}\n```')
    O.research_toolkit_node(state, sdk, _StubMCP())  # type: ignore[arg-type]
    prompt = sdk.calls[0]["prompt"]
    # Always-on (registry-loaded — rka + context7 are canonical).
    assert "rka" in prompt
    assert "context7" in prompt
    # Domain catalog (registry-loaded).
    assert "finance" in prompt
    assert "bioinformatics" in prompt
    assert "ml_systems" in prompt
    # Per-domain shortlists — at least one canonical domain tool surfaces.
    assert "sec-edgar" in prompt  # finance shortlist


def test_prompt_handles_missing_topic_metadata():
    """If state has no topic_metadata, the prompt still renders with a
    sensible placeholder rather than a KeyError."""
    state = {"workflow_thread_id": "thr_t", "mission_id": "mis_t"}
    sdk = _FakeSDK(reply='```json\n{"selected_domains":[],"scored_tools":[]}\n```')
    O.research_toolkit_node(state, sdk, _StubMCP())  # type: ignore[arg-type]
    prompt = sdk.calls[0]["prompt"]
    assert "PI did not provide a topic" in prompt or "unspecified" in prompt


# ---------------------------------------------------------------------------
# Brain JSON parsing
# ---------------------------------------------------------------------------


def test_parse_happy_path():
    reply = """\
Some preamble.
```json
{
  "selected_domains": ["finance", "ml_systems"],
  "scored_tools": [
    {"name": "sec-edgar", "source": "registry", "rationale": "filings", "confidence": "high", "criticality_suggested": "required"}
  ],
  "notes_for_pi": "Reasoning here."
}
```
Trailing text.
"""
    parsed = O._parse_brain_toolkit_reply(reply)
    assert parsed["selected_domains"] == ["finance", "ml_systems"]
    assert len(parsed["scored_tools"]) == 1
    assert parsed["scored_tools"][0]["name"] == "sec-edgar"
    assert parsed["notes_for_pi"] == "Reasoning here."


def test_parse_missing_fence_returns_conservative_default():
    reply = "I forgot the fence. selected_domains: [finance]"
    parsed = O._parse_brain_toolkit_reply(reply)
    assert parsed["selected_domains"] == []
    assert parsed["scored_tools"] == []
    assert parsed.get("_parse_error") is True
    assert "missing" in parsed["notes_for_pi"]


def test_parse_malformed_json_returns_conservative_default():
    reply = "```json\n{not valid json}\n```"
    parsed = O._parse_brain_toolkit_reply(reply)
    assert parsed["selected_domains"] == []
    assert parsed["scored_tools"] == []
    assert parsed.get("_parse_error") is True


def test_parse_non_dict_top_level_returns_conservative_default():
    reply = "```json\n[\"this\", \"is\", \"a\", \"list\"]\n```"
    parsed = O._parse_brain_toolkit_reply(reply)
    assert parsed["selected_domains"] == []
    assert parsed.get("_parse_error") is True


def test_parse_tolerates_missing_optional_fields():
    """A minimal valid reply with only the required 'scored_tools' key
    still parses — defaults fill in for selected_domains + notes_for_pi."""
    reply = '```json\n{"scored_tools": []}\n```'
    parsed = O._parse_brain_toolkit_reply(reply)
    assert parsed["selected_domains"] == []
    assert parsed["scored_tools"] == []
    assert parsed["notes_for_pi"] == ""


# ---------------------------------------------------------------------------
# Materialization: registry-source vs user_added
# ---------------------------------------------------------------------------


def test_materialize_registry_source_preserves_canonical_metadata():
    """A scored entry sourced from the registry should reconstruct the
    full ToolDecl with command/args/secrets from the registry — Brain
    only needs to emit name + rationale + confidence + criticality."""
    scored = [
        {
            "name": "sec-edgar",
            "source": "registry",
            "rationale": "for SEC filings analysis",
            "confidence": "high",
            "criticality_suggested": "required",
        }
    ]
    # Load the registry's finance domain (sec-edgar lives here).
    from orchestrator import tool_registry as TR
    domain_tools = {"finance": TR.tools_for_domain("finance")}
    tools = O._materialize_scored_tools(scored, domain_tools=domain_tools)
    assert len(tools) == 1
    t = tools[0]
    assert t.name == "sec-edgar"
    assert t.source == "registry"
    assert t.command == "npx"
    assert t.args  # non-empty — from registry
    assert t.rationale == "for SEC filings analysis"
    # Brain's criticality_suggested propagated to the secret's criticality.
    assert t.secrets[0].criticality == "required"


def test_materialize_user_added_keeps_minimal_shape():
    """user_added scored entries are tools the Brain proposes beyond the
    registry. They have no canonical command/args/secrets — PI must
    review carefully at pi_toolkit_ratify."""
    scored = [
        {
            "name": "custom-mcp",
            "source": "user_added",
            "rationale": "niche tool",
            "command": "/usr/local/bin/custom-mcp",
            "args": ["--mode", "stream"],
        }
    ]
    tools = O._materialize_scored_tools(scored, domain_tools={})
    assert len(tools) == 1
    t = tools[0]
    assert t.name == "custom-mcp"
    assert t.source == "user_added"
    assert t.command == "/usr/local/bin/custom-mcp"
    assert t.args == ["--mode", "stream"]
    assert t.secrets == []


def test_materialize_skips_malformed_entries():
    """Brain emitting a non-dict entry or missing name shouldn't crash —
    skip silently."""
    scored = [
        {"name": "valid-tool", "source": "user_added"},
        {"source": "registry"},  # missing name
        "not_even_a_dict",
        {"name": None, "source": "user_added"},  # falsy name
    ]
    tools = O._materialize_scored_tools(scored, domain_tools={})
    assert len(tools) == 1
    assert tools[0].name == "valid-tool"


def test_materialize_overrides_secret_criticality_per_brain():
    """When Brain emits criticality_suggested for a registry-sourced
    entry, that overrides the registry's default criticality on each
    secret of that tool."""
    scored = [
        {
            "name": "sec-edgar",
            "source": "registry",
            "criticality_suggested": "optional",  # downgrade from registry's "required"
        }
    ]
    from orchestrator import tool_registry as TR
    domain_tools = {"finance": TR.tools_for_domain("finance")}
    tools = O._materialize_scored_tools(scored, domain_tools=domain_tools)
    assert tools[0].secrets[0].criticality == "optional"


def test_materialize_invalid_criticality_falls_back_to_registry_default():
    """A bogus criticality_suggested doesn't override the registry
    default (defense against typos / hallucinated tiers)."""
    scored = [
        {
            "name": "sec-edgar",
            "source": "registry",
            "criticality_suggested": "nonsense-tier",
        }
    ]
    from orchestrator import tool_registry as TR
    domain_tools = {"finance": TR.tools_for_domain("finance")}
    tools = O._materialize_scored_tools(scored, domain_tools=domain_tools)
    # Registry's original criticality for SEC_EDGAR_USER_AGENT is "required".
    assert tools[0].secrets[0].criticality == "required"


# ---------------------------------------------------------------------------
# End-to-end node call
# ---------------------------------------------------------------------------


def test_node_returns_proposed_toolkit_with_always_on_first():
    """The proposed_toolkit starts with always_on (rka, context7, fs,
    git) before any Brain-scored entries. Dedupe handles Brain
    accidentally re-listing an always-on tool."""
    reply = """```json
{
  "selected_domains": ["finance"],
  "scored_tools": [
    {"name": "rka", "source": "registry", "rationale": "duplicate of always_on"},
    {"name": "sec-edgar", "source": "registry", "rationale": "filings"}
  ],
  "notes_for_pi": "Notes here."
}
```"""
    state = _state_with_topic()
    sdk = _FakeSDK(reply=reply)
    update = O.research_toolkit_node(state, sdk, _StubMCP())  # type: ignore[arg-type]

    names = [t["name"] for t in update["proposed_toolkit"]]
    # rka comes from always_on (first), context7 too — and sec-edgar
    # is appended after. Brain's duplicate rka entry is deduped.
    assert names[0] == "rka"
    assert "context7" in names
    assert "sec-edgar" in names
    assert names.count("rka") == 1


def test_node_writes_brain_position_with_notes():
    reply = """```json
{
  "selected_domains": [],
  "scored_tools": [],
  "notes_for_pi": "DISTINCT_MARKER_TEXT"
}
```"""
    state = _state_with_topic()
    sdk = _FakeSDK(reply=reply)
    update = O.research_toolkit_node(state, sdk, _StubMCP())  # type: ignore[arg-type]
    assert "DISTINCT_MARKER_TEXT" in update.get("brain_position", "")


def test_node_handles_parse_failure_gracefully():
    """When Brain's reply doesn't parse, the proposed_toolkit still
    contains the always_on baseline (deterministic; doesn't depend on
    Brain) and the run continues."""
    sdk = _FakeSDK(reply="no fenced block here at all")
    state = _state_with_topic()
    update = O.research_toolkit_node(state, sdk, _StubMCP())  # type: ignore[arg-type]
    names = [t["name"] for t in update["proposed_toolkit"]]
    # always_on baseline still present.
    assert "rka" in names
    assert "context7" in names
    # No Brain-scored additions (because parse failed).
    assert "sec-edgar" not in names


def test_node_current_node_marks_research_toolkit():
    sdk = _FakeSDK(reply='```json\n{"scored_tools":[]}\n```')
    update = O.research_toolkit_node(_state_with_topic(), sdk, _StubMCP())  # type: ignore[arg-type]
    assert update["current_node"] == "research_toolkit"


def test_node_calls_sdk_with_brain_system_prompt():
    """The Brain system prompt (BRAIN_SYSTEM) is passed to the SDK call
    so the node inherits the Brain's discipline conventions
    (conservative parsing, evidence citation, etc.)."""
    sdk = _FakeSDK(reply='```json\n{"scored_tools":[]}\n```')
    O.research_toolkit_node(_state_with_topic(), sdk, _StubMCP())  # type: ignore[arg-type]
    from orchestrator.nodes.brain import BRAIN_SYSTEM
    assert sdk.calls[0]["system"] == BRAIN_SYSTEM
