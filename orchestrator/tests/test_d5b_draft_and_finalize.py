"""Phase D, D5b + D7 — draft_manifest_node + finalize_node tests.

Covers:
  - draft_manifest_node: writes tools.json + .env template, captures
    hash + path into state, handles missing project_id or empty
    ratified_toolkit gracefully.
  - finalize_node: probes credentials, escalates on required failures,
    emits the audit-trail journal entry (Q5), updates the manifest's
    audit_journal_id, surfaces clear errors when prerequisites are
    missing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from orchestrator import manifest as M
from orchestrator.nodes import onboarding as O


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    os.environ["RKA_PROJECTS_ROOT"] = str(tmp_path)
    yield tmp_path
    os.environ.pop("RKA_PROJECTS_ROOT", None)


class _StubSDK:
    def complete(self, **kw):
        return ""


class _RecordingMCP:
    """MCP fake that records every rka_add_note call. Scripted to
    return a deterministic id."""

    workflow_thread_id = "thr_t"

    def __init__(self, *, raise_on_add: bool = False):
        self.calls: list[dict] = []
        self.raise_on_add = raise_on_add
        self.next_id = "jrn_audit_test_001"

    def rka_add_note(self, **kw) -> str:
        if self.raise_on_add:
            raise RuntimeError("simulated rka write failure")
        self.calls.append({"op": "rka_add_note", **kw})
        return self.next_id


def _ratified_toolkit_two_tools() -> list[dict]:
    """Sample ratified_toolkit dict-list (the shape pi_toolkit_ratify
    produces on accept)."""
    return [
        {
            "name": "rka",
            "type": "mcp_stdio",
            "command": None,
            "args": [],
            "secrets": [],
            "always_on": True,
            "rationale": "baseline KB",
            "source": "registry",
        },
        {
            "name": "context7",
            "type": "mcp_stdio",
            "command": "npx",
            "args": ["-y", "@upstash/context7-mcp@latest"],
            "secrets": [],
            "always_on": False,
            "rationale": "docs lookup",
            "source": "registry",
        },
    ]


def _state_for_draft(
    project_id: str = "prj_d5b_test",
    ratified: list[dict] | None = None,
    topic_summary: str = "a test topic",
) -> dict:
    return {
        "workflow_thread_id": "thr_t",
        "mission_id": "mis_t",
        "project_id": project_id,
        "ratified_toolkit": ratified if ratified is not None else _ratified_toolkit_two_tools(),
        "topic_metadata": {
            "summary": topic_summary,
            "research_field": "ml systems",
            "venue": "MLSys 2026",
            "keywords": ["edge", "llm"],
        },
    }


# ---------------------------------------------------------------------------
# draft_manifest_node
# ---------------------------------------------------------------------------


def test_draft_manifest_writes_tools_json_with_ratified_tools(tmp_root: Path):
    state = _state_for_draft()
    update = O.draft_manifest_node(state, _StubSDK(), _RecordingMCP())
    # tools.json exists under the workspace dir.
    path = M.manifest_path(state["project_id"])
    assert path.exists()
    # Manifest re-loads with the right tools.
    loaded = M.load_manifest(state["project_id"])
    assert loaded is not None
    assert loaded.manifest_type == "baseline"
    assert [t.name for t in loaded.tools] == ["rka", "context7"]
    # Topic captured.
    assert loaded.topic is not None
    assert loaded.topic.venue == "MLSys 2026"
    # State update carries the hash + path.
    assert update["draft_manifest_path"] == str(path)
    assert update["draft_manifest_hash"] == loaded.compute_hash()


def test_draft_manifest_writes_env_template(tmp_root: Path):
    """When tools declare secrets, the .env template is written with
    placeholders."""
    state = _state_for_draft(
        ratified=[
            {
                "name": "sec-edgar",
                "type": "mcp_stdio",
                "secrets": [
                    {
                        "name": "SEC_EDGAR_API_KEY",
                        "auth_type": "api_key",
                        "criticality": "required",
                        "description": "SEC EDGAR API key",
                    }
                ],
            }
        ]
    )
    O.draft_manifest_node(state, _StubSDK(), _RecordingMCP())
    env = M.env_path(state["project_id"]).read_text()
    assert "SEC_EDGAR_API_KEY=<paste-here>" in env
    assert "(required)" in env


def test_draft_manifest_skips_env_template_when_no_secrets(tmp_root: Path):
    """No secrets → .env template still written (header + boilerplate),
    just with no actual `KEY=<paste-here>` placeholder lines.

    The instructional header mentions <paste-here> as a literal, so we
    can't grep for that substring; we grep for the placeholder PATTERN
    (=<paste-here> at the end of a line) instead.
    """
    state = _state_for_draft()
    O.draft_manifest_node(state, _StubSDK(), _RecordingMCP())
    env_p = M.env_path(state["project_id"])
    assert env_p.exists()
    text = env_p.read_text()
    # File is mostly the header — no actual KEY=value lines.
    assert "Generated by orchestrator onboarding" in text
    # No `KEY=<paste-here>` placeholder lines.
    placeholder_lines = [ln for ln in text.splitlines() if ln.endswith("=<paste-here>")]
    assert placeholder_lines == []


def test_draft_manifest_records_error_when_project_id_missing(tmp_root: Path):
    state = _state_for_draft(project_id="")
    update = O.draft_manifest_node(state, _StubSDK(), _RecordingMCP())
    errs = update.get("errors") or []
    assert any(e["error_type"] == "draft_manifest_no_project_id" for e in errs)
    # No manifest written.
    assert not M.manifest_path("prj_d5b_test").exists()


def test_draft_manifest_records_error_when_ratified_empty(tmp_root: Path):
    state = _state_for_draft(ratified=[])
    update = O.draft_manifest_node(state, _StubSDK(), _RecordingMCP())
    errs = update.get("errors") or []
    assert any(e["error_type"] == "draft_manifest_empty_toolkit" for e in errs)


def test_draft_manifest_marks_current_node(tmp_root: Path):
    state = _state_for_draft()
    update = O.draft_manifest_node(state, _StubSDK(), _RecordingMCP())
    assert update["current_node"] == "draft_manifest"


# ---------------------------------------------------------------------------
# finalize_node
# ---------------------------------------------------------------------------


def test_finalize_records_audit_journal_when_all_creds_ok(tmp_root: Path):
    # Set up: draft a manifest, fill in any required secrets in .env,
    # then run finalize. Use a no-secrets manifest so the probe layer
    # passes trivially.
    state = _state_for_draft()
    O.draft_manifest_node(state, _StubSDK(), _RecordingMCP())
    mcp = _RecordingMCP()
    update = O.finalize_node(state, _StubSDK(), mcp)
    assert update["finalize_outcome"] == "complete"
    assert update["audit_journal_id"] == mcp.next_id
    # Audit entry was written via rka_add_note.
    add_calls = [c for c in mcp.calls if c["op"] == "rka_add_note"]
    assert len(add_calls) == 1
    note = add_calls[0]
    assert note["source"] == "system"
    assert set(["orchestrator", "onboarding", "baseline"]).issubset(set(note["tags"]))
    # Audit content references the manifest hash.
    assert "sha256:" in note["content"]
    # Manifest on disk now has audit_journal_id populated.
    reloaded = M.load_manifest(state["project_id"])
    assert reloaded.audit_journal_id == mcp.next_id


def test_finalize_escalates_on_required_secret_missing(tmp_root: Path):
    """Required-tier failure → checkpoint emitted; no audit entry."""
    state = _state_for_draft(
        ratified=[
            {
                "name": "sec-edgar",
                "type": "mcp_stdio",
                "command": "npx",
                "args": ["@sec-edgar/mcp"],
                "secrets": [
                    {
                        "name": "SEC_EDGAR_API_KEY",
                        "auth_type": "api_key",
                        "criticality": "required",
                        "probe_url": None,  # no probe; will be 'no_probe' if value present
                        "description": "key",
                    }
                ],
            }
        ]
    )
    O.draft_manifest_node(state, _StubSDK(), _RecordingMCP())
    # .env still has the placeholder; no value set → required missing.
    mcp = _RecordingMCP()
    update = O.finalize_node(state, _StubSDK(), mcp)
    assert update["finalize_outcome"] == "escalated_required_missing"
    assert update.get("checkpoints"), "checkpoint must be created"
    chk = update["checkpoints"][0]
    assert "SEC_EDGAR_API_KEY" in chk["reason"]
    assert chk["resolved"] is False
    # No audit entry written (escalation aborts the happy-path emit).
    assert all(c["op"] != "rka_add_note" for c in mcp.calls)


def test_finalize_records_error_when_no_project_id(tmp_root: Path):
    state = {"workflow_thread_id": "thr_t", "mission_id": "mis_t"}
    update = O.finalize_node(state, _StubSDK(), _RecordingMCP())
    errs = update.get("errors") or []
    assert any(e["error_type"] == "finalize_no_project_id" for e in errs)


def test_finalize_records_error_when_no_manifest_on_disk(tmp_root: Path):
    """finalize_node depends on draft_manifest_node having run first.
    Without a manifest, surface a clear error rather than crash."""
    state = {
        "workflow_thread_id": "thr_t",
        "mission_id": "mis_t",
        "project_id": "prj_no_draft",
    }
    update = O.finalize_node(state, _StubSDK(), _RecordingMCP())
    errs = update.get("errors") or []
    assert any(e["error_type"] == "finalize_no_manifest" for e in errs)


def test_finalize_handles_rka_add_note_failure_gracefully(tmp_root: Path):
    """If the audit-write call raises, finalize records an error and
    DOES NOT crash the workflow."""
    state = _state_for_draft()
    O.draft_manifest_node(state, _StubSDK(), _RecordingMCP())
    mcp = _RecordingMCP(raise_on_add=True)
    update = O.finalize_node(state, _StubSDK(), mcp)
    assert update["finalize_outcome"] == "failed"
    errs = update.get("errors") or []
    assert any(e["error_type"] == "finalize_audit_write_failed" for e in errs)


def test_finalize_marks_current_node(tmp_root: Path):
    state = _state_for_draft()
    O.draft_manifest_node(state, _StubSDK(), _RecordingMCP())
    update = O.finalize_node(state, _StubSDK(), _RecordingMCP())
    assert update["current_node"] == "finalize"


def test_finalize_audit_summary_omits_secret_values(tmp_root: Path):
    """Critical safety: the audit journal entry's content must never
    contain a credential value. Test verifies a planted SECRET string
    in .env doesn't leak into the rka_add_note content arg."""
    state = _state_for_draft(
        ratified=[
            {
                "name": "test-tool",
                "type": "mcp_stdio",
                "command": "/bin/test",
                "secrets": [
                    {
                        "name": "MY_SECRET",
                        "auth_type": "none",  # auto-passes probe, no HTTP call
                        "criticality": "required",
                    }
                ],
            }
        ]
    )
    O.draft_manifest_node(state, _StubSDK(), _RecordingMCP())
    # Manually drop a real-looking value in the .env.
    env_p = M.env_path(state["project_id"])
    SECRET_VALUE = "DO-NOT-LEAK-THIS-IN-THE-AUDIT-ENTRY"
    env_p.write_text(f"MY_SECRET={SECRET_VALUE}\n", encoding="utf-8")
    mcp = _RecordingMCP()
    O.finalize_node(state, _StubSDK(), mcp)
    # rka_add_note was called; verify content has no secret leak.
    add_calls = [c for c in mcp.calls if c["op"] == "rka_add_note"]
    assert len(add_calls) == 1
    assert SECRET_VALUE not in add_calls[0]["content"]
