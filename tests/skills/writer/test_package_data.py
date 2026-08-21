"""Release-package coverage for the Writer workspace scaffold.

The test expands the configured package-data patterns with standard-library
glob rules. Hidden directories are skipped unless a pattern names them
explicitly, which catches the exact release regression without importing
setuptools (a build backend, not a runtime/dev dependency).
"""

from __future__ import annotations

import glob
from pathlib import Path
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_package_data_includes_hidden_writer_planning_templates() -> None:
    """The configured manifest must not drop data below the hidden directory."""
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    patterns = config["tool"]["setuptools"]["package-data"]["rka"]
    package_root = REPO_ROOT / "rka"
    packaged: set[str] = set()
    for pattern in patterns:
        packaged.update(
            Path(path).as_posix()
            for path in glob.glob(
                pattern,
                root_dir=package_root,
                recursive=True,
                include_hidden=False,
            )
        )

    expected = {
        "skills/writer/workspace-template/.planning/ACTIVE_WORKFLOW.md",
        "skills/writer/workspace-template/.planning/FRAMING_SESSION.yaml",
        "skills/writer/workspace-template/.planning/OUTLINE.md",
        "skills/writer/workspace-template/.planning/PRECIS.md",
        "skills/writer/workspace-template/.planning/REVIEW_STATE.md",
        "skills/writer/workspace-template/.planning/RKA_CLAIM_SPINE.yaml",
    }
    assert expected <= packaged
