"""The distributable plugin and installed-package Writer trees must not drift."""

from __future__ import annotations

from pathlib import Path


def _files(root: Path) -> dict[Path, Path]:
    ignored_names = {".DS_Store"}
    return {
        path.relative_to(root): path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and path.name not in ignored_names
        and not path.name.startswith("._")
    }


def test_writer_package_and_plugin_trees_are_byte_identical() -> None:
    repo = Path(__file__).resolve().parents[3]
    package_files = _files(repo / "rka" / "skills" / "writer")
    plugin_files = _files(repo / "plugin" / "skills" / "writer")

    assert package_files.keys() == plugin_files.keys()
    for relative_path in sorted(package_files):
        assert package_files[relative_path].read_bytes() == plugin_files[
            relative_path
        ].read_bytes(), relative_path
