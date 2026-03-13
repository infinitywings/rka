"""Artifact service tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from rka.services.artifacts import ArtifactService


@pytest.mark.asyncio
async def test_register_rejects_invalid_actor_without_partial_write(db, tmp_path: Path):
    path = tmp_path / "artifact.txt"
    path.write_text("artifact", encoding="utf-8")

    svc = ArtifactService(db)

    with pytest.raises(ValueError, match="Invalid actor 'smoke'"):
        await svc.register(filepath=str(path), filename="artifact.txt", created_by="smoke")

    row = await db.fetchone("SELECT COUNT(*) AS cnt FROM artifacts")
    assert row["cnt"] == 0
