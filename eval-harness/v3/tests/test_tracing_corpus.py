"""Locks for project-scoped tracing-corpus derivation."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_EVAL_HARNESS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_EVAL_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_HARNESS_DIR))

from v3.tracing.build_corpus import build  # noqa: E402


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE journal (
            id TEXT PRIMARY KEY, type TEXT, source TEXT, project_id TEXT
        );
        CREATE TABLE claims (
            id TEXT PRIMARY KEY, source_entry_id TEXT, project_id TEXT
        );
        CREATE TABLE literature (id TEXT PRIMARY KEY, project_id TEXT);
        CREATE TABLE missions (id TEXT PRIMARY KEY, project_id TEXT);
        CREATE TABLE evidence_clusters (id TEXT PRIMARY KEY, project_id TEXT);
        CREATE TABLE entity_links (
            source_type TEXT, source_id TEXT, link_type TEXT,
            target_type TEXT, target_id TEXT, project_id TEXT
        );
        CREATE TABLE decisions (
            id TEXT PRIMARY KEY, question TEXT, chosen TEXT, rationale TEXT,
            status TEXT, parent_id TEXT, superseded_by TEXT, phase TEXT,
            kind TEXT, related_journal TEXT, related_literature TEXT,
            related_missions TEXT, project_id TEXT
        );
        """
    )
    return conn


def _insert_decision(
    conn: sqlite3.Connection,
    entity_id: str,
    project_id: str,
    journal_id: str,
    *,
    status: str = "active",
    superseded_by: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, '[]', '[]', ?)",
        (
            entity_id,
            f"Why choose {entity_id}?",
            "current choice",
            "Auditable rationale",
            status,
            superseded_by,
            "design",
            "decision",
            f'["{journal_id}"]',
            project_id,
        ),
    )


def test_build_corpus_scopes_entity_links_to_project() -> None:
    conn = _db()
    try:
        _insert_decision(conn, "dec_a", "prj_a", "jrn_a")
        conn.execute("INSERT INTO journal VALUES ('jrn_a', 'directive', 'pi', 'prj_a')")
        conn.executemany(
            "INSERT INTO literature VALUES (?, ?)",
            [("lit_a", "prj_a"), ("lit_b", "prj_b")],
        )
        conn.execute("INSERT INTO missions VALUES ('mis_a', 'prj_a')")
        conn.executemany(
            "INSERT INTO entity_links VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("literature", "lit_a", "informed_by", "decision", "dec_a", "prj_a"),
                ("decision", "dec_a", "motivated", "mission", "mis_a", "prj_a"),
                # Deliberately corrupt/legacy-stamped cross-project edge.  The
                # builder must not turn it into project A ground truth.
                ("literature", "lit_b", "informed_by", "decision", "dec_a", "prj_b"),
            ],
        )
        scenarios = build(conn, "prj_a", limit=0)
    finally:
        conn.close()

    assert len(scenarios) == 1
    trace_ids = {entry["entity_id"] for entry in scenarios[0]["expected_trace"]}
    assert {"jrn_a", "lit_a", "mis_a"} <= trace_ids
    assert "lit_b" not in trace_ids


def test_build_corpus_keeps_same_project_pivot() -> None:
    conn = _db()
    try:
        _insert_decision(
            conn,
            "dec_old",
            "prj_a",
            "jrn_old",
            status="superseded",
            superseded_by="dec_new",
        )
        _insert_decision(conn, "dec_new", "prj_a", "jrn_new")
        conn.executemany(
            "INSERT INTO journal VALUES (?, 'note', 'brain', 'prj_a')",
            [("jrn_old",), ("jrn_new",)],
        )
        conn.execute("INSERT INTO literature VALUES ('lit_a', 'prj_a')")
        conn.executemany(
            "INSERT INTO missions VALUES (?, 'prj_a')",
            [("mis_old",), ("mis_new",)],
        )
        conn.executemany(
            "INSERT INTO entity_links VALUES (?, ?, ?, ?, ?, 'prj_a')",
            [
                ("literature", "lit_a", "informed_by", "decision", "dec_old"),
                ("decision", "dec_old", "motivated", "mission", "mis_old"),
                ("literature", "lit_a", "informed_by", "decision", "dec_new"),
                ("decision", "dec_new", "motivated", "mission", "mis_new"),
            ],
        )
        scenarios = build(conn, "prj_a", limit=0)
    finally:
        conn.close()

    by_anchor = {scenario["anchor_decision"]: scenario for scenario in scenarios}
    assert by_anchor["dec_old"]["pivot"] == {
        "superseded_decision_id": "dec_old",
        "superseding_decision_id": "dec_new",
    }
    assert by_anchor["dec_new"]["pivot"] == {
        "superseded_decision_id": "dec_old",
        "superseding_decision_id": "dec_new",
    }


def test_build_corpus_attests_declared_refs_and_supersession_to_project() -> None:
    conn = _db()
    try:
        _insert_decision(conn, "dec_a", "prj_a", "jrn_a")
        _insert_decision(conn, "dec_foreign", "prj_b", "jrn_foreign")
        conn.executemany(
            "INSERT INTO journal VALUES (?, 'note', 'brain', ?)",
            [("jrn_a", "prj_a"), ("jrn_foreign", "prj_b")],
        )
        conn.executemany(
            "INSERT INTO literature VALUES (?, ?)",
            [("lit_a", "prj_a"), ("lit_foreign", "prj_b")],
        )
        conn.executemany(
            "INSERT INTO missions VALUES (?, ?)",
            [("mis_a", "prj_a"), ("mis_foreign", "prj_b")],
        )
        conn.execute(
            "UPDATE decisions SET related_journal = ?, related_literature = ?, "
            "related_missions = ?, superseded_by = ? WHERE id = 'dec_a'",
            (
                '["jrn_a", "jrn_foreign"]',
                '["lit_a", "lit_foreign"]',
                '["mis_a", "mis_foreign"]',
                "dec_foreign",
            ),
        )
        scenarios = build(conn, "prj_a", limit=0)
    finally:
        conn.close()

    assert len(scenarios) == 1
    scenario = scenarios[0]
    trace_ids = {entry["entity_id"] for entry in scenario["expected_trace"]}
    assert {"jrn_a", "lit_a", "mis_a"} <= trace_ids
    assert trace_ids.isdisjoint({"jrn_foreign", "lit_foreign", "mis_foreign", "dec_foreign"})
    assert "pivot" not in scenario


def test_build_corpus_tolerates_only_explicit_missing_optional_tables() -> None:
    missing = _db()
    try:
        missing.execute("DROP TABLE literature")
        _insert_decision(missing, "dec_a", "prj_a", "jrn_a")
        missing.execute("INSERT INTO journal VALUES ('jrn_a', 'note', 'brain', 'prj_a')")
        assert build(missing, "prj_a", limit=0) == []
    finally:
        missing.close()

    malformed = _db()
    try:
        malformed.execute("DROP TABLE literature")
        malformed.execute("CREATE TABLE literature (id TEXT PRIMARY KEY)")
        _insert_decision(malformed, "dec_a", "prj_a", "jrn_a")
        malformed.execute("INSERT INTO journal VALUES ('jrn_a', 'note', 'brain', 'prj_a')")
        with pytest.raises(sqlite3.OperationalError, match="no such column"):
            build(malformed, "prj_a", limit=0)
    finally:
        malformed.close()
