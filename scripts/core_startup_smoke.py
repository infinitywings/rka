#!/usr/bin/env python3
"""Start and probe the supported RKA Core surfaces in disposable state."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from typing import TextIO

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


def _available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run_cli(
    cli: list[str], args: list[str], env: dict[str, str], cwd: Path
) -> str:
    result = subprocess.run(
        [*cli, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode:
        raise RuntimeError(
            f"{' '.join(args)} failed ({result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout


def _wait_for_health(base_url: str, server: subprocess.Popen[str]) -> dict:
    deadline = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"REST server exited early with status {server.returncode}")
        try:
            response = httpx.get(f"{base_url}/api/health", timeout=2)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.2)
    raise RuntimeError(f"REST health did not become ready: {last_error}")


def _assert_migration_state(db_path: Path, *, require_vec: bool) -> None:
    with sqlite3.connect(db_path) as conn:
        migrations = {
            row[0] for row in conn.execute("SELECT filename FROM schema_migrations")
        }
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }

    required_migrations = set()
    if require_vec:
        required_migrations = {
            "002_add_vec_artifacts.sql",
            "010_v2_vec_claims.sql",
        }
    missing_migrations = required_migrations - migrations
    if missing_migrations:
        raise RuntimeError(
            f"migrate omitted vector migrations: {sorted(missing_migrations)}"
        )

    required_tables = {
        "projects",
        "journal",
        "decisions",
        "fts_journal",
        "schema_migrations",
    }
    if require_vec:
        required_tables |= {
            "embedding_metadata",
            "vec_artifacts",
            "vec_claims",
            "vec_journal",
        }
    missing_tables = required_tables - tables
    if missing_tables:
        raise RuntimeError(f"migrate omitted Phase-2 tables: {sorted(missing_tables)}")


async def _probe_mcp(
    python: str, cwd: Path, env: dict[str, str], errlog: TextIO
) -> None:
    params = StdioServerParameters(
        command=python,
        args=["-m", "rka", "mcp"],
        cwd=cwd,
        env=env,
    )
    async with stdio_client(params, errlog=errlog) as (read, write):
        async with ClientSession(
            read,
            write,
            read_timeout_seconds=timedelta(seconds=15),
        ) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            required = {
                "rka_query",
                "rka_execute",
                "rka_describe",
                "rka_load_tools",
                "rka_help",
            }
            missing = required - names
            if missing:
                raise RuntimeError(
                    f"MCP startup omitted required tools: {sorted(missing)}"
                )

            result = await session.call_tool(
                "rka_query",
                {"args": {"operation": "health"}},
            )
            if result.isError:
                raise RuntimeError(f"MCP health call failed: {result.content}")
            rendered = "\n".join(
                block.text for block in result.content if hasattr(block, "text")
            )
            payload = json.loads(rendered)
            if payload.get("status") not in {"ok", "healthy"}:
                raise RuntimeError(f"unexpected MCP health result: {rendered}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-web",
        action="store_true",
        help="Fail unless the built web dashboard is served from /.",
    )
    parser.add_argument(
        "--require-vec",
        action="store_true",
        help="Fail unless sqlite-vec and the Phase-2 vector schema are available.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter whose installed RKA package should be tested.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=ROOT,
        help="Working directory for all tested RKA subprocesses.",
    )
    args = parser.parse_args()

    # Do not resolve the interpreter symlink: a venv's ``python`` commonly
    # points at the base interpreter, and resolving it would silently discard
    # the isolated environment we intend to test.
    runtime_python = str(Path(args.python).expanduser().absolute())
    runtime_cwd = args.cwd.expanduser().resolve()
    runtime_cwd.mkdir(parents=True, exist_ok=True)
    cli = [runtime_python, "-m", "rka"]

    with tempfile.TemporaryDirectory(prefix="rka-core-smoke-") as temp_dir:
        data_dir = Path(temp_dir)
        port = _available_port()
        base_url = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        # A clean-wheel smoke must not import RKA from a source checkout or
        # inherit a caller's project-local database selection.
        env.pop("PYTHONPATH", None)
        env.pop("RKA_DB_PATH", None)
        env.pop("RKA_PROJECT_DIR", None)
        env.update(
            {
                "RKA_DATA_DIR": str(data_dir),
                "RKA_LLM_ENABLED": "false",
                # Avoid a model download while still proving sqlite-vec loads.
                "RKA_EMBEDDINGS_ENABLED": "false",
                "RKA_API_URL": base_url,
                "PYTHONUNBUFFERED": "1",
            }
        )

        db_path = data_dir / "rka.db"
        version_output = _run_cli(cli, ["--version"], env, runtime_cwd)
        migration_output = _run_cli(cli, ["migrate"], env, runtime_cwd)
        if not db_path.is_file():
            raise RuntimeError(f"default database was not created under data_dir: {db_path}")
        stray_db = runtime_cwd / "rka.db"
        if stray_db != db_path and stray_db.exists():
            raise RuntimeError(f"RKA created a cwd-relative database: {stray_db}")
        _assert_migration_state(db_path, require_vec=args.require_vec)
        worker_output = _run_cli(cli, ["worker", "--once"], env, runtime_cwd)

        log_path = data_dir / "server.log"
        mcp_log_path = data_dir / "mcp.log"
        with (
            log_path.open("w+", encoding="utf-8") as log,
            mcp_log_path.open("w+", encoding="utf-8") as mcp_log,
        ):
            server = subprocess.Popen(
                [*cli, "serve", "--host", "127.0.0.1", "--port", str(port)],
                cwd=runtime_cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                health = _wait_for_health(base_url, server)
                if health.get("status") != "ok":
                    raise RuntimeError(f"unexpected REST health payload: {health}")
                if args.require_vec and health.get("vec_available") is not True:
                    raise RuntimeError(f"sqlite-vec unavailable: {health}")

                web_index = ROOT / "web" / "dist" / "index.html"
                if args.require_web and not web_index.is_file():
                    raise RuntimeError("--require-web was set but web/dist/index.html is absent")
                if args.require_web:
                    dashboard = httpx.get(f"{base_url}/", timeout=5)
                    dashboard.raise_for_status()
                    if "text/html" not in dashboard.headers.get("content-type", ""):
                        raise RuntimeError("web dashboard did not return HTML")

                    asset_match = re.search(r'src="(/assets/[^"]+\.js)"', dashboard.text)
                    if not asset_match:
                        raise RuntimeError("web dashboard HTML references no JavaScript asset")
                    asset = httpx.get(f"{base_url}{asset_match.group(1)}", timeout=5)
                    asset.raise_for_status()
                    content_type = asset.headers.get("content-type", "")
                    if "javascript" not in content_type:
                        raise RuntimeError(
                            f"web dashboard asset has unexpected content type: {content_type}"
                        )

                    brand_icon = httpx.get(
                        f"{base_url}/brand/rka-project-plugin-app-icon.svg",
                        timeout=5,
                    )
                    brand_icon.raise_for_status()
                    brand_content_type = brand_icon.headers.get("content-type", "")
                    if "image/svg+xml" not in brand_content_type:
                        raise RuntimeError(
                            "web brand icon has unexpected content type: "
                            f"{brand_content_type}"
                        )
                    if not brand_icon.text.lstrip().startswith("<svg"):
                        raise RuntimeError(
                            "web brand icon did not return SVG content; "
                            "the SPA fallback may have masked a missing asset"
                        )

                asyncio.run(
                    asyncio.wait_for(
                        _probe_mcp(runtime_python, runtime_cwd, env, mcp_log),
                        timeout=30,
                    )
                )
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read(), file=sys.stderr)
                mcp_log.flush()
                mcp_log.seek(0)
                print(mcp_log.read(), file=sys.stderr)
                raise
            finally:
                if server.poll() is None:
                    server.terminate()
                    try:
                        server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=5)

        print(
            "Core startup smoke passed: installed entry point, migrations, REST, MCP, worker"
            + (", sqlite-vec" if args.require_vec else "")
            + (", and web dashboard." if args.require_web else ".")
        )
        print(version_output.strip())
        print(migration_output.strip())
        print(worker_output.strip())


if __name__ == "__main__":
    main()
