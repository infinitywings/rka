"""E1.2 regressions for project-partitioned sqlite-vec retrieval."""

from __future__ import annotations

import struct

import pytest

from rka.infra.database import Database
from rka.infra.embeddings import EmbeddingService
from rka.services.embedding_backfill import BackfillService, register_job
from rka.services.embedding_reshape import ensure_vec_table_partitions
from rka.services.knowledge_pack import KnowledgePackService
from rka.services.project import ProjectService
from rka.services.search import SearchService


def _blob(values: list[float]) -> bytes:
    return struct.pack(f"{len(values)}f", *values)


async def _project(db, project_id: str) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO projects (id, name, created_by) VALUES (?, ?, 'system')",
        [project_id, project_id],
    )


async def _journal(db, entry_id: str, project_id: str, content: str) -> None:
    await db.execute(
        """INSERT INTO journal
           (id, type, content, source, project_id)
           VALUES (?, 'note', ?, 'executor', ?)""",
        [entry_id, content, project_id],
    )


@pytest.mark.asyncio
async def test_fresh_vec_tables_expose_project_partitions(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")

    tables = (
        "vec_journal",
        "vec_decisions",
        "vec_literature",
        "vec_missions",
        "vec_claims",
        "vec_artifacts",
    )
    for table in tables:
        row = await db.fetchone(
            "SELECT sql FROM sqlite_master WHERE name = ?",
            [table],
        )
        sql = " ".join((row["sql"] or "").lower().split())
        assert "project_id text partition key" in sql

    row = await db.fetchone(
        "SELECT sql FROM sqlite_master WHERE name = 'vec_artifacts'"
    )
    sql = " ".join((row["sql"] or "").lower().split())
    assert "entity_type text partition key" in sql
    assert await db.fetchone(
        "SELECT name FROM runtime_schema_upgrades "
        "WHERE name = '053_vec_project_partitions_v1'"
    ) == {"name": "053_vec_project_partitions_v1"}


@pytest.mark.asyncio
async def test_legacy_partition_migration_preserves_vectors_and_isolates_orphans(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")

    await _project(db, "proj_alpha")
    await _project(db, "proj_beta")
    await _journal(db, "jrn_alpha", "proj_alpha", "alpha")
    await _journal(db, "jrn_beta", "proj_beta", "beta")
    await db.execute("DROP TABLE vec_journal")
    await db.execute(
        "CREATE VIRTUAL TABLE vec_journal USING vec0("
        "id TEXT PRIMARY KEY, embedding float[4])"
    )
    for entity_id, values in (
        ("jrn_alpha", [1.0, 0.0, 0.0, 0.0]),
        ("jrn_beta", [0.0, 1.0, 0.0, 0.0]),
        ("jrn_orphan", [0.0, 0.0, 1.0, 0.0]),
    ):
        await db.execute(
            "INSERT INTO vec_journal (id, embedding) VALUES (?, ?)",
            [entity_id, _blob(values)],
        )

    result = await ensure_vec_table_partitions(db)

    assert result["vec_journal"] is True
    rows = await db.fetchall(
        "SELECT id, project_id FROM vec_journal ORDER BY id"
    )
    assert rows == [
        {"id": "jrn_alpha", "project_id": "proj_alpha"},
        {"id": "jrn_beta", "project_id": "proj_beta"},
        {"id": "jrn_orphan", "project_id": "__orphan__"},
    ]
    second = await ensure_vec_table_partitions(db)
    assert second["vec_journal"] is False


@pytest.mark.asyncio
async def test_shared_artifact_migration_recovers_artifact_and_figure_types(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")

    await _project(db, "proj_alpha")
    await db.execute(
        """INSERT INTO artifacts (id, filename, filepath, project_id)
           VALUES ('art_migrate', 'artifact.png', '/tmp/artifact.png', 'proj_alpha')"""
    )
    await db.execute(
        """INSERT INTO figures
           (id, artifact_id, caption, project_id)
           VALUES ('fig_migrate', 'art_migrate', 'figure', 'proj_alpha')"""
    )
    await db.execute("DROP TABLE vec_artifacts")
    await db.execute(
        "CREATE VIRTUAL TABLE vec_artifacts USING vec0("
        "id TEXT PRIMARY KEY, embedding float[4])"
    )
    for entity_id in ("art_migrate", "fig_migrate", "lost_migrate"):
        await db.execute(
            "INSERT INTO vec_artifacts (id, embedding) VALUES (?, ?)",
            [entity_id, _blob([1.0, 0.0, 0.0, 0.0])],
        )

    result = await ensure_vec_table_partitions(db)

    assert result["vec_artifacts"] is True
    assert await db.fetchall(
        "SELECT id, project_id, entity_type FROM vec_artifacts ORDER BY id"
    ) == [
        {
            "id": "art_migrate",
            "project_id": "proj_alpha",
            "entity_type": "artifact",
        },
        {
            "id": "fig_migrate",
            "project_id": "proj_alpha",
            "entity_type": "figure",
        },
        {
            "id": "lost_migrate",
            "project_id": "__orphan__",
            "entity_type": "__orphan__",
        },
    ]
    issues = await KnowledgePackService(
        db, project_id="proj_alpha"
    ).check_integrity()
    vector_issue = next(
        issue for issue in issues if issue["category"] == "orphaned_vector_rows"
    )
    assert "lost_migrate" in vector_issue["ids"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_prefix",
    [
        "CREATE VIRTUAL TABLE vec_journal",
        "INSERT INTO vec_journal (id, project_id, embedding)",
    ],
)
async def test_partition_migration_rolls_back_on_failure(
    db, monkeypatch, failure_prefix
):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")

    await db.execute("DROP TABLE vec_journal")
    await db.execute(
        "CREATE VIRTUAL TABLE vec_journal USING vec0("
        "id TEXT PRIMARY KEY, embedding float[4])"
    )
    await db.execute(
        "INSERT INTO vec_journal (id, embedding) VALUES ('jrn_survives', ?)",
        [_blob([1.0, 0.0, 0.0, 0.0])],
    )
    original_execute = db.execute

    async def fail_upgrade(sql, params=None):
        if sql.startswith(failure_prefix):
            raise RuntimeError("injected upgrade failure")
        return await original_execute(sql, params)

    monkeypatch.setattr(db, "execute", fail_upgrade)
    with pytest.raises(RuntimeError, match="injected upgrade failure"):
        await ensure_vec_table_partitions(db)

    schema = await db.fetchone(
        "SELECT sql FROM sqlite_master WHERE name = 'vec_journal'"
    )
    assert "partition key" not in (schema["sql"] or "").lower()
    assert await db.fetchone(
        "SELECT id FROM vec_journal WHERE id = 'jrn_survives'"
    ) == {"id": "jrn_survives"}


@pytest.mark.asyncio
async def test_reopening_legacy_file_migrates_before_search(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    legacy = Database(db_path)
    await legacy.connect()
    await legacy.initialize_schema()
    await legacy.initialize_phase2_schema()
    if not legacy.vec_available:
        await legacy.close()
        pytest.skip("sqlite-vec extension not loaded")

    await _project(legacy, "proj_alpha")
    await _journal(legacy, "jrn_legacy", "proj_alpha", "legacy vector")
    await legacy.execute("DROP TABLE vec_journal")
    await legacy.execute(
        "CREATE VIRTUAL TABLE vec_journal USING vec0("
        "id TEXT PRIMARY KEY, embedding float[4])"
    )
    await legacy.execute(
        "INSERT INTO vec_journal (id, embedding) VALUES ('jrn_legacy', ?)",
        [_blob([1.0, 0.0, 0.0, 0.0])],
    )
    await legacy.execute(
        """INSERT OR REPLACE INTO embedding_metadata
           (project_id, entity_type, entity_id, content_hash, model_name, dimensions)
           VALUES ('proj_alpha', 'journal', 'jrn_legacy', 'hash', 'legacy', 4)"""
    )
    await legacy.execute(
        "DELETE FROM runtime_schema_upgrades "
        "WHERE name = '053_vec_project_partitions_v1'"
    )
    await legacy.close()

    reopened = Database(db_path)
    await reopened.connect()
    await reopened.initialize_schema()
    await reopened.initialize_phase2_schema()
    try:
        schema = await reopened.fetchone(
            "SELECT sql FROM sqlite_master WHERE name = 'vec_journal'"
        )
        assert "project_id text partition key" in " ".join(
            (schema["sql"] or "").lower().split()
        )
        assert await reopened.fetchone(
            "SELECT content_hash, model_name, dimensions FROM embedding_metadata "
            "WHERE project_id = 'proj_alpha' AND entity_type = 'journal' "
            "AND entity_id = 'jrn_legacy'"
        ) == {"content_hash": "hash", "model_name": "legacy", "dimensions": 4}
        rows = await reopened.fetchall(
            """SELECT id, distance FROM vec_journal
               WHERE embedding MATCH ? AND project_id = 'proj_alpha' AND k = 1
               ORDER BY distance""",
            [_blob([1.0, 0.0, 0.0, 0.0])],
        )
        assert rows[0]["id"] == "jrn_legacy"
        assert rows[0]["distance"] == pytest.approx(0.0)
        assert await reopened.fetchone(
            "SELECT name FROM runtime_schema_upgrades "
            "WHERE name = '053_vec_project_partitions_v1'"
        ) == {"name": "053_vec_project_partitions_v1"}
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_vector_knn_filters_project_before_top_k(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")

    await _project(db, "proj_alpha")
    await _project(db, "proj_beta")
    await _journal(db, "jrn_alpha", "proj_alpha", "target project result")
    await _journal(db, "jrn_beta_1", "proj_beta", "closer other project result")
    await _journal(db, "jrn_beta_2", "proj_beta", "another closer result")
    await db.execute("DROP TABLE vec_journal")
    await db.execute(
        "CREATE VIRTUAL TABLE vec_journal USING vec0("
        "id TEXT PRIMARY KEY, project_id TEXT partition key, embedding float[4])"
    )
    for entity_id, project_id, values in (
        ("jrn_alpha", "proj_alpha", [0.8, 0.2, 0.0, 0.0]),
        ("jrn_beta_1", "proj_beta", [1.0, 0.0, 0.0, 0.0]),
        ("jrn_beta_2", "proj_beta", [0.99, 0.01, 0.0, 0.0]),
    ):
        await db.execute(
            "INSERT INTO vec_journal (id, project_id, embedding) VALUES (?, ?, ?)",
            [entity_id, project_id, _blob(values)],
        )

    hits = await SearchService(
        db=db,
        embeddings=None,
        project_id="proj_alpha",
    )._vector_search([1.0, 0.0, 0.0, 0.0], ["journal"], 1)

    assert [hit.entity_id for hit in hits] == ["jrn_alpha"]


@pytest.mark.asyncio
async def test_shared_artifact_table_filters_entity_type_before_top_k(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")

    await _project(db, "proj_alpha")
    await db.execute(
        """INSERT INTO artifacts (id, filename, filepath, project_id)
           VALUES ('art_alpha', 'artifact.png', '/tmp/artifact.png', 'proj_alpha')"""
    )
    await db.execute(
        """INSERT INTO figures
           (id, artifact_id, caption, summary, project_id)
           VALUES ('fig_alpha', 'art_alpha', 'figure caption', 'figure summary', 'proj_alpha')"""
    )
    await db.execute("DROP TABLE vec_artifacts")
    await db.execute(
        "CREATE VIRTUAL TABLE vec_artifacts USING vec0("
        "id TEXT PRIMARY KEY, project_id TEXT partition key, "
        "entity_type TEXT partition key, embedding float[4])"
    )
    await db.execute(
        "INSERT INTO vec_artifacts (id, project_id, entity_type, embedding) "
        "VALUES ('art_alpha', 'proj_alpha', 'artifact', ?)",
        [_blob([1.0, 0.0, 0.0, 0.0])],
    )
    await db.execute(
        "INSERT INTO vec_artifacts (id, project_id, entity_type, embedding) "
        "VALUES ('fig_alpha', 'proj_alpha', 'figure', ?)",
        [_blob([0.8, 0.2, 0.0, 0.0])],
    )

    hits = await SearchService(
        db=db,
        embeddings=None,
        project_id="proj_alpha",
    )._vector_search([1.0, 0.0, 0.0, 0.0], ["figure"], 1)

    assert [hit.entity_id for hit in hits] == ["fig_alpha"]


@pytest.mark.asyncio
async def test_store_embedding_persists_project_and_entity_partitions(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")

    service = EmbeddingService(model_name="partition-test", db=db)
    vector = [0.0] * 768
    await service.store_embedding(
        "journal",
        "jrn_partitioned",
        "journal text",
        embedding=vector,
        project_id="proj_alpha",
    )
    await service.store_embedding(
        "figure",
        "fig_partitioned",
        "figure text",
        embedding=vector,
        project_id="proj_alpha",
    )

    journal = await db.fetchone(
        "SELECT project_id FROM vec_journal WHERE id = 'jrn_partitioned'"
    )
    figure = await db.fetchone(
        "SELECT project_id, entity_type FROM vec_artifacts "
        "WHERE id = 'fig_partitioned'"
    )
    assert journal == {"project_id": "proj_alpha"}
    assert figure == {
        "project_id": "proj_alpha",
        "entity_type": "figure",
    }


@pytest.mark.asyncio
async def test_main_backfill_indexes_figures_with_both_partitions(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")

    class _Embeddings:
        model_name = "partition-test"
        dim = 768

        async def embed_batch(self, texts, is_query=False):
            return [[0.0] * self.dim for _text in texts]

    await _project(db, "proj_alpha")
    await db.execute(
        """INSERT INTO artifacts (id, filename, filepath, project_id)
           VALUES ('art_backfill', 'artifact.png', '/tmp/artifact.png', 'proj_alpha')"""
    )
    await db.execute(
        """INSERT INTO figures
           (id, artifact_id, caption, summary, claims, project_id)
           VALUES ('fig_backfill', 'art_backfill', 'caption', 'summary', '[]',
                   'proj_alpha')"""
    )

    status = register_job()
    await BackfillService(db=db, embeddings=_Embeddings()).run_backfill(
        status, entity_types=["figure"]
    )

    assert status.state == "complete"
    assert status.processed == 1
    assert await db.fetchone(
        "SELECT project_id, entity_type FROM vec_artifacts "
        "WHERE id = 'fig_backfill'"
    ) == {"project_id": "proj_alpha", "entity_type": "figure"}


@pytest.mark.asyncio
async def test_project_delete_removes_shared_artifact_and_figure_vectors(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")

    await _project(db, "proj_doomed")
    await db.execute(
        """INSERT INTO artifacts (id, filename, filepath, project_id)
           VALUES ('art_doomed', 'artifact.png', '/tmp/artifact.png', 'proj_doomed')"""
    )
    await db.execute(
        """INSERT INTO figures
           (id, artifact_id, caption, project_id)
           VALUES ('fig_doomed', 'art_doomed', 'figure', 'proj_doomed')"""
    )
    vector = _blob([0.0] * 768)
    await db.execute(
        "INSERT INTO vec_artifacts (id, project_id, entity_type, embedding) "
        "VALUES ('art_doomed', 'proj_doomed', 'artifact', ?)",
        [vector],
    )
    await db.execute(
        "INSERT INTO vec_artifacts (id, project_id, entity_type, embedding) "
        "VALUES ('fig_doomed', 'proj_doomed', 'figure', ?)",
        [vector],
    )

    await ProjectService(db).delete_project("proj_doomed", confirm=True)

    assert await db.fetchall(
        "SELECT id FROM vec_artifacts WHERE project_id = 'proj_doomed'"
    ) == []
