"""Tests for venue/CHI.md and venue/EMNLP.md schema and content.

Each venue file must carry the seven-field schema per references/venue/CHI.md
and EMNLP.md design. Tests verify each required schema section is present
and the em-dash absolute ban is dogfooded.

Per mis_01KS0C3RP04XANCZAB3HTNAG0P T4 acceptance criteria.
"""

from __future__ import annotations

from pathlib import Path


REQUIRED_SCHEMA_SECTIONS = [
    "Section names and order",
    "Page-limit class",
    "Tone characteristics",
    "Forbidden constructions",
    "Citation style",
    "Required sections",
    "Sample corpus pointers",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chi_md_exists(refs_dir: Path) -> None:
    assert (refs_dir / "venue" / "CHI.md").exists()


def test_emnlp_md_exists(refs_dir: Path) -> None:
    assert (refs_dir / "venue" / "EMNLP.md").exists()


def test_chi_has_all_seven_schema_sections(refs_dir: Path) -> None:
    text = _read(refs_dir / "venue" / "CHI.md")
    for section in REQUIRED_SCHEMA_SECTIONS:
        assert section in text, f"CHI.md missing schema section: {section}"


def test_emnlp_has_all_seven_schema_sections(refs_dir: Path) -> None:
    text = _read(refs_dir / "venue" / "EMNLP.md")
    for section in REQUIRED_SCHEMA_SECTIONS:
        assert section in text, f"EMNLP.md missing schema section: {section}"


def test_emnlp_documents_mandatory_limitations(refs_dir: Path) -> None:
    """EMNLP requires a Limitations section since 2022; the venue file must say so."""
    text = _read(refs_dir / "venue" / "EMNLP.md")
    assert "Limitations" in text
    lower = text.lower()
    assert ("mandatory" in lower or "required" in lower)


def test_venue_files_em_dash_clean(refs_dir: Path) -> None:
    """Em-dash absolute ban dogfooded in venue files."""
    for name in ("CHI.md", "EMNLP.md"):
        text = _read(refs_dir / "venue" / name)
        assert chr(0x2014) not in text, f"{name} contains U+2014"
        assert chr(0x2013) not in text, f"{name} contains U+2013"
