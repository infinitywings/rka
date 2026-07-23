"""Behavioral contracts for persuasive, integrity-preserving Writer framing."""

from __future__ import annotations

from pathlib import Path


def _section(text: str, heading: str) -> str:
    """Return one Markdown H2 section, excluding the next H2."""
    start = text.index(f"## {heading}")
    remainder = text[start + len(f"## {heading}") :]
    next_heading = remainder.find("\n## ")
    if next_heading >= 0:
        remainder = remainder[:next_heading]
    return remainder


def _table_rows(section: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] in {"M1", "M2", "M3", "M4", "S"}:
            rows[cells[0]] = cells
    return rows


def _squash(text: str) -> str:
    return " ".join(text.split())


def test_publication_boundary_contract(skill_dir: Path, skill_md_path: Path) -> None:
    skill_text = skill_md_path.read_text(encoding="utf-8")
    framing_path = skill_dir / "references" / "persuasive_framing.md"
    framing_text = framing_path.read_text(encoding="utf-8")

    assert "Advocacy Law" in skill_text
    assert "references/persuasive_framing.md" in skill_text

    rows = _table_rows(_section(framing_text, "Publication boundary"))
    assert set(rows) == {"M1", "M2", "M3", "M4", "S"}
    assert "Disclose prominently" in rows["M1"][3]
    assert "State the boundary concisely" in rows["M2"][3]
    assert "Retain it in RKA" in rows["M4"][3]
    assert "omit it from public prose" in rows["M4"][3]
    assert "internal risk register" in rows["S"][3]
    assert "omit it from public prose" in rows["S"][3]

    risk_register = _section(framing_text, "Internal risk register")
    assert "author tool, not manuscript text" in risk_register
    assert "every M1/M2 row must name" in _squash(risk_register)
    assert "Public manuscript location" in risk_register

    publication_boundary = _squash(
        _section(framing_text, "Publication boundary")
    )
    assert "If the PI asks to omit an M1/M2 issue" in publication_boundary
    assert "refuse that omission" in publication_boundary
    assert "do not advance the affected unit" in publication_boundary


def test_scope_boundary_does_not_catalog_every_untested_condition(
    skill_dir: Path,
) -> None:
    framing_text = (
        skill_dir / "references" / "persuasive_framing.md"
    ).read_text(encoding="utf-8")
    publication_boundary = _squash(
        _section(framing_text, "Publication boundary")
    )

    assert "clear positive statement of the supported scope" in publication_boundary
    assert "Do not enumerate every untested model" in publication_boundary
    assert "outside an explicit, salient claim boundary is M4 or S" in (
        publication_boundary
    )


def test_quick_reader_contract(skill_dir: Path) -> None:
    framing_text = (
        skill_dir / "references" / "persuasive_framing.md"
    ).read_text(encoding="utf-8")
    quick_reader = _section(framing_text, "Quick-reader checks")

    required_scans = (
        "Title and abstract scan",
        "Introduction and contribution scan",
        "Evidence scan",
        "Boundary scan",
    )
    for scan in required_scans:
        assert scan in quick_reader

    quick_reader_flat = _squash(quick_reader)
    assert "revise or escalate to the PI" in quick_reader_flat
    assert (
        "Never make a scan pass by deleting a material limitation"
        in quick_reader_flat
    )


def test_workflow_applies_materiality_before_public_drafting(
    skill_dir: Path,
) -> None:
    workflows = (
        skill_dir / "references" / "workflows.md"
    ).read_text(encoding="utf-8")
    section_drafter = workflows[workflows.index("### 5. Section drafter") :]

    section_drafter_flat = _squash(section_drafter)
    assert "persuasive_framing.md" in section_drafter_flat
    assert "M1 and M2 issues receive" in section_drafter_flat
    assert "M4 and S items remain" in section_drafter_flat
    assert "Run the four quick-reader checks" in section_drafter_flat
    assert "Never omit an issue whose absence would materially mislead" in (
        section_drafter_flat
    )
    assert "Map every M1/M2 item to its public" in section_drafter_flat
    assert "do not advance the affected unit to `drafted`" in section_drafter_flat
