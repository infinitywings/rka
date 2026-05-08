"""Regression tests for migration 021 (entity_links.link_type CHECK constraint).

Pre-migration the link_type column was unconstrained, so a typo in any
caller (or a stale historical row) could silently land. Migration 021 adds
a CHECK enumerating every link_type emitted by production code paths plus
two legacy types preserved for historical rows. Filed under
mis_01KR1Z28QW9WYXG4VV8PGYWD8G (T1 of v2.3.4 defect remediation).
"""

from __future__ import annotations

import pytest

from rka.infra.database import Database


PROJECT_ID = "proj_test_migration_021"


# Active types emitted by production code (services, api, mcp, backfill).
ACTIVE_LINK_TYPES = (
    "justified_by",
    "informed_by",
    "supersedes",
    "motivated",
    "references",
    "cites",
    "produced",
    "derived_from",
    "resolved_as",
)

# Legacy types preserved for historical rows + backfill compatibility.
LEGACY_LINK_TYPES = (
    "evidence_for",
    "triggered",
)


class TestMigration021Check:
    """The CHECK constraint enumerates 11 valid link_types and rejects others."""

    @pytest.mark.parametrize("link_type", ACTIVE_LINK_TYPES + LEGACY_LINK_TYPES)
    async def test_valid_link_type_accepted(self, db: Database, link_type: str):
        """Each enumerated link_type must INSERT successfully."""
        await db.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            [PROJECT_ID, "test_migration_021"],
        )
        await db.execute(
            """INSERT INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                f"lnk_021_valid_{link_type}",
                "journal",
                f"jrn_021_{link_type}",
                link_type,
                "decision",
                f"dec_021_{link_type}",
                PROJECT_ID,
            ],
        )
        await db.commit()

        async with db._conn.execute(  # type: ignore[attr-defined]
            "SELECT link_type FROM entity_links WHERE id = ?",
            [f"lnk_021_valid_{link_type}"],
        ) as cur:
            row = await cur.fetchone()
        assert row is not None and row[0] == link_type

    async def test_invalid_link_type_rejected(self, db: Database):
        """A link_type not in the enumeration must raise IntegrityError."""
        await db.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            [PROJECT_ID, "test_migration_021"],
        )
        await db.commit()

        with pytest.raises(Exception) as excinfo:
            await db.execute(
                """INSERT INTO entity_links
                   (id, source_type, source_id, link_type, target_type, target_id, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    "lnk_021_invalid",
                    "journal",
                    "jrn_021_inv",
                    "this_type_should_not_exist",
                    "decision",
                    "dec_021_inv",
                    PROJECT_ID,
                ],
            )
            await db.commit()
        assert "CHECK constraint failed" in str(excinfo.value), (
            f"Expected CHECK constraint failure; got {excinfo.value!r}"
        )
