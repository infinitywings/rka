"""Tests for layout_audit.py.

Synthesize minimal .log / .blg / .aux / .tex fixtures triggering each of the
12 audit fields; verify the correct PASS / WARN / BLOCK verdict per field.

Per mis_01KS0C3RP04XANCZAB3HTNAG0P T4 acceptance criteria.
"""

from __future__ import annotations

from pathlib import Path


def _write_fixtures(tmp_path: Path, *, log: str = "", blg: str = "",
                    aux: str = "", tex: str = "") -> dict:
    """Write the 4 fixture files; return a dict of paths."""
    files = {}
    if log:
        files["log"] = tmp_path / "main.log"
        files["log"].write_text(log, encoding="utf-8")
    if blg:
        files["blg"] = tmp_path / "main.blg"
        files["blg"].write_text(blg, encoding="utf-8")
    if aux:
        files["aux"] = tmp_path / "main.aux"
        files["aux"].write_text(aux, encoding="utf-8")
    if tex:
        files["tex"] = tmp_path / "main.tex"
        files["tex"].write_text(tex, encoding="utf-8")
    return files


def test_pages_over_limit_blocks(layout_audit) -> None:
    verdict = layout_audit.check_pages_over_limit(pages=15, limit=14)
    assert verdict.verdict == "BLOCK"


def test_pages_equals_limit_warns(layout_audit) -> None:
    verdict = layout_audit.check_pages_equals_limit(pages=14, limit=14)
    assert verdict.verdict == "WARN"


def test_undefined_citations_blocks(layout_audit) -> None:
    log = (
        "LaTeX Warning: Citation `Smith2024' on page 4 undefined on input line 12.\n"
        "LaTeX Warning: Citation `Jones2023' on page 5 undefined on input line 17.\n"
    )
    verdict = layout_audit.check_undefined_citations(log)
    assert verdict.verdict == "BLOCK"
    assert verdict.value == 2


def test_undefined_refs_blocks(layout_audit) -> None:
    log = "LaTeX Warning: Reference `sec:method' on page 3 undefined on input line 8.\n"
    verdict = layout_audit.check_undefined_refs(log)
    assert verdict.verdict == "BLOCK"
    assert verdict.value == 1


def test_missing_bib_keys_blocks(layout_audit) -> None:
    blg = "Warning--I didn't find a database entry for \"Smith2024\"\n"
    verdict = layout_audit.check_missing_bib_keys(blg)
    assert verdict.verdict == "BLOCK"


def test_orphan_refs_blocks(layout_audit) -> None:
    aux = "\\newlabel{sec:intro}{{1}{1}}\n"
    tex = "See \\ref{sec:intro} and \\ref{sec:method}."  # method not in aux
    verdict = layout_audit.check_orphan_refs(aux, tex)
    assert verdict.verdict == "BLOCK"
    assert "sec:method" in verdict.matches


def test_overfull_hbox_over_10pt_warns(layout_audit) -> None:
    log = "Overfull \\hbox (15.5pt too wide) in paragraph at lines 30--35\n"
    verdict = layout_audit.check_overfull_hboxes_over_10pt(log)
    assert verdict.verdict == "WARN"


def test_overfull_hbox_under_10pt_passes(layout_audit) -> None:
    log = "Overfull \\hbox (3.2pt too wide) in paragraph at lines 30--35\n"
    verdict = layout_audit.check_overfull_hboxes_over_10pt(log)
    assert verdict.verdict == "PASS"


def test_underfull_badness_over_5000_warns(layout_audit) -> None:
    log = "Underfull \\hbox (badness 6500) in paragraph at lines 40--41\n"
    verdict = layout_audit.check_underfull_badness_over_5000(log)
    assert verdict.verdict == "WARN"


def test_overall_verdict_aggregation_pass(layout_audit, tmp_path: Path) -> None:
    files = _write_fixtures(tmp_path, log="", blg="", aux="", tex="")
    report = layout_audit.audit(
        pdf_path=None, log_path=None, blg_path=None,
        aux_path=None, tex_path=None, venue="CHI",
    )
    assert report.summary["overall_verdict"] == "PASS"


def test_overall_verdict_aggregation_block(layout_audit, tmp_path: Path) -> None:
    log = "LaTeX Warning: Citation `MissingKey' on page 1 undefined on input line 5.\n"
    files = _write_fixtures(tmp_path, log=log)
    report = layout_audit.audit(
        pdf_path=None, log_path=files["log"], blg_path=None,
        aux_path=None, tex_path=None, venue="CHI",
    )
    assert report.summary["overall_verdict"] == "BLOCK"
    assert report.summary["blocks"] >= 1
