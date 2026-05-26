"""Phase O, O2.1 — workspace_setup node tests.

Covers:
  - Happy path: creates the workspace + writes state[project_slug, workspace_path]
  - Slug sources: explicit state['project_slug'] takes precedence over derivation
  - Slug derivation from RKA project name (rka_get_status -> project_name)
  - Slug derivation falls back to polished_idea.research_question when status absent
  - Slug derivation falls back to project_id when neither status nor polish available
  - Missing project_id raises an ErrorRecord
  - Slug derivation failure raises an ErrorRecord
  - Workspace conflict raises a checkpoint, not an error (so PI can resolve)
  - On disk: README + .gitignore + .rka/project_id + .rka/workspace.json all written
  - workspace.json phase advanced to 'o2'
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


def test_workspace_setup_happy_path_creates_workspace(tmp_workspace_root):
    """Given a fresh state with project_id + an explicit slug, the node
    creates the directory tree, writes the .rka scaffold, and threads
    project_slug + workspace_path back to state."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = {"project_id": "prj_test_01", "project_slug": "iot-edge-llm"}

    out = onboarding.workspace_setup_node(state, sdk, mcp)

    assert out["current_node"] == "workspace_setup"
    assert out["current_phase"] == "init"
    assert out["project_slug"] == "iot-edge-llm"
    assert out["workspace_path"] == str(tmp_workspace_root / "iot-edge-llm")

    # Filesystem proof.
    root = tmp_workspace_root / "iot-edge-llm"
    assert root.is_dir()
    for sub in ("data", "code", "notebooks", "manuscripts", "results", ".rka"):
        assert (root / sub).is_dir()
    assert (root / "README.md").exists()
    assert (root / ".gitignore").exists()
    pid = (root / ".rka" / "project_id").read_text(encoding="utf-8").strip()
    assert pid == "prj_test_01"
    meta = json.loads((root / ".rka" / "workspace.json").read_text(encoding="utf-8"))
    assert meta["rka_project_id"] == "prj_test_01"
    assert meta["slug"] == "iot-edge-llm"


def test_workspace_setup_advances_phase_to_o2(tmp_workspace_root):
    onboarding.workspace_setup_node(
        {"project_id": "prj_t", "project_slug": "test-slug-aa"},
        FakeSDK(),
        FakeMCP(),
    )
    meta = W.load_workspace_meta("test-slug-aa")
    assert meta["phase"] == "o2"
    # phase_history records the OUTGOING phase ("init") — advance_phase
    # appends an entry for the phase being exited, not the one being
    # entered.
    history = meta.get("phase_history") or []
    assert any(h.get("phase") == "init" for h in history)


# ---------------------------------------------------------------------------
# Slug source resolution
# ---------------------------------------------------------------------------


def test_workspace_setup_explicit_slug_takes_precedence(tmp_workspace_root):
    """If state['project_slug'] is set, derive_slug isn't called."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    mcp.status_response = {"project_name": "Unrelated Name"}

    out = onboarding.workspace_setup_node(
        {"project_id": "prj_x", "project_slug": "explicit-choice"},
        sdk,
        mcp,
    )
    assert out["project_slug"] == "explicit-choice"
    assert (tmp_workspace_root / "explicit-choice").is_dir()


def test_workspace_setup_derives_slug_from_rka_project_name(tmp_workspace_root):
    sdk = FakeSDK()
    mcp = FakeMCP()
    mcp.status_response = {"project_name": "IoT Edge LLM Hosting"}

    out = onboarding.workspace_setup_node(
        {"project_id": "prj_x"}, sdk, mcp
    )
    assert out["project_slug"] == "iot-edge-llm-hosting"
    assert (tmp_workspace_root / "iot-edge-llm-hosting").is_dir()


def test_workspace_setup_derives_slug_from_polished_idea_fallback(tmp_workspace_root):
    """RKA status has no project name; polish provides the research_question."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    mcp.status_response = {"phase": "design"}  # no project_name key

    out = onboarding.workspace_setup_node(
        {
            "project_id": "prj_x",
            "polished_idea": {
                "research_question": "Can edge LLMs hit 5 tok/s on Pi 5?",
            },
        },
        sdk,
        mcp,
    )
    # Derivation strips punctuation + lowercases + truncates to 40 chars.
    assert out["project_slug"].startswith("can-edge-llms")
    assert len(out["project_slug"]) <= 40


def test_workspace_setup_falls_back_to_project_id_when_no_other_source(
    tmp_workspace_root,
):
    """When neither RKA status nor polished_idea has anything, derive
    from the project_id directly (which always starts with 'prj_')."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    mcp.status_response = {"phase": "design"}

    out = onboarding.workspace_setup_node({"project_id": "prj_abc123"}, sdk, mcp)
    # 'prj_abc123' → 'prj-abc123' after slug normalization.
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
    # Should fall back to polished_idea → still produces a valid slug.
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


def test_workspace_setup_conflict_emits_checkpoint(tmp_workspace_root):
    """Pre-create the target dir; node must NOT overwrite — emits a
    checkpoint so PI can resolve."""
    target = tmp_workspace_root / "preexisting-slug"
    target.mkdir(parents=True)
    (target / "evidence-it-was-yours.txt").write_text("hi")

    out = onboarding.workspace_setup_node(
        {"project_id": "prj_x", "project_slug": "preexisting-slug"},
        FakeSDK(),
        FakeMCP(),
    )
    # Checkpoint emitted; project_slug + workspace_path still threaded
    # so the PI can see what the conflict is.
    assert "checkpoints" in out
    chk = out["checkpoints"][0]
    assert chk["type"] == "decision"
    assert chk["resolved"] is False
    assert "workspace conflict" in chk["reason"].lower()
    # The PI's content is untouched.
    assert (target / "evidence-it-was-yours.txt").exists()
    # No errors record (the conflict is recoverable; the user just needs
    # to rename or remove).
    assert "errors" not in out


def test_workspace_setup_invalid_slug_explicit_path_returns_error(tmp_workspace_root):
    """Explicit but invalid slug → ProjectSlug constructor raises →
    create_workspace raises InvalidSlugError → ErrorRecord."""
    out = onboarding.workspace_setup_node(
        {"project_id": "prj_x", "project_slug": "BAD_SLUG_!!!"},
        FakeSDK(),
        FakeMCP(),
    )
    assert "errors" in out
    assert out["errors"][0]["error_type"] == "workspace_setup_invalid_slug"


def test_workspace_setup_slug_derivation_failure_returns_error(tmp_workspace_root):
    """If the derivation pipeline produces empty input (project_id
    empty after derivation) raises a ValueError that maps to an error."""

    # Force a path where neither RKA status, polish, nor project_id
    # has anything useful. derive_slug_from_name on "" raises ValueError.
    class _EmptyStatusMCP(FakeMCP):
        def rka_get_status(self):
            return {}

    out = onboarding.workspace_setup_node(
        {"project_id": ""},  # missing → caught first
        FakeSDK(),
        _EmptyStatusMCP(),
    )
    assert "errors" in out
    # missing project_id is the first guard.
    assert out["errors"][0]["error_type"] == "workspace_setup_no_project_id"


# ---------------------------------------------------------------------------
# Graph registry wiring
# ---------------------------------------------------------------------------


def test_graph_onboarding_node_names_include_workspace_setup():
    assert "workspace_setup" in graph.ONBOARDING_NODE_NAMES
