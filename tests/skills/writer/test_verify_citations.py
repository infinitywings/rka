"""Tests for the Writer citation-key cross-check (P4)."""

from __future__ import annotations


def test_all_keys_resolve_passes(verify_citations):
    tex = r"We cite \citep{smith2024} and \citet{jones2023}."
    bib = "@article{smith2024,title={A}}\n@inproceedings{jones2023,title={B}}\n"
    rep = verify_citations.audit([tex], [bib])
    assert rep.verdict == "PASS"
    assert rep.unresolved == []


def test_unresolved_key_blocks(verify_citations):
    tex = r"We cite \cite{ghost2099}."
    bib = "@article{smith2024,title={A}}\n"
    rep = verify_citations.audit([tex], [bib])
    assert rep.verdict == "BLOCK"
    assert "ghost2099" in rep.unresolved


def test_case_mismatch_blocks(verify_citations):
    tex = r"We cite \cite{Smith2024}."
    bib = "@article{smith2024,title={A}}\n"
    rep = verify_citations.audit([tex], [bib])
    assert rep.verdict == "BLOCK"
    assert rep.case_mismatch and rep.case_mismatch[0]["cited"] == "Smith2024"
    assert rep.case_mismatch[0]["bib"] == "smith2024"


def test_unused_entry_warns(verify_citations):
    tex = r"We cite \cite{smith2024}."
    bib = "@article{smith2024,title={A}}\n@misc{orphan2020,title={X}}\n"
    rep = verify_citations.audit([tex], [bib])
    assert rep.verdict == "WARN"
    assert "orphan2020" in rep.unused


def test_multi_key_and_starred_and_options(verify_citations):
    tex = r"See \citep[e.g.][]{a2024,b2024} and \cite*{c2024}."
    bib = "@article{a2024,t={}}\n@article{b2024,t={}}\n@article{c2024,t={}}\n"
    rep = verify_citations.audit([tex], [bib])
    assert rep.verdict == "PASS"
    assert set(rep.cite_keys) == {"a2024", "b2024", "c2024"}


def test_bibitem_style_bibliography(verify_citations):
    tex = r"We cite \cite{ref1}."
    bib = r"\bibitem{ref1} Some reference."
    rep = verify_citations.audit([tex], [bib])
    assert rep.verdict == "PASS"
