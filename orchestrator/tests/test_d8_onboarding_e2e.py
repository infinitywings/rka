"""Phase D, D8 — onboarding end-to-end integration.

Walks the onboarding subgraph from `start` to `finalize` via the FastAPI
HTTP layer using a fake compiled-graph scripted with the expected
segment outputs. Mirrors the mission-side test_e2e_integration.py
pattern but for the onboarding subgraph.

Tests the full chain at the contract boundary:
  POST /onboard
   → pi_onboarding_topic parked
   → /inbox shows the topic-elicitation payload
   → /inbox/{id}/correct (PI provides topic text)
   → pi_toolkit_ratify parked
   → /inbox shows the proposed_toolkit payload
   → /inbox/{id}/accept (PI ratifies)
   → pi_credentials_ready parked
   → /inbox shows the env_file_path + expected_secrets
   → /inbox/{id}/accept (PI signals ready)
   → /onboard returns terminal_state="complete" (post-finalize)

The fake graph emits production-shape payloads so the runner +
parked_store + server all see realistic data shapes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from orchestrator.parked_store import ParkedStore
from orchestrator.runner import OrchestratorRunner, SegmentOutcome
from orchestrator.server import create_app


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    os.environ["RKA_PROJECTS_ROOT"] = str(tmp_path)
    yield tmp_path
    os.environ.pop("RKA_PROJECTS_ROOT", None)


class _Interrupt:
    def __init__(self, value: Any):
        self.value = value


class _OnboardingFakeGraph:
    """Production-shape onboarding graph fake. Each `invoke()` returns
    the next segment's output. Captures resume tokens for assertions."""

    def __init__(self):
        self.invocations: list[tuple[Any, dict]] = []
        self._step = 0

    def invoke(self, input_or_command, config):
        self.invocations.append((input_or_command, config))
        step = self._step
        self._step += 1

        # Step 0: kicked off; parks at pi_onboarding_topic
        if step == 0:
            return {
                "current_node": "pi_onboarding_topic",
                "__interrupt__": [
                    _Interrupt(
                        value={
                            "type": "pi_onboarding_topic",
                            "title": "PI topic elicitation",
                            "prompt": "Tell me about the project",
                        }
                    )
                ],
            }
        # Step 1: PI provided topic; advance to research_toolkit then park
        # at pi_toolkit_ratify
        if step == 1:
            return {
                "current_node": "pi_toolkit_ratify",
                "__interrupt__": [
                    _Interrupt(
                        value={
                            "type": "pi_toolkit_ratify",
                            "title": "PI ratification — proposed toolkit",
                            "items": [
                                {"name": "rka", "type": "mcp_stdio"},
                                {"name": "context7", "type": "mcp_stdio"},
                                {"name": "huggingface", "type": "mcp_stdio"},
                            ],
                            "total_items": 3,
                            "brain_notes": "ML systems project; HF for benchmarks.",
                        }
                    )
                ],
            }
        # Step 2: PI ratified; advance to draft_manifest then park at
        # pi_credentials_ready
        if step == 2:
            return {
                "current_node": "pi_credentials_ready",
                "__interrupt__": [
                    _Interrupt(
                        value={
                            "type": "pi_credentials_ready",
                            "title": "PI credential entry",
                            "env_file_path": "~/rka-projects/prj_e2e_test/.env",
                            "expected_secrets": [
                                {
                                    "tool": "huggingface",
                                    "name": "HUGGINGFACE_API_KEY",
                                    "criticality": "recommended",
                                    "description": "HF API key",
                                }
                            ],
                            "items": [],
                            "total_items": 0,
                        }
                    )
                ],
            }
        # Step 3: PI signaled ready; finalize completes → terminal
        return {
            "current_node": "finalize",
            "terminal_state": "complete",
        }


@pytest.fixture
def setup(tmp_root):
    store = ParkedStore(":memory:")

    class _FakeMCP:
        workflow_thread_id = "thr_t"

        def rka_add_note(self, **kw):
            return "jrn_audit_e2e_001"

    fake_graph = _OnboardingFakeGraph()
    runner = OrchestratorRunner(
        store=store,
        sdk_factory=lambda pid: object(),
        mcp_factory=lambda tid, pid: _FakeMCP(),
        saver_factory=lambda tid: None,
        compile_factory=lambda **kw: object(),  # mission factory not used
        onboarding_compile_factory=lambda **kw: fake_graph,
    )
    app = create_app(store=store, runner=runner)
    client = TestClient(app)
    with client:
        yield client, store, runner, fake_graph
    store.close()


# ---------------------------------------------------------------------------
# Full chain
# ---------------------------------------------------------------------------


def test_onboarding_e2e_walks_through_three_interrupts_to_terminal(setup):
    """The canonical onboarding-completion path. Each step verifies the
    inbox shape, the response action, and the next parked interrupt."""
    client, store, runner, fake_graph = setup

    # Step 1: kick off onboarding.
    r = client.post("/onboard", json={"project_id": "prj_e2e_test"})
    assert r.status_code == 200
    start = r.json()
    thread_id = start["workflow_thread_id"]
    int1 = start["parked_interrupt_id"]
    assert start["parked_interrupt_type"] == "pi_onboarding_topic"

    # Step 2: inbox shows the topic-elicitation payload.
    r = client.get(f"/inbox?workflow_thread_id={thread_id}")
    inbox = r.json()
    assert len(inbox) == 1
    assert inbox[0]["payload"]["type"] == "pi_onboarding_topic"

    # Step 3: PI provides topic via /correct (freeform text → topic_metadata).
    topic_text = (
        "IoT edge LLM hosting for smart-home intents; ML systems; "
        "MLSys 2026; edge llm smart-home inference"
    )
    r = client.post(
        f"/inbox/{int1}/correct", json={"response_text": topic_text}
    )
    assert r.status_code == 200
    seg2 = r.json()
    assert seg2["parked_interrupt_type"] == "pi_toolkit_ratify"
    int2 = seg2["parked_interrupt_id"]

    # Verify the resume token carried the topic text — wrapped in the
    # Phase D2 REDIRECT_SENTINEL because action='correct' is the post-
    # Phase-D2 path for PI freeform input (closes substring-routing bug).
    from orchestrator.response_tokens import REDIRECT_SENTINEL
    resume_input = fake_graph.invocations[1][0]
    assert resume_input.resume == REDIRECT_SENTINEL + topic_text

    # Step 4: inbox shows the toolkit ratification payload.
    r = client.get(f"/inbox?workflow_thread_id={thread_id}")
    payload = r.json()[0]["payload"]
    assert payload["type"] == "pi_toolkit_ratify"
    assert payload["total_items"] == 3
    assert "huggingface" in {t["name"] for t in payload["items"]}
    assert "ML systems" in payload.get("brain_notes", "")

    # Step 5: PI accepts the toolkit. Token must be "accept".
    r = client.post(f"/inbox/{int2}/accept")
    assert r.status_code == 200
    seg3 = r.json()
    assert seg3["parked_interrupt_type"] == "pi_credentials_ready"
    int3 = seg3["parked_interrupt_id"]
    resume_input = fake_graph.invocations[2][0]
    assert resume_input.resume == "accept"

    # Step 6: inbox shows the credentials payload — file path + expected secrets.
    r = client.get(f"/inbox?workflow_thread_id={thread_id}")
    payload = r.json()[0]["payload"]
    assert payload["type"] == "pi_credentials_ready"
    assert payload["env_file_path"].endswith("/prj_e2e_test/.env")
    assert len(payload["expected_secrets"]) == 1
    assert payload["expected_secrets"][0]["name"] == "HUGGINGFACE_API_KEY"
    # CRITICAL: payload never includes a 'value' field.
    for s in payload["expected_secrets"]:
        assert "value" not in s

    # Step 7: PI signals ready (file edited). Token must be "accept".
    r = client.post(f"/inbox/{int3}/accept")
    assert r.status_code == 200
    final = r.json()
    assert final["terminal_state"] == "complete"
    resume_input = fake_graph.invocations[3][0]
    assert resume_input.resume == "accept"

    # Step 8: final run state is "complete".
    r = client.get(f"/runs/{thread_id}")
    assert r.json()["status"] == "complete"
    assert r.json()["terminal_state"] == "complete"

    # All interrupts are answered.
    for iid in (int1, int2, int3):
        assert store.get_interrupt(iid)["status"] == "answered"


def test_onboarding_e2e_reject_at_toolkit_ratify_ends_workflow(setup):
    """If PI rejects the toolkit at pi_toolkit_ratify, the run ends
    without producing a manifest. The reject path mirrors a clean
    abandonment — no escalation needed."""
    client, store, runner, fake_graph = setup
    # Override step 2 to a terminal output instead of pi_credentials_ready.
    # We patch the fake graph's next response so on reject, the subgraph
    # routes to END.
    fake_graph._step = 0  # reset since we'll re-script

    class _RejectFake:
        def __init__(self):
            self.invocations = []
            self._step = 0

        def invoke(self, input_or_command, config):
            self.invocations.append((input_or_command, config))
            step = self._step
            self._step += 1
            if step == 0:
                return {
                    "current_node": "pi_onboarding_topic",
                    "__interrupt__": [_Interrupt(value={"type": "pi_onboarding_topic"})],
                }
            if step == 1:
                return {
                    "current_node": "pi_toolkit_ratify",
                    "__interrupt__": [
                        _Interrupt(
                            value={
                                "type": "pi_toolkit_ratify",
                                "items": [{"name": "x"}],
                                "total_items": 1,
                            }
                        )
                    ],
                }
            # On reject, subgraph routes directly to END.
            return {"current_node": "pi_toolkit_ratify", "terminal_state": "complete"}

    reject_fake = _RejectFake()

    # Rebuild the test stack with the reject_fake graph.
    store2 = ParkedStore(":memory:")

    class _FakeMCP:
        workflow_thread_id = "thr_t"

        def rka_add_note(self, **kw):
            return "jrn_x"

    runner2 = OrchestratorRunner(
        store=store2,
        sdk_factory=lambda pid: object(),
        mcp_factory=lambda tid, pid: _FakeMCP(),
        saver_factory=lambda tid: None,
        compile_factory=lambda **kw: object(),
        onboarding_compile_factory=lambda **kw: reject_fake,
    )
    app2 = create_app(store=store2, runner=runner2)
    with TestClient(app2) as client2:
        # Start onboarding.
        r = client2.post("/onboard", json={"project_id": "prj_reject_test"})
        topic_int = r.json()["parked_interrupt_id"]
        # Provide topic via correct.
        client2.post(f"/inbox/{topic_int}/correct", json={"response_text": "x"})
        # Inbox now has pi_toolkit_ratify.
        ratify_int = client2.get(
            f"/inbox?workflow_thread_id={r.json()['workflow_thread_id']}"
        ).json()[0]["interrupt_id"]
        # PI rejects.
        r = client2.post(
            f"/inbox/{ratify_int}/reject", json={"reason": "wrong scope"}
        )
        assert r.status_code == 200
        # The fake routes to terminal; verify.
        assert r.json()["terminal_state"] == "complete"

    store2.close()
