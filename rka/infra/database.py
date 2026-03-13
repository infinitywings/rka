"""SQLite database connection and initialization."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)


class Database:
    """Async SQLite database wrapper."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._vec_loaded = False

    async def connect(self) -> None:
        """Open database connection and apply PRAGMAs."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        # Enable loading extensions (needed for sqlite-vec)
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA busy_timeout = 5000")
        # Allow extension loading for sqlite-vec (must run on aiosqlite's thread)
        try:
            await self._conn._execute(self._conn._conn.enable_load_extension, True)
        except (AttributeError, Exception):
            pass  # Some Python builds don't support this

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def initialize_schema(self) -> None:
        """Create tables from schema.sql if they don't exist, then run migrations."""
        schema_path = Path(__file__).parent.parent / "db" / "schema.sql"
        schema_sql = schema_path.read_text()
        await self._conn.executescript(schema_sql)
        await self._conn.commit()
        await self.run_migrations()

    async def run_migrations(self) -> int:
        """Run pending SQL migrations from rka/db/migrations/.

        Returns the number of newly applied migrations.
        """
        # Ensure the tracking table exists
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  filename TEXT PRIMARY KEY,"
            "  applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))"
            ")"
        )
        await self._conn.commit()

        migrations_dir = Path(__file__).parent.parent / "db" / "migrations"
        if not migrations_dir.exists():
            return 0

        # Gather .sql files sorted by name
        sql_files = sorted(f for f in migrations_dir.iterdir() if f.suffix == ".sql")
        if not sql_files:
            return 0

        # Fetch already-applied filenames
        cursor = await self._conn.execute("SELECT filename FROM schema_migrations")
        applied = {row[0] for row in await cursor.fetchall()}

        count = 0
        for sql_file in sql_files:
            if sql_file.name in applied:
                continue

            sql = sql_file.read_text()

            # Skip vec0 virtual tables if sqlite-vec is not loaded
            if "USING vec0(" in sql and not self._vec_loaded:
                logger.info(
                    "Skipping migration %s (sqlite-vec not available)", sql_file.name
                )
                continue

            logger.info("Applying migration: %s", sql_file.name)
            await self._conn.executescript(sql)
            await self._conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (?)",
                [sql_file.name],
            )
            await self._conn.commit()
            count += 1

        if count:
            logger.info("Applied %d migration(s)", count)
        return count

    async def initialize_phase2_schema(self) -> None:
        """Load sqlite-vec extension and create Phase 2 tables (FTS5 + vec)."""
        # Try to load sqlite-vec extension
        await self._load_sqlite_vec()
        # Re-run migrations now that vec may be available. This lets skipped
        # vec-specific migrations apply on a later startup once the extension loads.
        await self.run_migrations()

        schema_path = Path(__file__).parent.parent / "db" / "schema_phase2.sql"
        if not schema_path.exists():
            logger.warning("Phase 2 schema not found at %s", schema_path)
            return

        schema_sql = schema_path.read_text()

        if not self._vec_loaded:
            # Strip sqlite-vec virtual table CREATE statements if extension not loaded
            lines = schema_sql.split("\n")
            filtered = []
            skip = False
            for line in lines:
                if "USING vec0(" in line:
                    skip = True
                    continue
                if skip and ");" in line:
                    skip = False
                    continue
                if skip:
                    continue
                filtered.append(line)
            schema_sql = "\n".join(filtered)
            logger.info("sqlite-vec not available; skipping vector tables. FTS5 still active.")

        await self._conn.executescript(schema_sql)
        await self._conn.commit()
        logger.info("Phase 2 schema initialized (vec=%s)", self._vec_loaded)

    async def _load_sqlite_vec(self) -> None:
        """Try to load the sqlite-vec extension (runs on aiosqlite's thread)."""
        load_errors: list[str] = []

        for candidate in self._sqlite_vec_candidates():
            try:
                await self._conn._execute(self._conn._conn.load_extension, str(candidate))
                self._vec_loaded = True
                logger.info("sqlite-vec extension loaded from %s", candidate)
                return
            except Exception as exc:
                load_errors.append(f"{candidate}: {exc}")

        try:
            import sqlite_vec
            await self._conn._execute(sqlite_vec.load, self._conn._conn)
            self._vec_loaded = True
            logger.info("sqlite-vec extension loaded successfully via sqlite_vec package")
        except ImportError:
            logger.info("sqlite-vec not installed; vector search disabled")
            self._vec_loaded = False
        except Exception as exc:
            if load_errors:
                logger.warning(
                    "Failed to load sqlite-vec. Tried explicit paths [%s] and package loader error: %s",
                    "; ".join(load_errors),
                    exc,
                )
            else:
                logger.warning("Failed to load sqlite-vec: %s", exc)
            self._vec_loaded = False

    def _sqlite_vec_candidates(self) -> list[Path]:
        """Return possible loadable extension paths for sqlite-vec."""
        seen: set[str] = set()
        candidates: list[Path] = []

        def _add(path_str: str | None) -> None:
            if not path_str:
                return
            path = Path(path_str)
            key = str(path)
            if key in seen:
                return
            seen.add(key)
            candidates.append(path)

        _add(os.getenv("RKA_SQLITE_VEC_PATH"))
        for path_str in (
            "/usr/local/lib/vec0",
            "/usr/local/lib/vec0.so",
            "/usr/local/lib/vec0.dylib",
            "/usr/local/lib/vec0.dll",
        ):
            _add(path_str)

        try:
            import sqlite_vec

            package_dir = Path(sqlite_vec.__file__).resolve().parent
            for name in ("vec0", "vec0.so", "vec0.dylib", "vec0.dll"):
                _add(str(package_dir / name))
        except ImportError:
            pass

        return [path for path in candidates if path.exists()]

    @property
    def vec_available(self) -> bool:
        """Whether sqlite-vec extension is loaded."""
        return self._vec_loaded

    async def execute(self, sql: str, params: list | tuple | None = None) -> aiosqlite.Cursor:
        """Execute a single SQL statement."""
        if params:
            return await self._conn.execute(sql, params)
        return await self._conn.execute(sql)

    async def executemany(self, sql: str, params_list: list) -> aiosqlite.Cursor:
        """Execute SQL with multiple parameter sets."""
        return await self._conn.executemany(sql, params_list)

    async def fetchone(self, sql: str, params: list | tuple | None = None) -> dict | None:
        """Fetch a single row as a dict."""
        cursor = await self.execute(sql, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def fetchall(self, sql: str, params: list | tuple | None = None) -> list[dict]:
        """Fetch all rows as dicts."""
        cursor = await self.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._conn.commit()

    @property
    def conn(self) -> aiosqlite.Connection:
        """Get the raw connection (for transactions)."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn
