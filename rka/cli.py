"""RKA CLI — init, serve, mcp, status."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from rka import __version__


@click.group()
@click.version_option(version=__version__)
def main():
    """Research Knowledge Agent — AI-assisted research orchestration."""
    pass


@main.command()
@click.argument("name")
@click.option("--description", "-d", default=None, help="Project description")
@click.option("--dir", "directory", default=".", help="Project directory")
def init(name: str, description: str | None, directory: str):
    """Initialize a new RKA project."""
    from rka.infra.database import Database
    from rka.services.project import ProjectService

    project_dir = Path(directory).resolve()
    db_path = project_dir / "rka.db"

    async def _init():
        db = Database(str(db_path))
        await db.connect()
        await db.initialize_schema()

        svc = ProjectService(db)
        state = await svc.initialize(name, description)
        await db.close()
        return state

    state = asyncio.run(_init())
    click.echo(f"✅ Initialized RKA project: {state.project_name}")
    click.echo(f"   Database: {db_path}")
    click.echo(f"   Phase: {state.current_phase}")
    click.echo("\nRun 'rka serve' to start the API server.")

    # Create .env file if it doesn't exist
    env_path = project_dir / ".env"
    if not env_path.exists():
        env_path.write_text(
            f"# RKA Configuration\n"
            f"RKA_PROJECT_DIR={project_dir}\n"
            f"RKA_DB_PATH=rka.db\n"
            f"RKA_HOST=127.0.0.1\n"
            f"RKA_PORT=9712\n"
            f"\n"
            f"# LLM (Phase 2 — uncomment when ready)\n"
            f"# RKA_LLM_MODEL=<provider/model>\n"
            f"# RKA_LLM_API_BASE=<your_openai_compatible_endpoint>\n"
            f"# RKA_LLM_ENABLED=true\n"
            f"# RKA_EMBEDDINGS_ENABLED=true\n"
        )
        click.echo("   Created .env file")


@main.command()
@click.option("--host", default=None, help="Override host")
@click.option("--port", default=None, type=int, help="Override port")
@click.option("--reload", "do_reload", is_flag=True, help="Enable auto-reload for development")
def serve(host: str | None, port: int | None, do_reload: bool):
    """Start the RKA API server."""
    import uvicorn
    from rka.config import RKAConfig

    config = RKAConfig()
    h = host or config.host
    p = port or config.port

    click.echo(f"🚀 Starting RKA server at http://{h}:{p}")
    click.echo(f"   API docs: http://{h}:{p}/docs")
    click.echo(f"   Database: {config.database_url}")

    uvicorn.run(
        "rka.api.app:create_app",
        factory=True,
        host=h,
        port=p,
        reload=do_reload,
        log_level="info",
    )


@main.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http"], case_sensitive=False),
    default=None,
    help="Transport mode: stdio (default, for Claude Desktop / Claude Code) or http (Streamable HTTP, dev/remote access).",
)
@click.option("--host", default="127.0.0.1", help="Host for HTTP transport only.")
@click.option("--port", default=9713, type=int, help="Port for HTTP transport only. Default 9713 (avoids REST API port 9712).")
def mcp(transport: str | None, host: str, port: int):
    """Start the MCP server.

    Defaults to stdio transport (Claude Desktop spawns this as a subprocess).
    HTTP transport is opt-in via --transport http or RKA_MCP_TRANSPORT=http
    for dev, remote access, or mitmproxy-based debugging.
    """
    import os
    from rka.mcp.server import mcp as mcp_server

    # Resolve effective transport: CLI flag > env var > stdio default.
    effective = (transport or os.environ.get("RKA_MCP_TRANSPORT") or "stdio").lower()

    if effective == "http":
        mcp_server.settings.host = host
        mcp_server.settings.port = port
        click.echo(
            f"🚀 Starting MCP server on Streamable HTTP at http://{host}:{port}"
            f"{mcp_server.settings.streamable_http_path}"
        )
        mcp_server.run(transport="streamable-http")
    else:
        # stdio — the default for Claude Desktop / Claude Code subprocess integration.
        mcp_server.run()


@main.command()
@click.option("--poll-interval", default=None, type=float, help="Override worker poll interval")
@click.option("--lease-seconds", default=None, type=int, help="Override job lease duration")
@click.option("--max-attempts", default=None, type=int, help="Override max attempts per job")
@click.option("--once", is_flag=True, help="Process at most one available job and exit")
def worker(
    poll_interval: float | None,
    lease_seconds: int | None,
    max_attempts: int | None,
    once: bool,
):
    """Run the background enrichment worker."""
    from rka.config import RKAConfig
    from rka.infra.database import Database
    from rka.infra.embeddings import EmbeddingService
    from rka.services.worker import EnrichmentWorker

    config = RKAConfig()

    async def _worker():
        db = Database(config.database_url)
        await db.connect()
        await db.initialize_schema()
        await db.initialize_phase2_schema()

        try:
            embeddings = (
                EmbeddingService(model_name=config.embedding_model, db=db)
                if config.embeddings_enabled
                else None
            )
            runner = EnrichmentWorker(
                db=db,
                embeddings=embeddings,
                poll_interval=poll_interval or config.job_poll_interval,
                lease_seconds=lease_seconds or config.job_lease_seconds,
                max_attempts=max_attempts or config.job_max_attempts,
            )

            if once:
                handled = await runner.run_once()
                click.echo("Processed 1 job." if handled else "No jobs available.")
                return

            click.echo(f"Starting worker for {config.database_url}")
            await runner.run_forever()
        finally:
            await db.close()

    try:
        asyncio.run(_worker())
    except KeyboardInterrupt:
        click.echo("Worker stopped.")


@main.command()
def status():
    """Show current project status."""
    from rka.config import RKAConfig
    from rka.infra.database import Database
    from rka.services.project import ProjectService
    from rka.services.missions import MissionService
    from rka.services.checkpoints import CheckpointService

    config = RKAConfig()

    async def _status():
        db = Database(config.database_url)
        await db.connect()

        proj_svc = ProjectService(db)
        state = await proj_svc.get()
        if state is None:
            click.echo("❌ Project not initialized. Run `rka init <name>` first.")
            await db.close()
            return

        mis_svc = MissionService(db)
        active = await mis_svc.list(status="active", limit=1)

        chk_svc = CheckpointService(db)
        open_chks = await chk_svc.list(status="open")

        click.echo(f"📋 Project: {state.project_name}")
        click.echo(f"   Phase: {state.current_phase or 'not set'}")
        if state.summary:
            click.echo(f"   Summary: {state.summary[:120]}")
        if state.blockers:
            click.echo(f"   ⚠️  Blockers: {state.blockers}")

        if active:
            m = active[0]
            click.echo(f"\n▶  Active Mission: {m.id}")
            click.echo(f"   {m.objective[:100]}")

        if open_chks:
            click.echo(f"\n🔔 Open Checkpoints: {len(open_chks)}")
            for chk in open_chks[:5]:
                icon = "🔴" if chk.blocking else "🟡"
                click.echo(f"   {icon} {chk.id}: {chk.description[:80]}")

        await db.close()

    asyncio.run(_status())


@main.command()
@click.option("--output", "-o", default=None, help="Output file path")
def backup(output: str | None):
    """Backup the database to a file."""
    import shutil
    from rka.config import RKAConfig

    config = RKAConfig()
    src = Path(config.database_url)
    if not src.exists():
        click.echo("❌ No database found.")
        return

    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = Path(output) if output else src.parent / f"rka_backup_{timestamp}.db"
    shutil.copy2(src, dst)
    click.echo(f"✅ Backed up to {dst}")


@main.command()
def migrate():
    """Run pending database migrations."""
    from rka.config import RKAConfig
    from rka.infra.database import Database

    config = RKAConfig()

    async def _migrate():
        db = Database(config.database_url)
        await db.connect()
        # initialize_schema runs the base schema + migrations;
        # run_migrations() returns 0 if already applied (idempotent)
        await db.initialize_schema()
        count = await db.run_migrations()
        await db.close()
        return count

    count = asyncio.run(_migrate())
    click.echo(f"Applied {count} migration(s).")


@main.group()
def bootstrap():
    """Workspace bootstrap — scan and ingest research files."""
    pass


@main.command()
def backfill():
    """Backfill entity_links from legacy JSON arrays in existing entries."""
    from rka.config import RKAConfig
    from rka.infra.database import Database
    from rka.services.backfill import backfill_entity_links

    config = RKAConfig()

    async def _backfill():
        db = Database(config.database_url)
        await db.connect()
        await db.initialize_schema()
        counts = await backfill_entity_links(db)
        await db.close()
        return counts

    counts = asyncio.run(_backfill())
    click.echo("Entity links backfill complete:")
    for source, count in counts.items():
        click.echo(f"  {source}: {count} links created")
    click.echo(f"  Total: {sum(counts.values())}")


@main.command("backfill-embeddings")
@click.option("--project", "project_id", default="proj_default", help="Project id to backfill")
@click.option("--batch-size", default=50, show_default=True, type=int, help="Rows per batch")
@click.option("--figures/--no-figures", default=True, help="Backfill figure embeddings")
@click.option("--artifacts/--no-artifacts", default=True, help="Backfill artifact embeddings")
@click.option("--force", is_flag=True, help="Re-embed even if metadata is current")
def backfill_embeddings_cmd(
    project_id: str,
    batch_size: int,
    figures: bool,
    artifacts: bool,
    force: bool,
):
    """Backfill artifact and figure embeddings for a project."""
    from rka.config import RKAConfig
    from rka.infra.database import Database
    from rka.infra.embeddings import EmbeddingService
    from rka.services.backfill import backfill_embeddings

    config = RKAConfig()

    async def _run():
        db = Database(config.database_url)
        await db.connect()
        await db.initialize_schema()
        await db.initialize_phase2_schema()
        embeddings = EmbeddingService(model_name=config.embedding_model, db=db)
        counts = await backfill_embeddings(
            db,
            embeddings,
            project_id=project_id,
            batch_size=batch_size,
            include_artifacts=artifacts,
            include_figures=figures,
            force=force,
        )
        await db.close()
        return counts

    counts = asyncio.run(_run())
    click.echo(f"Embedding backfill complete for {project_id}:")
    for entity_type, count in counts.items():
        click.echo(f"  {entity_type}: {count}")


@bootstrap.command("scan")
@click.argument("folder")
@click.option("--ignore", "-i", multiple=True, help="Additional ignore patterns")
@click.option("--no-llm", is_flag=True, help="Disable LLM-enhanced classification")
@click.option("--json-output", is_flag=True, help="Output raw JSON manifest")
def bootstrap_scan(folder: str, ignore: tuple, no_llm: bool, json_output: bool):
    """Scan a workspace folder and preview file classifications."""
    from rka.config import RKAConfig
    from rka.infra.database import Database
    from rka.infra.llm import LLMClient
    from rka.services.workspace import WorkspaceService
    from rka.services.notes import NoteService
    from rka.services.literature import LiteratureService
    from rka.services.academic import AcademicImportService

    config = RKAConfig()

    async def _scan():
        db = Database(config.database_url)
        await db.connect()
        await db.initialize_schema()

        llm = LLMClient(config) if config.llm_enabled and not no_llm else None
        note_svc = NoteService(db, llm=llm)
        lit_svc = LiteratureService(db, llm=llm)
        academic_svc = AcademicImportService(lit_svc, note_service=note_svc)
        ws_svc = WorkspaceService(db, academic_svc, note_svc, lit_svc, llm=llm)

        manifest = await ws_svc.scan(
            folder_path=folder,
            ignore_patterns=list(ignore),
            use_llm=not no_llm,
        )
        await db.close()
        return manifest

    manifest = asyncio.run(_scan())

    if json_output:
        click.echo(manifest.model_dump_json(indent=2))
        return

    click.echo(f"📂 Scanned: {manifest.root_path}")
    click.echo(f"   Scan ID: {manifest.scan_id}")
    click.echo(f"   Files: {manifest.total_files_found} found, {manifest.total_files_scanned} scanned")
    click.echo(f"   Categories: {manifest.summary.by_category}")
    click.echo(f"   Targets: {manifest.summary.by_target}")

    if manifest.summary.duplicate_count:
        click.echo(f"   ⚠️  Duplicates: {manifest.summary.duplicate_count}")
    if manifest.summary.llm_classified_count:
        click.echo(f"   🤖 LLM-classified: {manifest.summary.llm_classified_count}")

    click.echo(f"\nFiles ({len(manifest.files)}):")
    for f in manifest.files:
        dup = " [DUP]" if f.is_duplicate else ""
        llm_tag = " [LLM]" if f.llm_classified else ""
        click.echo(f"  {f.relative_path} [{f.category.value}→{f.proposed_type}]{dup}{llm_tag}")

    if manifest.warnings:
        click.echo("\n⚠️  Warnings:")
        for w in manifest.warnings:
            click.echo(f"  - {w}")

    click.echo(f"\nRun 'rka bootstrap ingest {folder}' to ingest these files.")


@bootstrap.command("ingest")
@click.argument("folder")
@click.option("--phase", "-p", default=None, help="Research phase for all entries")
@click.option("--tags", "-t", multiple=True, help="Tags to add to all entries")
@click.option("--skip", "-s", multiple=True, help="Relative paths to skip")
@click.option("--no-llm", is_flag=True, help="Disable LLM-enhanced classification")
@click.option("--dry-run", is_flag=True, help="Preview without creating entries")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def bootstrap_ingest(
    folder: str, phase: str | None, tags: tuple,
    skip: tuple, no_llm: bool, dry_run: bool, yes: bool,
):
    """Scan and ingest a workspace folder into the knowledge base."""
    from rka.config import RKAConfig
    from rka.infra.database import Database
    from rka.infra.llm import LLMClient
    from rka.services.workspace import WorkspaceService
    from rka.services.notes import NoteService
    from rka.services.literature import LiteratureService
    from rka.services.academic import AcademicImportService
    from rka.models.workspace import WorkspaceIngestRequest

    config = RKAConfig()

    async def _ingest():
        db = Database(config.database_url)
        await db.connect()
        await db.initialize_schema()

        llm = LLMClient(config) if config.llm_enabled and not no_llm else None
        note_svc = NoteService(db, llm=llm)
        lit_svc = LiteratureService(db, llm=llm)
        academic_svc = AcademicImportService(lit_svc, note_service=note_svc)
        ws_svc = WorkspaceService(db, academic_svc, note_svc, lit_svc, llm=llm)

        # Scan
        manifest = await ws_svc.scan(
            folder_path=folder,
            ignore_patterns=[],
            use_llm=not no_llm,
        )

        # Ingest
        request = WorkspaceIngestRequest(
            manifest=manifest,
            skip_files=list(skip),
            override_tags=list(tags),
            phase=phase,
            source="pi",
            dry_run=dry_run,
        )
        result = await ws_svc.ingest(request)
        await db.close()
        return manifest, result

    # Confirmation
    if not dry_run and not yes:
        if not click.confirm(f"Ingest files from {folder}?"):
            click.echo("Cancelled.")
            return

    manifest, result = asyncio.run(_ingest())

    prefix = "🔍 DRY RUN — " if dry_run else "✅ "
    click.echo(f"{prefix}Bootstrap complete")
    click.echo(f"   Scan ID: {manifest.scan_id}")
    click.echo(f"   Processed: {result.total_processed}")
    click.echo(f"   Created: {result.total_created}")
    click.echo(f"   Skipped: {result.total_skipped}")
    click.echo(f"   Errors: {result.total_errors}")

    for item in result.results:
        if item.error and not item.success:
            click.echo(f"  ❌ {item.relative_path}: {item.error}")
        elif item.entity_ids:
            click.echo(f"  ✓ {item.relative_path} → {item.entity_count} entries")


@main.command("periodic-hooks")
@click.option(
    "--project-id",
    "project_ids",
    multiple=True,
    help="Project IDs to fire 'periodic' hooks for. Repeat for multiple, "
         "or omit to fire across every project in the database.",
)
def periodic_hooks(project_ids: tuple[str, ...]):
    """Fire 'periodic' hooks once across one or more projects.

    Intended to be invoked by cron or a scheduler at the cadence the PI/Brain
    chooses (hourly, daily). Each invocation fires the periodic event once;
    handler config inside individual hooks decides what to do.

    Mission 2 v1: simple cron-driven invocation. v1.1 may add per-hook
    interval scheduling inside the dispatcher.
    """
    from datetime import datetime, timezone
    from rka.config import RKAConfig
    from rka.infra.database import Database
    from rka.services.hook_dispatcher import HookDispatcher

    config = RKAConfig()

    async def _run() -> None:
        db = Database(config.database_url)
        await db.connect()
        try:
            targets = list(project_ids)
            if not targets:
                rows = await db.fetchall("SELECT id FROM projects")
                targets = [r["id"] for r in rows]
            if not targets:
                click.echo("No projects found; nothing to fire.")
                return
            dispatcher = HookDispatcher(db)
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            total = 0
            for pid in targets:
                ids = await dispatcher.fire(
                    event="periodic",
                    payload={"project_id": pid, "now": now},
                    project_id=pid,
                )
                click.echo(f"  {pid}: fired {len(ids)} hook execution(s)")
                total += len(ids)
            click.echo(f"Done. {total} executions across {len(targets)} project(s).")
        finally:
            await db.close()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
