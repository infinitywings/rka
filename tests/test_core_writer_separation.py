"""Regression contract: RKA Core must not activate manuscript writing."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_core_plugin_contains_no_writer_skill_or_command() -> None:
    assert not (ROOT / "plugin/skills/writer/SKILL.md").exists()
    assert not (ROOT / "plugin/commands/rka-start-manuscript.md").exists()
    assert not (ROOT / "plugin/scripts/start-manuscript.py").exists()


def test_core_python_distribution_contains_no_writer_runtime() -> None:
    writer_root = ROOT / "rka/skills/writer"
    assert not any(path.is_file() for path in writer_root.rglob("*"))
    assert not (ROOT / "rka/cli_writer.py").exists()

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "rka-writer-tools" not in pyproject
    assert "writer-tools =" not in pyproject

    cli = (ROOT / "rka/cli.py").read_text(encoding="utf-8")
    assert "cli_writer" not in cli
    assert "_writer_group" not in cli


def test_core_exposes_no_reference_validation_write_path() -> None:
    operations = (ROOT / "rka/mcp/operations_schema.py").read_text(
        encoding="utf-8"
    )
    routes = (ROOT / "rka/api/routes/manuscripts.py").read_text(
        encoding="utf-8"
    )
    worker = (ROOT / "rka/services/worker.py").read_text(encoding="utf-8")

    assert '"validate_reference": {' not in operations
    assert '@router.post(\n    "/manuscripts/{manuscript_id}/validate-reference"' not in routes
    assert "ReferenceValidationRunner" not in worker
    assert '"reason": "writer_runtime_moved"' in worker


def test_core_plugin_metadata_has_no_writing_activation_triggers() -> None:
    manifest = json.loads(
        (ROOT / "plugin/.claude-plugin/plugin.json").read_text(encoding="utf-8")
    )
    searchable = " ".join(
        [manifest.get("description", ""), *manifest.get("keywords", [])]
    ).lower()
    for forbidden in ("manuscript drafting", "latex", "venue selection"):
        assert forbidden not in searchable


def test_marketplace_advertises_writer_as_separate() -> None:
    marketplace = json.loads(
        (ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
    )
    description = marketplace["plugins"][0]["description"].lower()
    assert "separate" in description
    assert "rka-writer" in description
    assert "/rka-start-manuscript" not in description
