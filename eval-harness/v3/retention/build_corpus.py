#!/usr/bin/env python3
"""Build the project-F retention corpus from a real RKA snapshot.

Design choices worth stating, because they decide what the numbers mean:

* **Seeds are real project-F records**, quoted verbatim from the snapshot with
  their entity ids and dates, so all three arms see identical material and
  can cite it.
* **The same target is probed at three distances** (near / mid / far). Fade is
  then a within-item comparison — pass near, fail far — rather than a
  comparison across items of differing difficulty.
* **Filler is real, topically adjacent text** drawn from the PI's other
  CPS-security projects (project-D, project-G, project-B, project-E) plus
  project-F's own journal. Synthetic filler would let the lexical RAG baseline
  win too easily.
* **The `rka` arm reads the live project-F project itself, read-only** — not a
  disposable copy. That is stricter than the schema's disposable-project
  recipe: retrieval must find the seeds among ~270 competing real entities
  instead of in an otherwise-empty index, and nothing is written to the PI's
  knowledge base. The baselines are handed the seeds outright, so any
  remaining bias favours the baselines, not RKA.

Usage:
    python eval-harness/v3/retention/build_corpus.py \
        --db <snapshot.db> --out eval-harness/v3/retention/scenarios.project-F.jsonl
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
from pathlib import Path

# Filler must be topically adjacent to the seeds or the lexical RAG baseline
# wins too easily. Supply the project ids in the spec file.
FILLER_PROJECTS: list[str] = []

# Distance targets. The completer runs on a separate LM Studio host
# (qwen3.8-27b-mlx, ~227 tok/s measured on a 13k-token prefill), so this
# machine only serves embeddings and a 35k-token probe prefills in ~150 s --
# comfortably inside one timeout. Report bucket edges, not nominal targets.
DISTANCES = {"near": 800, "mid": 8_000, "far": 35_000}


def fetch(conn: sqlite3.Connection, entity_id: str) -> dict:
    conn.row_factory = sqlite3.Row
    if entity_id.startswith("jrn_"):
        r = conn.execute(
            "SELECT id, content, created_at FROM journal WHERE id = ?", (entity_id,)
        ).fetchone()
        return {"id": r["id"], "date": r["created_at"][:10], "text": r["content"]}
    if entity_id.startswith("clm_"):
        r = conn.execute(
            "SELECT id, content, created_at FROM claims WHERE id = ?", (entity_id,)
        ).fetchone()
        return {"id": r["id"], "date": r["created_at"][:10], "text": r["content"]}
    r = conn.execute(
        "SELECT id, question, chosen, status, created_at FROM decisions WHERE id = ?",
        (entity_id,),
    ).fetchone()
    return {
        "id": r["id"],
        "date": r["created_at"][:10],
        "status": r["status"],
        "text": f"Question: {r['question']}\nDecision: {r['chosen']}",
    }


def seed(conn, entity_id, item_id, kind) -> dict:
    row = fetch(conn, entity_id)
    status = f" [status: {row['status']}]" if row.get("status") else ""
    return {
        "item_id": item_id,
        "kind": kind,
        "text": f"({row['date']}, entity {row['id']}{status}) {row['text']}",
    }


def build_filler(conn: sqlite3.Connection, target_tokens: int) -> list[dict]:
    """Real, topically adjacent working notes, as canned (deterministic) turns."""
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(FILLER_PROJECTS))
    rows = conn.execute(
        f"SELECT id, content FROM journal WHERE project_id IN ({placeholders})"
        " AND content IS NOT NULL AND LENGTH(content) > 400"
        " ORDER BY id",
        FILLER_PROJECTS,
    ).fetchall()

    tasks: list[dict] = []
    budget = target_tokens * 4  # chars
    used = 0
    for index, row in enumerate(rows):
        if used >= budget:
            break
        body = row["content"]
        tasks.append(
            {
                "prompt": f"Continue the working session: review working note {index + 1}"
                " and note anything relevant to the evaluation design.",
                "canned_response": body,
            }
        )
        used += len(body)
    return tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--spec", required=True,
        help=(
            "JSON describing which real records to plant and what to probe for. "
            "Kept OUT of version control: seeds quote a live project verbatim, "
            "and the expectations name the exact values a correct answer must "
            "contain. See schema.md for the shape and local/ for a template."
        ),
    )
    parser.add_argument(
        "--project", default=None,
        help="Project id the seeds belong to; also the project the rka arm reads.",
    )
    args = parser.parse_args(argv)

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        global FILLER_PROJECTS
        FILLER_PROJECTS = spec_projects = json.loads(
            pathlib.Path(args.spec).read_text(encoding="utf-8")
        ).get("filler_projects", [])
        filler = build_filler(conn, DISTANCES["far"] + 6_000)

        spec = json.loads(pathlib.Path(args.spec).read_text(encoding="utf-8"))
        scenarios = []
        for sc in spec["scenarios"]:
            scenarios.append({
                "scenario_id": sc["scenario_id"],
                "seeded_items": [
                    seed(conn, item["entity_id"], item["item_id"], item["kind"])
                    for item in sc["seeded_items"]
                ],
                "filler_tasks": filler,
                "probes": [
                    {**probe, "after_tokens": DISTANCES[probe["distance"]]}
                    for probe in (
                        {k: v for k, v in p.items() if k != "distance"} | {"distance": p["distance"]}
                        for p in sc["probes"]
                    )
                ],
            })
    finally:
        conn.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Eval-v3 retention corpus — project-F. Seeds are verbatim project-F records;"
        " filler is real topically-adjacent notes from the PI's other CPS-security"
        " projects; the rka arm reads the live project-F project read-only. Same target"
        " probed near/mid/far so fade is a within-item comparison.\n"
    )
    with out.open("w", encoding="utf-8") as handle:
        handle.write(header)
        for scenario in scenarios:
            handle.write(json.dumps(scenario) + "\n")

    total = sum(len(t["canned_response"]) for t in filler)
    print(f"wrote {out}")
    print(f"  filler turns: {len(filler)}  (~{total // 4} tokens)")
    for scenario in scenarios:
        print(f"  {scenario['scenario_id']}: {len(scenario['seeded_items'])} seeds,"
              f" {len(scenario['probes'])} probes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
