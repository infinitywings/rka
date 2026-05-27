"""Phase O, O2.1 — workspace_setup node tests (ask-not-create pattern).

The orchestrator does NOT create directories on the host filesystem.
workspace_setup_node validates PI-provided paths (or emits checkpoints
asking the PI to create/provide a directory).

Covers:
  - PI provides workspace_path + path exists → validated + recorded
  - PI provides workspace_path + path missing → checkpoint emitted
  - No workspace_path → slug derived + suggested path + checkpoint
  - Missing project_id → ErrorRecord
  - graph.ONBOARDING_NODE_NAMES contains 'workspace_setup'
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator import graph
from orchestrator import workspace as W
from orchestrator.nodes import onboarding

from tests._fakes import FakeMCP, FakeSDK


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace_root(tmp_path, monkeypatch):
    """Redirect $RKA_WORKSPACE_ROOT to tmp dir so tests don't pollute $HOME."""
    monkeypatch.setenv("RKA_WORKSPACE_ROOT", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_workspace_setup_validates_pi_provided_path(tmp_workspace_root):
    """When PI provides workspace_path and the directory exists, the node
    validates it and records the path in state."""
    existing = tmp_workspace_root / "my-project"
    existing.mkdir()

    out = onboarding.workspace_setup_node(
        {"project_id": "prj_test_01", "workspace_path": str(existing)},
        FakeSDK(),
        FakeMCP(),
    )
    assert out["current_node"] == "workspace_setup"
    assert out["project_slug"] == "my-project"
    assert out["workspace_path"] == str(existing.resolve())
    assert "errors" not in out
    assert "checkpoints" not in out


def test_workspace_setup_missing_pi_path_emits_checkpoint(tmp_workspace_root):
    """When PI provides workspace_path but the directory doesn't exist,
    the node emits a checkpoint asking the PI to create it."""
    out = onboarding.workspace_setup_node(
        {"project_id": "prj_test_01", "workspace_path": "/nonexistent/path"},
        FakeSDK(),
        FakeMCP(),
    )
    assert "checkpoints" in out
    chk = out["checkpoints"][0]
    assert chk["resolved"] is False
    assert "/nonexistent/path" in chk["reason"]
    assert "does not exist" in chk["reason"]


def test_workspace_setup_no_path_suggests_and_checkpoints(tmp_workspace_root):
    """When no workspace_path is provided, the node derives a suggested
    path from the slug and emits a checkpoint."""
    out = onboarding.workspace_setup_node(
        {"project_id": "prj_x", "project_slug": "iot-edge-llm"},
        FakeSDK(),
        FakeMCP(),
    )
    assert "checkpoints" in out
    assert out["project_slug"] == "iot-edge-llm"
    assert "iot-edge-llm" in out["workspace_path"]
    chk = out["checkpoints"][0]
    assert "create your project workspace" in chk["reason"].lower()


# ---------------------------------------------------------------------------
# Slug source resolution
# ---------------------------------------------------------------------------


def test_workspace_setup_explicit_slug_emits_checkpoint(tmp_workspace_root):
    """If state['project_slug'] is set but no workspace_path, the node
    derives a suggested path and emits a checkpoint."""
    out = onboarding.workspace_setup_node(
        {"project_id": "prj_x", "project_slug": "explicit-choice"},
        FakeSDK(),
        FakeMCP(),
    )
    assert out["project_slug"] == "explicit-choice"
    assert "checkpoints" in out


def test_workspace_setup_derives_slug_from_rka_project_name(tmp_workspace_root):
    mcp = FakeMCP()
    mcp.status_response = {"project_name": "IoT Edge LLM Hosting"}
    out = onboarding.workspace_setup_node(
        {"project_id": "prj_x"}, FakeSDK(), mcp
    )
    assert out["project_slug"] == "iot-edge-llm-hosting"
    assert "checkpoints" in out


def test_workspace_setup_derives_slug_from_polished_idea_fallback(tmp_workspace_root):
    mcp = FakeMCP()
    mcp.status_response = {"phase": "design"}
    out = onboarding.workspace_setup_node(
        {
            "project_id": "prj_x",
            "polished_idea": {
                "research_question": "Can edge LLMs hit 5 tok/s on Pi 5?",
            },
        },
        FakeSDK(),
        mcp,
    )
    assert out["project_slug"].startswith("can-edge-llms")
    assert len(out["project_slug"]) <= 40


def test_workspace_setup_falls_back_to_project_id_when_no_other_source(
    tmp_workspace_root,
):
    mcp = FakeMCP()
    mcp.status_response = {"phase": "design"}
    out = onboarding.workspace_setup_node({"project_id": "prj_abc123"}, FakeSDK(), mcp)
    assert out["project_slug"] == "prj-abc123"


def test_workspace_setup_tolerates_mcp_status_failure(tmp_workspace_root):
    class _RaisingMCP(FakeMCP):
        def rka_get_status(self):
            raise RuntimeError("RKA down")

    out = onboarding.workspace_setup_node(
        {
            "project_id": "prj_x",
            "polished_idea": {"research_question": "Edge LLM hosting study"},
        },
        FakeSDK(),
        _RaisingMCP(),
    )
    assert out.get("project_slug", "").startswith("edge-llm-hosting")
    assert "errors" not in out


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_workspace_setup_missing_project_id_returns_error(tmp_workspace_root):
    out = onboarding.workspace_setup_node({}, FakeSDK(), FakeMCP())
    assert "errors" in out
    assert out["errors"][0]["error_type"] == "workspace_setup_no_project_id"
    # No filesystem side effects.
    assert not list(tmp_workspace_root.iterdir())


def test_workspace_setup_slug_derivation_failure_returns_error(tmp_workspace_root):
    """If the derivation pipeline produces empty input (project_id
    empty after derivation) raises a ValueError that maps to an error."""
    out = onboarding.workspace_setup_node(
        {"project_id": ""},
        FakeSDK(),
        FakeMCP(),
    )
    assert "errors" in out
    assert out["errors"][0]["error_type"] == "workspace_setup_no_project_id"


# ---------------------------------------------------------------------------
# Graph registry wiring
# ---------------------------------------------------------------------------


def test_graph_onboarding_node_names_include_workspace_setup():
    assert "workspace_setup" in graph.ONBOARDING_NODE_NAMES
