"""A/B sweep harness for Phase-3.1 metric tuning (Mission mis_01KS3EB2671CDD4V9RZCMYCEH1).

Runs the Eval-v2 corpus once per (shape_N, w_recency, bundle_K) config,
restarting the rka container with env-var overrides between runs.
Aggregates per-config metrics into ``eval-harness/v2/results/sweep_v2_5_9/``.

Sweep matrix (64 configs total, per Brain ratification of
chk_01KS3FZDX78FD89CVR4K6VYJFK):

  shape_N    ∈ {1, 30, 90, 365}        (RKA_CTX_RECENCY_SHAPE_N)
  w_recency  ∈ {0.05, 0.10, 0.15, 0.20} (RKA_CTX_W_RECENCY)
  bundle_K   ∈ {30, 50, 80, 150}        (RKA_CTX_BUNDLE_K)

Winner selection — Brain Option B (mis_01KS3EB2671CDD4V9RZCMYCEH1):

  PRIMARY GATES (both must pass)
    mean_recall            ≥ 0.85
    mean_efficiency        ≥ 0.13

  SIDE CONSTRAINT
    mean_ordering_score    ≥ 0.363    (don't regress below floor)

  TIE-BREAKS (among configs clearing all three)
    1. min w_recency (less recency amplification)
    2. max shape_N   (slower decay, more stable across DB drift)
    3. max bundle_K  (less aggressive truncation)

If NO config clears all three → MANDATORY CHECKPOINT for Brain + PI on
PARTIAL close vs Phase-3.2 vs architectural pivot.

Hot-reconfig vs container-restart: Brain's strong preference was
hot-reconfig if `_reload_coefficients_from_env()` extended cleanly. T3
analysis: the helper re-reads env vars at the call site, but env vars
of the container PROCESS can't be changed without restart (Docker
limitation). Hot-reconfig would require a new `/api/reload-coefficients`
endpoint accepting env overrides — that's net-new code beyond T2 scope.
Defer to container-restart path (~10-15 sec per config; sweep wall-clock
~15-20 min for 64 configs) per Brain's path-2 fallback.

DB-snapshot taken pre- and post-sweep to detect drift mid-run. Drift IS
expected (recency mechanism + ambient brain/executor activity), but the
DELTA tells us how much the absolute floor numbers should be discounted.
"""

from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx


REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO_ROOT / "eval-harness" / "v2" / "results" / "sweep_v2_5_9"
SWEEP_SUMMARY_PATH = RESULTS_DIR / "summary.json"
WINNER_PATH = RESULTS_DIR / "winner.md"
PROJECT_ID = "prj_01KKQM9JFG67GT5FGWTAHD9YE4"
HEALTH_URL = "http://localhost:9712/api/health"

# Floor gates (Option B; recall + efficiency primary, ordering side constraint).
RECALL_FLOOR = 0.85
EFFICIENCY_FLOOR = 0.13
ORDERING_FLOOR = 0.363


@dataclasses.dataclass(frozen=True)
class Config:
    cfg_id: int
    shape_n: float
    w_recency: float
    bundle_k: int

    @property
    def label(self) -> str:
        return f"N={self.shape_n:g}/wR={self.w_recency}/K={self.bundle_k}"

    def env(self) -> dict[str, str]:
        return {
            "RKA_CTX_RECENCY_SHAPE_N": str(self.shape_n),
            "RKA_CTX_W_RECENCY": str(self.w_recency),
            "RKA_CTX_BUNDLE_K": str(self.bundle_k),
        }


def _enumerate_configs() -> list[Config]:
    """Cartesian product of the 3 sweep dimensions → 4 × 4 × 4 = 64."""
    shape_ns = [1, 30, 90, 365]
    w_recencies = [0.05, 0.10, 0.15, 0.20]
    bundle_ks = [30, 50, 80, 150]
    configs: list[Config] = []
    for cfg_id, (n, wr, k) in enumerate(
        itertools.product(shape_ns, w_recencies, bundle_ks), start=1
    ):
        configs.append(Config(cfg_id=cfg_id, shape_n=n, w_recency=wr, bundle_k=k))
    return configs


def _snapshot_db_counts() -> dict[str, int]:
    """Snapshot key row counts from /data/rka.db so post-sweep drift is detectable."""
    cmd = [
        "docker", "compose", "exec", "-T", "rka", "python", "-c",
        "import sqlite3; c = sqlite3.connect('/data/rka.db'); "
        "print(c.execute(\"SELECT 'journal', COUNT(*) FROM journal\").fetchone()); "
        "print(c.execute(\"SELECT 'decisions', COUNT(*) FROM decisions\").fetchone()); "
        "print(c.execute(\"SELECT 'missions', COUNT(*) FROM missions\").fetchone()); "
        "print(c.execute(\"SELECT 'entity_links', COUNT(*) FROM entity_links\").fetchone()); "
        "print(c.execute(\"SELECT 'evidence_clusters', COUNT(*) FROM evidence_clusters\").fetchone());",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    counts: dict[str, int] = {}
    for line in out.stdout.strip().splitlines():
        line = line.strip("()")
        name, count = line.split(",", 1)
        counts[name.strip().strip("'")] = int(count.strip())
    return counts


def _apply_config_and_wait(cfg: Config) -> float:
    """Restart rka with the config's env vars; poll /api/health until 200.
    Returns wall-clock seconds for the restart + health-poll."""
    t0 = time.time()
    env = os.environ.copy()
    env.update(cfg.env())
    subprocess.run(
        ["docker", "compose", "up", "-d", "--force-recreate"],
        cwd=REPO_ROOT, env=env, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            r = httpx.get(HEALTH_URL, timeout=2.0)
            if r.status_code == 200:
                return time.time() - t0
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Container failed health within 30s for cfg{cfg.cfg_id}")


def _run_eval(cfg_id: int) -> Path:
    """Run the eval-v2 runner; return the raw-output dir path."""
    out_dir = RESULTS_DIR / f"raw_cfg{cfg_id:02d}"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable,
            "-m", "eval-harness.v2.runner",
            "--output-dir", str(out_dir),
            "--project-id", PROJECT_ID,
        ],
        cwd=REPO_ROOT, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return out_dir


def _compute_metrics(cfg_id: int, raw_dir: Path) -> Path:
    """Run the metrics module; return the metrics JSON path.

    Note: metrics.py exits 1 when the critical-recall floor (0.85) isn't
    cleared. For a sweep this is expected for most configs (we're looking
    for the config that DOES clear), so we do not check the return code —
    only verify the output file is written and parses.
    """
    out_path = RESULTS_DIR / f"metrics_cfg{cfg_id:02d}.json"
    if out_path.exists():
        out_path.unlink()
    proc = subprocess.run(
        [
            sys.executable,
            "-m", "eval-harness.v2.metrics",
            "--raw-dir", str(raw_dir),
            "--output", str(out_path),
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        check=False,
    )
    if not out_path.exists():
        raise RuntimeError(
            f"metrics.py did not write {out_path} for cfg{cfg_id}; "
            f"exit={proc.returncode}; stderr=\n{proc.stderr.decode(errors='replace')[:500]}"
        )
    return out_path


def _summarize(cfg: Config, metrics_path: Path) -> dict[str, Any]:
    m = json.loads(metrics_path.read_text())
    agg = m["aggregate"]
    return {
        "cfg_id": cfg.cfg_id,
        "label": cfg.label,
        "shape_n": cfg.shape_n,
        "w_recency": cfg.w_recency,
        "bundle_k": cfg.bundle_k,
        "metrics_path": str(metrics_path.relative_to(REPO_ROOT)),
        "mean_recall": agg["mean_recall"],
        "mean_ordering_score": agg["mean_ordering_score"],
        "mean_efficiency": agg["mean_efficiency"],
        "mean_breadth": agg["mean_breadth"],
        "passes_recall": agg["mean_recall"] >= RECALL_FLOOR,
        "passes_efficiency": agg["mean_efficiency"] >= EFFICIENCY_FLOOR,
        "passes_ordering": agg["mean_ordering_score"] >= ORDERING_FLOOR,
    }


def _select_winner(summaries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Apply Option B winner-selection criteria.

    Returns the winning config dict, or None if no config clears all
    three gates. Tie-breaks: min w_recency, then max shape_n, then max
    bundle_K.
    """
    qualifying = [
        s
        for s in summaries
        if s["passes_recall"] and s["passes_efficiency"] and s["passes_ordering"]
    ]
    if not qualifying:
        return None
    # Sort by tie-breaks. Python's sort is stable, so primary first reversed.
    qualifying.sort(
        key=lambda s: (s["w_recency"], -s["shape_n"], -s["bundle_k"])
    )
    return qualifying[0]


def _write_winner_md(
    winner: dict[str, Any] | None,
    summaries: list[dict[str, Any]],
    db_pre: dict[str, int],
    db_post: dict[str, int],
    sweep_elapsed: float,
) -> None:
    """Write a human-readable winner.md for Brain + PI ratification at T4 close."""
    lines: list[str] = []
    lines.append("# Phase-3.1 sweep — winner selection")
    lines.append("")
    lines.append(f"Mission: `mis_01KS3EB2671CDD4V9RZCMYCEH1`")
    lines.append(f"Decision: `dec_01KS3E6ZJXXV7542QPWZ9W8BQS`")
    lines.append(f"Sweep wall-clock: {sweep_elapsed:.0f} s")
    lines.append("")

    if winner is None:
        lines.append("## ⛔ No config clears all three gates")
        lines.append("")
        lines.append(
            "Per Brain Option B, recall + efficiency are PRIMARY GATES; "
            "ordering ≥ 0.363 is SIDE CONSTRAINT. None of the 64 configs "
            "in the matrix achieves all three simultaneously."
        )
        lines.append("")
        lines.append(
            "This is a **MANDATORY CHECKPOINT** per mission spec T4 "
            "failure mode. Surface to Brain + PI for one of:"
        )
        lines.append("- PARTIAL close (recall + ordering only; defer efficiency)")
        lines.append("- Phase-3.2 candidate (architectural pivot beyond bundle_K + shape_N)")
        lines.append("- Scope expansion (e.g., per-tool K beyond bundle_K)")
        lines.append("")
    else:
        lines.append("## ✅ Winner")
        lines.append("")
        lines.append(f"**Config {winner['cfg_id']}**: `{winner['label']}`")
        lines.append("")
        lines.append("| Parameter | Value |")
        lines.append("|---|---|")
        lines.append(f"| `RKA_CTX_RECENCY_SHAPE_N` | `{winner['shape_n']}` |")
        lines.append(f"| `RKA_CTX_W_RECENCY` | `{winner['w_recency']}` |")
        lines.append(f"| `RKA_CTX_BUNDLE_K` | `{winner['bundle_k']}` |")
        lines.append("")
        lines.append("| Metric | Value | Floor | Status |")
        lines.append("|---|---|---|---|")
        lines.append(
            f"| mean_recall | {winner['mean_recall']:.4f} | {RECALL_FLOOR} | "
            f"{'PASS' if winner['passes_recall'] else 'FAIL'} |"
        )
        lines.append(
            f"| mean_ordering_score | {winner['mean_ordering_score']:.4f} | "
            f"{ORDERING_FLOOR} | "
            f"{'PASS' if winner['passes_ordering'] else 'FAIL'} |"
        )
        lines.append(
            f"| mean_efficiency | {winner['mean_efficiency']:.4f} | "
            f"{EFFICIENCY_FLOOR} | "
            f"{'PASS' if winner['passes_efficiency'] else 'FAIL'} |"
        )
        lines.append("")

    # Top 5 by ordering, top 5 by efficiency, top 5 by recall for cross-cut.
    lines.append("## Sweep table (all 64 configs)")
    lines.append("")
    lines.append("| cfg | N | wR | K | recall | ordering | efficiency | passes |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for s in summaries:
        flags = (
            ("R" if s["passes_recall"] else "·")
            + ("O" if s["passes_ordering"] else "·")
            + ("E" if s["passes_efficiency"] else "·")
        )
        lines.append(
            f"| {s['cfg_id']:02d} | {s['shape_n']:g} | {s['w_recency']} | "
            f"{s['bundle_k']} | {s['mean_recall']:.4f} | "
            f"{s['mean_ordering_score']:.4f} | {s['mean_efficiency']:.4f} | "
            f"{flags} |"
        )
    lines.append("")
    lines.append("Passes column: R = recall, O = ordering, E = efficiency.")
    lines.append("")

    lines.append("## DB drift across sweep window")
    lines.append("")
    lines.append("| Entity | Pre | Post | Δ |")
    lines.append("|---|---|---|---|")
    for k in sorted(db_pre.keys()):
        pre_v = db_pre[k]
        post_v = db_post.get(k, 0)
        delta = post_v - pre_v
        marker = " ⚠" if delta != 0 else ""
        lines.append(f"| {k} | {pre_v} | {post_v} | {delta:+d}{marker} |")
    lines.append("")

    WINNER_PATH.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Run only the first N configs (smoke test).",
    )
    parser.add_argument(
        "--skip", type=int, default=0,
        help="Skip the first N configs (resume after partial sweep).",
    )
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    all_configs = _enumerate_configs()
    configs = all_configs[args.skip:]
    if args.limit:
        configs = configs[: args.limit]

    print(f"=== Phase-3.1 sweep: {len(configs)} of {len(all_configs)} configs ===")
    print()

    print("=== Pre-sweep DB snapshot ===")
    db_pre = _snapshot_db_counts()
    for k, v in sorted(db_pre.items()):
        print(f"  {k}: {v}")
    print()

    sweep_started = time.time()
    summaries: list[dict[str, Any]] = []
    for i, cfg in enumerate(configs, start=1):
        cfg_t0 = time.time()
        restart_secs = _apply_config_and_wait(cfg)
        raw_dir = _run_eval(cfg.cfg_id)
        metrics_path = _compute_metrics(cfg.cfg_id, raw_dir)
        s = _summarize(cfg, metrics_path)
        summaries.append(s)
        elapsed = time.time() - cfg_t0
        flags = (
            ("R" if s["passes_recall"] else "·")
            + ("O" if s["passes_ordering"] else "·")
            + ("E" if s["passes_efficiency"] else "·")
        )
        print(
            f"  [{i:02d}/{len(configs):02d}] cfg{cfg.cfg_id:02d} {cfg.label:<28s} "
            f"r={s['mean_recall']:.3f} o={s['mean_ordering_score']:.3f} "
            f"e={s['mean_efficiency']:.3f}  [{flags}]  ({elapsed:.1f}s)"
        )

    sweep_elapsed = time.time() - sweep_started

    print()
    print("=== Post-sweep DB snapshot ===")
    db_post = _snapshot_db_counts()
    for k, v in sorted(db_post.items()):
        drift = v - db_pre.get(k, 0)
        marker = " ⚠" if drift != 0 else ""
        print(f"  {k}: {v} (Δ {drift:+d}){marker}")
    print()

    winner = _select_winner(summaries)
    summary = {
        "mission": "mis_01KS3EB2671CDD4V9RZCMYCEH1",
        "decision": "dec_01KS3E6ZJXXV7542QPWZ9W8BQS",
        "sweep_elapsed_seconds": sweep_elapsed,
        "n_configs_run": len(summaries),
        "n_configs_total": len(all_configs),
        "winner_cfg_id": winner["cfg_id"] if winner else None,
        "winner_criteria_option_b": {
            "primary_recall_floor": RECALL_FLOOR,
            "primary_efficiency_floor": EFFICIENCY_FLOOR,
            "side_ordering_floor": ORDERING_FLOOR,
            "tie_breaks": [
                "min w_recency",
                "max shape_n",
                "max bundle_k",
            ],
        },
        "db_snapshot_pre": db_pre,
        "db_snapshot_post": db_post,
        "configs": summaries,
    }
    SWEEP_SUMMARY_PATH.write_text(json.dumps(summary, indent=2))
    _write_winner_md(winner, summaries, db_pre, db_post, sweep_elapsed)

    print(f"wrote {SWEEP_SUMMARY_PATH}")
    print(f"wrote {WINNER_PATH}")
    print()
    if winner:
        print(
            f"=== Winner: cfg{winner['cfg_id']} {winner['label']} ===\n"
            f"  recall      = {winner['mean_recall']:.4f} (≥ {RECALL_FLOOR})\n"
            f"  ordering    = {winner['mean_ordering_score']:.4f} (≥ {ORDERING_FLOOR})\n"
            f"  efficiency  = {winner['mean_efficiency']:.4f} (≥ {EFFICIENCY_FLOOR})"
        )
        return 0
    else:
        n_recall = sum(1 for s in summaries if s["passes_recall"])
        n_order = sum(1 for s in summaries if s["passes_ordering"])
        n_eff = sum(1 for s in summaries if s["passes_efficiency"])
        print(
            f"=== NO WINNER — MANDATORY CHECKPOINT ===\n"
            f"  configs passing recall:     {n_recall}/{len(summaries)}\n"
            f"  configs passing ordering:   {n_order}/{len(summaries)}\n"
            f"  configs passing efficiency: {n_eff}/{len(summaries)}\n"
            f"  configs passing all three:  0/{len(summaries)}"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
