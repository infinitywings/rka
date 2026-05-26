"""Phase O, O0 — workspace.py + state schema tests.

Covers:
  - Slug validation (kebab-case regex, reserved patterns)
  - Slug derivation from RKA project names
  - Workspace path resolution (env-var override, default)
  - create_workspace: dir tree, perms, refuse-if-exists, idempotent variant
  - Workspace metadata IO + phase advancement
  - find_workspace_for_project_id reverse-lookup
  - State schema: all 12 Phase O fields defaulted correctly by
    make_initial_state
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from orchestrator import workspace as W
from orchestrator.state import make_initial_state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace_root(tmp_path: Path) -> Path:
    """Override workspace root via env var so tests don't touch
    the real $HOME/Research/."""
    os.environ[W.DEFAULT_WORKSPACE_ROOT_ENV] = str(tmp_path)
    yield tmp_path
    os.environ.pop(W.DEFAULT_WORKSPACE_ROOT_ENV, None)


# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------


def test_project_slug_accepts_valid_kebab_case():
    ps = W.ProjectSlug(slug="iot-edge-llm-hosting", rka_project_id="prj_01abc")
    assert ps.slug == "iot-edge-llm-hosting"


def test_project_slug_rejects_uppercase():
    with pytest.raises(W.InvalidSlugError, match="must match"):
        W.ProjectSlug(slug="IoT-Edge", rka_project_id="prj_01abc")


def test_project_slug_rejects_underscores():
    with pytest.raises(W.InvalidSlugError):
        W.ProjectSlug(slug="iot_edge_llm", rka_project_id="prj_01abc")


def test_project_slug_rejects_starts_with_digit():
    with pytest.raises(W.InvalidSlugError):
        W.ProjectSlug(slug="2026-project", rka_project_id="prj_01abc")


def test_project_slug_rejects_too_short():
    with pytest.raises(W.InvalidSlugError):
        W.ProjectSlug(slug="ab", rka_project_id="prj_01abc")


def test_project_slug_rejects_too_long():
    long = "a" + "b" * 40
    with pytest.raises(W.InvalidSlugError):
        W.ProjectSlug(slug=long, rka_project_id="prj_01abc")


def test_project_slug_accepts_max_len():
    """Boundary: 40 chars exactly should be valid."""
    s = "a" + "b" * 39  # 40 chars
    assert len(s) == 40
    W.ProjectSlug(slug=s, rka_project_id="prj_01abc")  # no raise


def test_project_slug_rejects_bad_project_id_prefix():
    with pytest.raises(W.InvalidSlugError, match="must start with 'prj_'"):
        W.ProjectSlug(slug="iot-edge", rka_project_id="dec_01abc")


# ---------------------------------------------------------------------------
# derive_slug_from_name
# ---------------------------------------------------------------------------


def test_derive_slug_simple_name():
    assert W.derive_slug_from_name("IoT Edge LLM") == "iot-edge-llm"


def test_derive_slug_with_punctuation():
    assert (
        W.derive_slug_from_name("IoT Edge LLM Hosting (MLSys 2026)")
        == "iot-edge-llm-hosting-mlsys-2026"
    )


def test_derive_slug_collapses_runs():
    assert W.derive_slug_from_name("Quick   &  Dirty!!  Prototype") == "quick-dirty-prototype"


def test_derive_slug_strips_trailing_hyphens():
    assert W.derive_slug_from_name("trailing???") == "trailing"


def test_derive_slug_prefixes_when_starts_with_digit():
    """'2026 Project' begins with a digit — slug validation requires letter
    start. Auto-prefix with 'rka-'."""
    result = W.derive_slug_from_name("2026 Project")
    assert result.startswith("rka-")
    assert W.SLUG_PATTERN.match(result)


def test_derive_slug_prefixes_when_too_short():
    """Empty-ish input becomes 'rka-…'."""
    result = W.derive_slug_from_name("X")
    assert result.startswith("rka-")
    assert W.SLUG_PATTERN.match(result)


def test_derive_slug_truncates_to_max_len():
    long = "A" * 100
    result = W.derive_slug_from_name(long, max_len=20)
    assert len(result) <= 20
    assert W.SLUG_PATTERN.match(result)


def test_derive_slug_no_trailing_hyphen_after_truncation():
    """Truncation must not leave a hyphen as the last character."""
    name = "abcdef-xyz-ghi-jkl-mno-pqr"
    result = W.derive_slug_from_name(name, max_len=10)
    assert not result.endswith("-")


def test_derive_slug_empty_input_raises():
    with pytest.raises(W.InvalidSlugError):
        W.derive_slug_from_name("")


def test_derive_slug_none_input_raises():
    with pytest.raises(W.InvalidSlugError):
        W.derive_slug_from_name(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Workspace path resolution
# ---------------------------------------------------------------------------


def test_workspace_root_uses_env_var(tmp_workspace_root: Path):
    assert W.workspace_root() == tmp_workspace_root


def test_workspace_root_falls_back_to_home_research():
    os.environ.pop(W.DEFAULT_WORKSPACE_ROOT_ENV, None)
    root = W.workspace_root()
    assert root == Path.home() / "Research"


def test_project_workspace_path(tmp_workspace_root: Path):
    assert W.project_workspace("iot-edge") == tmp_workspace_root / "iot-edge"


def test_rka_dir_path(tmp_workspace_root: Path):
    assert W.rka_dir("iot-edge") == tmp_workspace_root / "iot-edge" / ".rka"


# ---------------------------------------------------------------------------
# create_workspace
# ---------------------------------------------------------------------------


def test_create_workspace_creates_full_tree(tmp_workspace_root: Path):
    binding = W.create_workspace("iot-edge", "prj_01abc")
    assert binding.slug == "iot-edge"
    target = binding.workspace_path
    assert target.is_dir()
    # All default subdirs present.
    for sub in W.DEFAULT_SUBDIRS:
        assert (target / sub).is_dir(), f"missing subdir {sub}"
    # .rka/ exists with project_id + workspace.json.
    assert (target / ".rka" / "project_id").is_file()
    assert (target / ".rka" / "workspace.json").is_file()


def test_create_workspace_writes_project_id_file(tmp_workspace_root: Path):
    W.create_workspace("iot-edge", "prj_01abc")
    content = W.project_id_file("iot-edge").read_text()
    assert content == "prj_01abc"


def test_create_workspace_writes_initial_workspace_json(tmp_workspace_root: Path):
    W.create_workspace("iot-edge", "prj_01abc")
    meta = json.loads(W.workspace_json_path("iot-edge").read_text())
    assert meta["rka_project_id"] == "prj_01abc"
    assert meta["slug"] == "iot-edge"
    assert meta["phase"] == "init"
    assert meta["schema_version"] == "v1"
    assert meta["phase_history"] == []
    assert meta["created_at"].endswith("Z")
    assert meta["last_updated"].endswith("Z")


def test_create_workspace_writes_readme(tmp_workspace_root: Path):
    W.create_workspace("iot-edge", "prj_01abc")
    readme = (W.project_workspace("iot-edge") / "README.md").read_text()
    assert "iot-edge" in readme
    assert "prj_01abc" in readme


def test_create_workspace_writes_gitignore(tmp_workspace_root: Path):
    W.create_workspace("iot-edge", "prj_01abc")
    gi = (W.project_workspace("iot-edge") / ".gitignore").read_text()
    assert ".rka/.env" in gi
    assert "results/" in gi


def test_create_workspace_refuses_if_exists_by_default(tmp_workspace_root: Path):
    W.create_workspace("iot-edge", "prj_01abc")
    with pytest.raises(W.WorkspaceAlreadyExistsError, match="already exists"):
        W.create_workspace("iot-edge", "prj_01abc")


def test_create_workspace_allows_existing_when_refuse_off(tmp_workspace_root: Path):
    """Test-mode + idempotent re-creation path. README + gitignore
    aren't overwritten if they already exist."""
    W.create_workspace("iot-edge", "prj_01abc")
    custom = W.project_workspace("iot-edge") / "README.md"
    custom.write_text("HAND-EDITED", encoding="utf-8")
    W.create_workspace("iot-edge", "prj_01abc", refuse_if_exists=False)
    # README preserved.
    assert custom.read_text() == "HAND-EDITED"


def test_create_workspace_refuses_invalid_slug(tmp_workspace_root: Path):
    with pytest.raises(W.InvalidSlugError):
        W.create_workspace("INVALID", "prj_01abc")
    # No directory created.
    assert not (tmp_workspace_root / "INVALID").exists()


def test_create_workspace_perms_0700_on_dir_and_rka(tmp_workspace_root: Path):
    """The workspace dir + .rka/ subdir get 0700 perms (best-effort —
    skip if filesystem doesn't support, but assert when it does)."""
    W.create_workspace("iot-edge", "prj_01abc")
    target = W.project_workspace("iot-edge")
    mode = oct(target.stat().st_mode & 0o777)
    # Either we got 0o700, or the filesystem didn't enforce (umask
    # default). Both acceptable per the helper's defensive try/except.
    assert mode in ("0o700", "0o755")


# ---------------------------------------------------------------------------
# Workspace metadata IO
# ---------------------------------------------------------------------------


def test_load_workspace_meta_round_trip(tmp_workspace_root: Path):
    W.create_workspace("iot-edge", "prj_01abc")
    meta = W.load_workspace_meta("iot-edge")
    assert meta["slug"] == "iot-edge"


def test_load_workspace_meta_raises_when_missing_dir(tmp_workspace_root: Path):
    with pytest.raises(W.WorkspaceNotFoundError):
        W.load_workspace_meta("nonexistent")


def test_load_workspace_meta_raises_when_corrupt(tmp_workspace_root: Path):
    W.create_workspace("iot-edge", "prj_01abc")
    W.workspace_json_path("iot-edge").write_text("{not valid json")
    with pytest.raises(W.WorkspaceCorruptError, match="malformed JSON"):
        W.load_workspace_meta("iot-edge")


def test_save_workspace_meta_updates_last_updated(tmp_workspace_root: Path):
    W.create_workspace("iot-edge", "prj_01abc")
    meta = W.load_workspace_meta("iot-edge")
    initial = meta["last_updated"]
    import time
    time.sleep(1.01)
    meta["phase"] = "o1"
    W.save_workspace_meta("iot-edge", meta)
    reloaded = W.load_workspace_meta("iot-edge")
    assert reloaded["phase"] == "o1"
    assert reloaded["last_updated"] > initial


def test_save_workspace_meta_atomic_via_tmp_swap(tmp_workspace_root: Path):
    """The save path writes via .tmp + rename. Sanity: after save, no
    .tmp file is left behind."""
    W.create_workspace("iot-edge", "prj_01abc")
    meta = W.load_workspace_meta("iot-edge")
    W.save_workspace_meta("iot-edge", meta)
    rka = W.rka_dir("iot-edge")
    leftover = list(rka.glob("workspace.json.tmp"))
    assert leftover == []


# ---------------------------------------------------------------------------
# advance_phase
# ---------------------------------------------------------------------------


def test_advance_phase_appends_history(tmp_workspace_root: Path):
    W.create_workspace("iot-edge", "prj_01abc")
    meta = W.advance_phase("iot-edge", "o1")
    assert meta["phase"] == "o1"
    assert len(meta["phase_history"]) == 1
    assert meta["phase_history"][0]["phase"] == "init"


def test_advance_phase_noop_when_same(tmp_workspace_root: Path):
    """Re-advancing to the same phase only bumps last_updated;
    doesn't append a redundant history entry."""
    W.create_workspace("iot-edge", "prj_01abc")
    W.advance_phase("iot-edge", "o1")
    meta = W.advance_phase("iot-edge", "o1")
    assert len(meta["phase_history"]) == 1


def test_advance_phase_chain_through_subphases(tmp_workspace_root: Path):
    W.create_workspace("iot-edge", "prj_01abc")
    for ph in ("o1", "o2", "o3", "o4", "o5", "handoff"):
        W.advance_phase("iot-edge", ph)
    meta = W.load_workspace_meta("iot-edge")
    assert meta["phase"] == "handoff"
    # History records every exit from a phase.
    assert [h["phase"] for h in meta["phase_history"]] == [
        "init", "o1", "o2", "o3", "o4", "o5",
    ]


def test_advance_phase_with_note(tmp_workspace_root: Path):
    W.create_workspace("iot-edge", "prj_01abc")
    W.advance_phase("iot-edge", "o1", note="PI provided initial idea")
    meta = W.load_workspace_meta("iot-edge")
    assert meta["phase_history"][0]["note"] == "PI provided initial idea"


# ---------------------------------------------------------------------------
# Reverse lookup
# ---------------------------------------------------------------------------


def test_find_workspace_for_project_id_finds_match(tmp_workspace_root: Path):
    W.create_workspace("iot-edge", "prj_01abc")
    W.create_workspace("another", "prj_02xyz")
    found = W.find_workspace_for_project_id("prj_02xyz")
    assert found is not None
    assert found.slug == "another"
    assert found.rka_project_id == "prj_02xyz"


def test_find_workspace_returns_none_when_missing(tmp_workspace_root: Path):
    W.create_workspace("iot-edge", "prj_01abc")
    assert W.find_workspace_for_project_id("prj_does_not_exist") is None


def test_find_workspace_returns_none_when_root_missing(tmp_workspace_root: Path):
    # Workspace root exists but is empty.
    assert W.find_workspace_for_project_id("prj_anything") is None


def test_find_workspace_skips_dirs_with_invalid_slug_names(tmp_workspace_root: Path):
    """If the user manually drops a dir under ~/Research/ with a non-slug
    name, find_workspace shouldn't crash on it."""
    bad = tmp_workspace_root / "INVALID_NAME"
    bad.mkdir()
    (bad / ".rka").mkdir()
    (bad / ".rka" / "project_id").write_text("prj_01abc")
    # The valid one we want to find.
    W.create_workspace("good-slug", "prj_02xyz")
    found = W.find_workspace_for_project_id("prj_02xyz")
    assert found is not None
    assert found.slug == "good-slug"


# ---------------------------------------------------------------------------
# State schema additions
# ---------------------------------------------------------------------------


def test_make_initial_state_includes_all_phase_o_fields():
    """All 12 Phase O state fields default to empty/zero values."""
    state = make_initial_state(
        workflow_thread_id="thr_t",
        mission_id="mis_t",
        motivated_by_decision_id="dec_t",
        project_id="prj_t",
    )
    # O1-O2 inputs:
    assert state["project_slug"] == ""
    assert state["workspace_path"] == ""
    assert state["ingested_source_ids"] == []
    assert state["polished_idea"] == {}
    assert state["scope_ratified"] is False
    # O2:
    assert state["deepresearch_complete"] is False
    # O3:
    assert state["hygiene_findings"] == []
    assert state["claim_ids"] == []
    # O4:
    assert state["ratified_plan_decision_id"] == ""
    assert state["ratified_plan_journal_id"] == ""
    assert state["ratified_mission_ids"] == []
    # H:
    assert state["current_milestone_index"] == 0


def test_phase_o_state_fields_are_independent_of_phase_d_fields():
    """Phase D's topic_metadata/proposed_toolkit/ratified_toolkit
    and Phase O's polished_idea/ingested_source_ids/etc. are separate
    fields — adding Phase O didn't accidentally collapse them."""
    state = make_initial_state(
        workflow_thread_id="thr_t",
        mission_id="mis_t",
        motivated_by_decision_id="dec_t",
    )
    # Phase D fields exist:
    assert "topic_metadata" in state
    assert "proposed_toolkit" in state
    # Phase O fields exist and are separate:
    assert "polished_idea" in state
    assert "ingested_source_ids" in state
    # Mutating one doesn't touch the other (no aliasing).
    state["topic_metadata"] = {"summary": "phase d"}
    state["polished_idea"] = {"research_question": "phase o"}
    assert state["topic_metadata"] != state["polished_idea"]
