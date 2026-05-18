"""Operational driver — run the LangGraph orchestrator against a real RKA mission.

Phase 2.4 (mis_01KRVE4J71T6M6XWPDVPXMFJ49) deliverable. Peer to `pilot_t12.py`
but with three differences: (a) loads a real RKA mission via MCP instead of
defaulting to the Phase-1 pilot anchors; (b) interactive PI prompt at each
`pi_node` interrupt (read from stdin instead of pre-canned responses);
(c) real `claude-agent-sdk` only — no PilotSDK fallback.

Usage:

  python orchestrator/scripts/driver.py --mission-id mis_01XYZ... \\
      --project-id prj_01KKQM9JFG67GT5FGWTAHD9YE4 \\
      --output-dir orchestrator/results/op_rollout_v1/

Workflow:

  1. Health-check RKA at `--rka-url` (default localhost:9712).
  2. Load the mission spec via `mcp.rka_get_mission(mission_id)` — fails fast
     if the mission ID doesn't exist or isn't reachable.
  3. Build the LangGraph with `make_sdk()` (real Claude Agent SDK, Claude Max
     auth) + `RestMCPClient` (workflow-thread-id-tagged).
  4. Invoke the graph. At every `pi_node` interrupt, prompt the operator
     interactively on stdin: show the proposed change, accept (`a`),
     correct (`c <new value>`), or reject (`r`).
  5. On graph completion, print the terminal state + artifact summary.
     If `--output-dir` is set, write a JSON pilot-artifact-style record.

The interactive prompt is the safety affordance: every Brain proposal
goes through PI ratification before `executor_node` commits via
`rka_update_note` (or analogous MCP write).

Auth thesis preservation: `make_sdk()` scrubs `ANTHROPIC_API_KEY` from
the SDK subprocess env and logs the auth-path label (`keychain` /
`credentials_json` / etc.). Run aborts with a clean error if no Claude
Max path is available.
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
from orchestrator.llm_client import make_sdk
from orchestrator.mcp_client import make_client
from orchestrator.state import make_initial_state


# Per-interrupt-type token mapping for the `a` shortcut. Mirrors the
# routing-function contracts in `orchestrator/orchestrator/graph.py`:
#   - `_route_after_pi_greenlight`   checks `"approve" in response`
#   - `_route_after_pi_decision`     checks `"accept"  in response`
#   - `pi_acceptance` is a terminal node — response is recorded but doesn't
#     drive routing; "accept" is the conventional token for symmetry.
# Phase 2.4 first run (chk_01KRVG6GE119ASG26QKXH0N5D2) short-circuited because
# the driver returned "accept" for every interrupt type, including pi_greenlight
# — `"approve" in "accept"` is False, so the graph routed to escalation_router
# instead of backbrief_draft, skipping 7 nodes including the pi_decision_select
# interrupt where the brain_node's per-item proposal would have surfaced. This
# table closes the bug; the pilot_t12 fixture in Phase 1 had it right.
_ACCEPT_TOKEN_BY_INTERRUPT_TYPE: dict[str, str] = {
    "pi_greenlight": "approve",
    "pi_decision_select": "accept",
    "pi_acceptance": "accept",
}


def _default_accept_token(interrupt_type: str) -> str:
    """Token the `a` shortcut returns for a given interrupt type. Defaults
    to 'approve' for unknown types — matches the pre-decision gate semantics
    (greenlight, gate-style verdicts) which the orchestrator routes via
    'approve in response'."""
    return _ACCEPT_TOKEN_BY_INTERRUPT_TYPE.get(interrupt_type, "approve")


def interactive_interrupt(payload: dict) -> str:
    """Render a `pi_node` interrupt payload on stdout and read PI's response from stdin.

    The orchestrator's pi_node passes a structured payload (`type`, `prompt`,
    `proposal`, etc.). We render it as a human-readable block and prompt the
    operator for a single-character response:

      a            — accept (token chosen per interrupt type; see
                     `_ACCEPT_TOKEN_BY_INTERRUPT_TYPE`)
      r            — reject (return "reject"; orchestrator routes to escalation)
      c <text>     — correct (the rest of the line becomes the response text)

    Anything else (non-empty) is treated as free-form input and passed
    through. The orchestrator's interrupt-response contract is "string" —
    every node that reads the response either substring-matches a specific
    token or treats the whole thing as a freeform PI directive.

    Phase 2.7 T4 (mis_01KRXNAJDM2DQ3K1VH6CXAPK8R) — **empty Enter
    re-prompts**, never falls through to `_default_accept_token`. Phase 2.6
    run `thr_op_rollout_v2_1779044069` showed that a buffered newline after
    PI typed `a` at pi_greenlight auto-accepted both pi_decision_select and
    pi_acceptance via the prior `return raw if raw else _default_accept_token(kind)`
    fallback. Only `EOFError` (Ctrl-D / closed stdin in non-interactive mode)
    now falls through to the type-aware default token.
    """
    kind = payload.get("type", "(unknown)")
    print()
    print("=" * 72)
    print(f"PI INTERRUPT [{kind}]")
    print("=" * 72)
    # Pretty-print the payload — keys vary by interrupt type.
    for key, value in payload.items():
        if key == "type":
            continue
        if isinstance(value, (dict, list)):
            print(f"\n{key}:")
            print(json.dumps(value, indent=2, default=str))
        else:
            print(f"\n{key}: {value}")
    print()
    print("Respond:  a = accept  |  r = reject  |  c <text> = correct  |  <freeform>")
    print()
    return _read_pi_response_loop(kind)


def _read_pi_response_loop(kind: str) -> str:
    """Read a non-empty PI response from stdin, re-prompting on empty input.

    Only `EOFError` (Ctrl-D / non-interactive stdin) falls through to
    `_default_accept_token(kind)`. Bare Enter is treated as "no input yet,
    please type something" — re-prompts with a brief reminder. Phase 2.6
    surfaced the buffered-newline-auto-accept hazard; this loop closes it.
    """
    while True:
        try:
            raw = input("PI > ").strip()
        except EOFError:
            # Non-interactive stdin — default to the type-appropriate accept
            # token so the driver remains testable, but log a warning so
            # misuse is visible.
            accept_token = _default_accept_token(kind)
            print(f"(stdin closed; defaulting to {accept_token!r})", file=sys.stderr)
            return accept_token

        if raw == "a":
            return _default_accept_token(kind)
        if raw == "r":
            return "reject"
        if raw.startswith("c "):
            return raw[2:].strip()
        if raw:
            return raw
        # Empty Enter: re-prompt instead of silently auto-accepting.
        print(
            "(empty input; please type 'a' to accept, 'r' to reject, "
            "'c <text>' to correct, or any freeform response)",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Operational driver for the autonomous orchestrator."
    )
    parser.add_argument(
        "--mission-id",
        required=True,
        help="RKA mission ID for the orchestrator to execute.",
    )
    parser.add_argument(
        "--project-id",
        default="prj_01KKQM9JFG67GT5FGWTAHD9YE4",
        help="RKA project containing the mission.",
    )
    parser.add_argument("--rka-url", default="http://localhost:9712")
    parser.add_argument(
        "--workflow-thread-id",
        default=None,
        help="Stable tag applied to every RKA write during the run. "
             "Defaults to thr_op_rollout_<unix_ts>.",
    )
    parser.add_argument(
        "--checkpoint-db",
        default=":memory:",
        help="SqliteSaver path. `:memory:` keeps state ephemeral.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="If set, write a JSON pilot-artifact file under this directory.",
    )
    args = parser.parse_args(argv)

    workflow_thread_id = (
        args.workflow_thread_id or f"thr_op_rollout_{int(time.time())}"
    )

    print(f"=== Operational driver — workflow_thread_id={workflow_thread_id} ===")
    print(f"  mission_id={args.mission_id}")
    print(f"  project_id={args.project_id}")
    print(f"  rka_url={args.rka_url}\n")

    # MCP client first — needed to load the mission spec.
    mcp = make_client(
        workflow_thread_id=workflow_thread_id,
        base_url=args.rka_url,
        project_id=args.project_id,
    )

    # Smoke: RKA reachable + mission exists.
    try:
        status = mcp.rka_get_status()
        phase = status.get("current_phase", "(unknown)")
        print(f"  RKA reachable; project phase: {phase}")
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR: RKA unreachable at {args.rka_url}: {e}", file=sys.stderr)
        return 2

    try:
        mission = mcp.rka_get_mission(id=args.mission_id)
        if not mission or not mission.get("id"):
            print(
                f"  ERROR: mission {args.mission_id} not found in project "
                f"{args.project_id}",
                file=sys.stderr,
            )
            return 2
        print(f"  Mission loaded: {mission.get('id')} — {mission.get('objective', '')[:80]}")
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR: failed to load mission: {e}", file=sys.stderr)
        return 2

    motivated_by = mission.get("motivated_by_decision") or mission.get(
        "motivated_by_decision_id"
    ) or ""

    # Real SDK only — Claude Max via the auth chain in llm_client.
    try:
        sdk = make_sdk()
        print("  SDK: REAL claude-agent-sdk (Claude Max routing)\n")
    except RuntimeError as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return 2

    # Build + invoke the graph.
    ckpt = (
        None
        if args.checkpoint_db == ":memory:"
        else graph.open_checkpointer(args.checkpoint_db)
    )
    g = graph.build_graph(
        sdk=sdk, mcp=mcp, checkpointer=ckpt, interrupt_fn=interactive_interrupt
    )

    initial = make_initial_state(
        workflow_thread_id=workflow_thread_id,
        mission_id=args.mission_id,
        motivated_by_decision_id=motivated_by,
    )

    config: dict[str, Any] = (
        {"configurable": {"thread_id": workflow_thread_id}}
        if ckpt is not None
        else {}
    )

    print("--- invoking graph ---")
    final = g.invoke(initial, config=config)

    print("\n--- run complete ---")
    print(f"  terminal_state:  {final.get('terminal_state')}")
    print(f"  current_phase:   {final.get('current_phase')}")
    print(f"  interrupts:      {len(final.get('interrupts', []))}")
    print(f"  artifacts:       {len(final.get('artifacts', []))}")
    print(f"  checkpoints:     {len(final.get('checkpoints', []))}")
    print(f"  errors:          {len(final.get('errors', []))}")
    print(f"  final_report_id: {final.get('final_report_id')}")
    print(f"\nArtifact IDs (retrievable via tags=[{workflow_thread_id}]):")
    for a in final.get("artifacts", []):
        print(f"  - {a.get('rka_id')}  ({a.get('entity_type')})  by {a.get('node_name')}")

    summary = {
        "workflow_thread_id": workflow_thread_id,
        "mission_id": args.mission_id,
        "project_id": args.project_id,
        "terminal_state": final.get("terminal_state"),
        "current_phase": final.get("current_phase"),
        "interrupts_count": len(final.get("interrupts", [])),
        "checkpoints_count": len(final.get("checkpoints", [])),
        "errors_count": len(final.get("errors", [])),
        "final_report_id": final.get("final_report_id"),
        "artifacts": [
            {
                "rka_id": a.get("rka_id"),
                "entity_type": a.get("entity_type"),
                "node_name": a.get("node_name"),
            }
            for a in final.get("artifacts", [])
        ],
        "errors": final.get("errors", []),
    }
    if args.output_dir:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{workflow_thread_id}.json"
        out_path.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"\nWrote artifact: {out_path}")

    return 0 if final.get("terminal_state") == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
