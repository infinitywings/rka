"""`submit_report`'s list fields must be reachable.

`findings`, `anomalies` and `questions` could not be populated in any shape.
The typed `submit_report` operation declares `list[str]` — matching
`MissionReportCreate`, which is also `list[str]` — but the legacy tool the
dispatcher calls accepted only newline-separated text and ran `.strip()` on
whatever it got. So a list crashed the adapter with `'list' object has no
attribute 'strip'`, a string was refused by the typed model before the call
was emitted, and omitting the fields was the only thing that worked. Reports
went in with their findings silently dropped.

The two ends already agreed; the tool in the middle was the odd one out, so it
is the one that learns both shapes.

Found by an Executor agent running a real mission, not by the type checker —
each layer was internally consistent.
"""

from __future__ import annotations

import inspect
import json

import httpx
import pytest

from rka.mcp import server
from rka.mcp.operation_args import SubmitReportArgs
from rka.mcp.operations_schema import OPERATIONS_SCHEMA
from rka.models.mission import MissionReportCreate


from rka.mcp.server import _report_lines


class TestNormaliser:
    def test_a_list_survives(self):
        assert _report_lines(["one", "two"]) == ["one", "two"]

    def test_newline_text_still_splits(self):
        assert _report_lines("one\ntwo") == ["one", "two"]

    @pytest.mark.parametrize("value", [None, "", "   ", [], ["", "  "]])
    def test_empty_shapes_become_none(self, value):
        assert _report_lines(value) is None

    def test_blank_entries_are_dropped_from_a_list(self):
        assert _report_lines(["one", "", "  ", "two"]) == ["one", "two"]

    def test_entries_are_stripped(self):
        assert _report_lines(["  padded  "]) == ["padded"]


class TestLayersAgree:
    def test_the_typed_model_and_the_rest_model_declare_the_same_shape(self):
        typed = SubmitReportArgs.model_fields["findings"].annotation
        rest = MissionReportCreate.model_fields["findings"].annotation
        assert "list" in str(typed) and "list" in str(rest)

    @pytest.mark.parametrize("field", ["findings", "anomalies", "questions"])
    def test_the_tool_accepts_both_shapes(self, field):
        parameter = inspect.signature(server.rka_submit_report).parameters[field]
        assert "list" in str(parameter.annotation), (
            f"{field} must accept the list the typed layer sends"
        )

    def test_a_list_the_typed_model_accepts_reaches_the_rest_model(self):
        """End to end across the three layers, without a live server."""
        findings = ["p99 dropped 30%.", "cold start regressed."]
        SubmitReportArgs(
            project_id="prj_01TEST0000000000000000000",
            mission_id="mis_01TEST0000000000000000000",
            summary="done",
            findings=findings,
        )
        assert _report_lines(findings) == findings
        MissionReportCreate(summary="done", findings=_report_lines(findings))


class TestDocumentedExample:
    """The example is what an agent copies; it must be a shape that works."""

    def test_the_example_findings_validate_against_both_models(self):
        example = OPERATIONS_SCHEMA["submit_report"]["examples"][0]["call"]
        findings = example.get("findings")
        if findings is None:
            pytest.skip("the example does not set findings")
        SubmitReportArgs(
            project_id="prj_01TEST0000000000000000000",
            mission_id="mis_01TEST0000000000000000000",
            summary="done",
            findings=findings,
        )
        MissionReportCreate(summary="done", findings=_report_lines(findings))


@pytest.mark.asyncio
async def test_typed_submit_report_returns_mission_consistency_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning = (
        "Mission is complete but has non-terminal task rows (pending=1); "
        "reconcile task status before treating the report as a fully closed "
        "execution record."
    )
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "path": request.url.path,
                "body": json.loads(request.content),
            }
        )
        return httpx.Response(
            200,
            json={
                "id": "mis_01TEST",
                "project_id": "prj_01TEST",
                "status": "complete",
                "tasks": [{"description": "unfinished", "status": "pending"}],
                "report": {"mission_id": "mis_01TEST", "summary": "done"},
                "consistency_warnings": [warning],
            },
        )

    def client(_project_id: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://testserver",
        )

    monkeypatch.setattr(server, "_client", client)
    result = await server.rka_execute(
        SubmitReportArgs(
            operation="submit_report",
            project_id="prj_01TEST",
            mission_id="mis_01TEST",
            summary="done",
        )
    )
    payload = json.loads(result)

    assert payload["status"] == "complete"
    assert payload["report"]["summary"] == "done"
    assert payload["consistency_warnings"] == [warning]
    report_request = next(
        request
        for request in captured
        if request["path"] == "/api/missions/mis_01TEST/report"
    )
    assert report_request["body"] == {
        "summary": "done",
        "tasks_completed": ["done"],
    }
