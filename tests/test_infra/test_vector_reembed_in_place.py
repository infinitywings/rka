"""Re-embedding an entity must replace its vector, not keep the old one.

`vec0` virtual tables do not honour the REPLACE conflict clause. The write
path used `INSERT OR REPLACE`, so every re-embed of an entity that already
had a vector raised `UNIQUE constraint failed on <table> primary key` — and
`BaseService._sync_embedding` swallowed that at `logger.debug`, which is off
by default.

The result: an edited entry kept the vector for its withdrawn text. It stayed
semantically retrievable by wording that is no longer in it, and was
unretrievable by the wording that is. FTS updated correctly, so the entry
looked repaired. It never self-healed — every later edit raised and was
swallowed again.

Nothing in this suite re-embedded in place before, which is why the defect
survived the PRs (#101, #106) that fixed the same bug in the backfill path.
"""

import inspect
import struct

import pytest

from rka.infra.database import Database
from rka.services.base import BaseService


def _vec(*values: float) -> bytes:
    return struct.pack(f"{len(values)}f", *values)


class TestVec0RejectsReplace:
    """The premise. If this ever stops being true, the fix is unnecessary."""

    def test_insert_or_replace_raises_on_a_vec0_table(self):
        import sqlite3

        import sqlite_vec

        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            "CREATE VIRTUAL TABLE t USING vec0(id TEXT PRIMARY KEY, embedding float[4])"
        )
        conn.execute("INSERT INTO t (id, embedding) VALUES (?, ?)", ["a", _vec(1, 0, 0, 0)])

        with pytest.raises(Exception, match="UNIQUE constraint failed"):
            conn.execute(
                "INSERT OR REPLACE INTO t (id, embedding) VALUES (?, ?)",
                ["a", _vec(0, 1, 0, 0)],
            )

    def test_delete_then_insert_does_not(self):
        import sqlite3

        import sqlite_vec

        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            "CREATE VIRTUAL TABLE t USING vec0(id TEXT PRIMARY KEY, embedding float[4])"
        )
        conn.execute("INSERT INTO t (id, embedding) VALUES (?, ?)", ["a", _vec(1, 0, 0, 0)])
        conn.execute("DELETE FROM t WHERE id = ?", ["a"])
        conn.execute("INSERT INTO t (id, embedding) VALUES (?, ?)", ["a", _vec(0, 1, 0, 0)])

        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 1


class _StubBackend:
    """Returns a different vector per text, so a stale write is detectable."""

    model_name = "stub"
    dim = 768  # matches the vec_journal column the schema creates

    async def embed(self, text: str, is_query: bool = False) -> list[float]:
        return self._for(text)

    async def embed_batch(
        self, texts: list[str], is_query: bool = False
    ) -> list[list[float]]:
        return [self._for(t) for t in texts]

    @staticmethod
    def _for(text: str) -> list[float]:
        v = [0.0] * 768
        v[0 if "original" in text else 1] = 1.0
        return v


class TestTheStoredVectorFollowsTheText:
    @pytest.mark.asyncio
    async def test_re_embedding_replaces_the_vector(self, db: Database):
        from rka.infra.embeddings import EmbeddingService

        if not db.vec_available:
            pytest.skip("sqlite-vec not loaded in this environment")

        svc = EmbeddingService(model_name="stub", db=db, backend=_StubBackend())

        await svc.store_embedding(
            "journal", "jrn_x", "the original wording", project_id="prj_t",
        )
        await svc.store_embedding(
            "journal", "jrn_x", "the revised wording", project_id="prj_t",
        )

        rows = await db.fetchall(
            "SELECT embedding FROM vec_journal WHERE id = ?", ["jrn_x"],
        )
        assert len(rows) == 1, "re-embedding must not leave two vectors"

        stored = struct.unpack("768f", rows[0]["embedding"])
        assert (stored[0], stored[1]) == pytest.approx((0.0, 1.0)), (
            "the stored vector still matches the withdrawn text; the entity is "
            "retrievable by wording it no longer contains"
        )


class TestTheFailureIsNoLongerSilent:
    def test_embedding_sync_logs_at_the_same_level_as_fts_sync(self):
        src = inspect.getsource(BaseService._sync_embedding)
        assert "logger.warning" in src, (
            "debug is off by default, so a permanently stale vector produced "
            "no signal anywhere"
        )
        assert "logger.debug" not in src

    def test_the_message_says_what_to_do(self):
        src = inspect.getsource(BaseService._sync_embedding)
        assert "backfill" in src.lower(), (
            "a warning a reader cannot act on is only noise"
        )
