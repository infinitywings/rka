#!/usr/bin/env python3
"""Pivot-currency benchmark: will an agent chase its own tail?

The question this answers is narrower and more operational than Track 2's.
Track 2 asks "given the right decision, can the graph reconstruct it and
surface its replacement?" (yes: 14/14). This asks the thing that actually
bites during research:

    A researcher remembers the OLD framing of a question and asks about it.
    Does the agent come back with the decision that is in force now, or with
    the superseded one -- and can it even tell the difference?

For every supersede chain in a project, the runner issues the *old* decision's
question as the query (the realistic "I remember we decided X" case, and the
case most favourable to the stale record), then measures on each surface:

  entry (`/api/search`)  - rank of the superseded vs the current decision,
                           and whether any staleness signal is present at all
  graph (`/api/graph/ego` from the top hit, depth 2)
                         - whether the current decision is reachable, and
                           whether its status is visible

Verdicts per pivot, on the entry surface:
  current_first  - the in-force decision outranks the superseded one
  stale_first    - the superseded one outranks it   <- tail-chasing risk
  stale_only     - only the superseded one came back <- worst case
  neither        - the pivot is invisible to search

`blind_stale_exposure` is the headline: the fraction of pivots where an agent
doing entry-retrieval alone would be handed the superseded decision with no
signal that it has been replaced.

Usage:
    python eval-harness/v3/currency/runner.py --db <snapshot> \
        --rka-url http://localhost:9712 --project prj_... \
        --out eval-harness/v3/currency/results/<name>.json
"""
from __future__ import annotations

import argparse, asyncio, json, sqlite3, sys
from pathlib import Path

import httpx

STATUS_KEYS = ("status", "state", "superseded_by", "stale")


def load_pivots(db: str, project_id: str) -> list[dict]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT d.id AS old_id, d.question AS old_q, d.superseded_by AS new_id,"
            "       n.question AS new_q, n.status AS new_status"
            "  FROM decisions d JOIN decisions n ON n.id = d.superseded_by"
            " WHERE d.project_id = ? AND d.superseded_by IS NOT NULL"
            " ORDER BY d.id",
            (project_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


async def run(pivots: list[dict], rka_url: str, project_id: str) -> dict:
    results = []
    async with httpx.AsyncClient(base_url=rka_url.rstrip("/"), timeout=90.0) as cx:
        for p in pivots:
            rec = {k: p[k] for k in ("old_id", "new_id")}
            rec["query"] = p["old_q"]
            params = {"project_id": project_id}

            # --- entry surface -------------------------------------------------
            try:
                r = await cx.post(
                    "/api/search", json={"query": p["old_q"], "limit": 20}, params=params
                )
                hits = r.json() if r.status_code < 400 else []
            except httpx.HTTPError as exc:
                rec["divergence"] = f"search: {exc!r}"
                hits = []
            ids = [h.get("entity_id") for h in hits]
            old_rank = ids.index(p["old_id"]) + 1 if p["old_id"] in ids else None
            new_rank = ids.index(p["new_id"]) + 1 if p["new_id"] in ids else None
            rec["entry"] = {"old_rank": old_rank, "new_rank": new_rank, "n": len(ids)}
            rec["entry"]["status_signal"] = bool(
                hits and any(k in hits[0] for k in STATUS_KEYS)
            )

            if old_rank and new_rank:
                verdict = "current_first" if new_rank < old_rank else "stale_first"
            elif old_rank:
                verdict = "stale_only"
            elif new_rank:
                verdict = "current_first"
            else:
                verdict = "neither"
            rec["entry"]["verdict"] = verdict

            # --- graph surface: expand from whatever the entry actually returned
            seed = ids[0] if ids else p["old_id"]
            rec["graph"] = {"seed": seed}
            try:
                g = await cx.get(f"/api/graph/ego/{seed}", params={**params, "depth": 2})
                nodes = g.json().get("nodes", []) if g.status_code < 400 else []
            except httpx.HTTPError as exc:
                rec["graph"]["divergence"] = f"ego: {exc!r}"
                nodes = []
            by_id = {n.get("id"): n for n in nodes}
            rec["graph"]["reaches_current"] = p["new_id"] in by_id
            old_node = by_id.get(p["old_id"])
            rec["graph"]["stale_marked"] = bool(
                old_node and str(old_node.get("status", "")).lower()
                in {"superseded", "abandoned", "retracted", "merged"}
            )
            results.append(rec)

    n = len(results)
    verdicts = [r["entry"]["verdict"] for r in results]
    blind = [
        r for r in results
        if r["entry"]["verdict"] in {"stale_first", "stale_only"}
        and not r["entry"]["status_signal"]
    ]
    return {
        "n_pivots": n,
        "entry": {
            "verdicts": {v: verdicts.count(v) for v in sorted(set(verdicts))},
            "current_first_rate": round(verdicts.count("current_first") / n, 4) if n else None,
            "any_status_signal": any(r["entry"]["status_signal"] for r in results),
            "blind_stale_exposure": round(len(blind) / n, 4) if n else None,
        },
        "graph": {
            "reaches_current_rate": round(
                sum(r["graph"]["reaches_current"] for r in results) / n, 4) if n else None,
            "stale_marked_rate": round(
                sum(r["graph"]["stale_marked"] for r in results) / n, 4) if n else None,
        },
        "per_pivot": results,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--rka-url", default="http://localhost:9712")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    pivots = load_pivots(a.db, a.project)
    if not pivots:
        print("no supersede chains in this project", file=sys.stderr)
        return 1
    out = asyncio.run(run(pivots, a.rka_url, a.project))
    out["meta"] = {"project": a.project, "rka_url": a.rka_url, "db": Path(a.db).name}
    p = Path(a.out); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    e, g = out["entry"], out["graph"]
    print(f"pivots={out['n_pivots']}")
    print(f"  entry verdicts:        {e['verdicts']}")
    print(f"  current_first_rate:    {e['current_first_rate']}")
    print(f"  any status signal:     {e['any_status_signal']}")
    print(f"  BLIND STALE EXPOSURE:  {e['blind_stale_exposure']}")
    print(f"  graph reaches current: {g['reaches_current_rate']}")
    print(f"  graph marks stale:     {g['stale_marked_rate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
