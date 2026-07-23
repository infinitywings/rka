"""Keep the packaged Writer skill identical to its canonical source tree."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_DIR = REPO_ROOT / "rka" / "skills" / "writer"
PLUGIN_DIR = REPO_ROOT / "plugin" / "skills" / "writer"


def _files_under(root: Path) -> dict[Path, bytes]:
    """Return stable relative paths and bytes, excluding Python caches."""
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
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
