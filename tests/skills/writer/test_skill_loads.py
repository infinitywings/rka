"""Test that SKILL.md loads correctly: frontmatter, required sections, and references.

Per mis_01KS0C3RP04XANCZAB3HTNAG0P T4 acceptance criteria. The "Pre-Submission
Review" section (v2.5.0) sits between "Local Rendering" and "Revision Loop".
"""

from __future__ import annotations

import re
from pathlib import Path

EXPECTED_SECTIONS = [
    "# Writer Skill",
    "## Supplementary references",
    "## Session Start",
    "## Tool Surface",
    "## Source Attribution",
    "## Outline Brief",
    "## PI Checkpoints",
    "## Provenance",
    "## Reference Validation Pipeline",
    "## Anti-AI-tic Enforcement",
    "## Venue Tone",
    "## LaTeX Template Management",
    "## Local Rendering",
    "## Pre-Submission Review",
    "## Revision Loop",
    "## Anti-Patterns",
    "## Related",
]


def _read_skill(skill_md_path: Path) -> str:
    return skill_md_path.read_text(encoding="utf-8")


def test_frontmatter_has_name_description_version(skill_md_path: Path) -> None:
    text = _read_skill(skill_md_path)
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter delimiter"
    end = text.find("\n---\n", 4)
    assert end > 0, "SKILL.md frontmatter must close with --- delimiter"
    fm = text[4:end]
    assert re.search(r"^name:\s*rka-writer\s*$", fm, re.MULTILINE)
    assert re.search(r"^metadata:\s*$", fm, re.MULTILINE)
    assert re.search(r'^\s+version:\s*"2\.7\.4"\s*$', fm, re.MULTILINE)
    assert re.search(r"^description:\s*\S", fm, re.MULTILINE)


def test_required_sections_present_in_stable_order(skill_md_path: Path) -> None:
    text = _read_skill(skill_md_path)
    last_pos = -1
    for section_header in EXPECTED_SECTIONS:
        idx = text.find(section_header)
        assert idx >= 0, f"section header missing: {section_header}"
        assert idx > last_pos, (
            f"section {section_header!r} appears out of order "
            f"(expected position after previous section)"
        )
        last_pos = idx


def test_supplementary_references_all_discoverable(
    skill_md_path: Path, refs_dir: Path
) -> None:
    text = _read_skill(skill_md_path)
    relative_paths = set(re.findall(r"references/([\w/.-]+\.md)", text))
    assert relative_paths, "SKILL.md must reference at least one file under references/"
    for rel in relative_paths:
        target = refs_dir / rel
        assert target.exists(), f"referenced file does not exist: {target}"


def test_em_dash_absolute_ban_dogfooded(skill_md_path: Path) -> None:
    """SKILL.md itself must not contain em-dash U+2014 or en-dash U+2013."""
    text = _read_skill(skill_md_path)
    assert chr(0x2014) not in text, "SKILL.md contains em-dash; dogfood discipline violated"
    assert chr(0x2013) not in text, "SKILL.md contains en-dash; dogfood discipline violated"


def test_skill_md_within_line_budget(skill_md_path: Path) -> None:
    """Soft budget: 200 to 700 lines per PATCH 2 revised target (~350-450).

    Tests that the skill stays roughly the right size; below 200 suggests
    underbuilt; above 700 suggests bloat that should move to references/.
    """
    text = _read_skill(skill_md_path)
    line_count = len(text.splitlines())
    assert 200 <= line_count <= 700, (
        f"SKILL.md has {line_count} lines; expected 200-700 per PATCH 2 budget"
    )
