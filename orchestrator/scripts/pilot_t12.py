"""T12 Phase-1 pilot — drive the compiled graph end-to-end against real RKA.

This is the Phase 1 pilot deliverable. The LangGraph topology is wired to
real `RestMCPClient` calls against the running RKA at localhost:9712, with
FakeSDK + FakeInterrupt standing in for the claude-agent-sdk loop (the
real SDK integration is Phase 2). Each node still writes real artifacts
to RKA tagged with the run's `workflow_thread_id`, so the run produces
genuine journal entries, a decision, and a mission report — exactly what
a Phase 2 production run will produce, minus the LLM-quality dimension.

Usage:

  python scripts/pilot_t12.py \\
      --project-id prj_01KKQM9JFG67GT5FGWTAHD9YE4 \\
      --mission-id mis_01KRKG9K1SSDZNDH90K2Z7ZM92 \\
      --workflow-thread-id thr_pilot_t12_$(date +%s)

After the run, every artifact can be retrieved via
`rka_get_journal(tags=[workflow_thread_id])` (Affordance F pattern).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# Make the package importable when run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import graph
from orchestrator.mcp_client import make_client
from orchestrator.state import make_initial_state


class PilotSDK:
    """A near-FakeSDK with pre-canned per-node replies, so each Brain/Executor
    node produces a distinct, recognizable journal note in RKA."""

    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, prompt: str, *, max_tokens: int = 4096, system: str | None = None) -> str:
        self.call_count += 1
        # Best-effort detection of which node we're answering based on
        # prompt content. Cheap heuristics — Phase 1, FakeSDK shaping.
        if "Session-start strategy synthesis" in prompt:
            return (
                "T12 pilot strategy: drive all 15 nodes end-to-end; "
                "confirm artifacts land in RKA; verify workflow_thread_id "
                "tagging; report pilot outcome."
            )
        if "Confirmation Brief" in prompt:
            return "Pilot Confirmation Brief — PI may approve to continue."
        if "Draft an upfront Backbrief" in prompt:
            return (
                "T12 pilot Backbrief.\nA1: orchestrator can write to RKA.\n"
                "R1: SDK is faked, so LLM-quality is Phase 2 work."
            )
        if "Gate 1" in prompt:
            return "APPROVED\nPilot Backbrief covers Phase 1 acceptance criteria."
        if "Execute the mission" in prompt:
            return "Pilot mission_execute: graph wired, all 15 nodes reachable."
        if "Compose the mission report" in prompt:
            return (
                "T12 pilot mission report. "
                "Findings: graph end-to-end works; RKA writes propagate; "
                "workflow_thread_id auto-tagging confirmed."
            )
        if "Review the current research map" in prompt:
            return "Cluster review: no new contradictions surfaced during the pilot."
        if "Draft a decision packet" in prompt:
            return "Decision packet: should Phase 2 proceed? options accept/modify/reject."
        if "Final mission synthesis" in prompt:
            return (
                "T12 pilot final synthesis. The orchestrator's Phase 1 graph "
                "is complete and validated end-to-end against real RKA."
            )
        return f"[pilot-stub reply #{self.call_count}]"


def pilot_interrupt(payload: dict) -> str:
    """Return PI-style responses that route the happy path to terminal=complete."""
    kind = payload.get("type", "")
    if kind in ("pi_decision_select", "pi_acceptance"):
        return "accept"
    return "approve"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T12 Phase-1 pilot run")
    parser.add_argument("--project-id", default="prj_01KKQM9JFG67GT5FGWTAHD9YE4")
    parser.add_argument("--mission-id", default="mis_01KRKG9K1SSDZNDH90K2Z7ZM92")
    parser.add_argument(
        "--decision-id", default="dec_01KRKE6ERDPQTFQS6ZGY9A3CK0"
    )
    parser.add_argument(
        "--workflow-thread-id",
        default=f"thr_pilot_t12_{int(time.time())}",
    )
    parser.add_argument("--rka-url", default="http://localhost:9712")
    parser.add_argument(
        "--checkpoint-db",
        default=":memory:",
        help="SqliteSaver path (`:memory:` keeps it ephemeral).",
    )
    args = parser.parse_args(argv)

    print(f"=== T12 pilot — workflow_thread_id={args.workflow_thread_id} ===")
    print(f"  project_id={args.project_id}")
    print(f"  mission_id={args.mission_id}")
    print(f"  rka_url={args.rka_url}\n")

    mcp = make_client(
        workflow_thread_id=args.workflow_thread_id,
        base_url=args.rka_url,
        project_id=args.project_id,
    )
    sdk = PilotSDK()

    # Quick smoke against RKA before running the graph.
    try:
        status = mcp.rka_get_status()
        phase = status.get("current_phase", "(unknown)")
        print(f"  RKA reachable; project phase: {phase}\n")
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR: RKA unreachable at {args.rka_url}: {e}")
        return 2

    ckpt = (
        None
        if args.checkpoint_db == ":memory:"
        else graph.open_checkpointer(args.checkpoint_db)
    )
    g = graph.build_graph(sdk=sdk, mcp=mcp, checkpointer=ckpt, interrupt_fn=pilot_interrupt)

    initial = make_initial_state(
        workflow_thread_id=args.workflow_thread_id,
        mission_id=args.mission_id,
        motivated_by_decision_id=args.decision_id,
    )

    config: dict[str, Any] = {
        "configurable": {"thread_id": args.workflow_thread_id}
    } if ckpt is not None else {}

    print("--- invoking graph ---")
    final = g.invoke(initial, config=config)

    print("\n--- pilot complete ---")
    print(f"  terminal_state:  {final.get('terminal_state')}")
    print(f"  current_phase:   {final.get('current_phase')}")
    print(f"  interrupts:      {len(final.get('interrupts', []))}")
    print(f"  artifacts:       {len(final.get('artifacts', []))}")
    print(f"  checkpoints:     {len(final.get('checkpoints', []))}")
    print(f"  errors:          {len(final.get('errors', []))}")
    print(f"  final_report_id: {final.get('final_report_id')}")
    print(f"  SDK calls:       {sdk.call_count}")
    print(f"\nArtifact IDs (retrievable via tags=[{args.workflow_thread_id}]):")
    for a in final.get("artifacts", []):
        print(f"  - {a.get('rka_id')}  ({a.get('entity_type')})  by {a.get('node_name')}")

    print(json.dumps(
        {
            "workflow_thread_id": args.workflow_thread_id,
            "terminal_state": final.get("terminal_state"),
            "artifact_count": len(final.get("artifacts", [])),
            "final_report_id": final.get("final_report_id"),
        },
        indent=2,
    ))

    return 0 if final.get("terminal_state") == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
