"""Validate that a Core release tag exactly matches the packaged version."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

_STABLE_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def project_version(pyproject: Path) -> str:
    payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = payload.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"missing project.version in {pyproject}")
    return version


def validate_release_tag(tag: str, version: str) -> str:
    """Return the version when a stable release tag is canonical and exact."""

    if not _STABLE_SEMVER.fullmatch(version):
        raise ValueError(
            f"container publication currently accepts stable SemVer only; got {version!r}"
        )

    expected = f"v{version}"
    if tag != expected:
        raise ValueError(
            f"release tag {tag!r} does not match project version {version!r}; expected {expected!r}"
        )
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="GitHub release tag, including the leading v")
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "pyproject.toml",
    )
    args = parser.parse_args()

    print(validate_release_tag(args.tag, project_version(args.pyproject)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
