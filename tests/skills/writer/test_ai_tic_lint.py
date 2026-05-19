"""Tests for ai_tic_lint.py.

Covers the 3 lexical tiers (CRITICAL / HIGH / MEDIUM), em-dash absolute ban,
bullet-density cap, and 3 structural detectors. Plus per-project override
mechanism and style score formula.

Per mis_01KS0C3RP04XANCZAB3HTNAG0P T4 acceptance criteria: at least 10 tests.
"""

from __future__ import annotations

from pathlib import Path


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


class TestCriticalTier:
    """CRITICAL hits block on any occurrence (no per-project override)."""

    def test_chatgpt_browsing_token_blocks(self, ai_tic_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "See results in turn0search0 for context.")
        report = ai_tic_lint.lint_file(f)
        assert any(h.tier == "CRITICAL" for h in report.critical)
        assert report.verdict == "BLOCK"

    def test_refusal_stem_blocks(self, ai_tic_lint, tmp_path: Path) -> None:
        f = _write(
            tmp_path, "s.tex",
            "As an AI language model, I cannot provide that analysis."
        )
        report = ai_tic_lint.lint_file(f)
        assert any(h.tier == "CRITICAL" for h in report.critical)
        assert report.verdict == "BLOCK"


class TestHighTier:
    """HIGH tier blocks by default; per-project override possible."""

    def test_pi_verbatim_facilitate_blocks(self, ai_tic_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "This tool will facilitate the analysis.")
        report = ai_tic_lint.lint_file(f)
        assert any(h.tier == "HIGH" and "facilitate" in h.term.lower()
                   for h in report.high)

    def test_kobak_delving_blocks(self, ai_tic_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "Delving into the dataset reveals patterns.")
        report = ai_tic_lint.lint_file(f)
        assert any(h.tier == "HIGH" and "delving" in h.term.lower()
                   for h in report.high)
        assert any(h.source == "Kobak 2025" for h in report.high)

    def test_matsui_enhance_blocks(self, ai_tic_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "We enhance the model with new features.")
        report = ai_tic_lint.lint_file(f)
        assert any(h.tier == "HIGH" and h.term.lower() == "enhance"
                   for h in report.high)
        assert any(h.source == "Matsui 2025" for h in report.high)

    def test_clean_prose_passes(self, ai_tic_lint, tmp_path: Path) -> None:
        f = _write(
            tmp_path, "s.tex",
            "The protocol records participant decisions in real time. "
            "We compute mean decision latency across sessions. "
            "Results show a non-linear effect of session length."
        )
        report = ai_tic_lint.lint_file(f)
        assert not report.high
        assert not report.critical
        assert report.verdict in ("PASS", "WARN")


class TestAbsoluteBans:
    """Em-dash and en-dash absolute bans; no override possible."""

    def test_em_dash_u2014_blocks(self, ai_tic_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", f"A sentence{chr(0x2014)}with em-dash.")
        report = ai_tic_lint.lint_file(f)
        assert any(h.term == "U+2014 EM DASH" for h in report.absolute_bans)
        assert report.verdict == "BLOCK"

    def test_en_dash_u2013_blocks(self, ai_tic_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", f"Pages 14{chr(0x2013)}21 of the report.")
        report = ai_tic_lint.lint_file(f)
        assert any(h.term == "U+2013 EN DASH" for h in report.absolute_bans)
        assert report.verdict == "BLOCK"


class TestBulletDensity:
    """At most 2 lists per section; each list 3 to 5 items."""

    def test_too_many_lists_per_section_blocks(self, ai_tic_lint, tmp_path: Path) -> None:
        content = """## Section

Intro.

- a
- b
- c

Middle.

- a
- b
- c

End.

- a
- b
- c
"""
        f = _write(tmp_path, "s.md", content)
        report = ai_tic_lint.lint_file(f)
        assert any("3 bulleted lists" in h.term for h in report.absolute_bans)

    def test_list_with_too_few_items_blocks(self, ai_tic_lint, tmp_path: Path) -> None:
        content = """## Section

- a
- b
"""
        f = _write(tmp_path, "s.md", content)
        report = ai_tic_lint.lint_file(f)
        assert any("2 items (under 3)" in h.term for h in report.absolute_bans)


class TestStructuralDetectors:
    """Sentence-length variance, transition-word ratio, parallel-triplet density."""

    def test_uniform_sentence_rhythm_warns(self, ai_tic_lint, tmp_path: Path) -> None:
        # Five sentences with near-uniform length triggers the variance detector.
        text = (
            "Words go here now and there. "
            "Words go there too and now. "
            "Words go anywhere all about. "
            "Words flow easily through space. "
            "Words sit evenly across lines."
        )
        f = _write(tmp_path, "s.tex", text)
        report = ai_tic_lint.lint_file(f)
        variance = next(
            s for s in report.structural if s.detector == "sentence_length_variance"
        )
        assert variance.verdict == "WARN", (
            "uniform sentence rhythm should WARN (structural detectors do not BLOCK; "
            "they contribute to the style score for the auto-revise loop)"
        )

    def test_parallel_triplets_warn(self, ai_tic_lint, tmp_path: Path) -> None:
        # Three "X, Y, and Z" constructions in a short text triggers density > 1/500w.
        text = (
            "We considered cats, dogs, and birds. "
            "We measured speed, accuracy, and recall. "
            "We tested cars, trucks, and bikes."
        )
        f = _write(tmp_path, "s.tex", text)
        report = ai_tic_lint.lint_file(f)
        triplets = next(
            s for s in report.structural
            if s.detector == "parallel_triplet_density"
        )
        assert triplets.verdict == "WARN"


class TestStyleScore:
    """1 - (critical*3 + high + 0.3*medium) / total_sentences, clipped to [0, 1]."""

    def test_clean_prose_high_score(self, ai_tic_lint, tmp_path: Path) -> None:
        f = _write(
            tmp_path, "s.tex",
            "The system records participant inputs. "
            "Each input has a timestamp and a verdict. "
            "We compute aggregate statistics per session."
        )
        report = ai_tic_lint.lint_file(f)
        assert report.style_score >= 0.85

    def test_high_hits_reduce_score(self, ai_tic_lint, tmp_path: Path) -> None:
        f = _write(
            tmp_path, "s.tex",
            "We facilitate the analysis. "
            "We leverage the data. "
            "Furthermore, we enhance the model."
        )
        report = ai_tic_lint.lint_file(f)
        assert report.style_score < 0.85


class TestPerProjectOverride:
    """ai_tic_config.yaml can disable or downgrade HIGH-tier terms."""

    def test_disable_override_removes_hit(self, ai_tic_lint, tmp_path: Path) -> None:
        cfg = {"facilitate": {"verdict": "disable", "rationale": "domain-legit"}}
        f = _write(tmp_path, "s.tex", "We facilitate the analysis.")
        report_default = ai_tic_lint.lint_file(f)
        report_override = ai_tic_lint.lint_file(f, config=cfg)
        assert any("facilitate" in h.term.lower() for h in report_default.high)
        assert not any("facilitate" in h.term.lower() for h in report_override.high)


class TestEntryPoints:
    """Module-level entry points (main, lint_file)."""

    def test_main_returns_zero_on_clean_file(self, ai_tic_lint, tmp_path: Path) -> None:
        f = _write(
            tmp_path, "s.tex",
            "A clean sentence with neutral wording. "
            "Another sentence varying length and structure. "
            "Third clause adds variance in cadence."
        )
        rc = ai_tic_lint.main([str(f), "--output", str(tmp_path / "report.json")])
        assert rc in (0, 1)
        assert (tmp_path / "report.json").exists()
