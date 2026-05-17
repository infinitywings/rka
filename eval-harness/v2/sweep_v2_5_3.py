"""A/B coefficient sweep harness for Mission v2.5.4-D2-coefficient-tuning.

Runs the Eval-v2 corpus once per coefficient config, restarting the rka
container with env-var overrides between runs. Aggregates per-config
metrics into ``eval-harness/v2/results/sweep_v2_5_3.json``.

Configs swept (mission spec mis_01KRSP44W7BDZH11PZRGXH1WM4 T2):

  Config 1 — w_imp=0.5  w_cent=0.3  w_recency=0.2  (v2.5.3 baseline reference)
  Config 2 — w_imp=0.4  w_cent=0.2  w_recency=0.4  (recency-heavy)
  Config 3 — w_imp=0.3  w_cent=0.5  w_recency=0.2  (centrality-heavy)
  Config 4 — w_imp=0.7  w_cent=0.2  w_recency=0.1  (importance-dominant)
  Config 5 — w_imp=0.45 w_cent=0.35 w_recency=0.2  (balanced; centrality bumped)

Config 1 is the inherited v2.5.3 baseline (commit db2a345 produced
``eval-harness/v2/results/raw_v2.5.3/``). The harness can re-run it for
reproducibility, but the spec's expected pattern is to reuse those
artifacts. Skip behavior controlled by ``--skip-cfg1``.

For each non-skipped config:

  1. ``RKA_CTX_W_*`` env vars set in the harness's shell env.
  2. ``docker compose up -d --force-recreate`` — Compose recreates
     containers with the new env (image NOT rebuilt; T1's code is already
     baked in).
  3. Poll ``/api/health`` until 200.
  4. Run ``python eval-harness/v2/runner.py --output-dir raw_sweep_cfgN/``.
  5. Run ``python eval-harness/v2/metrics.py --raw-dir ... --output ...``.
  6. Collect aggregate metrics into the sweep summary.

PI lift is NOT swept (mission assumption 7); all configs use the default
0.125. Snapshot of DB row counts taken pre-sweep so any drift mid-sweep
is detectable post-hoc.
"""

from __future__ import annotations

import argparse
import dataclasses
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
RESULTS_DIR = REPO_ROOT / "eval-harness" / "v2" / "results"
INHERITED_BASELINE_DIR = RESULTS_DIR / "raw_v2.5.3"
INHERITED_BASELINE_METRICS = RESULTS_DIR / "metrics_v2.5.3.json"
SWEEP_SUMMARY_PATH = RESULTS_DIR / "sweep_v2_5_3.json"
PROJECT_ID = "prj_01KKQM9JFG67GT5FGWTAHD9YE4"
HEALTH_URL = "http://localhost:9712/api/health"


@dataclasses.dataclass(frozen=True)
class Config:
    cfg_id: int
    label: str
    w_imp: float
    w_cent: float
    w_recency: float

    def env(self) -> dict[str, str]:
        return {
            "RKA_CTX_W_IMP": str(self.w_imp),
            "RKA_CTX_W_CENT": str(self.w_cent),
            "RKA_CTX_W_RECENCY": str(self.w_recency),
            # PI lift not swept; left to module default.
        }


CONFIGS: list[Config] = [
    Config(1, "v2.5.3 baseline", 0.5, 0.3, 0.2),
    Config(2, "recency-heavy", 0.4, 0.2, 0.4),
    Config(3, "centrality-heavy", 0.3, 0.5, 0.2),
    Config(4, "importance-dominant", 0.7, 0.2, 0.1),
    Config(5, "balanced (centrality bumped)", 0.45, 0.35, 0.2),
]


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
        # Lines like: "('journal', 1234)"
        line = line.strip("()")
        name, count = line.split(",", 1)
        counts[name.strip().strip("'")] = int(count.strip())
    return counts


def _apply_config_and_wait(cfg: Config) -> None:
    """Restart rka with the config's env vars; poll /api/health until 200."""
    env = os.environ.copy()
    env.update(cfg.env())
    print(f"  → applying env: RKA_CTX_W_IMP={cfg.w_imp} "
          f"W_CENT={cfg.w_cent} W_RECENCY={cfg.w_recency}")
    subprocess.run(
        ["docker", "compose", "up", "-d", "--force-recreate"],
        cwd=REPO_ROOT, env=env, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # Poll health. Container restart is fast (~5s) but the schema
    # migration + vec load can push to 15-20s on first start.
    for _ in range(60):
        try:
            r = httpx.get(HEALTH_URL, timeout=2.0)
            if r.status_code == 200:
                print(f"  → health 200 OK (version: {r.json().get('version')})")
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError("Container failed to become healthy within 30 seconds")


def _run_eval(cfg_id: int) -> Path:
    """Run the eval-v2 runner; return the raw-output dir path."""
    out_dir = RESULTS_DIR / f"raw_sweep_cfg{cfg_id}"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "eval-harness" / "v2" / "runner.py"),
            "--output-dir", str(out_dir),
            "--project-id", PROJECT_ID,
        ],
        cwd=REPO_ROOT, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return out_dir


def _compute_metrics(cfg_id: int, raw_dir: Path) -> Path:
    """Run the metrics module; return the metrics JSON path."""
    out_path = RESULTS_DIR / f"metrics_sweep_cfg{cfg_id}.json"
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "eval-harness" / "v2" / "metrics.py"),
            "--raw-dir", str(raw_dir),
            "--output", str(out_path),
        ],
        cwd=REPO_ROOT, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return out_path


def _summarize(cfg: Config, metrics_path: Path) -> dict[str, Any]:
    m = json.loads(metrics_path.read_text())
    agg = m["aggregate"]
    return {
        "cfg_id": cfg.cfg_id,
        "label": cfg.label,
        "coefficients": {
            "w_imp": cfg.w_imp, "w_cent": cfg.w_cent, "w_recency": cfg.w_recency,
        },
        "metrics_path": str(metrics_path.relative_to(REPO_ROOT)),
        "mean_recall_critical": agg["mean_recall"],
        "mean_expanded_recall": agg["mean_expanded_recall"],
        "mean_ordering_score": agg["mean_ordering_score"],
        "mean_breadth": agg["mean_breadth"],
        "mean_efficiency": agg["mean_efficiency"],
        "per_scenario_ordering": [
            {"scenario_id": s["scenario_id"], "ordering_score": s["ordering_score"]}
            for s in m.get("per_scenario", [])
        ],
    }


def _reuse_inherited_baseline(cfg: Config) -> dict[str, Any]:
    """For Config 1, reuse the inherited raw_v2.5.3 / metrics_v2.5.3 artifacts."""
    if not INHERITED_BASELINE_METRICS.exists():
        raise RuntimeError(
            f"Inherited baseline metrics missing: {INHERITED_BASELINE_METRICS}. "
            "Run with --include-cfg1 to re-execute Config 1."
        )
    # Also stage the artifacts under the sweep naming so the report has a
    # consistent file layout per config.
    out_dir = RESULTS_DIR / "raw_sweep_cfg1"
    if not out_dir.exists():
        shutil.copytree(INHERITED_BASELINE_DIR, out_dir)
    metrics_out = RESULTS_DIR / "metrics_sweep_cfg1.json"
    if not metrics_out.exists():
        shutil.copy(INHERITED_BASELINE_METRICS, metrics_out)
    return _summarize(cfg, metrics_out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-cfg1", action="store_true",
        help="Re-run Config 1 instead of reusing inherited raw_v2.5.3/.",
    )
    args = parser.parse_args()

    print("=== Pre-sweep DB snapshot ===")
    db_pre = _snapshot_db_counts()
    for k, v in sorted(db_pre.items()):
        print(f"  {k}: {v}")
    print()

    sweep_started = time.time()
    summaries: list[dict[str, Any]] = []
    for cfg in CONFIGS:
        print(f"=== Config {cfg.cfg_id}: {cfg.label} ({cfg.w_imp}/{cfg.w_cent}/{cfg.w_recency}) ===")
        t0 = time.time()
        if cfg.cfg_id == 1 and not args.include_cfg1:
            print("  → reusing inherited raw_v2.5.3/ + metrics_v2.5.3.json")
            summaries.append(_reuse_inherited_baseline(cfg))
        else:
            _apply_config_and_wait(cfg)
            raw_dir = _run_eval(cfg.cfg_id)
            metrics_path = _compute_metrics(cfg.cfg_id, raw_dir)
            summaries.append(_summarize(cfg, metrics_path))
        print(f"  done in {time.time() - t0:.1f}s")
        print()

    print("=== Post-sweep DB snapshot ===")
    db_post = _snapshot_db_counts()
    for k, v in sorted(db_post.items()):
        drift = v - db_pre.get(k, 0)
        marker = " ⚠" if drift != 0 else ""
        print(f"  {k}: {v} (Δ {drift:+d}){marker}")
    print()

    summary = {
        "mission": "mis_01KRSP44W7BDZH11PZRGXH1WM4",
        "decision": "dec_01KRSMMCS8MD7KQDBS0E2DVKBQ",
        "sweep_elapsed_seconds": time.time() - sweep_started,
        "db_snapshot_pre": db_pre,
        "db_snapshot_post": db_post,
        "configs": summaries,
        "winner_criteria": {
            "primary": "mean_ordering_score (max)",
            "hard_floor": "mean_recall_critical >= 0.85",
            "lift_floor": "mean_ordering_score >= 0.363 (= v2.5.2 baseline 0.263 + 0.10 lift)",
        },
    }
    SWEEP_SUMMARY_PATH.write_text(json.dumps(summary, indent=2))
    print(f"wrote {SWEEP_SUMMARY_PATH}")
    print()
    print("=== Sweep table ===")
    print(f"  {'cfg':4s} {'label':32s} {'recall':>7s} {'ordering':>9s} {'breadth':>8s}")
    for s in summaries:
        print(
            f"  cfg{s['cfg_id']} {s['label']:32s} "
            f"{s['mean_recall_critical']:7.3f} "
            f"{s['mean_ordering_score']:9.4f} "
            f"{s['mean_breadth']:8.2f}"
        )
    best = max(summaries, key=lambda s: s["mean_ordering_score"])
    print()
    print(
        f"Best ordering_score: cfg{best['cfg_id']} = {best['mean_ordering_score']:.4f} "
        f"({best['label']})"
    )
    floor = 0.363
    if best["mean_ordering_score"] >= floor:
        print(f"  ✓ clears 0.10 floor (v2.5.2 0.263 + 0.10 = {floor})")
    else:
        gap = floor - best["mean_ordering_score"]
        print(
            f"  ✗ DOES NOT CLEAR 0.10 floor (best is {gap:.4f} short). "
            "MANDATORY PAUSE per mission spec T3 trigger."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
