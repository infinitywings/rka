"""Unit test for the `RKA_FTS_QUERY_MODE` feature flag.

This is the ONLY `rka/` modification this mission introduces — adds a
mode toggle on `SearchService._sanitize_fts_query`. The test lives in
`eval-harness/tests/` (not `tests/test_services/`) per the mission's
scope_boundaries lock keeping the eval-harness self-contained.
PR-review can relocate later if the test naturally belongs alongside
other service unit tests.

Mission: mis_01KRKJ9G20EM5XMA147JTKQCFF
"""

from __future__ import annotations

import pytest

from rka.services.search import SearchService


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Ensure each test starts with no `RKA_FTS_QUERY_MODE` set."""
    monkeypatch.delenv("RKA_FTS_QUERY_MODE", raising=False)


def test_default_mode_is_or_space_joined():
    # Default behavior with no env var: space-joined quoted tokens.
    assert (
        SearchService._sanitize_fts_query("foo bar baz")
        == '"foo" "bar" "baz"'
    )


def test_explicit_or_matches_default(monkeypatch):
    monkeypatch.setenv("RKA_FTS_QUERY_MODE", "or")
    assert (
        SearchService._sanitize_fts_query("foo bar baz")
        == '"foo" "bar" "baz"'
    )


def test_and_mode_uses_explicit_AND_separator(monkeypatch):
    monkeypatch.setenv("RKA_FTS_QUERY_MODE", "and")
    assert (
        SearchService._sanitize_fts_query("foo bar baz")
        == '"foo" AND "bar" AND "baz"'
    )


def test_case_insensitive_and(monkeypatch):
    for value in ("and", "AND", "And", " and ", "\tAND\n"):
        monkeypatch.setenv("RKA_FTS_QUERY_MODE", value)
        assert (
            SearchService._sanitize_fts_query("foo bar")
            == '"foo" AND "bar"'
        ), f"value={value!r} should be normalized to and"


def test_unknown_value_falls_back_to_or_silently(monkeypatch):
    # Safe-default behavior: an unrecognized mode does NOT raise; it
    # preserves the pre-flag production semantics.
    monkeypatch.setenv("RKA_FTS_QUERY_MODE", "xor")
    assert SearchService._sanitize_fts_query("foo bar") == '"foo" "bar"'


def test_single_word_emits_no_separator_in_and_mode(monkeypatch):
    monkeypatch.setenv("RKA_FTS_QUERY_MODE", "and")
    assert SearchService._sanitize_fts_query("foo") == '"foo"'


def test_empty_query_returns_unchanged(monkeypatch):
    monkeypatch.setenv("RKA_FTS_QUERY_MODE", "and")
    assert SearchService._sanitize_fts_query("") == ""


def test_non_word_query_returns_unchanged(monkeypatch):
    # FTS5 syntax characters with no alphanumerics fall through.
    monkeypatch.setenv("RKA_FTS_QUERY_MODE", "and")
    assert SearchService._sanitize_fts_query("???") == "???"


def test_hyphenated_tokens_split_into_separate_terms(monkeypatch):
    # `_sanitize_fts_query` splits on non-word characters, so
    # "snake_case-mixed" produces three separate quoted terms in both
    # modes. The AND-mode case is what the mission's Q7
    # (`_sanitize_fts_query AND-fix evaluation`) exercises empirically.
    monkeypatch.setenv("RKA_FTS_QUERY_MODE", "and")
    assert (
        SearchService._sanitize_fts_query("snake_case-mixed")
        == '"snake" AND "case" AND "mixed"'
    )
