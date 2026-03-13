"""Tests for backfill_entity_links."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.services.backfill import backfill_entity_links, _parse_json_list


@pytest_asyncio.fixture
async def seeded_db(db: Database) -> Database:
    """DB with legacy related_* JSON arrays for backfill testing."""
    # Journal with related_decisions and related_literature
    await db.execute(
        """INSERT INTO journal (id, type, content, source, confidence, phase, related_decisions, related_literature, related_mission)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ["jrn_001", "finding", "Observation X", "pi", "hypothesis", "phase_1",
         json.dumps(["dec_001"]), json.dumps(["lit_001"]), "mis_001"],
    )
    # Journal with supersedes
    await db.execute(
        """INSERT INTO journal (id, type, content, source, confidence, phase, supersedes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ["jrn_002", "finding", "Updated observation", "brain", "tested", "phase_1", "jrn_001"],
    )
    # Decision with related_missions and related_literature
    await db.execute(
        """INSERT INTO decisions (id, question, rationale, decided_by, status, phase, related_missions, related_literature)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ["dec_001", "Which approach?", "Reason", "brain", "active", "phase_1",
         json.dumps(["mis_001"]), json.dumps(["lit_001"])],
    )
    # Decision with parent
    await db.execute(
        """INSERT INTO decisions (id, parent_id, question, rationale, decided_by, status, phase)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ["dec_002", "dec_001", "Sub-decision", "Sub-reason", "brain", "active", "phase_1"],
    )
    # Mission
    await db.execute(
        "INSERT INTO missions (id, objective, phase, status) VALUES (?, ?, ?, ?)",
        ["mis_001", "Survey methods", "phase_1", "active"],
    )
    # Literature
    await db.execute(
        "INSERT INTO literature (id, title, status) VALUES (?, ?, ?)",
        ["lit_001", "Paper A", "reading"],
    )
    await db.commit()
    return db


class TestBackfill:
    @pytest.mark.asyncio
    async def test_creates_links_from_journal(self, seeded_db: Database):
        counts = await backfill_entity_links(seeded_db)
        assert counts["journal"] >= 3  # references dec, cites lit, produced by mission

    @pytest.mark.asyncio
    async def test_creates_links_from_decisions(self, seeded_db: Database):
        counts = await backfill_entity_links(seeded_db)
        assert counts["decision"] >= 2  # triggered mission, cites lit, parent→child

    @pytest.mark.asyncio
    async def test_creates_supersedes_link(self, seeded_db: Database):
        await backfill_entity_links(seeded_db)
        rows = await seeded_db.fetchall(
            "SELECT * FROM entity_links WHERE link_type = 'supersedes'"
        )
        assert len(rows) >= 1
        assert rows[0]["source_id"] == "jrn_002"
        assert rows[0]["target_id"] == "jrn_001"

    @pytest.mark.asyncio
    async def test_idempotent(self, seeded_db: Database):
        counts1 = await backfill_entity_links(seeded_db)
        await backfill_entity_links(seeded_db)
        # Second run should still succeed (INSERT OR IGNORE)
        total1 = sum(counts1.values())
        assert total1 > 0
        # The actual link rows shouldn't double
        rows = await seeded_db.fetchall("SELECT * FROM entity_links")
        # Should be same count as after first run
        assert len(rows) == total1

    @pytest.mark.asyncio
    async def test_parent_child_decision_link(self, seeded_db: Database):
        await backfill_entity_links(seeded_db)
        rows = await seeded_db.fetchall(
            "SELECT * FROM entity_links WHERE source_id = 'dec_001' AND target_id = 'dec_002'"
        )
        assert len(rows) >= 1
        assert rows[0]["link_type"] == "triggered"


class TestParseJsonList:
    def test_parses_valid_json(self):
        assert _parse_json_list('["a", "b"]') == ["a", "b"]

    def test_handles_none(self):
        assert _parse_json_list(None) == []

    def test_handles_empty_string(self):
        assert _parse_json_list("") == []

    def test_handles_already_list(self):
        assert _parse_json_list(["x", "y"]) == ["x", "y"]

    def test_handles_invalid_json(self):
        assert _parse_json_list("{bad json}") == []

    def test_handles_non_list_json(self):
        assert _parse_json_list('"just a string"') == []
