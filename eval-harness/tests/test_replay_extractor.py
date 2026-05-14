"""Tests for the replay extractor's regex + entry-scan logic.

The extractor is intentionally heuristic, so these tests focus on:

  - Tool-name regex matches each of the 3 supported tools.
  - Structured query extraction handles the 3 call shapes the
    docstring promises (`rka_search("…")`, `query="…"`, JSON
    tool_use blocks).
  - Context window respects the documented before/after sizes.
  - Empty / unrelated content yields zero candidates.

These don't touch the network — `extract_candidates_from_entry` is
pure regex + slicing.
"""

from __future__ import annotations

from eval_harness.replay_extractor import (
    CONTEXT_CHARS_AFTER,
    CONTEXT_CHARS_BEFORE,
    extract_candidates_from_entry,
)


def _entry(content: str, journal_id: str = "jrn_test") -> dict:
    return {
        "id": journal_id,
        "content": content,
        "created_at": "2026-05-14T00:00:00Z",
    }


def test_rka_search_simple_mention():
    candidates = extract_candidates_from_entry(
        _entry("Brain ran rka_search to find the decision.")
    )
    assert len(candidates) == 1
    c = candidates[0]
    assert c.tool == "rka_search"
    assert c.query is None  # prose mention, no structured call
    assert c.original_journal_id == "jrn_test"


def test_rka_get_research_map_mention():
    candidates = extract_candidates_from_entry(
        _entry("Then call rka_get_research_map for the cluster overview.")
    )
    assert len(candidates) == 1
    assert candidates[0].tool == "rka_get_research_map"


def test_rka_multi_hop_retrieval_mention():
    candidates = extract_candidates_from_entry(
        _entry("Try rka_multi_hop_retrieval with max_depth=3.")
    )
    assert len(candidates) == 1
    assert candidates[0].tool == "rka_multi_hop_retrieval"


def test_call_with_positional_string_extracts_query():
    candidates = extract_candidates_from_entry(
        _entry('We tried rka_search("AND-fix evaluation") earlier.')
    )
    assert len(candidates) == 1
    assert candidates[0].query == "AND-fix evaluation"


def test_call_with_keyword_arg_extracts_query():
    candidates = extract_candidates_from_entry(
        _entry('rka_search(query="provenance trail") returned no results.')
    )
    assert len(candidates) == 1
    assert candidates[0].query == "provenance trail"


def test_call_with_single_quotes_extracts_query():
    candidates = extract_candidates_from_entry(
        _entry("rka_search('decisions about agentic workflow')")
    )
    assert len(candidates) == 1
    assert candidates[0].query == "decisions about agentic workflow"


def test_json_tool_use_block_extracts_query():
    content = (
        '"tool_use": {"name": "rka_search", "input": '
        '{"query": "Brain calibration", "limit": 10}}'
    )
    candidates = extract_candidates_from_entry(_entry(content))
    assert len(candidates) >= 1
    queries = [c.query for c in candidates if c.query]
    assert "Brain calibration" in queries


def test_multiple_mentions_yield_multiple_candidates():
    content = (
        "First rka_search for clusters, then rka_get_research_map "
        "for synthesis, finally rka_multi_hop_retrieval for the chain."
    )
    candidates = extract_candidates_from_entry(_entry(content))
    tools = {c.tool for c in candidates}
    assert tools == {
        "rka_search",
        "rka_get_research_map",
        "rka_multi_hop_retrieval",
    }


def test_no_mentions_yields_empty():
    candidates = extract_candidates_from_entry(
        _entry("Plain narrative with no retrieval calls.")
    )
    assert candidates == []


def test_empty_content_yields_empty():
    assert extract_candidates_from_entry(_entry("")) == []


def test_context_window_size_approx_matches_documented_bounds():
    # Place the tool mention in the middle of a long string so we can
    # measure context-window slicing predictably. The mention must be
    # surrounded by non-word chars so the `\b` regex boundary fires.
    prefix = "x" * 500
    suffix = "y" * 500
    content = prefix + " rka_search " + suffix
    candidates = extract_candidates_from_entry(_entry(content))
    assert len(candidates) == 1
    ctx = candidates[0].original_context
    # `…` markers indicate truncation on both sides; the context bytes
    # in between should be roughly CONTEXT_CHARS_BEFORE + CONTEXT_CHARS_AFTER
    # + "rka_search" length + the two adjacent spaces we added.
    inner = ctx.strip(" …")
    expected_inner_chars = CONTEXT_CHARS_BEFORE + len("rka_search") + CONTEXT_CHARS_AFTER
    # Allow some slack for whitespace stripping + the adjacency spaces.
    assert abs(len(inner) - expected_inner_chars) < 10


def test_does_not_match_substring_of_other_word():
    # "rka_search_helper" should NOT match as `rka_search` (word boundary).
    # \b boundary on the regex makes underscore-extended names skipped.
    # NB: actually rka_search IS a prefix here separated by underscore which
    # IS a word char, so the regex won't word-boundary at the underscore.
    # In our case, the implementation treats `_` as part of the identifier,
    # so `rka_search_helper` does NOT match `\brka_search\b`. Verify.
    candidates = extract_candidates_from_entry(_entry("foo rka_search_helper bar"))
    assert candidates == []
