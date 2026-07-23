"""Conservative legacy-manuscript backfill contract for migration 034."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


MIGRATIONS = Path(__file__).parents[2] / "rka" / "db" / "migrations"
MIGRATION_033 = MIGRATIONS / "033_add_native_manuscript_spine.sql"
MIGRATION_034 = MIGRATIONS / "034_backfill_legacy_manuscripts.sql"


def _connection(tmp_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(tmp_path / "migration-034.db")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE projects (id TEXT PRIMARY KEY);
        CREATE TABLE journal (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            verbatim_input TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE tags (
            tag TEXT NOT NULL COLLATE NOCASE,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            project_id TEXT,
            PRIMARY KEY (tag, entity_type, entity_id)
        );
        CREATE TABLE decisions (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            decided_by TEXT,
            status TEXT,
            chosen TEXT
        );
        CREATE TABLE claims (
            id TEXT PRIMARY KEY,
            project_id TEXT
        );
        """
    )
    connection.executescript(MIGRATION_033.read_text())
    return connection


def _journal(
    connection: sqlite3.Connection,
    entry_id: str,
    project_id: str | None,
    *,
    verbatim_input: str | None = "A bounded paper\n\nA cautious abstract.",
    status: str = "active",
) -> None:
    connection.execute(
        """
        INSERT INTO journal (
            id, project_id, verbatim_input, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, '2026-01-01T00:00:00Z', '2026-02-01T00:00:00Z')
        """,
        (entry_id, project_id, verbatim_input, status),
    )


def _tag(
    connection: sqlite3.Connection,
    entry_id: str,
    project_id: str | None,
    tag: str,
) -> None:
    connection.execute(
        """
        INSERT INTO tags (tag, entity_type, entity_id, project_id)
        VALUES (?, 'journal', ?, ?)
        """,
        (tag, entry_id, project_id),
    )


def _writer_tags(
    connection: sqlite3.Connection,
    entry_id: str,
    project_id: str | None,
    *,
    venue: str = "USENIX Security",
    phase: str = "draft",
) -> None:
    for tag in ("manuscript", f"venue:{venue}", f"phase:{phase}"):
        _tag(connection, entry_id, project_id, tag)


def test_backfill_preserves_legacy_and_projects_only_unambiguous_rows(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    try:
        connection.executemany(
            "INSERT INTO projects (id) VALUES (?)",
            [("prj_a",), ("prj_b",)],
        )
        _journal(connection, "jrn_GOOD", "prj_a")
        _writer_tags(connection, "jrn_GOOD", "prj_a")

        # This row already has a non-derived dual-write aggregate and must not
        # gain a duplicate deterministic aggregate.
        _journal(connection, "jrn_DUAL", "prj_a", verbatim_input="Dual paper")
        _writer_tags(connection, "jrn_DUAL", "prj_a", venue="CHI", phase="review")
        connection.execute(
            """
            INSERT INTO manuscripts (
                id, project_id, title, venue, phase, legacy_journal_id
            ) VALUES (
                'man_EXISTING', 'prj_a', 'Dual paper', 'CHI', 'review',
                'jrn_DUAL'
            )
            """
        )

        # A same candidate suffix in another project still collides because
        # native manuscript IDs are globally unique.  The legacy row is logged,
        # not rebound across projects.
        _journal(connection, "jrn_COLLIDE", "prj_b")
        _writer_tags(connection, "jrn_COLLIDE", "prj_b")
        connection.execute(
            """
            INSERT INTO manuscripts (id, project_id, title)
            VALUES ('man_COLLIDE', 'prj_a', 'Unrelated paper')
            """
        )

        before = connection.execute("SELECT count(*) FROM journal").fetchone()[0]
        connection.executescript(MIGRATION_034.read_text())
        connection.executescript(MIGRATION_034.read_text())

        assert connection.execute("SELECT count(*) FROM journal").fetchone()[0] == before
        assert connection.execute(
            """
            SELECT id, project_id, title, abstract, venue, phase, state,
                   legacy_journal_id, created_at, updated_at
            FROM manuscripts WHERE legacy_journal_id = 'jrn_GOOD'
            """
        ).fetchone() == (
            "man_GOOD",
            "prj_a",
            "A bounded paper",
            "A cautious abstract.",
            "USENIX Security",
            "drafting",
            "active",
            "jrn_GOOD",
            "2026-01-01T00:00:00Z",
            "2026-02-01T00:00:00Z",
        )
        assert connection.execute(
            "SELECT count(*) FROM manuscripts WHERE legacy_journal_id = 'jrn_DUAL'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM manuscripts WHERE id = 'man_DUAL'"
        ).fetchone() == (0,)
        assert connection.execute(
            """
            SELECT reason FROM manuscript_migration_issues
            WHERE legacy_journal_id = 'jrn_COLLIDE'
            """
        ).fetchall() == [("deterministic_id_conflict",)]

        # The backfill never invents semantic manuscript truth.
        for table in (
            "manuscript_claims",
            "manuscript_claim_ratifications",
            "manuscript_checkpoints",
        ):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
    finally:
        connection.close()


def test_backfill_logs_every_incomplete_or_ambiguous_candidate(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    try:
        connection.execute("INSERT INTO projects (id) VALUES ('prj_a')")

        _journal(connection, "jrn_AMBIG", "prj_a", verbatim_input=" ")
        _writer_tags(connection, "jrn_AMBIG", "prj_a")
        _tag(connection, "jrn_AMBIG", "prj_a", "venue:IEEE S&P")
        _tag(connection, "jrn_AMBIG", "prj_a", "phase:review")

        _journal(connection, "jrn_MISSING", "prj_a")
        _tag(connection, "jrn_MISSING", "prj_a", "manuscript")

        _journal(connection, "jrn_UNSUPPORTED", "prj_a")
        _writer_tags(
            connection,
            "jrn_UNSUPPORTED",
            "prj_a",
            phase="camera-ready",
        )

        _journal(connection, "jrn_INACTIVE", "prj_a", status="retracted")
        _writer_tags(connection, "jrn_INACTIVE", "prj_a")

        _journal(connection, "bad_id", "prj_a")
        _writer_tags(connection, "bad_id", "prj_a")

        _journal(connection, "jrn_WRONG_SCOPE", "prj_a")
        _writer_tags(connection, "jrn_WRONG_SCOPE", "prj_b")

        _journal(connection, "jrn_NO_PROJECT_ROW", "prj_missing")
        _writer_tags(connection, "jrn_NO_PROJECT_ROW", "prj_missing")

        connection.executescript(MIGRATION_034.read_text())

        reasons = {
            entry_id: {
                row[0]
                for row in connection.execute(
                    """
                    SELECT reason FROM manuscript_migration_issues
                    WHERE legacy_journal_id = ?
                    """,
                    (entry_id,),
                )
            }
            for entry_id in (
                "jrn_AMBIG",
                "jrn_MISSING",
                "jrn_UNSUPPORTED",
                "jrn_INACTIVE",
                "bad_id",
                "jrn_WRONG_SCOPE",
                "jrn_NO_PROJECT_ROW",
            )
        }
        assert reasons["jrn_AMBIG"] == {
            "missing_title",
            "ambiguous_venue",
            "ambiguous_phase",
        }
        assert reasons["jrn_MISSING"] == {"missing_venue", "missing_phase"}
        assert reasons["jrn_UNSUPPORTED"] == {"unsupported_phase"}
        assert reasons["jrn_INACTIVE"] == {"inactive_legacy_status"}
        assert reasons["bad_id"] == {"invalid_legacy_id"}
        assert reasons["jrn_WRONG_SCOPE"] == {
            "tag_project_mismatch",
            "missing_venue",
            "missing_phase",
        }
        assert reasons["jrn_NO_PROJECT_ROW"] == {"missing_project_record"}

        assert connection.execute("SELECT count(*) FROM manuscripts").fetchone() == (0,)
        details = connection.execute(
            """
            SELECT details FROM manuscript_migration_issues
            WHERE legacy_journal_id = 'jrn_AMBIG'
              AND reason = 'ambiguous_venue'
            """
        ).fetchone()[0]
        assert json.loads(details) == {"venue_tag_count": 2}
    finally:
        connection.close()
