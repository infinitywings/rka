"""E1.2 regressions for project-isolated sqlite-vec retrieval."""

from __future__ import annotations

import asyncio
import struct

import pytest

import rka.services.embedding_reshape as embedding_reshape_module
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


async def _clear_project_filter_marker(db) -> None:
    await db.execute(
        "DELETE FROM runtime_schema_upgrades "
        "WHERE name = '053_vec_project_filters_v1'"
    )


@pytest.mark.asyncio
async def test_fresh_vec_tables_expose_project_filters_without_oversharding(
    db, monkeypatch
):
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
        assert "project_id text" in sql
        assert "project_id text partition key" not in sql

    row = await db.fetchone(
        "SELECT sql FROM sqlite_master WHERE name = 'vec_artifacts'"
    )
    sql = " ".join((row["sql"] or "").lower().split())
    assert "entity_type text" in sql
    assert "entity_type text partition key" not in sql
    assert await db.fetchone(
        "SELECT name FROM runtime_schema_upgrades "
        "WHERE name = '053_vec_project_filters_v1'"
    ) == {"name": "053_vec_project_filters_v1"}

    async def fail_if_lock_is_taken(_conn):
        raise AssertionError("idempotent startup must not take the migration lock")

    monkeypatch.setattr(db, "_begin_migration_transaction", fail_if_lock_is_taken)
    result = await ensure_vec_table_partitions(db)
    assert not any(result.values())


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
    await _clear_project_filter_marker(db)

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
async def test_sparse_partition_key_schema_is_compacted_to_metadata_filter(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")

    await _project(db, "proj_alpha")
    await _journal(db, "jrn_alpha", "proj_alpha", "alpha")
    await db.execute("DROP TABLE vec_journal")
    await db.execute(
        "CREATE VIRTUAL TABLE vec_journal USING vec0("
        "id TEXT PRIMARY KEY, project_id TEXT partition key, embedding float[4])"
    )
    await db.execute(
        "INSERT INTO vec_journal (id, project_id, embedding) VALUES (?, ?, ?)",
        ["jrn_alpha", "proj_alpha", _blob([1.0, 0.0, 0.0, 0.0])],
    )
    await _clear_project_filter_marker(db)

    result = await ensure_vec_table_partitions(db)

    assert result["vec_journal"] is True
    schema = await db.fetchone(
        "SELECT sql FROM sqlite_master WHERE name = 'vec_journal'"
    )
    normalized = " ".join((schema["sql"] or "").lower().split())
    assert "project_id text" in normalized
    assert "project_id text partition key" not in normalized
    assert await db.fetchone(
        "SELECT id, project_id FROM vec_journal WHERE id = 'jrn_alpha'"
    ) == {"id": "jrn_alpha", "project_id": "proj_alpha"}


@pytest.mark.asyncio
async def test_dual_partition_artifact_schema_upgrades_without_data_loss(db):
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")

    await _project(db, "proj_alpha")
    await _project(db, "proj_beta")
    await db.execute(
        """INSERT INTO artifacts (id, filename, filepath, project_id)
           VALUES ('art_alpha', 'alpha.png', '/tmp/alpha.png', 'proj_alpha'),
                  ('art_beta', 'beta.png', '/tmp/beta.png', 'proj_beta')"""
    )
    await db.execute(
        """INSERT INTO figures (id, artifact_id, caption, project_id)
           VALUES ('fig_alpha', 'art_alpha', 'alpha figure', 'proj_alpha')"""
    )
    await db.execute("DROP TABLE vec_artifacts")
    await db.execute(
        "CREATE VIRTUAL TABLE vec_artifacts USING vec0("
        "id TEXT PRIMARY KEY, project_id TEXT partition key, "
        "entity_type TEXT partition key, embedding float[4])"
    )
    vectors = {
        "art_alpha": _blob([0.8, 0.2, 0.0, 0.0]),
        "art_beta": _blob([1.0, 0.0, 0.0, 0.0]),
        "fig_alpha": _blob([0.7, 0.3, 0.0, 0.0]),
        "lost_legacy": _blob([0.99, 0.01, 0.0, 0.0]),
    }
    metadata = {
        "art_alpha": ("proj_alpha", "artifact"),
        "art_beta": ("proj_beta", "artifact"),
        "fig_alpha": ("proj_alpha", "figure"),
        "lost_legacy": ("proj_legacy", "legacy"),
    }
    for entity_id, embedding in vectors.items():
        project_id, entity_type = metadata[entity_id]
        await db.execute(
            "INSERT INTO vec_artifacts "
            "(id, project_id, entity_type, embedding) VALUES (?, ?, ?, ?)",
            [entity_id, project_id, entity_type, embedding],
        )
    await db.execute(
        "DELETE FROM runtime_schema_upgrades "
        "WHERE name = '053_vec_project_filters_v1'"
    )
    await db.execute(
        "INSERT OR IGNORE INTO runtime_schema_upgrades (name, details) "
        "VALUES ('053_vec_project_partitions_v1', 'early sparse schema')"
    )

    result = await ensure_vec_table_partitions(db)

    assert result["vec_artifacts"] is True
    schema = await db.fetchone(
        "SELECT sql FROM sqlite_master WHERE name = 'vec_artifacts'"
    )
    normalized = " ".join((schema["sql"] or "").lower().split())
    assert "project_id text partition key" not in normalized
    assert "entity_type text partition key" not in normalized
    rows = await db.fetchall(
        "SELECT id, project_id, entity_type, embedding "
        "FROM vec_artifacts ORDER BY id"
    )
    assert {
        row["id"]: (
            row["project_id"],
            row["entity_type"],
            bytes(row["embedding"]),
        )
        for row in rows
    } == {
        entity_id: (*metadata[entity_id], embedding)
        for entity_id, embedding in vectors.items()
    }
    markers = await db.fetchall(
        "SELECT name FROM runtime_schema_upgrades "
        "WHERE name LIKE '053_vec_project_%' ORDER BY name"
    )
    assert [row["name"] for row in markers] == [
        "053_vec_project_filters_v1",
        "053_vec_project_partitions_v1",
    ]

    artifact_hits = await SearchService(
        db=db, embeddings=None, project_id="proj_alpha"
    )._vector_search([1.0, 0.0, 0.0, 0.0], ["artifact"], 1)
    figure_hits = await SearchService(
        db=db, embeddings=None, project_id="proj_alpha"
    )._vector_search([1.0, 0.0, 0.0, 0.0], ["figure"], 1)
    assert [hit.entity_id for hit in artifact_hits] == ["art_alpha"]
    assert [hit.entity_id for hit in figure_hits] == ["fig_alpha"]

    second = await ensure_vec_table_partitions(db)
    assert not any(second.values())


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
    await _clear_project_filter_marker(db)

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

    claim_vector = _blob([0.0, 1.0, 0.0, 0.0])
    journal_vector = _blob([1.0, 0.0, 0.0, 0.0])
    for table_name, entity_id, vector in (
        ("vec_claims", "clm_survives", claim_vector),
        ("vec_journal", "jrn_survives", journal_vector),
    ):
        await db.execute(f"DROP TABLE {table_name}")
        await db.execute(
            f"CREATE VIRTUAL TABLE {table_name} USING vec0("
            "id TEXT PRIMARY KEY, embedding float[4])"
        )
        await db.execute(
            f"INSERT INTO {table_name} (id, embedding) VALUES (?, ?)",
            [entity_id, vector],
        )
    await db.execute(
        "DELETE FROM runtime_schema_upgrades "
        "WHERE name = '053_vec_project_filters_v1'"
    )
    original_execute = db.execute

    async def fail_upgrade(sql, params=None):
        if sql.startswith(failure_prefix):
            raise RuntimeError("injected upgrade failure")
        return await original_execute(sql, params)

    monkeypatch.setattr(db, "execute", fail_upgrade)
    with pytest.raises(RuntimeError, match="injected upgrade failure"):
        await ensure_vec_table_partitions(db)

    for table_name, entity_id, vector in (
        ("vec_claims", "clm_survives", claim_vector),
        ("vec_journal", "jrn_survives", journal_vector),
    ):
        schema = await db.fetchone(
            "SELECT sql FROM sqlite_master WHERE name = ?", [table_name]
        )
        assert "project_id text" not in (schema["sql"] or "").lower()
        row = await db.fetchone(
            f"SELECT id, embedding FROM {table_name} WHERE id = ?", [entity_id]
        )
        assert row["id"] == entity_id
        assert bytes(row["embedding"]) == vector
    assert await db.fetchone(
        "SELECT name FROM runtime_schema_upgrades "
        "WHERE name = '053_vec_project_filters_v1'"
    ) is None
    integrity = await db.fetchone("PRAGMA integrity_check")
    assert list(integrity.values()) == ["ok"]


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
        "WHERE name = '053_vec_project_filters_v1'"
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
        normalized = " ".join((schema["sql"] or "").lower().split())
        assert "project_id text" in normalized
        assert "project_id text partition key" not in normalized
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
            "WHERE name = '053_vec_project_filters_v1'"
        ) == {"name": "053_vec_project_filters_v1"}
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_concurrent_runtime_upgrade_waits_and_rereads_schema(
    tmp_path, monkeypatch
):
    db_path = str(tmp_path / "concurrent-upgrade.db")
    seed = Database(db_path)
    await seed.connect()
    await seed.initialize_schema()
    await seed.initialize_phase2_schema()
    if not seed.vec_available:
        await seed.close()
        pytest.skip("sqlite-vec extension not loaded")
    await _project(seed, "proj_alpha")
    await _journal(seed, "jrn_concurrent", "proj_alpha", "journal")
    await seed.execute(
        "INSERT INTO claims "
        "(id, source_entry_id, claim_type, content, project_id) "
        "VALUES ('clm_concurrent', 'jrn_concurrent', 'evidence', "
        "'claim', 'proj_alpha')"
    )
    await seed.execute(
        "INSERT INTO decisions (id, phase, question, decided_by, project_id) "
        "VALUES ('dec_concurrent', 'design', 'question', 'brain', 'proj_alpha')"
    )
    await seed.execute(
        "INSERT INTO literature (id, title, project_id) "
        "VALUES ('lit_concurrent', 'paper', 'proj_alpha')"
    )
    await seed.execute(
        "INSERT INTO missions (id, phase, objective, project_id) "
        "VALUES ('mis_concurrent', 'design', 'objective', 'proj_alpha')"
    )
    await seed.execute(
        "INSERT INTO artifacts (id, filename, filepath, project_id) "
        "VALUES ('art_concurrent', 'a.png', '/tmp/a.png', 'proj_alpha')"
    )
    await seed.execute(
        "INSERT INTO figures (id, artifact_id, caption, project_id) "
        "VALUES ('fig_concurrent', 'art_concurrent', 'figure', 'proj_alpha')"
    )
    vectors = {
        "vec_claims": {"clm_concurrent": _blob([1.0, 0.0, 0.0, 0.0])},
        "vec_journal": {"jrn_concurrent": _blob([2.0, 0.0, 0.0, 0.0])},
        "vec_decisions": {"dec_concurrent": _blob([3.0, 0.0, 0.0, 0.0])},
        "vec_literature": {"lit_concurrent": _blob([4.0, 0.0, 0.0, 0.0])},
        "vec_missions": {"mis_concurrent": _blob([5.0, 0.0, 0.0, 0.0])},
        "vec_artifacts": {
            "art_concurrent": _blob([6.0, 0.0, 0.0, 0.0]),
            "fig_concurrent": _blob([7.0, 0.0, 0.0, 0.0]),
        },
    }
    for table_name, table_vectors in vectors.items():
        await seed.execute(f"DROP TABLE {table_name}")
        columns = [
            "id TEXT PRIMARY KEY",
            "project_id TEXT partition key",
        ]
        if table_name == "vec_artifacts":
            columns.append("entity_type TEXT partition key")
        columns.append("embedding float[4]")
        await seed.execute(
            f"CREATE VIRTUAL TABLE {table_name} USING vec0("
            f"{', '.join(columns)})"
        )
        for entity_id, vector in table_vectors.items():
            if table_name == "vec_artifacts":
                await seed.execute(
                    f"INSERT INTO {table_name} "
                    "(id, project_id, entity_type, embedding) "
                    "VALUES (?, ?, ?, ?)",
                    [entity_id, "proj_stale", "legacy", vector],
                )
            else:
                await seed.execute(
                    f"INSERT INTO {table_name} "
                    "(id, project_id, embedding) VALUES (?, ?, ?)",
                    [entity_id, "proj_stale", vector],
                )
    await seed.execute(
        "DELETE FROM runtime_schema_upgrades "
        "WHERE name = '053_vec_project_filters_v1'"
    )
    await seed.commit()
    await seed.close()

    first = Database(db_path)
    second = Database(db_path)
    await first.connect()
    await second.connect()
    monkeypatch.setenv("RKA_MIGRATION_LOCK_TIMEOUT_MS", "5000")

    lock_held = asyncio.Event()
    release_first = asyncio.Event()
    second_load_started = asyncio.Event()
    original_first_load = first._load_sqlite_vec
    original_second_load = second._load_sqlite_vec
    original_ensure = embedding_reshape_module.ensure_vec_table_partitions
    first_load_calls = 0
    second_load_calls = 0
    upgrade_results: dict[int, list[dict[str, bool]]] = {
        id(first): [],
        id(second): [],
    }

    async def pause_first_load():
        nonlocal first_load_calls
        first_load_calls += 1
        lock_held.set()
        await release_first.wait()
        await original_first_load()

    async def observe_second_load():
        nonlocal second_load_calls
        second_load_calls += 1
        second_load_started.set()
        await original_second_load()

    async def record_upgrade(target_db):
        result = await original_ensure(target_db)
        upgrade_results[id(target_db)].append(result)
        return result

    monkeypatch.setattr(first, "_load_sqlite_vec", pause_first_load)
    monkeypatch.setattr(second, "_load_sqlite_vec", observe_second_load)
    monkeypatch.setattr(
        embedding_reshape_module,
        "ensure_vec_table_partitions",
        record_upgrade,
    )

    first_task = asyncio.create_task(first.initialize_phase2_schema())
    second_task = None
    try:
        await asyncio.wait_for(lock_held.wait(), timeout=1)
        second_task = asyncio.create_task(second.initialize_phase2_schema())
        await asyncio.sleep(0.05)
        assert not second_load_started.is_set()
        assert not second_task.done()
        release_first.set()
        await asyncio.wait_for(
            asyncio.gather(first_task, second_task), timeout=5
        )
    finally:
        release_first.set()
        if not first_task.done():
            first_task.cancel()
        if second_task is not None and not second_task.done():
            second_task.cancel()
        await asyncio.gather(
            first_task,
            *(task for task in (second_task,) if task is not None),
            return_exceptions=True,
        )
        await first.close()
        await second.close()

    assert first_load_calls == 1
    assert second_load_calls == 1
    assert sum(
        sum(result.values()) for result in upgrade_results[id(first)]
    ) == 6
    assert not any(
        value
        for result in upgrade_results[id(second)]
        for value in result.values()
    )
    monkeypatch.setattr(
        embedding_reshape_module,
        "ensure_vec_table_partitions",
        original_ensure,
    )
    verify = Database(db_path)
    await verify.connect()
    await verify.initialize_phase2_schema()
    try:
        integrity = await verify.fetchone("PRAGMA integrity_check")
        assert list(integrity.values()) == ["ok"]
        assert await verify.fetchall("PRAGMA foreign_key_check") == []
        for table_name, table_vectors in vectors.items():
            schema = await verify.fetchone(
                "SELECT sql FROM sqlite_master WHERE name = ?", [table_name]
            )
            normalized = " ".join((schema["sql"] or "").lower().split())
            assert "project_id text" in normalized
            assert "project_id text partition key" not in normalized
            rows = await verify.fetchall(
                f"SELECT * FROM {table_name} ORDER BY id"
            )
            assert len(rows) == len(table_vectors)
            for row in rows:
                assert row["project_id"] == "proj_alpha"
                assert bytes(row["embedding"]) == table_vectors[row["id"]]
            if table_name == "vec_artifacts":
                assert "entity_type text partition key" not in normalized
                assert {
                    row["id"]: row["entity_type"] for row in rows
                } == {
                    "art_concurrent": "artifact",
                    "fig_concurrent": "figure",
                }
        assert await verify.fetchone(
            "SELECT name FROM runtime_schema_upgrades "
            "WHERE name = '053_vec_project_filters_v1'"
        ) == {"name": "053_vec_project_filters_v1"}
    finally:
        await verify.close()


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
        "id TEXT PRIMARY KEY, project_id TEXT, embedding float[4])"
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
        "id TEXT PRIMARY KEY, project_id TEXT, "
        "entity_type TEXT, embedding float[4])"
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
