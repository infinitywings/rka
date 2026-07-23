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

The workspace must be new and empty. Reusing a prior run directory is rejected
so old reports, code, or measurements cannot leak into the baseline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.eval import graders
from orchestrator.eval.run_record import RunRecord
from orchestrator.eval.sort_crossover import (
    SORT_EXPERIMENT_CAPABILITY_KINDS,
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


def _require_fresh_workspace(workspace: str) -> None:
    """Reject non-empty workspaces so prior-run answers cannot leak."""
    ws = Path(workspace)
    entries = sorted(ws.iterdir()) if ws.exists() else []
    if entries:
        preview = ", ".join(p.name for p in entries[:5])
        more = "..." if len(entries) > 5 else ""
        raise ValueError(
            "Arm B requires a new, empty workspace; found "
            f"{len(entries)} existing entr{'y' if len(entries) == 1 else 'ies'}: "
            f"{preview}{more}"
        )


def _workspace_snapshot(workspace: str) -> dict[Path, str]:
    """Return content hashes for visible, regular files in ``workspace``.

    Arm B starts from a fresh workspace. The snapshot still excludes hidden
    SDK state and lets the grader count only files produced by this run.
    """
    ws = Path(workspace)
    snapshot: dict[Path, str] = {}
    if not ws.exists():
        return snapshot
    for f in sorted(ws.rglob("*")):
        if not f.is_file() or f.is_symlink():
            continue
        rel = f.relative_to(ws)
        if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue
        try:
            digest = hashlib.sha256()
            with f.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            snapshot[rel] = digest.hexdigest()
        except OSError:
            continue
    return snapshot


def _changed_workspace_files(
    workspace: str,
    before: dict[Path, str],
) -> list[Path]:
    """Return files created or content-modified since ``before``."""
    ws = Path(workspace)
    after = _workspace_snapshot(workspace)
    return [ws / rel for rel, digest in sorted(after.items()) if before.get(rel) != digest]


def _classify_workspace_artifacts(files: list[Path]) -> list[dict]:
    """Map files produced by this arm-B run to grader artifact kinds."""
    arts: list[dict] = []
    for f in files:
        name = f.name.lower()
        suffix = f.suffix.lower()
        figure_token = re.search(
            r"(?:^|[^a-z0-9])fig(?:ure)?[0-9]*(?:[^a-z0-9]|$)",
            f.stem.lower(),
        )
        if suffix in (".png", ".svg", ".jpg", ".jpeg") or figure_token:
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


def _extract_claim(text: str, workspace: str, produced_files: list[Path]) -> str:
    """Pull ``FINAL CLAIM:`` from the completion or this run's report."""
    sources = [text or ""]
    report = Path(workspace) / "armB_report.md"
    if report in set(produced_files):
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
    p.add_argument(
        "--workspace",
        default="/Volumes/base/projects/sort-crossover-armB",
        help="New, empty workspace dedicated to this single Arm-B run.",
    )
    p.add_argument("--model", default="claude-opus-4-8")
    p.add_argument("--run-label", default="armB-plain-claude")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--budget-usd", type=float, default=20.0)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    Path(args.workspace).mkdir(parents=True, exist_ok=True)
    _require_fresh_workspace(args.workspace)
    before = _workspace_snapshot(args.workspace)
    from orchestrator.llm_client import make_plain_sdk
    sdk = make_plain_sdk(workspace_path=args.workspace, model=args.model)

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
    produced_files = _changed_workspace_files(args.workspace, before)
    claim_text = _extract_claim(out, args.workspace, produced_files)
    artifacts = _classify_workspace_artifacts(produced_files)
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
        expected_kinds=SORT_EXPERIMENT_CAPABILITY_KINDS,
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
