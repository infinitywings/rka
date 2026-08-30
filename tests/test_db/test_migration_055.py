"""Migration 055 adds one constrained embedding-index lifecycle row."""

from __future__ import annotations

import sqlite3

import pytest


@pytest.mark.asyncio
async def test_embedding_index_state_singleton_constraints(db) -> None:
    await db.execute(
        """INSERT INTO embedding_index_state
           (singleton, generation, space_signature, model_name, dimensions, status)
           VALUES (1, 1, 'sig-a', 'model-a', 768, 'ready')"""
    )
    row = await db.fetchone(
        "SELECT generation, status FROM embedding_index_state WHERE singleton = 1"
    )
    assert row == {"generation": 1, "status": "ready"}

    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO embedding_index_state
               (singleton, generation, space_signature, model_name, dimensions, status)
               VALUES (2, 1, 'sig-b', 'model-b', 768, 'ready')"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "UPDATE embedding_index_state SET status = 'unknown' WHERE singleton = 1"
        )
