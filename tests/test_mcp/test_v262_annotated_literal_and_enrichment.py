"""v2.6.2 — Annotated[Literal] type-hint promotion + 4xx/5xx
response enrichment regression tests.

v2.6.2 promotes the canonical RKA enum values from docstring-only
declarations to `Annotated[Literal[...], Field(description=...)]` on
the MCP signatures. FastMCP renders these into
`inputSchema.properties.*.enum` so LLM clients (Claude Desktop,
Claude Code, etc.) see the constrained set directly in the rendered
tool definition.

Plus enrichment of the MCP-side `_raise_with_detail` to format
FastAPI's structured 422 validation-error detail (list-of-dicts
shape) into a human-readable per-field summary. Mirrors the
orchestrator's Phase-X² polish RestMCPClient enrichment for
consistent diagnostic surface across the agentic + main code paths.
"""

from __future__ import annotations

import inspect
import typing
from typing import get_args, get_origin

import pytest

from rka.mcp import server as mcp_server


def _get_underlying_func(name: str):
    obj = getattr(mcp_server, name, None)
    if obj is None:
        return None
    for attr in ("fn", "func", "__wrapped__"):
        fn = getattr(obj, attr, None)
        if fn is not None and inspect.iscoroutinefunction(fn):
            return fn
    if inspect.iscoroutinefunction(obj):
        return obj
    return None


def _resolved_annotation(fn, param_name: str):
    """Resolve a parameter's annotation through PEP 563's
    `from __future__ import annotations` postponed-evaluation. Uses
    typing.get_type_hints with include_extras=True so the
    Annotated[Literal[...], Field(...)] envelope survives."""
    hints = typing.get_type_hints(fn, include_extras=True)
    return hints.get(param_name)


# ---------------------------------------------------------------------------
# Annotated[Literal] promotion regression
# ---------------------------------------------------------------------------


def _literal_values(annotation) -> tuple[str, ...] | None:
    """Extract the Literal[...] string values from an
    Annotated[Literal[...], ...] annotation. Returns None when the
    annotation isn't an Annotated[Literal] shape (i.e. promotion
    hasn't happened yet)."""
    # Annotated[Literal[...], ...] surfaces as Annotated origin with
    # __metadata__ containing the Field(...); typing.get_args returns
    # (Literal[...], *metadata).
    args = get_args(annotation)
    if not args:
        return None
    literal_part = args[0]
    if get_origin(literal_part) is None:
        return None
    return get_args(literal_part)


def test_rka_add_note_confidence_uses_annotated_literal() -> None:
    """`confidence` parameter on rka_add_note must be promoted to
    Annotated[Literal[...]] so LLMs see the enum via inputSchema."""
    fn = _get_underlying_func("rka_add_note")
    if fn is None:
        pytest.skip("could not unwrap @tool() for rka_add_note")
    annotation = _resolved_annotation(fn, "confidence")
    values = _literal_values(annotation)
    assert values is not None, (
        f"rka_add_note.confidence is not Annotated[Literal[...]] — "
        f"got: {annotation!r}"
    )
    assert "hypothesis" in values
    assert "tested" in values
    assert "verified" in values
    assert "superseded" in values
    assert "retracted" in values
    # Critical: 'confirmed' is NOT a valid value (empirical Brain hallucination).
    assert "confirmed" not in values


def test_rka_add_note_importance_uses_annotated_literal() -> None:
    fn = _get_underlying_func("rka_add_note")
    if fn is None:
        pytest.skip("could not unwrap @tool() for rka_add_note")
    annotation = _resolved_annotation(fn, "importance")
    values = _literal_values(annotation)
    assert values is not None
    assert set(values) == {"critical", "high", "normal", "low", "archived"}


def test_rka_add_note_source_uses_annotated_literal() -> None:
    fn = _get_underlying_func("rka_add_note")
    if fn is None:
        pytest.skip("could not unwrap @tool() for rka_add_note")
    annotation = _resolved_annotation(fn, "source")
    values = _literal_values(annotation)
    assert values is not None
    assert "brain" in values and "executor" in values and "pi" in values


def test_rka_add_decision_decided_by_uses_annotated_literal() -> None:
    fn = _get_underlying_func("rka_add_decision")
    if fn is None:
        pytest.skip("could not unwrap @tool() for rka_add_decision")
    annotation = _resolved_annotation(fn, "decided_by")
    values = _literal_values(annotation)
    assert values is not None
    assert set(values) == {"pi", "brain", "executor"}


def test_rka_add_decision_kind_uses_annotated_literal() -> None:
    fn = _get_underlying_func("rka_add_decision")
    if fn is None:
        pytest.skip("could not unwrap @tool() for rka_add_decision")
    annotation = _resolved_annotation(fn, "kind")
    values = _literal_values(annotation)
    assert values is not None
    assert set(values) == {
        "research_question", "design_choice", "decision", "operational",
    }


def test_rka_submit_checkpoint_type_uses_annotated_literal() -> None:
    fn = _get_underlying_func("rka_submit_checkpoint")
    if fn is None:
        pytest.skip("could not unwrap @tool() for rka_submit_checkpoint")
    annotation = _resolved_annotation(fn, "type")
    values = _literal_values(annotation)
    assert values is not None
    assert set(values) == {"decision", "clarification", "inspection", "gate"}


def test_rka_update_mission_status_status_uses_annotated_literal() -> None:
    fn = _get_underlying_func("rka_update_mission_status")
    if fn is None:
        pytest.skip("could not unwrap @tool() for rka_update_mission_status")
    annotation = _resolved_annotation(fn, "status")
    values = _literal_values(annotation)
    assert values is not None
    assert set(values) == {
        "pending", "active", "complete", "partial", "blocked", "cancelled",
    }


def test_rka_ingest_document_source_uses_annotated_literal() -> None:
    fn = _get_underlying_func("rka_ingest_document")
    if fn is None:
        pytest.skip("could not unwrap @tool() for rka_ingest_document")
    annotation = _resolved_annotation(fn, "source")
    values = _literal_values(annotation)
    assert values is not None
    assert set(values) == {"brain", "executor", "pi", "import", "web_ui"}


# ---------------------------------------------------------------------------
# 4xx/5xx response enrichment regression
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal httpx.Response stand-in for _raise_with_detail tests."""

    def __init__(self, status_code: int, body: object, text: str = ""):
        self.status_code = status_code
        self._body = body
        self.text = text

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        if self._body is None:
            raise ValueError("no json body")
        return self._body


def test_raise_with_detail_renders_structured_422_validation_errors() -> None:
    """The hyperscaler-auditing empirical bug shape — FastAPI 422 with
    a list-of-dicts detail (per-field validation errors). Pre-v2.6.2
    this collapsed to a repr; post-v2.6.2 each entry renders as
    `<field>=<input>: <msg>`."""
    body = {
        "detail": [
            {
                "loc": ["body", "confidence"],
                "msg": "Input should be one of: hypothesis, tested, ...",
                "type": "literal_error",
                "input": "confirmed",
                "ctx": {"expected": "'hypothesis', 'tested', 'verified'"},
            }
        ]
    }
    response = _FakeResponse(422, body)
    with pytest.raises(Exception) as exc:
        mcp_server._raise_with_detail(response)
    msg = str(exc.value)
    assert "422" in msg
    assert "confidence" in msg
    assert "confirmed" in msg  # offending value surfaced
    assert "Input should be one of" in msg


def test_raise_with_detail_handles_multiple_validation_errors() -> None:
    """Multiple per-field errors render as joined entries."""
    body = {
        "detail": [
            {"loc": ["body", "type"], "msg": "missing", "type": "value_error"},
            {"loc": ["body", "summary"], "msg": "field required",
             "type": "missing"},
        ]
    }
    response = _FakeResponse(422, body)
    with pytest.raises(Exception) as exc:
        mcp_server._raise_with_detail(response)
    msg = str(exc.value)
    assert "type" in msg and "summary" in msg
    # Both errors rendered, separated by '; '
    assert msg.count(";") >= 1


def test_raise_with_detail_passes_through_404_string_detail() -> None:
    """404 / 409 / 500 with a plain-string `detail` field continue to
    render as before (no regression for non-422 shapes)."""
    body = {"detail": "Mission mis_test not found"}
    response = _FakeResponse(404, body)
    with pytest.raises(Exception) as exc:
        mcp_server._raise_with_detail(response)
    msg = str(exc.value)
    assert "404" in msg
    assert "Mission mis_test not found" in msg


def test_raise_with_detail_falls_back_to_text_when_no_json_body() -> None:
    """Plain-text 5xx responses (no JSON body) fall back to r.text."""
    response = _FakeResponse(500, None, text="Internal Server Error")
    with pytest.raises(Exception) as exc:
        mcp_server._raise_with_detail(response)
    msg = str(exc.value)
    assert "500" in msg
    assert "Internal Server Error" in msg


def test_raise_with_detail_strips_loc_prefix() -> None:
    """The leading 'body'/'query'/'path' prefix is stripped from the
    loc path so `body.confidence` reads as `confidence`."""
    body = {
        "detail": [
            {"loc": ["body", "mission_id"], "msg": "missing",
             "input": None, "type": "missing"},
        ]
    }
    response = _FakeResponse(422, body)
    with pytest.raises(Exception) as exc:
        mcp_server._raise_with_detail(response)
    msg = str(exc.value)
    # 'mission_id' present but not 'body.mission_id'
    assert "mission_id" in msg
    assert "body.mission_id" not in msg
    assert "body=" not in msg


def test_raise_with_detail_noop_on_success() -> None:
    """2xx responses don't raise."""
    response = _FakeResponse(200, {"ok": True})
    mcp_server._raise_with_detail(response)  # should not raise


def test_format_validation_detail_handles_non_dict_items() -> None:
    """If FastAPI's detail entry isn't a dict (unusual but possible
    under custom exception handlers), fall back to str()."""
    out = mcp_server._format_validation_detail([
        "raw-string entry",
        {"loc": ["body", "x"], "msg": "ok", "input": "v"},
    ])
    assert "raw-string entry" in out
    assert "x" in out
