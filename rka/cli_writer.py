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
    initialize_workspace,
    propose_assist,
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
@click.option("--manuscript-id", default=None, help="Verify/reuse an existing jrn_ manifest.")
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
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Fresh project-scoped JSON entity packet.",
)
@click.option("--manuscript-id", default=None)
@click.option(
    "--claim-spine",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
def readiness_command(
    project_id: str,
    entity_packet: Path,
    manuscript_id: str | None,
    claim_spine: Path | None,
) -> None:
    """Report drafting readiness without writing to RKA or the workspace."""
    try:
        report = evaluate_readiness(
            packet_path=entity_packet,
            project_id=project_id,
            manuscript_id=manuscript_id,
            claim_spine_path=claim_spine,
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
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Fresh project-scoped JSON entity packet.",
)
@click.option("--manuscript-id", default=None)
def assist_command(project_id: str, entity_packet: Path, manuscript_id: str | None) -> None:
    """Print a candidate claim spine; never write or ratify records."""
    try:
        proposal = propose_assist(
            packet_path=entity_packet,
            project_id=project_id,
            manuscript_id=manuscript_id,
        )
    except WriterWorkflowError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(proposal, indent=2, sort_keys=True))
