#!/usr/bin/env python
"""Live oracle-driven driver for the sorting-crossover e2e eval (arm A).

Drives the REAL mission graph with ``build_sort_oracle()`` as the in-process PI,
against the live RKA REST API, using a pluggable SDK backend (DeepSeek v4 Flash
by default). Captures the LangGraph terminal state, builds a ``RunRecord``, runs
the three-axis grader, and writes per-run JSON deliverables.

This is the "reproducible arm-A run" the runbook describes
(``orchestrator/docs/e2e-sort-crossover-runbook.md`` §"Sequence of runs"):
``build_sort_oracle()`` decides every PI gate per the sealed ground truth, so a
size-only design is redirected (DESIGN_REDIRECT_TEXT → confirmation_brief_redraft)
and a naive final claim is redirected (PIVOT_REDIRECT_TEXT → mission_redraft)
until the interaction claim is re-proposed and ratified.

The SDK backend is TEXT-ONLY: the orchestrator dispatches every RKA read/write
parent-side through the ``mcp`` client (RestMCPClient), so the SDK only needs
single-turn ``complete()``. This lets us run on DeepSeek (cheap, no claude SDK
subprocess, no Docker daemon) while exercising the identical graph + RKA writes.

Usage:
  .venv/bin/python orchestrator/scripts/eval_sort_driver.py \
      --project-id prj_... --mission-id mis_... \
      --motivated-by-decision-id dec_... \
      --arc mission --run-label M3-experiment-and-pivot \
      --output-dir orchestrator/results/e2e-sort-2026-06-15
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Make the orchestrator package importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import graph
from orchestrator.llm_client import (
    SDK_TIMEOUT_BACKBRIEF_S,
    SDK_TIMEOUT_DEFAULT_S,
    SDK_TIMEOUT_TOOL_USE_S,
    SDKTimeoutError,
)
from orchestrator.mcp_client import make_client
from orchestrator.state import make_initial_state
from orchestrator.eval import graders
from orchestrator.eval.run_record import RunRecord
from orchestrator.eval.runbook_sort import build_sort_oracle, mission_spec
from orchestrator.eval.sort_crossover import (
    full_quadrant_design,
    run_sort_experiment,
    sort_crossover_subject,
    sort_surprise_signal,
)


class DeepSeekSDK:
    """``SDKClient``-Protocol backend over DeepSeek's OpenAI-compatible API.

    Text-only single-turn completion — satisfies the narrow Protocol
    (``complete()`` + ``last_call_cost_usd``). Raises ``SDKTimeoutError`` on a
    per-call timeout so the orchestrator's Phase-S4 timeout layer routes it as a
    classified error (identical to the real SDK contract)."""

    # Rough DeepSeek v4 Flash rates (USD per token). Small by design — used only
    # for the reliability budget check. Override via env if real pricing differs.
    _IN_RATE = float(os.environ.get("DEEPSEEK_IN_RATE_PER_MTOK", "0.07")) / 1_000_000
    _OUT_RATE = float(os.environ.get("DEEPSEEK_OUT_RATE_PER_MTOK", "0.28")) / 1_000_000

    def __init__(self, model: str = "deepseek-v4-flash",
                 base_url: str = "https://api.deepseek.com") -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY not set in env")
        self._key = key
        self.last_call_cost_usd: float = 0.0
        self.calls = 0
        self.total_cost_usd = 0.0
        self.total_in_tokens = 0
        self.total_out_tokens = 0

    def complete(self, prompt: str, *, max_tokens: int = 4096,
                 system: str | None = None, timeout_s: float | None = None) -> str:
        self.last_call_cost_usd = 0.0
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=body,
            headers={"Authorization": f"Bearer {self._key}",
                     "Content-Type": "application/json"},
        )
        to = timeout_s if timeout_s else 180.0
        try:
            with urllib.request.urlopen(req, timeout=to) as resp:
                data = json.loads(resp.read())
        except (socket.timeout, TimeoutError) as exc:
            raise SDKTimeoutError(
                f"DeepSeek complete() exceeded {to:.0f}s budget") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
        choices = data.get("choices") or []
        text = (choices[0].get("message", {}).get("content") if choices else "") or ""
        usage = data.get("usage", {}) or {}
        in_tok = int(usage.get("prompt_tokens", 0) or 0)
        out_tok = int(usage.get("completion_tokens", 0) or 0)
        self.last_call_cost_usd = round(in_tok * self._IN_RATE + out_tok * self._OUT_RATE, 6)
        self.total_cost_usd = round(self.total_cost_usd + self.last_call_cost_usd, 6)
        self.total_in_tokens += in_tok
        self.total_out_tokens += out_tok
        self.calls += 1
        return text


def _git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return "unknown"


def _orchestrator_version() -> str:
    try:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        for line in pyproject.read_text().splitlines():
            if line.strip().startswith("version"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "unknown"


def _decision_text(d: dict) -> str:
    parts = [d.get("question", ""), d.get("chosen", ""), d.get("rationale", "")]
    if isinstance(d.get("rationale"), str):
        pass
    return " ".join(p for p in parts if isinstance(p, str) and p)


def _extract_final_claim(final: dict, mcp, subject) -> tuple[str, list[dict]]:
    """Best-effort: the run's final claim text + the fetched decision dicts.

    Pulls every ``decision``-kind artifact the run wrote, fetches each from RKA,
    and returns the concatenated text of the decision that best matches the
    sealed interaction vocabulary (falling back to all decisions, then to the
    final-synthesis/report note text)."""
    decisions: list[dict] = []
    for a in final.get("artifacts", []) or []:
        kind = (a.get("entity_type") or a.get("kind") or "").lower()
        rid = a.get("rka_id") or a.get("id")
        if kind == "decision" and rid:
            try:
                decisions.append(mcp.rka_get(id=rid))
            except Exception:
                pass
    if decisions:
        req = [k.lower() for k in subject.required_claim_keywords]
        def score(d):
            t = _decision_text(d).lower()
            return sum(1 for k in req if k in t)
        best = max(decisions, key=score)
        if score(best) > 0:
            return _decision_text(best), decisions
        return " ".join(_decision_text(d) for d in decisions), decisions
    # fallback: final report / synthesis text in state
    for key in ("final_report_text", "final_synthesis", "synthesis"):
        v = final.get(key)
        if isinstance(v, str) and v:
            return v, decisions
    return "", decisions


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Live arm-A oracle driver (sorting subject)")
    p.add_argument("--project-id", required=True)
    p.add_argument("--mission-id", required=True)
    p.add_argument("--motivated-by-decision-id", default="dec_eval")
    p.add_argument("--workflow-thread-id", default=None)
    p.add_argument("--arc", default="mission",
                   choices=["mission", "writer", "revision", "phase_o"])
    p.add_argument("--run-label", required=True)
    p.add_argument("--sdk", default="claude", choices=["claude", "deepseek", "pilot", "fake"])
    p.add_argument("--model", default="claude-opus-4-8")
    p.add_argument("--workspace", default=None,
                   help="Executor FS-tool scope (Bash/Read/Write cwd-equivalent). "
                        "Created if absent. Used by --sdk claude.")
    p.add_argument("--rka-url", default="http://localhost:9712")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--budget-usd", type=float, default=5.0,
                   help="Grader reliability threshold (within_budget check).")
    p.add_argument("--cap-usd", type=float, default=30.0,
                   help="Orchestrator INTERNAL hard cap (budget_check). Must exceed "
                        "the real run cost or the run escalates before the pivot. "
                        "Opus runs need >> the 5.0 default.")
    p.add_argument("--max-redrafts", type=int, default=4)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    thread = args.workflow_thread_id or f"thr_eval_{args.run_label}_{int(time.time())}"
    print(f"=== arm-A run: {args.run_label} (arc={args.arc}) ===")
    print(f"  project={args.project_id} mission={args.mission_id}")
    print(f"  workflow_thread_id={thread}  sdk={args.sdk} model={args.model}")

    # --- SDK backend ---
    if args.sdk == "claude":
        from orchestrator.llm_client import make_sdk
        model = args.model if args.model.startswith("claude") else "claude-opus-4-8"
        workspace = args.workspace
        if workspace:
            Path(workspace).mkdir(parents=True, exist_ok=True)
        sdk = make_sdk(project_id=args.project_id, workspace_path=workspace, model=model)
        print(f"  SDK: Claude Agent SDK (model={model}, real Bash/Read/Write — "
              f"Executor runs the experiment for real)")
    elif args.sdk == "deepseek":
        sdk = DeepSeekSDK(model=args.model)
    elif args.sdk == "pilot":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pilot_t12 import PilotSDK
        sdk = PilotSDK()
    else:
        from tests._fakes import FakeSDK
        sdk = FakeSDK(canned_reply="APPROVED\nfine")

    # --- MCP client (real REST) ---
    mcp = make_client(workflow_thread_id=thread, base_url=args.rka_url,
                      project_id=args.project_id)
    try:
        status = mcp.rka_get_status()
        print(f"  RKA reachable; phase={status.get('current_phase', '(n/a)')}")
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR: RKA unreachable at {args.rka_url}: {e}")
        return 2

    subject = sort_crossover_subject()
    oracle = build_sort_oracle()
    ckpt = graph.open_checkpointer(None)
    g = graph.build_graph(sdk=sdk, mcp=mcp, checkpointer=ckpt, interrupt_fn=oracle)
    initial = make_initial_state(
        workflow_thread_id=thread, mission_id=args.mission_id,
        motivated_by_decision_id=args.motivated_by_decision_id,
        project_id=args.project_id,
    )
    # Raise the orchestrator's internal budget cap (budget_check reads
    # state["cap_usd"]) above the 5.0 default so an expensive Opus run reaches
    # the decision/pivot stage instead of escalating at budget_check.
    initial["cap_usd"] = args.cap_usd

    print("--- invoking graph (this makes live LLM + RKA calls) ---")
    t0 = time.time()
    try:
        final = g.invoke(initial, config={"configurable": {"thread_id": thread}})
    except Exception as e:  # noqa: BLE001 — capture a crashed run as a failed record
        wall = round(time.time() - t0, 1)
        print(f"  graph.invoke raised after {wall}s: {type(e).__name__}: {e}")
        final = {"workflow_thread_id": thread, "project_id": args.project_id,
                 "mission_id": args.mission_id, "terminal_state": "failed",
                 "artifacts": [], "errors": [{"node_name": "driver",
                 "error_type": "graph_invoke_raised", "detail": f"{type(e).__name__}: {e}"}]}
    wall = round(time.time() - t0, 1)

    # cost: prefer the graph's accrued usd_spent; floor at the SDK's own tally
    sdk_cost = getattr(sdk, "total_cost_usd", 0.0)
    final["usd_spent"] = max(float(final.get("usd_spent", 0.0) or 0.0), sdk_cost)

    print(f"--- run complete in {wall}s ---")
    print(f"  terminal_state: {final.get('terminal_state')}")
    print(f"  artifacts:      {len(final.get('artifacts', []))}")
    print(f"  greenlight_redrafts: {final.get('greenlight_redrafts')}  "
          f"decision_redrafts: {final.get('decision_redrafts')}")
    print(f"  errors:         {len(final.get('errors', []))}")
    print(f"  usd_spent(est): {final.get('usd_spent')}  "
          f"sdk_calls: {getattr(sdk, 'calls', 'n/a')}")

    claim_text, decisions = _extract_final_claim(final, mcp, subject)
    print(f"  decisions written: {len(decisions)}")
    print(f"  final claim (first 220 chars): {claim_text[:220]!r}")

    # --- build record + grade ---
    record = RunRecord.from_final_state(
        arc=args.arc, run_label=args.run_label, final_state=final,
        oracle_decisions=oracle.as_dicts(),
        seed=args.seed, orchestrator_version=_orchestrator_version(),
        rka_head=_git_head(), subject_id=subject.subject_id,
        subject_ground_truth_hash=subject.ground_truth_hash(), arm="A",
        wall_clock_s=wall,
    )
    spec_kinds = None
    try:
        spec_kinds = tuple(mission_spec(args.run_label.split("-", 1)[-1])["expected_artifact_kinds"])
    except Exception:
        pass

    surprise = sort_surprise_signal(run_sort_experiment(full_quadrant_design(), seed=args.seed))
    report = graders.grade_run(
        record, subject=subject, claim_text=claim_text, surprise=surprise,
        expected_kinds=spec_kinds, budget_usd=args.budget_usd,
        max_redrafts=args.max_redrafts,
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rec_path = out_dir / f"{args.run_label}.record.json"
    grade_path = out_dir / f"{args.run_label}.grade.json"
    record.write(rec_path)
    grade_blob = {
        **report.to_dict(),
        "claim_text": claim_text,
        "surprise_shape": surprise.shape,
        "contradicts_naive": surprise.contradicts_naive,
        "decisions_fetched": decisions,
        "sdk": {"backend": args.sdk, "model": args.model,
                "calls": getattr(sdk, "calls", None),
                "in_tokens": getattr(sdk, "total_in_tokens", None),
                "out_tokens": getattr(sdk, "total_out_tokens", None),
                "cost_usd_est": getattr(sdk, "total_cost_usd", None)},
        "wall_clock_s": wall,
        "oracle_decisions": oracle.as_dicts(),
    }
    grade_path.write_text(json.dumps(grade_blob, indent=2, default=str) + "\n")

    print("\n=== GRADE ===")
    print(json.dumps(report.to_dict(), indent=2))
    print(f"\nWrote: {rec_path}\n       {grade_path}")
    return 0 if final.get("terminal_state") == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
