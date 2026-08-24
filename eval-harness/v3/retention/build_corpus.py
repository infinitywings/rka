#!/usr/bin/env python3
"""Build the CAREER retention corpus from a real RKA snapshot.

Design choices worth stating, because they decide what the numbers mean:

* **Seeds are real CAREER records**, quoted verbatim from the snapshot with
  their entity ids and dates, so all three arms see identical material and
  can cite it.
* **The same target is probed at three distances** (near / mid / far). Fade is
  then a within-item comparison — pass near, fail far — rather than a
  comparison across items of differing difficulty.
* **Filler is real, topically adjacent text** drawn from the PI's other
  CPS-security projects (detectability, CPSEval, Invarllm, delaysteer) plus
  CAREER's own journal. Synthetic filler would let the lexical RAG baseline
  win too easily.
* **The `rka` arm reads the live CAREER project itself, read-only** — not a
  disposable copy. That is stricter than the schema's disposable-project
  recipe: retrieval must find the seeds among ~270 competing real entities
  instead of in an otherwise-empty index, and nothing is written to the PI's
  knowledge base. The baselines are handed the seeds outright, so any
  remaining bias favours the baselines, not RKA.

Usage:
    python eval-harness/v3/retention/build_corpus.py \
        --db <snapshot.db> --out eval-harness/v3/retention/scenarios.CAREER.jsonl
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

CAREER = "prj_01KWFRG2TZGHV1A8G4MXVDFPJ5"
# topically adjacent CPS-security projects used only as filler
FILLER_PROJECTS = [
    CAREER,
    "prj_01KS8EQ8J1J0EZPF5T1Z65W7RC",  # detectability
    "prj_01KPVB7NHJ0N33C024TD0E6CZ6",  # CPSEval
    "prj_01KN51HD73DSY9ZR9C56JYRNYZ",  # Invarllm
    "prj_01KZVF35ESDGKZKTG1D1J59TCF",  # delaysteer
]

# Distance targets. The completer runs on a separate LM Studio host
# (qwen3.8-27b-mlx, ~227 tok/s measured on a 13k-token prefill), so this
# machine only serves embeddings and a 35k-token probe prefills in ~150 s --
# comfortably inside one timeout. Report bucket edges, not nominal targets.
NEAR, MID, FAR = 800, 8_000, 35_000


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
    args = parser.parse_args(argv)

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        filler = build_filler(conn, FAR + 6_000)

        s1 = {
            "scenario_id": "career-directive-and-evidence-retention",
            "seeded_items": [
                seed(conn, "jrn_01KWFS3017NBZQM5BEXDQ99MSD", "dir-ot", "directive"),
                seed(conn, "jrn_01KXE4445AWE1PAF3PBKVYE4X1", "dir-prelim", "directive"),
                seed(conn, "clm_01KXNVS3AQKVBSC4E9KGA9GQHT", "ev-budget", "evidence"),
            ],
            "filler_tasks": filler,
            "probes": [
                {
                    "probe_id": "budget-near",
                    "target_item": "ev-budget",
                    "after_tokens": NEAR,
                    "prompt": "What is the final active CAREER budget total? State the figure"
                    " exactly as recorded and cite the source entity id.",
                    "expect": {
                        "must_include": ["711,271"],
                        "expected_citations": ["clm_01KXNVS3AQKVBSC4E9KGA9GQHT"],
                    },
                },
                {
                    "probe_id": "prelim-mid",
                    "target_item": "dir-prelim",
                    "after_tokens": MID,
                    "prompt": "Write one sentence for the proposal that draws on the paper"
                    " 'What the Detector Can See', labelling its status correctly.",
                    "expect": {
                        "must_include": ["preliminary"],
                        "must_not_include": ["peer-reviewed", "externally validated"],
                    },
                },
                {
                    "probe_id": "budget-far",
                    "target_item": "ev-budget",
                    "after_tokens": FAR,
                    "prompt": "What is the final active CAREER budget total? State the figure"
                    " exactly as recorded and cite the source entity id.",
                    "expect": {
                        "must_include": ["711,271"],
                        "expected_citations": ["clm_01KXNVS3AQKVBSC4E9KGA9GQHT"],
                    },
                },
            ],
        }

        s2 = {
            "scenario_id": "career-pivot-currency",
            "seeded_items": [
                seed(conn, "dec_01KWFSJFJS8NHTSVV24EK7H9Q2", "metric-old", "evidence"),
                seed(conn, "dec_01KWFSPDGZF3VG6JAZV72E4FCE", "papers-old", "evidence"),
                seed(conn, "dec_01KX6CZ30ZJWC11EST90ZWWE7Z", "metric-new", "directive"),
                seed(conn, "dec_01KX6CZZC3JGB44RW95VD0JS2J", "papers-new", "directive"),
            ],
            "filler_tasks": filler,
            "probes": [
                {
                    "probe_id": "metric-near",
                    "target_item": "metric-new",
                    "after_tokens": NEAR,
                    "prompt": "What is the current primary measurement object for adaptive CPS"
                    " defense evaluation? Answer with the decision that is in force now.",
                    "expect": {
                        "must_include": ["capability-conditioned"],
                        "must_not_include": ["physical-grounding premium"],
                    },
                },
                {
                    "probe_id": "papers-mid",
                    "target_item": "papers-new",
                    "after_tokens": MID,
                    "prompt": "How should LLM-GridEval be positioned in the proposal, per the"
                    " decision currently in force?",
                    "expect": {
                        "must_include": ["workflow-feasibility"],
                        "must_not_include": ["proof-of-concept"],
                    },
                },
                {
                    "probe_id": "metric-far",
                    "target_item": "metric-new",
                    "after_tokens": FAR,
                    "prompt": "What is the current primary measurement object for adaptive CPS"
                    " defense evaluation? Answer with the decision that is in force now.",
                    "expect": {
                        "must_include": ["capability-conditioned"],
                        "must_not_include": ["physical-grounding premium"],
                    },
                },
            ],
        }
    finally:
        conn.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Eval-v3 retention corpus — CAREER. Seeds are verbatim CAREER records;"
        " filler is real topically-adjacent notes from the PI's other CPS-security"
        " projects; the rka arm reads the live CAREER project read-only. Same target"
        " probed near/mid/far so fade is a within-item comparison.\n"
    )
    with out.open("w", encoding="utf-8") as handle:
        handle.write(header)
        for scenario in (s1, s2):
            handle.write(json.dumps(scenario) + "\n")

    total = sum(len(t["canned_response"]) for t in filler)
    print(f"wrote {out}")
    print(f"  filler turns: {len(filler)}  (~{total // 4} tokens)")
    for scenario in (s1, s2):
        print(f"  {scenario['scenario_id']}: {len(scenario['seeded_items'])} seeds,"
              f" {len(scenario['probes'])} probes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
