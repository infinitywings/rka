"""Tests for multi-project foundation migration."""

from __future__ import annotations

import pytest

from rka.infra.database import Database


@pytest.mark.asyncio
async def test_default_project_seeded(db: Database):
    row = await db.fetchone("SELECT id, name FROM projects WHERE id = 'proj_default'")
    assert row is not None
    assert row["name"] == "Default Project"


@pytest.mark.asyncio
async def test_core_tables_have_project_id_columns(db: Database):
    tables = [
        "decisions",
        "missions",
        "literature",
        "journal",
        "checkpoints",
        "events",
        "audit_log",
        "tags",
        "bootstrap_log",
        "entity_links",
        "keynodes",
        "graph_views",
    ]

    for table in tables:
        cols = await db.fetchall(f"PRAGMA table_info({table})")
        col_names = {c["name"] for c in cols}
        assert "project_id" in col_names
