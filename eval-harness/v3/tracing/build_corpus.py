#!/usr/bin/env python3
"""Derive tracing scenarios mechanically from an RKA snapshot.

The `expected_trace` of each scenario is *not* hand-picked: it is derived
from the decision's own declared provenance plus a bounded set of typed
graph relations, so the ground truth is reproducible and auditable rather
than a curated wish-list. `nl_query` is left absent here — paraphrases are
added by hand (a researcher's own words, not the decision's verbatim
question) and ratified by the PI before numbers are quoted.

Derivation rule (per anchor decision D):

| Source                                        | relation               | importance |
|-----------------------------------------------|------------------------|------------|
| D.related_journal, entry is PI/directive       | directive              | critical   |
| D.related_journal, other entries               | evidence               | critical   |
| D.parent_id                                    | parent_decision        | critical   |
| decision superseding D (D.superseded_by)       | superseded_alternative | critical   |
| decision D supersedes                          | superseded_alternative | useful     |
| D.related_literature + `informed_by` edges     | literature             | useful     |
| D.related_missions + `motivated` edges         | mission                | useful     |
| clusters via `answers` / `justified_by`        | evidence               | useful     |
| claims sourced from D.related_journal (2 hops) | evidence               | useful     |

The last row is the interesting probe: reaching the *evidence extracted
from* the entries that justify a decision needs two hops, so it separates
"the endpoint echoes its direct edges" from "back-tracing works".

Usage:
    python eval-harness/v3/tracing/build_corpus.py \
        --db <snapshot.db> --project prj_... --out scenarios.draft.jsonl
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# per-relation caps keep a scenario a trace, not a project dump
CAPS = {"journal": 4, "literature": 3, "mission": 2, "cluster": 3, "claim": 4}

DIRECTIVE_TYPES = {"pi_instruction", "directive"}
DIRECTIVE_SOURCES = {"pi"}


def json_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in parsed] if isinstance(parsed, list) else []


def slugify(text: str, limit: int = 48) -> str:
    keep = [ch.lower() if ch.isalnum() else "-" for ch in text]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:limit].strip("-")


def build(conn: sqlite3.Connection, project_id: str, limit: int) -> list[dict]:
    conn.row_factory = sqlite3.Row

    journals = {
        row["id"]: row
        for row in conn.execute(
            "SELECT id, type, source FROM journal WHERE project_id = ?", (project_id,)
        )
    }
    # claims grouped by the journal entry they were extracted from (2-hop probe)
    claims_by_entry: dict[str, list[str]] = {}
    for row in conn.execute(
        "SELECT id, source_entry_id FROM claims WHERE project_id = ?"
        " AND source_entry_id IS NOT NULL",
        (project_id,),
    ):
        claims_by_entry.setdefault(row["source_entry_id"], []).append(row["id"])

    # typed edges touching decisions
    edges: dict[str, dict[str, set[str]]] = {}
    for row in conn.execute(
        "SELECT source_type, source_id, link_type, target_type, target_id"
        " FROM entity_links WHERE project_id = ?"
        " AND (source_type = 'decision' OR target_type = 'decision')",
        (project_id,),
    ):
        if row["source_type"] == "decision":
            edges.setdefault(row["source_id"], {}).setdefault(
                f"out:{row['link_type']}:{row['target_type']}", set()
            ).add(row["target_id"])
        if row["target_type"] == "decision":
            edges.setdefault(row["target_id"], {}).setdefault(
                f"in:{row['link_type']}:{row['source_type']}", set()
            ).add(row["source_id"])

    decisions = list(
        conn.execute(
            "SELECT id, question, chosen, rationale, status, parent_id,"
            " superseded_by, phase, kind, related_journal, related_literature,"
            " related_missions"
            " FROM decisions WHERE project_id = ? AND rationale IS NOT NULL",
            (project_id,),
        )
    )
    decision_ids = {
        row["id"]
        for row in conn.execute("SELECT id FROM decisions WHERE project_id = ?", (project_id,))
    }

    def project_ids(table: str) -> set[str]:
        try:
            return {
                row["id"]
                for row in conn.execute(
                    f"SELECT id FROM {table} WHERE project_id = ?", (project_id,)
                )
            }
        except sqlite3.OperationalError as exc:
            # Older snapshots may legitimately predate an optional entity
            # table.  Do not mask malformed schemas, bad columns, locking, or
            # other operational failures as an empty ground-truth relation.
            if "no such table:" in str(exc).casefold():
                return set()
            raise

    valid_ids = {
        "journal": set(journals),
        "decision": decision_ids,
        "literature": project_ids("literature"),
        "mission": project_ids("missions"),
        "cluster": project_ids("evidence_clusters"),
        "claim": {claim for claims in claims_by_entry.values() for claim in claims},
    }
    supersedes_of: dict[str, str] = {
        d["superseded_by"]: d["id"] for d in decisions if d["superseded_by"] in decision_ids
    }

    scenarios: list[dict] = []
    for dec in decisions:
        trace: list[dict] = []
        seen: set[str] = set()

        def add(entity_id: str, entity_type: str, relation: str, importance: str) -> None:
            if not entity_id or entity_id in seen or entity_id == dec["id"]:
                return
            if entity_id not in valid_ids.get(entity_type, set()):
                return
            seen.add(entity_id)
            trace.append(
                {
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "relation": relation,
                    "importance": importance,
                }
            )

        dec_edges = edges.get(dec["id"], {})

        # --- critical: declared justification -------------------------------
        declared_journal = json_list(dec["related_journal"])[: CAPS["journal"]]
        for jid in declared_journal:
            meta = journals.get(jid)
            relation = "evidence"
            if meta is not None and (
                meta["type"] in DIRECTIVE_TYPES or meta["source"] in DIRECTIVE_SOURCES
            ):
                relation = "directive"
            add(jid, "journal", relation, "critical")

        if dec["parent_id"] and dec["parent_id"] in decision_ids:
            add(dec["parent_id"], "decision", "parent_decision", "critical")

        pivot = None
        if dec["superseded_by"] in decision_ids:
            add(dec["superseded_by"], "decision", "superseded_alternative", "critical")
            pivot = {
                "superseded_decision_id": dec["id"],
                "superseding_decision_id": dec["superseded_by"],
            }
        predecessor = supersedes_of.get(dec["id"])
        if predecessor:
            add(predecessor, "decision", "superseded_alternative", "useful")
            if pivot is None:
                pivot = {
                    "superseded_decision_id": predecessor,
                    "superseding_decision_id": dec["id"],
                }

        # --- useful: literature ---------------------------------------------
        lits = list(json_list(dec["related_literature"]))
        lits += sorted(dec_edges.get("in:informed_by:literature", set()))
        for lid in list(dict.fromkeys(lits))[: CAPS["literature"]]:
            add(lid, "literature", "literature", "useful")

        # --- useful: missions -------------------------------------------------
        miss = list(json_list(dec["related_missions"]))
        miss += sorted(dec_edges.get("out:motivated:mission", set()))
        for mid in list(dict.fromkeys(miss))[: CAPS["mission"]]:
            add(mid, "mission", "mission", "useful")

        # --- useful: evidence clusters ---------------------------------------
        clusters = sorted(dec_edges.get("in:answers:cluster", set())) + sorted(
            dec_edges.get("out:justified_by:cluster", set())
        )
        for cid in list(dict.fromkeys(clusters))[: CAPS["cluster"]]:
            add(cid, "cluster", "evidence", "useful")

        # --- useful: 2-hop claims extracted from the justifying entries -------
        two_hop: list[str] = []
        for jid in declared_journal:
            two_hop.extend(claims_by_entry.get(jid, []))
        for clm in list(dict.fromkeys(two_hop))[: CAPS["claim"]]:
            add(clm, "claim", "evidence", "useful")

        criticals = [e for e in trace if e["importance"] == "critical"]
        if len(trace) < 3 or not criticals:
            continue

        scenario = {
            "scenario_id": f"{slugify(dec['question'] or dec['id'])}-{dec['id'][-6:].lower()}",
            "anchor_decision": dec["id"],
            "expected_trace": trace,
        }
        if pivot:
            scenario["pivot"] = pivot
        scenario["_meta"] = {
            "question": dec["question"],
            "chosen": dec["chosen"],
            "status": dec["status"],
            "phase": dec["phase"],
            "kind": dec["kind"],
            "rationale_len": len(dec["rationale"] or ""),
            "n_critical": len(criticals),
            "relations": sorted({e["relation"] for e in trace}),
        }
        scenarios.append(scenario)

    # richest first: pivots, then relation diversity, then rationale depth
    scenarios.sort(
        key=lambda s: (
            "pivot" in s,
            len(s["_meta"]["relations"]),
            s["_meta"]["rationale_len"],
        ),
        reverse=True,
    )
    return scenarios[:limit] if limit else scenarios


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        scenarios = build(conn, args.project, args.limit)
    finally:
        conn.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for scenario in scenarios:
            handle.write(json.dumps(scenario) + "\n")
    print(f"{len(scenarios)} scenarios -> {out}", file=sys.stderr)
    for s in scenarios:
        m = s["_meta"]
        print(
            f"  {s['anchor_decision']} pivot={'Y' if 'pivot' in s else 'n'}"
            f" crit={m['n_critical']} n={len(s['expected_trace'])}"
            f" rel={','.join(m['relations'])}"
        )
        print(f"      Q: {(m['question'] or '')[:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
