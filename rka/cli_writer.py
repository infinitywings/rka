"""`rka writer` commands for safe manuscript workspace setup and readiness."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from rka.skills.writer.workflow import (
    WriterWorkflowError,
    default_workspace_path,
    evaluate_readiness,
    evaluate_server_readiness,
    import_argument_spine,
    initialize_workspace,
    inspect_server_impact,
    propose_assist,
    propose_server_assist,
    sync_argument_spine,
)


@click.group()
def writer() -> None:
    """Initialize and inspect RKA-backed Writer workspaces."""


@writer.command("init")
@click.option("--project-id", required=True, help="Explicit canonical RKA prj_ id.")
@click.option("--venue", required=True, help="Installed Writer venue id.")
@click.option("--title", required=True, help="PI-authored manuscript title.")
@click.option("--abstract", default=None, help="Optional PI-authored abstract.")
@click.option("--path", "target", type=click.Path(path_type=Path), default=None)
@click.option(
    "--manuscript-id",
    default=None,
    help="Verify/reuse an existing canonical man_ id or legacy jrn_ alias.",
)
@click.option("--cfp-url", default=None, help="Optional current call-for-papers URL.")
@click.option(
    "--api-url",
    default=lambda: os.environ.get("RKA_API_URL", "http://localhost:9712"),
    show_default="RKA_API_URL or http://localhost:9712",
)
@click.option("--timeout", type=float, default=20.0, show_default=True)
def init_command(
    project_id: str,
    venue: str,
    title: str,
    abstract: str | None,
    target: Path | None,
    manuscript_id: str | None,
    cfp_url: str | None,
    api_url: str,
    timeout: float,
) -> None:
    """Register/verify a manuscript, then atomically publish its workspace."""
    destination = target or default_workspace_path(project_id, venue)
    try:
        result = initialize_workspace(
            target=destination,
            project_id=project_id,
            venue=venue,
            title=title,
            abstract=abstract,
            manuscript_id=manuscript_id,
            cfp_url=cfp_url,
            api_url=api_url,
            timeout=timeout,
        )
    except WriterWorkflowError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, indent=2, sort_keys=True))


@writer.command("readiness")
@click.option("--project-id", required=True, help="Explicit canonical RKA prj_ id.")
@click.option(
    "--entity-packet",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Compatibility-only advisory from caller-supplied JSON. "
        "It never authorizes drafting; use server readiness for an exit-0 gate."
    ),
)
@click.option("--manuscript-id", default=None)
@click.option(
    "--claim-spine",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
@click.option("--target-phase", default="drafting", show_default=True)
@click.option(
    "--api-url",
    default=lambda: os.environ.get("RKA_API_URL", "http://localhost:9712"),
    show_default="RKA_API_URL or http://localhost:9712",
)
@click.option("--timeout", type=float, default=20.0, show_default=True)
def readiness_command(
    project_id: str,
    entity_packet: Path | None,
    manuscript_id: str | None,
    claim_spine: Path | None,
    target_phase: str,
    api_url: str,
    timeout: float,
) -> None:
    """Read drafting readiness without writing to RKA.

    Native server readiness is authoritative. ``--entity-packet`` is retained
    only for pre-native discovery and always exits non-zero.
    """
    try:
        if entity_packet is not None:
            report = evaluate_readiness(
                packet_path=entity_packet,
                project_id=project_id,
                manuscript_id=manuscript_id,
                claim_spine_path=claim_spine,
            )
        else:
            if manuscript_id is None and claim_spine is not None:
                from rka.skills.writer.scripts.claim_spine import load_spine

                manuscript_id = str(load_spine(claim_spine).get("manuscript_id") or "")
            if not manuscript_id:
                raise WriterWorkflowError(
                    "--manuscript-id is required for server-authoritative readiness"
                )
            report = evaluate_server_readiness(
                api_url=api_url,
                project_id=project_id,
                manuscript_id=manuscript_id,
                target_phase=target_phase,
                timeout=timeout,
            )
    except (WriterWorkflowError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report, indent=2, sort_keys=True))
    if not report["ready_for_drafting"]:
        raise click.exceptions.Exit(2)


@writer.command("assist")
@click.option("--project-id", required=True, help="Explicit canonical RKA prj_ id.")
@click.option(
    "--entity-packet",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Compatibility: fresh project-scoped JSON packet.",
)
@click.option("--manuscript-id", default=None)
@click.option(
    "--api-url",
    default=lambda: os.environ.get("RKA_API_URL", "http://localhost:9712"),
    show_default="RKA_API_URL or http://localhost:9712",
)
@click.option("--timeout", type=float, default=20.0, show_default=True)
def assist_command(
    project_id: str,
    entity_packet: Path | None,
    manuscript_id: str | None,
    api_url: str,
    timeout: float,
) -> None:
    """Print a candidate claim spine; never write or ratify records."""
    try:
        if entity_packet is not None:
            proposal = propose_assist(
                packet_path=entity_packet,
                project_id=project_id,
                manuscript_id=manuscript_id,
            )
        else:
            if not manuscript_id:
                raise WriterWorkflowError(
                    "--manuscript-id is required for server-attested assist"
                )
            proposal = propose_server_assist(
                api_url=api_url,
                project_id=project_id,
                manuscript_id=manuscript_id,
                timeout=timeout,
            )
    except WriterWorkflowError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(proposal, indent=2, sort_keys=True))


@writer.command("sync")
@click.option("--project-id", required=True, help="Explicit canonical RKA prj_ id.")
@click.option("--manuscript-id", required=True, help="Canonical man_ id or legacy alias.")
@click.option(
    "--output",
    "output_path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Destination RKA_CLAIM_SPINE.yaml or JSON projection.",
)
@click.option(
    "--render-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Optionally regenerate the three read-only planning views.",
)
@click.option(
    "--api-url",
    default=lambda: os.environ.get("RKA_API_URL", "http://localhost:9712"),
    show_default="RKA_API_URL or http://localhost:9712",
)
@click.option("--timeout", type=float, default=20.0, show_default=True)
def sync_command(
    project_id: str,
    manuscript_id: str,
    output_path: Path,
    render_dir: Path | None,
    api_url: str,
    timeout: float,
) -> None:
    """Refresh deterministic Writer projections from authoritative RKA."""
    try:
        result = sync_argument_spine(
            api_url=api_url,
            project_id=project_id,
            manuscript_id=manuscript_id,
            output_path=output_path,
            render_dir=render_dir,
            timeout=timeout,
        )
    except (WriterWorkflowError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, indent=2, sort_keys=True))


@writer.command("impact")
@click.option("--project-id", required=True, help="Explicit canonical RKA prj_ id.")
@click.option("--manuscript-id", required=True, help="Canonical man_ id or legacy alias.")
@click.option("--since-cursor", type=click.IntRange(min=0), default=None)
@click.option(
    "--claim-spine",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Read since_cursor from a synchronized spine projection.",
)
@click.option("--limit", type=click.IntRange(min=1, max=1000), default=100)
@click.option(
    "--api-url",
    default=lambda: os.environ.get("RKA_API_URL", "http://localhost:9712"),
    show_default="RKA_API_URL or http://localhost:9712",
)
@click.option("--timeout", type=float, default=20.0, show_default=True)
def impact_command(
    project_id: str,
    manuscript_id: str,
    since_cursor: int | None,
    claim_spine: Path | None,
    limit: int,
    api_url: str,
    timeout: float,
) -> None:
    """Show changed evidence mapped to affected claims and writing units."""
    try:
        if since_cursor is None and claim_spine is not None:
            from rka.skills.writer.scripts.claim_spine import load_spine

            stored = load_spine(claim_spine).get("changelog_cursor")
            if not isinstance(stored, int):
                raise WriterWorkflowError(
                    "claim spine does not contain an integer changelog_cursor"
                )
            since_cursor = stored
        if since_cursor is None:
            raise WriterWorkflowError(
                "--since-cursor or --claim-spine is required"
            )
        result = inspect_server_impact(
            api_url=api_url,
            project_id=project_id,
            manuscript_id=manuscript_id,
            since_cursor=since_cursor,
            limit=limit,
            timeout=timeout,
        )
    except (WriterWorkflowError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, indent=2, sort_keys=True))


@writer.command("import-spine")
@click.option("--project-id", required=True, help="Explicit canonical RKA prj_ id.")
@click.option("--manuscript-id", required=True, help="Canonical man_ id or legacy alias.")
@click.option(
    "--input",
    "spine_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--apply/--dry-run",
    default=False,
    help="Dry-run by default; --apply performs one revision-guarded RKA update.",
)
@click.option("--expected-revision", type=click.IntRange(min=1), default=None)
@click.option(
    "--api-url",
    default=lambda: os.environ.get("RKA_API_URL", "http://localhost:9712"),
    show_default="RKA_API_URL or http://localhost:9712",
)
@click.option("--timeout", type=float, default=20.0, show_default=True)
def import_spine_command(
    project_id: str,
    manuscript_id: str,
    spine_path: Path,
    apply: bool,
    expected_revision: int | None,
    api_url: str,
    timeout: float,
) -> None:
    """Preview or apply a legacy/local spine without importing ratifications."""
    try:
        result = import_argument_spine(
            api_url=api_url,
            project_id=project_id,
            manuscript_id=manuscript_id,
            spine_path=spine_path,
            apply=apply,
            expected_revision=expected_revision,
            timeout=timeout,
        )
    except (WriterWorkflowError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, indent=2, sort_keys=True))
