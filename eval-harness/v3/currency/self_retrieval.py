#!/usr/bin/env python3
"""Self-retrieval diagnostic: can a decision be found by its own question?

The weakest possible retrieval test. The query is the decision's *verbatim*
question text, so any index that works at all should rank it first. Failure
here is unambiguous: it is not a paraphrase problem, not an embedding-model
problem, and not an LLM problem.

Reports per project: hit rate in top-k, MRR, and the entity-type composition
of the result sets (to show what outranks decisions when they lose). Splits
by whether the decision itself carries an embedding, which turns the store's
partial index into a natural experiment.

Read-only. No LLM.
"""
from __future__ import annotations
import argparse, asyncio, json, sqlite3, sys
from collections import Counter
from pathlib import Path
import httpx


# entity -> (table, text column used as the self-query, vec rowid table, search type)
ENTITY_SPEC = {
    "decision":   ("decisions",  "question",  "vec_decisions_rowids",   "decision"),
    "journal":    ("journal",    "content",   "vec_journal_rowids",     "journal"),
    "claim":      ("claims",     "content",   "vec_claims_rowids",      "claim"),
    "literature": ("literature", "title",     "vec_literature_rowids",  "literature"),
    "mission":    ("missions",   "objective", "vec_missions_rowids",    "mission"),
}


def load(db: str, entity: str = "decision"):
    table, col, vec, _ = ENTITY_SPEC[entity]
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True); conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"SELECT d.id, d.project_id, d.{col} AS question,"
            f"  EXISTS(SELECT 1 FROM {vec} v WHERE v.id = d.id) AS embedded"
            f" FROM {table} d WHERE d.{col} IS NOT NULL AND LENGTH(d.{col}) > 10"
        ).fetchall()
        names = {r["id"]: r["name"] for r in conn.execute("SELECT id,name FROM projects")}
    finally:
        conn.close()
    return [dict(r) for r in rows], names


async def main(a) -> int:
    rows, names = load(a.db, a.entity)
    if a.project:
        rows = [r for r in rows if r["project_id"] == a.project]
    if a.sample:
        step = max(1, len(rows) // a.sample)
        rows = rows[::step][: a.sample]
    per = {}
    comp = Counter()
    async with httpx.AsyncClient(base_url=a.rka_url.rstrip("/"), timeout=90.0) as cx:
        for i, d in enumerate(rows, 1):
            try:
                qtext = d["question"]
                if a.truncate_words:
                    qtext = " ".join(qtext.split()[: a.truncate_words])
                body = {"query": qtext[:400], "limit": a.limit,
                        "keyword_weight": a.keyword_weight,
                        "semantic_weight": a.semantic_weight}
                if a.types:
                    body["entity_types"] = a.types.split(",")
                r = await cx.post("/api/search", json=body,
                                  params={"project_id": d["project_id"]})
                hits = r.json() if r.status_code < 400 else []
            except httpx.HTTPError:
                hits = []
            ids = [h.get("entity_id") for h in hits]
            comp.update(h.get("entity_type") for h in hits)
            rank = ids.index(d["id"]) + 1 if d["id"] in ids else None
            key = (d["project_id"], bool(d["embedded"]))
            s = per.setdefault(key, {"n": 0, "hit": 0, "rr": 0.0, "ranks": []})
            s["n"] += 1
            if rank:
                s["hit"] += 1; s["rr"] += 1 / rank; s["ranks"].append(rank)
            if i % 50 == 0:
                print(f"  ...{i}/{len(rows)}", file=sys.stderr, flush=True)

    out = {"limit": a.limit, "result_type_composition": dict(comp.most_common()), "by_project": {}}
    print(f"\n{'project':24}{'emb?':>6}{'n':>5}{'hit@'+str(a.limit):>8}{'rate':>8}{'MRR':>8}  median_rank")
    for (pid, emb), s in sorted(per.items(), key=lambda kv: (names.get(kv[0][0], ''), kv[0][1])):
        rate = s["hit"] / s["n"]; mrr = s["rr"] / s["n"]
        med = sorted(s["ranks"])[len(s["ranks"]) // 2] if s["ranks"] else None
        print(f"{names.get(pid,pid)[:23]:24}{'yes' if emb else 'NO':>6}{s['n']:>5}{s['hit']:>8}{rate:>7.1%}{mrr:>8.3f}  {med}")
        out["by_project"].setdefault(names.get(pid, pid), {})["embedded" if emb else "not_embedded"] = {
            "n": s["n"], "hit": s["hit"], "hit_rate": round(rate, 4),
            "mrr": round(mrr, 4), "median_rank": med}
    tot_n = sum(s["n"] for s in per.values()); tot_h = sum(s["hit"] for s in per.values())
    tot_rr = sum(s["rr"] for s in per.values())
    emb_n = sum(s["n"] for k, s in per.items() if k[1]); emb_h = sum(s["hit"] for k, s in per.items() if k[1])
    non_n = tot_n - emb_n; non_h = tot_h - emb_h
    print(f"\n  全部       n={tot_n} hit={tot_h} ({tot_h/tot_n:.1%}) MRR={tot_rr/tot_n:.3f}")
    if emb_n: print(f"  有向量的   n={emb_n} hit={emb_h} ({emb_h/emb_n:.1%})")
    if non_n: print(f"  无向量的   n={non_n} hit={non_h} ({non_h/non_n:.1%})")
    print(f"\n  结果集类型构成: {dict(comp.most_common())}")
    out["overall"] = {"n": tot_n, "hit": tot_h, "hit_rate": round(tot_h/tot_n, 4),
                      "mrr": round(tot_rr/tot_n, 4),
                      "embedded": {"n": emb_n, "hit": emb_h},
                      "not_embedded": {"n": non_n, "hit": non_h}}
    if a.out:
        p = Path(a.out); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True); ap.add_argument("--rka-url", default="http://localhost:9712")
    ap.add_argument("--project"); ap.add_argument("--limit", type=int, default=20); ap.add_argument("--out")
    ap.add_argument("--keyword-weight", type=float, default=0.3)
    ap.add_argument("--semantic-weight", type=float, default=0.7)
    ap.add_argument("--types", help="comma-separated entity_types filter")
    ap.add_argument("--sample", type=int, help="evaluate every Nth row (stratified by id order)")
    ap.add_argument("--entity", default="decision", choices=list(ENTITY_SPEC))
    ap.add_argument("--truncate-words", type=int, help="use only the first N words of the self-text as the query")
    raise SystemExit(asyncio.run(main(ap.parse_args())))
