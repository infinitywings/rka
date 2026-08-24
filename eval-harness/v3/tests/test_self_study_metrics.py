"""Locks for the Track-1 self-study metrics extractor.

Builds a real migrated database via the production
``Database.initialize_schema()`` (same pattern as ``tests/conftest.py``)
so the extractor is exercised against the schema exactly as shipped,
then inserts a synthetic record with known coverage structure and locks
the metric math.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
import pytest_asyncio

_EVAL_HARNESS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_EVAL_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_HARNESS_DIR))

from v3.self_study.compute_metrics import compute, main  # noqa: E402

from rka.infra.database import Database  # noqa: E402


@pytest_asyncio.fixture
async def snapshot(tmp_path: Path) -> Path:
    db_path = tmp_path / "snapshot.db"
    database = Database(str(db_path))
    await database.connect()
    await database.initialize_schema()
    await database.close()

    conn = sqlite3.connect(db_path)
    try:
        _seed(conn)
        conn.commit()
    finally:
        conn.close()
    return db_path


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO projects (id, name) VALUES ('prj_test', 'self-study fixture')"
    )

    journal_rows = [
        # researcher-authored entry -> claims sourced here are covered at birth
        ("jrn_pi", "pi_instruction", "PI directive text", "pi", None, None, "2026-01-05T10:00:00Z"),
        # plain brain entry, no literature -> not covering by itself
        ("jrn_brain", "finding", "brain finding", "brain", None, None, "2026-01-06T10:00:00Z"),
        # brain entry that cites literature inline
        ("jrn_lit", "finding", "cites a paper", "brain", '["lit_1"]', None, "2026-02-01T10:00:00Z"),
        # backbrief journal for the completed mission (12h after completion)
        ("jrn_000057REDACTED", "summary", "mission backbrief", "executor", None, "mis_done", "2026-03-03T00:00:00Z"),
    ]
    conn.executemany(
        "INSERT INTO journal (id, type, content, source, related_literature,"
        " related_mission, created_at, updated_at, project_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'prj_test')",
        [(*row, row[-1]) for row in journal_rows],
    )

    conn.execute(
        "INSERT INTO literature (id, title, status) VALUES ('lit_1', 'A paper', 'read')"
    )

    claims = [
        # covered: researcher-authored source entry
        ("clm_pi", "jrn_pi", "result", 0, "2026-01-05T11:00:00Z"),
        # covered: entity_links walk claim -> literature (link lands 10 days later)
        ("clm_link", "jrn_brain", "evidence", 0, "2026-01-06T11:00:00Z"),
        # covered: source entry's related_literature
        ("clm_inline", "jrn_lit", "method", 0, "2026-02-01T11:00:00Z"),
        # uncovered: brain source, no links anywhere
        ("clm_debt", "jrn_brain", "hypothesis", 0, "2026-02-02T11:00:00Z"),
        # covered but stale -> excluded from coverage_strict
        ("clm_stale", "jrn_pi", "observation", 1, "2026-03-01T11:00:00Z"),
    ]
    conn.executemany(
        "INSERT INTO claims (id, source_entry_id, claim_type, content, stale,"
        " created_at, updated_at, project_id)"
        " VALUES (?, ?, ?, 'claim text', ?, ?, ?, 'prj_test')",
        [(cid, src, ctype, stale, ts, ts) for cid, src, ctype, stale, ts in claims],
    )

    conn.execute(
        "INSERT INTO entity_links (id, source_type, source_id, link_type,"
        " target_type, target_id, created_at)"
        " VALUES ('lnk_1', 'claim', 'clm_link', 'cites', 'literature', 'lit_1',"
        " '2026-01-16T11:00:00Z')"
    )

    conn.executemany(
        "INSERT INTO missions (id, phase, objective, status, report, created_at,"
        " completed_at)"
        " VALUES (?, 'phase-1', ?, ?, ?, ?, ?)",
        [
            (
                "mis_done",
                "finished mission",
                "complete",
                '{"summary": "done"}',
                "2026-03-01T00:00:00Z",
                "2026-03-02T12:00:00Z",
            ),
            ("mis_open", "running mission", "active", None, "2026-03-05T00:00:00Z", None),
        ],
    )

    conn.execute(
        "INSERT INTO checkpoints (id, mission_id, type, description, status,"
        " created_at, resolved_at)"
        " VALUES ('chk_1', 'mis_done', 'inspection', 'gate', 'resolved',"
        " '2026-03-01T06:00:00Z', '2026-03-01T18:00:00Z')"
    )

    conn.executemany(
        "INSERT INTO interpretation_candidates (id, project_id, source_type,"
        " source_id, locator_kind, locator_start, locator_end, statement,"
        " epistemic_kind, created_by, extraction_tool, review_status,"
        " disposition, disposition_target_type, disposition_target_id,"
        " reviewed_by, reviewed_at)"
        " VALUES (?, 'prj_test', 'journal', 'jrn_brain', 'text_offset', 0, 10,"
        " ?, 'observation', 'brain', 'manual', ?, ?, ?, ?, ?, ?)",
        [
            (
                "icd_000058REDACTED",
                "promoted statement",
                "resolved",
                "promoted",
                "claim",
                "clm_link",
                "pi",
                "2026-02-10T00:00:00Z",
            ),
            ("icd_pending", "pending statement", "pending", None, None, None, None, None),
        ],
    )


async def test_provenance_coverage(snapshot: Path) -> None:
    payload = compute(snapshot)
    coverage = payload["provenance_coverage"]

    assert coverage["n_claims"] == 5
    assert coverage["covered"] == 4
    assert coverage["coverage_pct"] == 80.0
    # stale claim drops out of the strict figure
    assert coverage["coverage_strict"] == 3
    assert coverage["coverage_strict_pct"] == 60.0
    assert coverage["stale_claims"] == 1
    assert coverage["covered_via"] == {
        "researcher_source_entry": 2,
        "literature_link": 1,
        "source_entry_cites_literature": 1,
    }
    assert coverage["by_claim_type"]["hypothesis"] == {"claims": 1, "covered": 0}


async def test_research_debt_trajectory(snapshot: Path) -> None:
    payload = compute(snapshot)
    trajectory = payload["research_debt_trajectory"]
    months = trajectory["months"]

    assert months["2026-01"] == {
        "created": 2,
        "covered_now": 2,
        "uncovered_now": 0,
        "stale": 0,
        "cumulative_uncovered": 0,
    }
    assert months["2026-02"]["uncovered_now"] == 1
    assert months["2026-02"]["cumulative_uncovered"] == 1
    assert months["2026-03"]["stale"] == 1

    ttc = trajectory["time_to_coverage_days"]
    assert ttc["count"] == 4
    # clm_link's covering entity link landed 10 days after the claim
    assert ttc["max"] == 10.0
    assert ttc["min"] == 0.0


async def test_mission_cycle(snapshot: Path) -> None:
    payload = compute(snapshot)
    cycle = payload["mission_cycle"]

    assert cycle["n_missions"] == 2
    assert cycle["status"] == {"active": 1, "complete": 1}
    assert cycle["duration_hours"]["count"] == 1
    assert cycle["duration_hours"]["median"] == 36.0
    assert cycle["checkpoints_per_mission"]["max"] == 1.0
    assert cycle["checkpoint_resolution_hours"]["median"] == 12.0
    assert cycle["open_checkpoints"] == 0
    assert cycle["missions_with_report"] == 1
    assert cycle["completion_to_first_journal_hours"]["median"] == 12.0


async def test_pipeline_flow(snapshot: Path) -> None:
    payload = compute(snapshot)
    flow = payload["pipeline_flow"]

    assert flow["interpretation_candidates"]["by_review_status"] == {
        "pending": 1,
        "resolved": 1,
    }
    assert flow["interpretation_candidates"]["by_disposition"] == {"promoted": 1}
    # no scope versions were seeded: coverage exists but is 0%
    assert flow["claim_scope"]["claims"] == 5
    assert flow["claim_scope"]["with_scope_revision"] == 0
    assert flow["semantic_patch_proposals"]["by_status"] == {}
    assert flow["manuscript_claims"]["claims"] == 0


async def test_cli_writes_outputs(snapshot: Path, tmp_path: Path) -> None:
    out = tmp_path / "results" / "metrics.json"
    csv_out = tmp_path / "results" / "trajectory.csv"
    code = main(["--db", str(snapshot), "--out", str(out), "--csv", str(csv_out)])
    assert code == 0
    assert out.is_file() and csv_out.is_file()
    header, first = csv_out.read_text().splitlines()[:2]
    assert header.startswith("month,created,covered_now")
    assert first.startswith("2026-01,2,2,0")


async def test_meta_embeds_snapshot_hash(snapshot: Path) -> None:
    payload = compute(snapshot)
    assert len(payload["meta"]["db_sha256"]) == 64
    assert payload["meta"]["db_file"] == "snapshot.db"


def test_missing_snapshot_is_a_clean_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compute(tmp_path / "nope.db")


# --------------------------------------------------------- project isolation


@pytest_asyncio.fixture
async def two_project_snapshot(tmp_path: Path) -> Path:
    """Two projects sharing a link graph, for --project isolation locks.

    ``prj_a`` holds one claim whose only reachable anchors live in ``prj_b``
    (a foreign literature row) plus one claim covered through a *legacy* link
    row with a NULL ``project_id``. Scoping must reject the first and keep the
    second.
    """
    db_path = tmp_path / "two.db"
    database = Database(str(db_path))
    await database.connect()
    await database.initialize_schema()
    await database.close()

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            [("prj_a", "project A"), ("prj_b", "project B")],
        )
        conn.executemany(
            "INSERT INTO journal (id, type, content, source, created_at,"
            " updated_at, project_id) VALUES (?, 'finding', 'text', 'brain', ?, ?, ?)",
            [
                ("jrn_a", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "prj_a"),
                ("jrn_a2", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "prj_a"),
            ],
        )
        # literature belonging to the *other* project
        conn.execute(
            "INSERT INTO literature (id, title, status, project_id)"
            " VALUES ('lit_b', 'foreign paper', 'read', 'prj_b')"
        )
        # literature belonging to prj_a, reached only via a legacy NULL link
        conn.execute(
            "INSERT INTO literature (id, title, status, project_id)"
            " VALUES ('lit_a', 'own paper', 'read', 'prj_a')"
        )
        conn.executemany(
            "INSERT INTO claims (id, source_entry_id, claim_type, content, stale,"
            " created_at, updated_at, project_id)"
            " VALUES (?, ?, 'evidence', 'claim text', 0, ?, ?, 'prj_a')",
            [
                ("clm_foreign", "jrn_a", "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z"),
                ("clm_legacy", "jrn_a2", "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z"),
            ],
        )
        conn.executemany(
            "INSERT INTO entity_links (id, source_type, source_id, link_type,"
            " target_type, target_id, created_at, project_id) VALUES"
            " (?, 'claim', ?, 'cites', 'literature', ?, '2026-01-03T00:00:00Z', ?)",
            [
                # cross-project: must NOT confer coverage on prj_a
                ("lnk_cross", "clm_foreign", "lit_b", "prj_a"),
                # legacy row with no project stamp, both endpoints in prj_a
                ("lnk_legacy", "clm_legacy", "lit_a", None),
            ],
        )
        # a checkpoint that belongs to the other project only
        conn.execute(
            "INSERT INTO checkpoints (id, type, description, status, created_at,"
            " project_id) VALUES ('chk_b', 'inspection', 'gate', 'open',"
            " '2026-01-04T00:00:00Z', 'prj_b')"
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


async def test_project_filter_rejects_cross_project_coverage(
    two_project_snapshot: Path,
) -> None:
    """A prj_b literature row must not cover a prj_a claim."""
    payload = compute(two_project_snapshot, project_id="prj_a")
    coverage = payload["provenance_coverage"]
    assert coverage["n_claims"] == 2
    # only the legacy in-project link counts
    assert coverage["covered"] == 1
    assert coverage["covered_via"] == {"literature_link": 1}


async def test_project_filter_keeps_legacy_unstamped_links(
    two_project_snapshot: Path,
) -> None:
    """Links predating entity_links.project_id still carry in-project provenance."""
    scoped = compute(two_project_snapshot, project_id="prj_a")["provenance_coverage"]
    unscoped = compute(two_project_snapshot)["provenance_coverage"]
    # unscoped sees both links; scoped keeps only the legacy (in-project) one
    assert unscoped["covered"] == 2
    assert scoped["covered"] == 1


async def test_open_checkpoints_are_project_scoped(
    two_project_snapshot: Path,
) -> None:
    """Regression: checkpoints were counted globally regardless of --project."""
    assert compute(two_project_snapshot)["mission_cycle"]["open_checkpoints"] == 1
    a = compute(two_project_snapshot, project_id="prj_a")["mission_cycle"]
    b = compute(two_project_snapshot, project_id="prj_b")["mission_cycle"]
    assert a["open_checkpoints"] == 0
    assert b["open_checkpoints"] == 1
