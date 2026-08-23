#!/usr/bin/env python3
"""Track-1 self-study metrics extractor.

Computes the three metrics promised in the RKA paper's §7.1 — provenance
coverage, research-debt trajectory, and mission-cycle metrics — plus the
M-era pipeline-stage flow, from a **snapshot copy** of an RKA SQLite
database. Read-only by construction (the database is opened with
``mode=ro``); never point it at the live Docker-volume database.

Design notes:

- stdlib only (sqlite3, json, argparse) so it runs anywhere without the
  rka package installed.
- Every metric section is guarded by table/column introspection, so the
  extractor degrades gracefully on older snapshots that predate a
  migration: a missing table yields ``{"available": false, ...}`` for
  that section rather than an error.
- "Provenance coverage" operationalizes the paper's definition — the
  fraction of claims with a complete chain back to a researcher-authored
  or cited-literature source — as: the claim's source journal entry is
  researcher-authored (source ``pi`` or a directive/pi_instruction
  type), OR the claim reaches a ``literature`` entity or a
  researcher-authored journal/decision through its source entry's
  ``related_literature`` or a bounded (depth ≤ 3) walk of
  ``entity_links``, OR the claim was promoted from an interpretation
  candidate whose source is literature. ``coverage_strict`` additionally
  requires the claim not be flagged stale.
- Time-to-coverage is approximated as the earliest ``created_at`` among
  the entity links that establish coverage, minus the claim's
  ``created_at``; claims covered directly through their source entry are
  covered at birth (0 days). This is a current-state reconstruction, not
  an event replay — see the README's threats-to-validity note.

Exit codes: 0 success, 2 usage/input error.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

TOOL_VERSION = "v3.self_study.1"

RESEARCHER_JOURNAL_SOURCES = {"pi"}
RESEARCHER_JOURNAL_TYPES = {"pi_instruction", "directive"}
BFS_DEPTH_LIMIT = 3


# ---------------------------------------------------------------- helpers


def open_readonly(path: str | Path) -> sqlite3.Connection:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"database snapshot not found: {source}")
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not table_exists(conn, table):
        return False
    return any(
        row["name"] == column
        for row in conn.execute(f"PRAGMA table_info({table})")
    )


def parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def month_of(value: Any) -> str | None:
    if isinstance(value, str) and len(value) >= 7:
        return value[:7]
    return None


def json_list(value: Any) -> list:
    if not value or not isinstance(value, str):
        return []
    try:
        loaded = json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return []
    return loaded if isinstance(loaded, list) else []


def summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)

    def pct(fraction: float) -> float:
        index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
        return ordered[index]

    return {
        "count": len(ordered),
        "mean": round(mean(ordered), 2),
        "median": round(median(ordered), 2),
        "p25": round(pct(0.25), 2),
        "p75": round(pct(0.75), 2),
        "min": round(ordered[0], 2),
        "max": round(ordered[-1], 2),
    }


def unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def project_clause(
    conn: sqlite3.Connection, table: str, project_id: str | None
) -> tuple[str, tuple]:
    """WHERE fragment restricting to a project when both filter and column exist."""
    if project_id and column_exists(conn, table, "project_id"):
        return f" WHERE {table}.project_id = ?", (project_id,)
    return "", ()


# ------------------------------------------------- provenance foundations


def load_link_graph(
    conn: sqlite3.Connection,
) -> dict[str, list[tuple[str, str, str | None]]]:
    """Undirected adjacency over entity_links: id -> [(other_id, other_type, link_created_at)]."""
    adjacency: dict[str, list[tuple[str, str, str | None]]] = defaultdict(list)
    if not table_exists(conn, "entity_links"):
        return adjacency
    for row in conn.execute(
        "SELECT source_type, source_id, target_type, target_id, created_at"
        " FROM entity_links"
    ):
        adjacency[row["source_id"]].append(
            (row["target_id"], row["target_type"], row["created_at"])
        )
        adjacency[row["target_id"]].append(
            (row["source_id"], row["source_type"], row["created_at"])
        )
    return adjacency


def load_researcher_anchors(conn: sqlite3.Connection) -> tuple[set[str], set[str]]:
    """IDs of researcher-authored journal entries and PI-decided decisions."""
    researcher_journals: set[str] = set()
    if table_exists(conn, "journal"):
        has_type = column_exists(conn, "journal", "type")
        for row in conn.execute("SELECT id, source%s FROM journal" % (", type" if has_type else "",)):
            if row["source"] in RESEARCHER_JOURNAL_SOURCES:
                researcher_journals.add(row["id"])
            elif has_type and row["type"] in RESEARCHER_JOURNAL_TYPES:
                researcher_journals.add(row["id"])
    pi_decisions: set[str] = set()
    if table_exists(conn, "decisions"):
        for row in conn.execute(
            "SELECT id FROM decisions WHERE decided_by = 'pi'"
        ):
            pi_decisions.add(row["id"])
    return researcher_journals, pi_decisions


def walk_for_coverage(
    start_ids: list[str],
    adjacency: dict[str, list[tuple[str, str, str | None]]],
    researcher_journals: set[str],
    pi_decisions: set[str],
) -> tuple[str | None, str | None]:
    """Bounded BFS. Returns (coverage_kind, earliest covering link timestamp)."""
    seen = set(start_ids)
    queue: deque[tuple[str, int, str | None]] = deque(
        (node, 0, None) for node in start_ids
    )
    best: tuple[str, str | None] | None = None
    while queue:
        node, depth, first_link_ts = queue.popleft()
        if depth >= BFS_DEPTH_LIMIT:
            continue
        for other_id, other_type, link_ts in adjacency.get(node, []):
            if other_id in seen:
                continue
            seen.add(other_id)
            path_ts = first_link_ts or link_ts
            kind: str | None = None
            if other_type == "literature" or other_id.startswith("lit_"):
                kind = "literature_link"
            elif other_id in researcher_journals:
                kind = "researcher_journal_link"
            elif other_id in pi_decisions:
                kind = "pi_decision_link"
            if kind is not None and best is None:
                best = (kind, path_ts)
            queue.append((other_id, depth + 1, path_ts))
    if best is None:
        return None, None
    return best


def classify_claims(
    conn: sqlite3.Connection, project_id: str | None
) -> list[dict[str, Any]]:
    """Per-claim coverage classification shared by the coverage + trajectory sections."""
    where, params = project_clause(conn, "claims", project_id)
    claims = conn.execute(
        "SELECT id, source_entry_id, claim_type, stale, verified, created_at"
        f" FROM claims{where}",
        params,
    ).fetchall()

    journal_meta: dict[str, sqlite3.Row] = {}
    if table_exists(conn, "journal"):
        journal_meta = {
            row["id"]: row
            for row in conn.execute(
                "SELECT id, source, type, related_literature FROM journal"
            )
        }

    promoted_from_literature: set[str] = set()
    if table_exists(conn, "interpretation_candidates"):
        for row in conn.execute(
            "SELECT source_type, source_id, disposition_target_id"
            " FROM interpretation_candidates"
            " WHERE disposition = 'promoted' AND disposition_target_id IS NOT NULL"
        ):
            if row["source_type"] == "literature":
                promoted_from_literature.add(row["disposition_target_id"])

    adjacency = load_link_graph(conn)
    researcher_journals, pi_decisions = load_researcher_anchors(conn)

    classified: list[dict[str, Any]] = []
    for claim in claims:
        source_row = journal_meta.get(claim["source_entry_id"])
        via: str | None = None
        coverage_ts: str | None = claim["created_at"]

        if source_row is not None and (
            source_row["source"] in RESEARCHER_JOURNAL_SOURCES
            or source_row["type"] in RESEARCHER_JOURNAL_TYPES
        ):
            via = "researcher_source_entry"
        elif source_row is not None and json_list(source_row["related_literature"]):
            via = "source_entry_cites_literature"
        elif claim["id"] in promoted_from_literature:
            via = "candidate_from_literature"
        else:
            start = [claim["id"]]
            if claim["source_entry_id"]:
                start.append(claim["source_entry_id"])
            kind, link_ts = walk_for_coverage(
                start, adjacency, researcher_journals, pi_decisions
            )
            if kind is not None:
                via = kind
                coverage_ts = link_ts or claim["created_at"]

        classified.append(
            {
                "id": claim["id"],
                "claim_type": claim["claim_type"],
                "created_at": claim["created_at"],
                "month": month_of(claim["created_at"]),
                "stale": bool(claim["stale"]),
                "verified": bool(claim["verified"]),
                "covered": via is not None,
                "via": via,
                "coverage_ts": coverage_ts if via is not None else None,
            }
        )
    return classified


# ---------------------------------------------------------------- sections


def provenance_coverage(classified: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(classified)
    if total == 0:
        return {"available": True, "n_claims": 0}
    covered = [c for c in classified if c["covered"]]
    strict = [c for c in covered if not c["stale"]]
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"claims": 0, "covered": 0})
    for c in classified:
        by_type[c["claim_type"]]["claims"] += 1
        if c["covered"]:
            by_type[c["claim_type"]]["covered"] += 1
    via_counts: dict[str, int] = defaultdict(int)
    for c in covered:
        via_counts[c["via"]] += 1
    return {
        "available": True,
        "n_claims": total,
        "covered": len(covered),
        "coverage_pct": round(100.0 * len(covered) / total, 1),
        "coverage_strict": len(strict),
        "coverage_strict_pct": round(100.0 * len(strict) / total, 1),
        "stale_claims": sum(1 for c in classified if c["stale"]),
        "verified_claims": sum(1 for c in classified if c["verified"]),
        "by_claim_type": dict(sorted(by_type.items())),
        "covered_via": dict(sorted(via_counts.items())),
    }


def research_debt_trajectory(classified: list[dict[str, Any]]) -> dict[str, Any]:
    if not classified:
        return {"available": True, "months": {}}
    months: dict[str, dict[str, int]] = defaultdict(
        lambda: {"created": 0, "covered_now": 0, "uncovered_now": 0, "stale": 0}
    )
    time_to_coverage_days: list[float] = []
    for c in classified:
        key = c["month"] or "unknown"
        months[key]["created"] += 1
        months[key]["covered_now" if c["covered"] else "uncovered_now"] += 1
        if c["stale"]:
            months[key]["stale"] += 1
        created = parse_ts(c["created_at"])
        covered_at = parse_ts(c["coverage_ts"])
        if c["covered"] and created and covered_at:
            time_to_coverage_days.append(
                max(0.0, (covered_at - created).total_seconds() / 86400.0)
            )
    ordered = dict(sorted(months.items()))
    running_debt = 0
    for stats in ordered.values():
        running_debt += stats["uncovered_now"]
        stats["cumulative_uncovered"] = running_debt
    return {
        "available": True,
        "months": ordered,
        "time_to_coverage_days": summarize(time_to_coverage_days),
        "note": (
            "covered_now reflects the snapshot's current link state, not the"
            " claim's state at creation; time_to_coverage approximates arrival"
            " via covering-link created_at."
        ),
    }


def mission_cycle(conn: sqlite3.Connection, project_id: str | None) -> dict[str, Any]:
    if not table_exists(conn, "missions"):
        return unavailable("missions table missing")
    where, params = project_clause(conn, "missions", project_id)
    missions = conn.execute(
        "SELECT id, status, report, created_at, completed_at"
        f" FROM missions{where}",
        params,
    ).fetchall()
    status_counts: dict[str, int] = defaultdict(int)
    durations_h: list[float] = []
    completed_ids: dict[str, datetime] = {}
    for m in missions:
        status_counts[m["status"]] += 1
        created, completed = parse_ts(m["created_at"]), parse_ts(m["completed_at"])
        if created and completed:
            durations_h.append((completed - created).total_seconds() / 3600.0)
            completed_ids[m["id"]] = completed

    checkpoint_counts: dict[str, int] = defaultdict(int)
    resolution_h: list[float] = []
    open_checkpoints = 0
    if table_exists(conn, "checkpoints"):
        for row in conn.execute(
            "SELECT mission_id, status, created_at, resolved_at FROM checkpoints"
        ):
            if row["mission_id"]:
                checkpoint_counts[row["mission_id"]] += 1
            if row["status"] == "open":
                open_checkpoints += 1
            created, resolved = parse_ts(row["created_at"]), parse_ts(row["resolved_at"])
            if created and resolved:
                resolution_h.append((resolved - created).total_seconds() / 3600.0)

    backbrief_h: list[float] = []
    reported = 0
    if table_exists(conn, "journal") and column_exists(conn, "journal", "related_mission"):
        first_entry_after: dict[str, datetime] = {}
        for row in conn.execute(
            "SELECT related_mission, created_at FROM journal"
            " WHERE related_mission IS NOT NULL"
        ):
            completed = completed_ids.get(row["related_mission"])
            entry_ts = parse_ts(row["created_at"])
            if completed and entry_ts and entry_ts >= completed:
                prior = first_entry_after.get(row["related_mission"])
                if prior is None or entry_ts < prior:
                    first_entry_after[row["related_mission"]] = entry_ts
        backbrief_h = [
            (ts - completed_ids[mid]).total_seconds() / 3600.0
            for mid, ts in first_entry_after.items()
        ]
    reported = sum(1 for m in missions if m["report"])

    per_mission = [checkpoint_counts.get(m["id"], 0) for m in missions]
    return {
        "available": True,
        "n_missions": len(missions),
        "status": dict(sorted(status_counts.items())),
        "duration_hours": summarize(durations_h),
        "checkpoints_per_mission": summarize([float(v) for v in per_mission]),
        "open_checkpoints": open_checkpoints,
        "checkpoint_resolution_hours": summarize(resolution_h),
        "missions_with_report": reported,
        "completion_to_first_journal_hours": summarize(backbrief_h),
    }


def pipeline_flow(conn: sqlite3.Connection, project_id: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {"available": True}

    if table_exists(conn, "interpretation_candidates"):
        where, params = project_clause(conn, "interpretation_candidates", project_id)
        by_status: dict[str, int] = defaultdict(int)
        by_disposition: dict[str, int] = defaultdict(int)
        for row in conn.execute(
            "SELECT review_status, disposition"
            f" FROM interpretation_candidates{where}",
            params,
        ):
            by_status[row["review_status"]] += 1
            if row["disposition"]:
                by_disposition[row["disposition"]] += 1
        result["interpretation_candidates"] = {
            "by_review_status": dict(sorted(by_status.items())),
            "by_disposition": dict(sorted(by_disposition.items())),
        }
    else:
        result["interpretation_candidates"] = unavailable(
            "interpretation_candidates table missing"
        )

    if table_exists(conn, "claim_scope_versions") and column_exists(
        conn, "claims", "scope_revision"
    ):
        where, params = project_clause(conn, "claims", project_id)
        total = conn.execute(f"SELECT COUNT(*) FROM claims{where}", params).fetchone()[0]
        scoped = conn.execute(
            f"SELECT COUNT(*) FROM claims{where}"
            + (" AND" if where else " WHERE")
            + " scope_revision >= 1",
            params,
        ).fetchone()[0]
        reviewed = conn.execute(
            "SELECT COUNT(DISTINCT claim_id) FROM claim_scope_versions"
            " WHERE review_status = 'reviewed'"
        ).fetchone()[0]
        result["claim_scope"] = {
            "claims": total,
            "with_scope_revision": scoped,
            "with_reviewed_scope": reviewed,
            "scope_coverage_pct": round(100.0 * scoped / total, 1) if total else None,
        }
    else:
        result["claim_scope"] = unavailable("claim scope tables missing")

    if table_exists(conn, "semantic_patch_proposals"):
        by_status = defaultdict(int)
        for row in conn.execute("SELECT status FROM semantic_patch_proposals"):
            by_status[row["status"]] += 1
        result["semantic_patch_proposals"] = {"by_status": dict(sorted(by_status.items()))}
    else:
        result["semantic_patch_proposals"] = unavailable(
            "semantic_patch_proposals table missing"
        )

    if table_exists(conn, "manuscript_claims"):
        n_manuscript_claims = conn.execute(
            "SELECT COUNT(*) FROM manuscript_claims"
        ).fetchone()[0]
        evidence_bound = 0
        if table_exists(conn, "manuscript_claim_evidence"):
            evidence_bound = conn.execute(
                "SELECT COUNT(DISTINCT manuscript_claim_id)"
                " FROM manuscript_claim_evidence"
            ).fetchone()[0]
        ratified = 0
        if table_exists(conn, "manuscript_claim_ratifications"):
            ratified = conn.execute(
                "SELECT COUNT(DISTINCT claim_id) FROM manuscript_claim_ratifications"
            ).fetchone()[0]
        result["manuscript_claims"] = {
            "claims": n_manuscript_claims,
            "with_evidence_binding": evidence_bound,
            "with_ratification": ratified,
        }
    else:
        result["manuscript_claims"] = unavailable("manuscript_claims table missing")

    return result


# -------------------------------------------------------------------- main


def compute(db_path: str | Path, project_id: str | None = None) -> dict[str, Any]:
    conn = open_readonly(db_path)
    try:
        if not table_exists(conn, "claims"):
            claims_section: dict[str, Any] = unavailable("claims table missing")
            trajectory_section: dict[str, Any] = unavailable("claims table missing")
        else:
            classified = classify_claims(conn, project_id)
            claims_section = provenance_coverage(classified)
            trajectory_section = research_debt_trajectory(classified)
        payload = {
            "meta": {
                "tool_version": TOOL_VERSION,
                "generated_at": datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                "db_file": Path(db_path).name,
                "db_sha256": hashlib.sha256(Path(db_path).read_bytes()).hexdigest(),
                "project_filter": project_id,
            },
            "provenance_coverage": claims_section,
            "research_debt_trajectory": trajectory_section,
            "mission_cycle": mission_cycle(conn, project_id),
            "pipeline_flow": pipeline_flow(conn, project_id),
        }
        return payload
    finally:
        conn.close()


def write_month_csv(payload: dict[str, Any], csv_path: Path) -> None:
    months = payload.get("research_debt_trajectory", {}).get("months") or {}
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["month", "created", "covered_now", "uncovered_now", "stale", "cumulative_uncovered"]
        )
        for key, stats in months.items():
            writer.writerow(
                [
                    key,
                    stats["created"],
                    stats["covered_now"],
                    stats["uncovered_now"],
                    stats["stale"],
                    stats["cumulative_uncovered"],
                ]
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, help="path to a snapshot copy of rka.db")
    parser.add_argument("--project", help="restrict to one project_id (e.g. prj_...)")
    parser.add_argument("--out", help="write metrics JSON here (default: stdout)")
    parser.add_argument("--csv", help="also write the per-month trajectory CSV here")
    args = parser.parse_args(argv)

    try:
        payload = compute(args.db, args.project)
    except (FileNotFoundError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(payload, indent=2)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    if args.csv:
        write_month_csv(payload, Path(args.csv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
