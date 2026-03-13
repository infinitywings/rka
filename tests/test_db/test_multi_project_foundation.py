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


@pytest.mark.asyncio
async def test_literature_doi_is_unique_per_project(db: Database):
    await db.execute(
        "INSERT INTO projects (id, name, description, created_by) VALUES (?, ?, ?, ?)",
        ["proj_alpha", "Alpha", "alpha", "system"],
    )
    await db.execute(
        "INSERT INTO projects (id, name, description, created_by) VALUES (?, ?, ?, ?)",
        ["proj_beta", "Beta", "beta", "system"],
    )
    await db.execute(
        "INSERT INTO literature (id, title, doi, status, project_id) VALUES (?, ?, ?, ?, ?)",
        ["lit_alpha", "Shared Paper", "10.1234/shared-doi", "to_read", "proj_alpha"],
    )
    await db.execute(
        "INSERT INTO literature (id, title, doi, status, project_id) VALUES (?, ?, ?, ?, ?)",
        ["lit_beta", "Shared Paper", "10.1234/shared-doi", "to_read", "proj_beta"],
    )
    await db.commit()

    rows = await db.fetchall(
        "SELECT id, project_id FROM literature WHERE doi = ? ORDER BY project_id",
        ["10.1234/shared-doi"],
    )
    assert [(row["project_id"], row["id"]) for row in rows] == [
        ("proj_alpha", "lit_alpha"),
        ("proj_beta", "lit_beta"),
    ]
