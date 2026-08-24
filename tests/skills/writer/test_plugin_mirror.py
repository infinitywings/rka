"""Keep the packaged Writer skill identical to its canonical source tree."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_DIR = REPO_ROOT / "rka" / "skills" / "writer"
PLUGIN_DIR = REPO_ROOT / "plugin" / "skills" / "writer"


def _is_artifact(relative_path: Path) -> bool:
    """Packaging junk that legitimately exists in only one tree.

    ``._``-prefixed entries are macOS AppleDouble companions: on external,
    network and sync volumes the filesystem cannot hold extended attributes,
    so every write leaves a sibling — including ``.___pycache__`` for a
    ``__pycache__`` directory. They are not skill content, and without this
    guard the test fails for everyone working on such a volume (see the
    macOS section of CLAUDE.md). ``tests/test_skills_packaging.py`` already
    skips them; this keeps the two mirror checks consistent.
    """
    return any(
        part == "__pycache__" or part.startswith("._") for part in relative_path.parts
    ) or relative_path.suffix == ".pyc"


def _files_under(root: Path) -> dict[Path, bytes]:
    """Return stable relative paths and bytes, excluding packaging artifacts."""
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not _is_artifact(path.relative_to(root))
    }


def test_plugin_writer_is_byte_identical_to_canonical_writer() -> None:
    canonical = _files_under(CANONICAL_DIR)
    plugin = _files_under(PLUGIN_DIR)

    assert canonical.keys() == plugin.keys(), (
        "plugin Writer file set differs from canonical Writer source: "
        f"canonical_only={sorted(map(str, canonical.keys() - plugin.keys()))}, "
        f"plugin_only={sorted(map(str, plugin.keys() - canonical.keys()))}"
    )

    differing = sorted(
        str(relative_path)
        for relative_path in canonical
        if canonical[relative_path] != plugin[relative_path]
    )
    assert not differing, f"plugin Writer files differ from canonical source: {differing}"
