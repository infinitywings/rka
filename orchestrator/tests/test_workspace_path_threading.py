"""Gap 1 fix — workspace_path threading through sdk_factory.

The Phase G2 can_use_tool hook needs the per-project workspace_path to
scope FS escape detection. Pre-Gap-1, the runner only passed project_id
to sdk_factory; the hook fell back to HOST_WORKSPACE_ROOT, which is too
broad (any project under it was reachable). These tests assert:

  - runner._resolve_workspace_path() looks up via the store
  - sdk_factory now receives (project_id, workspace_path)
  - missing project_workspaces row degrades to "" cleanly
"""

from __future__ import annotations

from orchestrator.parked_store import ParkedStore
from orchestrator.runner import OrchestratorRunner
from tests._fakes import FakeMCP, FakeSDK


class _RecordingSDKFactory:
    """Records every (project_id, workspace_path) tuple the runner passes."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, project_id, workspace_path=""):
        self.calls.append((project_id, workspace_path))
        return FakeSDK()


def _make_runner(store, sdk_factory):
    return OrchestratorRunner(
        store=store,
        sdk_factory=sdk_factory,
        mcp_factory=lambda _t, _p: FakeMCP(),
        saver_factory=lambda _t: None,
    )


def test_resolve_workspace_path_returns_stored_value():
    """When the store has a project_workspaces row, _resolve_workspace_path
    returns it."""
    store = ParkedStore(":memory:")
    store.set_project_workspace("prj_test", "/Users/pi/Research/proj")
    runner = _make_runner(store, _RecordingSDKFactory())

    assert runner._resolve_workspace_path("prj_test") == "/Users/pi/Research/proj"

    store.close()


def test_resolve_workspace_path_returns_empty_for_unknown_project():
    """No row → empty string (lets the SDK hook fall back to
    HOST_WORKSPACE_ROOT instead of crashing)."""
    store = ParkedStore(":memory:")
    runner = _make_runner(store, _RecordingSDKFactory())

    assert runner._resolve_workspace_path("prj_does_not_exist") == ""

    store.close()


def test_resolve_workspace_path_empty_project_id_returns_empty():
    """Phase B and other project-independent flows pass project_id=""
    and expect an empty workspace_path back."""
    store = ParkedStore(":memory:")
    runner = _make_runner(store, _RecordingSDKFactory())

    assert runner._resolve_workspace_path("") == ""

    store.close()


def test_start_run_drive_threads_workspace_path_to_sdk_factory():
    """Gap 1 acceptance test: when a project has a registered
    workspace_path, start_run_drive's sdk_factory receives both
    project_id AND that workspace_path — not just project_id."""
    store = ParkedStore(":memory:")
    store.set_project_workspace("prj_alpha", "/Users/pi/Research/alpha")
    factory = _RecordingSDKFactory()
    runner = _make_runner(store, factory)

    # Create a workflow_runs row (start_run_drive needs one to exist).
    thread_id = store.create_run(
        mission_id="mis_test",
        project_id="prj_alpha",
        workflow_thread_id="thr_test_001",
    )

    # Wire a no-op compile factory so start_run_drive doesn't actually
    # run the graph (we just want to observe the sdk_factory call).
    class _StubCompiled:
        def invoke(self, *a, **kw):
            return {"current_node": "stub"}

    runner._compile_factory = lambda **kw: _StubCompiled()
    # Stub _execute_segment too so we don't hit graph internals.
    runner._execute_segment = lambda *a, **kw: None

    runner.start_run_drive(
        workflow_thread_id=thread_id,
        mission_id="mis_test",
        motivated_by_decision_id="dec_test",
        project_id="prj_alpha",
    )

    assert factory.calls == [("prj_alpha", "/Users/pi/Research/alpha")]

    store.close()


def test_start_run_drive_passes_empty_workspace_for_unregistered_project():
    """If the project was never onboarded (no project_workspaces row),
    sdk_factory gets workspace_path="" — the hook falls back to
    HOST_WORKSPACE_ROOT cleanly."""
    store = ParkedStore(":memory:")
    factory = _RecordingSDKFactory()
    runner = _make_runner(store, factory)

    thread_id = store.create_run(
        mission_id="mis_test",
        project_id="prj_no_workspace",
        workflow_thread_id="thr_test_002",
    )

    class _StubCompiled:
        def invoke(self, *a, **kw):
            return {"current_node": "stub"}

    runner._compile_factory = lambda **kw: _StubCompiled()
    runner._execute_segment = lambda *a, **kw: None

    runner.start_run_drive(
        workflow_thread_id=thread_id,
        mission_id="mis_test",
        motivated_by_decision_id="dec_test",
        project_id="prj_no_workspace",
    )

    assert factory.calls == [("prj_no_workspace", "")]

    store.close()
