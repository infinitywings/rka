"""v2.7.0.2 Bug 2: rka_execute / rka_query MUST JSON-stringify dict/list
dispatch returns.

Pre-v2.7.0.2 the wrappers declared `result: str` but operations whose
legacy tool returned a dict (link_literature_to_zotero, enrich_doi,
process_paper, validate_reference, …) propagated the dict through
unchanged. FastMCP's output validator rejected it as a string-type
mismatch — AFTER the underlying DB write had already landed. The PI
cockpit saw every dict-returning success as a client-side error.

This test pins the coercion contract directly on `_coerce_result_to_str`
plus end-to-end stubs that exercise the typed dispatch wrappers.
"""

from __future__ import annotations

import json

import pytest

from rka.mcp.verb_dispatch import _coerce_result_to_str


# ---------------------------------------------------------------------------
# Coerce helper — direct unit tests
# ---------------------------------------------------------------------------


def test_string_passthrough_no_re_encode():
    """Strings are returned as-is; coercion must not double-encode JSON."""
    assert _coerce_result_to_str("plain text") == "plain text"
    assert _coerce_result_to_str("Created jrn_01KT...") == "Created jrn_01KT..."
    # A string that happens to look like JSON stays a string — no parse-reformat.
    assert _coerce_result_to_str('{"already": "json"}') == '{"already": "json"}'


def test_none_becomes_empty_string():
    assert _coerce_result_to_str(None) == ""


def test_dict_becomes_json_string_callers_can_parse():
    """The Bug 2 case: dict-returning ops (link_literature_to_zotero etc.)
    must come back as a JSON string callers can json.loads() to recover
    structure."""
    payload = {"zotero_item_key": "IYWFJ23U", "matched_by": "title_author_year", "confidence": 1.35}
    out = _coerce_result_to_str(payload)
    assert isinstance(out, str)
    decoded = json.loads(out)
    assert decoded == payload


def test_list_becomes_json_string():
    """List results (e.g. search ops) get the same treatment."""
    payload = [{"id": "lit_01", "title": "x"}, {"id": "lit_02", "title": "y"}]
    out = _coerce_result_to_str(payload)
    decoded = json.loads(out)
    assert decoded == payload


def test_nested_dict_preserves_structure():
    payload = {
        "result": "ok",
        "details": {
            "candidates": [
                {"key": "AAA", "score": 0.9},
                {"key": "BBB", "score": 0.7},
            ],
            "reason": "weak_match_needs_confirmation",
        },
    }
    out = _coerce_result_to_str(payload)
    assert json.loads(out) == payload


def test_unrenderable_payload_falls_back_to_repr_not_raise():
    """Even genuinely unrenderable payloads must NOT raise out of the
    dispatch layer — the upstream operation may have already landed a
    DB write; an exception here would surface as a client error AFTER
    success. Fall back to repr() so the caller at least sees something."""

    class _Unrenderable:
        def __repr__(self):
            return "<_Unrenderable>"

        def __str__(self):
            return repr(self)

    # Force json.dumps to raise even with default=str by making __repr__
    # itself raise — default=str ultimately calls str(obj) on non-JSON-able
    # values, which here would succeed via __str__. Wrap inside a dict
    # whose default=str path actually raises during json encoding to test
    # the except branch. Easier: monkeypatch json.dumps.
    import json as _json
    from rka.mcp import verb_dispatch as VD

    sentinel = object()

    def _boom(*args, **kwargs):
        raise TypeError("simulated unrenderable")

    original = _json.dumps
    try:
        VD.json.dumps = _boom  # type: ignore[attr-defined]
        result = _coerce_result_to_str({"unrenderable": sentinel})
        # Doesn't raise; falls back to repr()
        assert isinstance(result, str)
        assert "unrenderable" in result or "object at" in result
    finally:
        VD.json.dumps = original  # type: ignore[attr-defined]


def test_unicode_passthrough_no_ascii_escape():
    """Non-ASCII content (e.g. paper titles with accents) must survive
    coercion without \\uXXXX escaping — readability matters for clients
    that display the string directly."""
    payload = {"title": "Détecter les anomalies — données financières (β)"}
    out = _coerce_result_to_str(payload)
    decoded = json.loads(out)
    assert decoded == payload
    # The raw string must contain the actual UTF-8 character, not \\uXXXX
    assert "Détecter" in out
    assert "β" in out


# ---------------------------------------------------------------------------
# End-to-end dispatch wrappers — confirm the wrapper actually wraps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_execute_typed_coerces_dict_result(monkeypatch):
    """The Bug 2 reproducer: a dispatch_execute that returns a dict (as
    link_literature_to_zotero does) must surface as a JSON string at the
    typed-dispatch boundary."""
    from rka.mcp import verb_dispatch as VD

    # Stub the underlying legacy dispatch to return a dict
    async def _stub_dispatch_execute(op, **kwargs):
        return {"zotero_item_key": "IYWFJ23U", "matched_by": "title_author_year"}

    monkeypatch.setattr(VD, "dispatch_execute", _stub_dispatch_execute)

    # Build a typed Args model — use LinkLiteratureToZoteroArgs since it
    # routes through the link_literature_to_zotero branch in
    # dispatch_execute_typed → dispatch_execute → dispatch_record_literature
    from rka.mcp.operation_args import LinkLiteratureToZoteroArgs

    args = LinkLiteratureToZoteroArgs(
        project_id="prj_test",
        lit_id="lit_test",
    )

    result = await VD.dispatch_execute_typed(args)
    assert isinstance(result, str)
    decoded = json.loads(result)
    assert decoded["zotero_item_key"] == "IYWFJ23U"
    assert decoded["matched_by"] == "title_author_year"


@pytest.mark.asyncio
async def test_dispatch_execute_typed_passes_through_string_result(monkeypatch):
    """When the underlying op already returns a string (record_note's
    'Created jrn_01...' return), coercion is a passthrough."""
    from rka.mcp import verb_dispatch as VD

    async def _stub(op, **kwargs):
        return "Created jrn_01KTSTUB"

    monkeypatch.setattr(VD, "dispatch_execute", _stub)

    from rka.mcp.operation_args import RecordNoteArgs

    args = RecordNoteArgs(
        project_id="prj_test",
        content="smoke test",
    )

    result = await VD.dispatch_execute_typed(args)
    assert result == "Created jrn_01KTSTUB"


@pytest.mark.asyncio
async def test_dispatch_query_typed_coerces_list_result(monkeypatch):
    """rka_query operations like list_projects return lists — must come
    back as a JSON string."""
    from rka.mcp import verb_dispatch as VD

    async def _stub_session(scope):
        if scope == "list_projects":
            return [{"id": "prj_a"}, {"id": "prj_b"}]
        return None

    monkeypatch.setattr(VD, "dispatch_session", _stub_session)

    from rka.mcp.operation_args import QueryListProjectsArgs

    args = QueryListProjectsArgs()
    result = await VD.dispatch_query_typed(args)
    assert isinstance(result, str)
    decoded = json.loads(result)
    assert decoded == [{"id": "prj_a"}, {"id": "prj_b"}]
