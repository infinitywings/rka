"""Tests for venue-aware ai-tic recalibration (P5).

Venue defaults downgrade domain-legitimate terms (HIGH -> MEDIUM) so they warn
rather than block, merged under the per-project config (project wins).
"""

from __future__ import annotations

from pathlib import Path


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_downgrade_moves_high_hit_to_medium(ai_tic_lint, tmp_path: Path) -> None:
    cfg = {"comprehensive": {"verdict": "downgrade"}}
    f = _write(tmp_path, "s.tex", "We ran a comprehensive evaluation.")
    default = ai_tic_lint.lint_file(f)
    over = ai_tic_lint.lint_file(f, config=cfg)
    assert any("comprehensive" in h.term.lower() for h in default.high)
    assert not any("comprehensive" in h.term.lower() for h in over.high)
    assert any("comprehensive" in h.term.lower() for h in over.medium)
    # downgraded term lowers the score penalty (HIGH 1.0 -> MEDIUM 0.3)
    assert over.style_score > default.style_score


def test_merge_configs_project_wins(ai_tic_lint) -> None:
    venue = {"enhance": {"verdict": "downgrade"}}
    project = {"enhance": {"verdict": "disable"}}
    merged = ai_tic_lint.merge_configs(venue, project)
    assert merged["enhance"]["verdict"] == "disable"


def test_load_venue_config_reads_shipped_default(ai_tic_lint) -> None:
    cfg = ai_tic_lint.load_venue_config("IEEE-SP")
    # ships at least the documented downgrades
    assert "enhance" in cfg and cfg["enhance"]["verdict"] == "downgrade"


def test_unknown_venue_returns_empty(ai_tic_lint) -> None:
    assert ai_tic_lint.load_venue_config("NoSuchVenue") == {}
    assert ai_tic_lint.load_venue_config(None) == {}
