"""Phase W1 — venue.md generator tests.

Covers:
  - render_md emits all expected section headings for each shipped venue
  - write_md creates the file with auto-gen markers
  - write_md appends sibling <id>.notes.md content under the auto-region
  - Re-running write_md is idempotent (no diff on second invocation)
  - Re-running write_md only replaces the auto-region (preserves prelude/tail)
"""

from __future__ import annotations

import shutil
from pathlib import Path


SHIPPED_VENUE_IDS = ["CHI", "EMNLP", "IEEE-SP", "Nature", "NeurIPS", "OSDI", "USENIX"]


def test_render_md_emits_canonical_sections(venue_loader, venue_md_generator):
    for vid in SHIPPED_VENUE_IDS:
        v = venue_loader.load_venue(vid)
        md = venue_md_generator.render_md(v)
        # Canonical seven sections present.
        assert "## 1. Section names and order" in md, f"{vid}: missing §1"
        assert "## 2. Page-limit class" in md, f"{vid}: missing §2"
        assert "## 3. Tone characteristics" in md, f"{vid}: missing §3"
        assert "## 4. Forbidden constructions" in md, f"{vid}: missing §4"
        assert "## 5. Citation style" in md, f"{vid}: missing §5"
        assert "## 6. Required sections" in md, f"{vid}: missing §6"
        assert "## 7. Sample corpus pointers" in md, f"{vid}: missing §7"
        # Template + CFP blocks too.
        assert "## Template notes" in md
        assert "## References (CFP + author guides)" in md


def test_render_md_includes_review_dimensions_when_present(venue_loader, venue_md_generator):
    v = venue_loader.load_venue("NeurIPS")
    md = venue_md_generator.render_md(v)
    assert "## 8. Review dimensions" in md
    assert "technical_quality" in md


def test_write_md_creates_auto_gen_block(
    venue_loader, venue_md_generator, tmp_path, monkeypatch
):
    """Verify write_md creates the file with BEGIN/END markers + content."""
    fake_venue_dir = tmp_path / "venue"
    fake_venue_dir.mkdir()
    # Copy the NeurIPS YAML into the fake dir.
    src_yaml = venue_loader.VENUE_DIR / "NeurIPS.yaml"
    shutil.copy(src_yaml, fake_venue_dir / "NeurIPS.yaml")

    # Monkey-patch directory pointers in both modules.
    monkeypatch.setattr(venue_loader, "VENUE_DIR", fake_venue_dir)
    monkeypatch.setattr(venue_md_generator, "VENUE_DIR", fake_venue_dir)

    v = venue_loader.load_venue("NeurIPS")
    out_path = venue_md_generator.write_md(v)

    text = out_path.read_text(encoding="utf-8")
    assert venue_md_generator.BEGIN_MARKER in text
    assert venue_md_generator.END_MARKER in text
    assert "Conference on Neural Information Processing Systems" in text


def test_write_md_appends_notes_md_tail(
    venue_loader, venue_md_generator, tmp_path, monkeypatch
):
    """When sibling <id>.notes.md exists, write_md appends it below the
    auto-region so the rich hand-written content is preserved."""
    fake_venue_dir = tmp_path / "venue"
    fake_venue_dir.mkdir()
    shutil.copy(venue_loader.VENUE_DIR / "NeurIPS.yaml", fake_venue_dir / "NeurIPS.yaml")
    (fake_venue_dir / "NeurIPS.notes.md").write_text(
        "## Hand-written tail\n\nThis content is preserved across regenerations.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(venue_loader, "VENUE_DIR", fake_venue_dir)
    monkeypatch.setattr(venue_md_generator, "VENUE_DIR", fake_venue_dir)

    v = venue_loader.load_venue("NeurIPS")
    out_path = venue_md_generator.write_md(v)
    text = out_path.read_text(encoding="utf-8")
    assert "Hand-written tail" in text
    assert "preserved across regenerations" in text


def test_write_md_is_idempotent(
    venue_loader, venue_md_generator, tmp_path, monkeypatch
):
    """Re-running write_md produces byte-identical output."""
    fake_venue_dir = tmp_path / "venue"
    fake_venue_dir.mkdir()
    shutil.copy(venue_loader.VENUE_DIR / "NeurIPS.yaml", fake_venue_dir / "NeurIPS.yaml")
    monkeypatch.setattr(venue_loader, "VENUE_DIR", fake_venue_dir)
    monkeypatch.setattr(venue_md_generator, "VENUE_DIR", fake_venue_dir)

    v = venue_loader.load_venue("NeurIPS")
    p1 = venue_md_generator.write_md(v)
    first = p1.read_text(encoding="utf-8")
    p2 = venue_md_generator.write_md(v)
    second = p2.read_text(encoding="utf-8")
    assert first == second, "second write differs from first — not idempotent"


def test_write_md_replaces_only_auto_region(
    venue_loader, venue_md_generator, tmp_path, monkeypatch
):
    """If the existing .md has content outside the markers, that content
    must survive a regeneration."""
    fake_venue_dir = tmp_path / "venue"
    fake_venue_dir.mkdir()
    shutil.copy(venue_loader.VENUE_DIR / "NeurIPS.yaml", fake_venue_dir / "NeurIPS.yaml")
    # Pre-seed an .md with content above and below the markers.
    prelude = "<!-- DO NOT REMOVE — release-note prelude -->\n\n"
    auto_block = (
        f"{venue_md_generator.BEGIN_MARKER}\n\n"
        f"# (will be replaced)\n\n"
        f"{venue_md_generator.END_MARKER}"
    )
    tail = "\n\n<!-- DO NOT REMOVE — release-note tail -->\n"
    (fake_venue_dir / "NeurIPS.md").write_text(prelude + auto_block + tail, encoding="utf-8")

    monkeypatch.setattr(venue_loader, "VENUE_DIR", fake_venue_dir)
    monkeypatch.setattr(venue_md_generator, "VENUE_DIR", fake_venue_dir)

    v = venue_loader.load_venue("NeurIPS")
    out = venue_md_generator.write_md(v)
    text = out.read_text(encoding="utf-8")
    assert "release-note prelude" in text
    assert "release-note tail" in text
    assert "Conference on Neural Information Processing Systems" in text
    # The placeholder body got replaced.
    assert "(will be replaced)" not in text
