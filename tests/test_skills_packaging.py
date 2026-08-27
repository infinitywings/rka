"""Consistency guarantees for RKA skills across distribution channels.

The same skill content ships two ways:
- ``rka/skills/`` — packaged into the wheel; served by the MCP server
  (``rka_read_skill`` / ``rka_start_session`` tools and the ``brain_skill`` /
  ``executor_skill`` / ``pi_skill`` prompts).
- ``plugin/skills/`` — served by the Claude Code plugin.

These tests keep a fresh installation on any machine consistent:
1. active Core skills in the two trees must stay byte-identical (modulo
   packaging artifacts and the temporarily wheel-only Writer compatibility
   implementation), and
2. every file under ``rka/skills/`` must be matched by a
   ``[tool.setuptools.package-data]`` glob so the wheel actually ships it
   (Python's glob does not match dot-prefixed names with wildcards, so hidden
   files like ``.planning/*.md`` need explicit patterns).

To fix a parity failure, edit skills in ONE tree and mirror with:
    rsync -rc --exclude='._*' --exclude='__pycache__' --exclude='__init__.py' \
        --exclude='/SKILL.md' rka/skills/ plugin/skills/
"""

from __future__ import annotations

import glob
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGED_SKILLS = REPO_ROOT / "rka" / "skills"
PLUGIN_SKILLS = REPO_ROOT / "plugin" / "skills"

# Artifacts that legitimately differ between the two trees or are junk.
_SKIP_NAMES = {".DS_Store", "__pycache__"}
# Files that exist only on the packaged side by design.
_PACKAGED_ONLY = {"SKILL.md"}  # top-level role index used by the MCP prompts
_PACKAGED_ONLY_PREFIXES = ("writer/",)


def _is_artifact(rel: Path) -> bool:
    return any(
        part in _SKIP_NAMES or part.startswith("._") or part.endswith(".pyc")
        for part in rel.parts
    ) or rel.name == "__init__.py"


def _tree(root: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if _is_artifact(rel):
            continue
        if rel.as_posix() in _PACKAGED_ONLY:
            continue
        if rel.as_posix().startswith(_PACKAGED_ONLY_PREFIXES):
            continue
        out[rel.as_posix()] = p.read_bytes()
    return out


@pytest.mark.skipif(not PLUGIN_SKILLS.exists(), reason="plugin/ not present in this checkout")
def test_plugin_skills_match_packaged_skills() -> None:
    packaged = _tree(PACKAGED_SKILLS)
    plugin = _tree(PLUGIN_SKILLS)

    only_packaged = sorted(set(packaged) - set(plugin))
    only_plugin = sorted(set(plugin) - set(packaged))
    drifted = sorted(
        rel for rel in set(packaged) & set(plugin) if packaged[rel] != plugin[rel]
    )
    assert not only_packaged and not only_plugin and not drifted, (
        f"skill trees drifted — only in rka/skills: {only_packaged}; "
        f"only in plugin/skills: {only_plugin}; content differs: {drifted}. "
        "Sync with the rsync command in this module's docstring."
    )


def test_all_packaged_skill_files_covered_by_package_data() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    patterns = pyproject["tool"]["setuptools"]["package-data"]["rka"]

    matched: set[Path] = set()
    for pattern in patterns:
        for hit in glob.glob(str(REPO_ROOT / "rka" / pattern), recursive=True):
            matched.add(Path(hit))

    missing = [
        rel.as_posix()
        for rel in (
            p.relative_to(REPO_ROOT)
            for p in sorted(PACKAGED_SKILLS.rglob("*"))
            if p.is_file() and not _is_artifact(p.relative_to(PACKAGED_SKILLS))
        )
        if REPO_ROOT / rel not in matched
    ]
    assert not missing, (
        "files under rka/skills/ not covered by any [tool.setuptools.package-data] "
        f"glob (a fresh `uv tool install` would not ship them): {missing}"
    )
