#!/usr/bin/env python
"""Arm B — plain Claude Code (Opus 4.8), NO RKA / NO orchestrator / NO oracle.

The thesis baseline. Drives the SAME model (claude-opus-4-8) with the SAME
real Bash/Read/Write tools as arm A, on the SAME sealed subject, but as a plain
single-agent research session: no orchestrator graph, no RKA knowledge graph, no
PI-oracle gates, no recorded/traceable/superseding decision. We then grade it on
the same three axes.

Expected, thesis-supporting result: comparable CAPABILITY (a capable agent runs
the comparison-count experiment and reaches the interaction conclusion) but
materially lower PROVENANCE — no workflow_thread_id tagging, no recorded pivot
decision, no traceable supersession of the naive hypothesis. The pivot lives only
in prose, not as a first-class, recoverable knowledge-graph artifact.

Usage:
  .venv/bin/python orchestrator/scripts/eval_sort_armB.py \
      --workspace /Volumes/base/projects/sort-crossover-armB \
      --output-dir orchestrator/results/e2e-sort-2026-06-15
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.eval import graders
from orchestrator.eval.run_record import RunRecord
from orchestrator.eval.sort_crossover import (
    full_quadrant_design,
    run_sort_experiment,
    sort_crossover_subject,
    sort_surprise_signal,
)

# A plain research-assistant system prompt — deliberately NO mention of RKA,
# decisions, provenance, or an orchestrator. This is "just Claude Code."
ARMB_SYSTEM = (
    "You are a capable research assistant working in a plain coding session. "
    "You have Bash/Read/Write tools. Do real empirical work: write and run code, "
    "observe the actual results, and report findings grounded strictly in what "
    "you measured. Do not assume an answer."
)


def _armb_prompt(workspace: str) -> str:
    subject = sort_crossover_subject()
    return (
        f"Research question: {subject.research_question}\n\n"
        f"A common assumption (to be tested, not assumed): {subject.naive_hypothesis}\n\n"
        "Investigate this empirically. Concretely:\n"
        "1. Implement insertion sort and a NAIVE first-pivot quicksort, each "
        "instrumented to COUNT element comparisons.\n"
        "2. Run both on a factorial of input SIZE (a small and a large n) x input "
        "ORDERING (random AND nearly-sorted), averaging a few seeded trials per "
        "cell. Verify both sorts produce correctly ordered output.\n"
        "3. Report the comparison-count quadrant and interpret it. State your "
        "FINAL CLAIM about quicksort's efficiency across input distributions in a "
        "single clearly-labelled sentence beginning 'FINAL CLAIM:'.\n"
        f"4. Write a short markdown report (findings + the FINAL CLAIM + the "
        f"comparison-count table) to {workspace}/armB_report.md, and if you can, "
        f"a simple comparison-count figure to {workspace}/armB_figure.txt (ASCII "
        f"is fine) or .png.\n\n"
        "Use Bash to actually run the experiment; ground every number in real output."
    )


def _classify_workspace_artifacts(workspace: str) -> list[dict]:
    """Map arm B's produced files to grader artifact kinds, so capability is
    measured on its real deliverables (it has no RKA entities)."""
    arts: list[dict] = []
    ws = Path(workspace)
    if not ws.exists():
        return arts
    for f in sorted(ws.rglob("*")):
        if not f.is_file():
            continue
        name = f.name.lower()
        suffix = f.suffix.lower()
        if suffix in (".png", ".svg", ".jpg", ".jpeg") or "figure" in name or "fig" in name:
            kind = "diagram"
        elif suffix in (".md", ".tex", ".pdf") or "report" in name or "manuscript" in name:
            kind = "report"
        elif suffix in (".py", ".ipynb"):
            kind = "journal"  # the analysis/working code = the research log
        elif suffix in (".json", ".csv", ".txt"):
            kind = "journal"
        else:
            continue
        arts.append({"id": str(f), "kind": kind, "node": "armB_session"})
    return arts


def _extract_claim(text: str, workspace: str) -> str:
    """Pull the 'FINAL CLAIM:' line from the completion or the report file."""
    sources = [text or ""]
    report = Path(workspace) / "armB_report.md"
    if report.exists():
        try:
            sources.append(report.read_text(encoding="utf-8"))
        except OSError:
            pass
    for src in sources:
        for line in src.splitlines():
            if "final claim" in line.lower():
                return line.strip()
    # fallback: the whole report (claim graders are keyword-based)
    return sources[-1] if len(sources) > 1 else (text or "")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Arm B — plain Claude Code, no RKA")
    p.add_argument("--workspace", default="/Volumes/base/projects/sort-crossover-armB")
    p.add_argument("--model", default="claude-opus-4-8")
    p.add_argument("--run-label", default="armB-plain-claude")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--budget-usd", type=float, default=20.0)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    Path(args.workspace).mkdir(parents=True, exist_ok=True)
    from orchestrator.llm_client import make_sdk
    sdk = make_sdk(workspace_path=args.workspace, model=args.model)

    print(f"=== ARM B (plain Claude Code, no RKA) — model={args.model} ===")
    print(f"  workspace={args.workspace}")
    t0 = time.time()
    try:
        out = sdk.complete(_armb_prompt(args.workspace), system=ARMB_SYSTEM, timeout_s=600.0)
        terminal = "complete"
    except Exception as e:  # noqa: BLE001
        out = f"[arm B raised: {type(e).__name__}: {e}]"
        terminal = "failed"
    wall = round(time.time() - t0, 1)
    print(f"  completed in {wall}s; terminal={terminal}; cost(est)={sdk.last_call_cost_usd}")

    subject = sort_crossover_subject()
    claim_text = _extract_claim(out, args.workspace)
    artifacts = _classify_workspace_artifacts(args.workspace)
    print(f"  workspace artifacts: {[(a['kind']) for a in artifacts]}")
    print(f"  FINAL CLAIM (extracted): {claim_text[:240]!r}")

    # Arm B leaves NO RKA provenance: no workflow_thread_id, no recorded decision.
    record = RunRecord(
        arc="mission", run_label=args.run_label, arm="B",
        workflow_thread_id=None,            # <-- the provenance discriminator
        subject_id=subject.subject_id,
        subject_ground_truth_hash=subject.ground_truth_hash(),
        terminal_state=terminal,
        artifacts=artifacts,
        usd_spent=float(getattr(sdk, "last_call_cost_usd", 0.0) or 0.0),
        wall_clock_s=wall,
        notes=["Arm B: plain Claude Code, no RKA / orchestrator / oracle. "
               "No recorded decision, no workflow_thread_id, no superseding pivot."],
    )

    surprise = sort_surprise_signal(run_sort_experiment(full_quadrant_design(), seed=args.seed))
    report = graders.grade_run(
        record, subject=subject, claim_text=claim_text, surprise=surprise,
        budget_usd=args.budget_usd, max_redrafts=4,
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record.write(out_dir / f"{args.run_label}.record.json")
    (out_dir / f"{args.run_label}.grade.json").write_text(
        json.dumps({**report.to_dict(), "claim_text": claim_text,
                    "completion_excerpt": (out or "")[:2000],
                    "wall_clock_s": wall, "cost_usd_est": sdk.last_call_cost_usd},
                   indent=2, default=str) + "\n")
    print("\n=== ARM B GRADE ===")
    print(json.dumps(report.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
