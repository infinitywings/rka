"""Tests for overclaim_lint.py (advisory calibration/overclaim linter).

WARN-only: this linter never BLOCKs. It surfaces absolute/overclaim wording
for the pre-submission review, and (Task 2) ranks a hit higher when the
backing RKA evidence is weak-confidence.
"""

from __future__ import annotations

import json
from pathlib import Path


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


class TestLexicalDetection:
    def test_flags_guarantee_word(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "Our system guarantees no data leakage.")
        rep = overclaim_lint.lint_file(f)
        assert any(h.term.lower() == "guarantees" for h in rep.hits)
        assert rep.verdict == "WARN"

    def test_flags_multiple_categories(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "It eliminates the attack and is model-agnostic.")
        rep = overclaim_lint.lint_file(f)
        cats = {h.category for h in rep.hits}
        assert "elimination" in cats and "generality" in cats

    def test_clean_prose_passes(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(
            tmp_path, "s.tex",
            "We observe a 12 percent reduction on the controlled benchmark. "
            "The external benchmark shows a smaller, mixed effect."
        )
        rep = overclaim_lint.lint_file(f)
        assert rep.verdict == "PASS"
        assert not rep.hits


class TestNeverBlocks:
    def test_never_blocks_even_on_many_hits(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(
            tmp_path, "s.tex",
            "verified guaranteed eliminates model-agnostic dominant fundamentally"
        )
        rep = overclaim_lint.lint_file(f)
        assert rep.verdict == "WARN"
        assert rep.verdict != "BLOCK"


class TestPerProjectOverride:
    def test_config_disable_drops_term(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "The evaluation is completely done.")
        cfg = {"completely": {"verdict": "disable"}}
        assert any("completely" in h.term.lower() for h in overclaim_lint.lint_file(f).hits)
        assert not overclaim_lint.lint_file(f, config=cfg).hits


class TestEntryPoint:
    def test_main_writes_report_and_returns_warn_code(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "Our approach eliminates the attack surface.")
        out = tmp_path / "r.json"
        rc = overclaim_lint.main([str(f), "--output", str(out)])
        assert rc == 1
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["verdict"] == "WARN"

    def test_main_returns_zero_on_clean_file(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "We report a partial improvement on one benchmark.")
        rc = overclaim_lint.main([str(f), "--output", str(tmp_path / "r.json")])
        assert rc == 0
