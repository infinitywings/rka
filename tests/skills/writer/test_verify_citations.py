"""Tests for the Writer citation-key cross-check (P4)."""

from __future__ import annotations

import json


def _manifest(
    verify_citations,
    *,
    active: set[str],
    approved: set[str] | None = None,
):
    return verify_citations.ManifestProjection(
        active_keys=active,
        approved_keys=active if approved is None else approved,
        schema_version="rka.manuscript-reference-manifest/v1",
        project_id="prj_test",
        manuscript_id="man_test",
        manuscript_revision=4,
    )


def _audit(verify_citations, tex_texts, bib_texts, *, manifest=None):
    return verify_citations.audit(
        tex_texts,
        bib_texts,
        manifest=manifest,
        expected_project_id="prj_test",
        expected_manuscript_id="man_test",
    )


def test_all_keys_resolve_passes(verify_citations):
    tex = r"We cite \citep{smith2024} and \citet{jones2023}."
    bib = "@article{smith2024,title={A}}\n@inproceedings{jones2023,title={B}}\n"
    rep = _audit(
        verify_citations,
        [tex],
        [bib],
        manifest=_manifest(
            verify_citations,
            active={"smith2024", "jones2023"},
        ),
    )
    assert rep.verdict == "PASS"
    assert rep.unresolved == []


def test_unresolved_key_blocks(verify_citations):
    tex = r"We cite \cite{ghost2099}."
    bib = "@article{smith2024,title={A}}\n"
    rep = _audit(
        verify_citations,
        [tex],
        [bib],
        manifest=_manifest(verify_citations, active={"smith2024"}),
    )
    assert rep.verdict == "BLOCK"
    assert "ghost2099" in rep.unresolved


def test_case_mismatch_blocks(verify_citations):
    tex = r"We cite \cite{Smith2024}."
    bib = "@article{smith2024,title={A}}\n"
    rep = _audit(
        verify_citations,
        [tex],
        [bib],
        manifest=_manifest(verify_citations, active={"smith2024"}),
    )
    assert rep.verdict == "BLOCK"
    assert rep.case_mismatch and rep.case_mismatch[0]["cited"] == "Smith2024"
    assert rep.case_mismatch[0]["bib"] == "smith2024"


def test_unused_entry_warns(verify_citations):
    tex = r"We cite \cite{smith2024}."
    bib = "@article{smith2024,title={A}}\n@misc{orphan2020,title={X}}\n"
    rep = _audit(
        verify_citations,
        [tex],
        [bib],
        manifest=_manifest(
            verify_citations,
            active={"smith2024", "orphan2020"},
        ),
    )
    assert rep.verdict == "WARN"
    assert "orphan2020" in rep.unused


def test_multi_key_and_starred_and_options(verify_citations):
    tex = r"See \citep[e.g.][]{a2024,b2024} and \cite*{c2024}."
    bib = "@article{a2024,t={}}\n@article{b2024,t={}}\n@article{c2024,t={}}\n"
    rep = _audit(
        verify_citations,
        [tex],
        [bib],
        manifest=_manifest(
            verify_citations,
            active={"a2024", "b2024", "c2024"},
        ),
    )
    assert rep.verdict == "PASS"
    assert set(rep.cite_keys) == {"a2024", "b2024", "c2024"}


def test_bibitem_style_bibliography(verify_citations):
    tex = r"We cite \cite{ref1}."
    bib = r"\bibitem{ref1} Some reference."
    rep = _audit(
        verify_citations,
        [tex],
        [bib],
        manifest=_manifest(verify_citations, active={"ref1"}),
    )
    assert rep.verdict == "PASS"


def test_missing_manifest_blocks_even_when_bibliography_resolves(
    verify_citations,
):
    rep = _audit(
        verify_citations,
        [r"We cite \cite{smith2024}."],
        ["@article{smith2024,title={A}}\n"],
    )
    assert rep.verdict == "BLOCK"
    assert rep.manifest_missing is True


def test_active_but_unvalidated_citation_blocks(verify_citations):
    rep = _audit(
        verify_citations,
        [r"We cite \cite{smith2024}."],
        ["@article{smith2024,title={A}}\n"],
        manifest=_manifest(
            verify_citations,
            active={"smith2024"},
            approved=set(),
        ),
    )
    assert rep.verdict == "BLOCK"
    assert rep.unapproved_citations == [
        {"cited": "smith2024", "reason": "validation_not_current"}
    ]


def test_added_bibtex_entry_and_citation_outside_manifest_blocks(
    verify_citations,
):
    rep = _audit(
        verify_citations,
        [r"We cite \cite{approved2024,new2099}."],
        [
            "@article{approved2024,title={A}}\n"
            "@article{new2099,title={Unvalidated}}\n"
        ],
        manifest=_manifest(
            verify_citations,
            active={"approved2024"},
        ),
    )
    assert rep.verdict == "BLOCK"
    assert rep.unapproved_citations == [
        {"cited": "new2099", "reason": "not_in_active_manifest"}
    ]


def test_manifest_projection_is_derived_and_cross_checked(
    verify_citations,
    tmp_path,
):
    path = tmp_path / "RKA_CLAIM_SPINE.json"
    path.write_text(
        """
        {
          "schema_version": "rka-claim-spine/v2",
          "authoritative_source": "rka",
          "project_id": "prj_test",
          "manuscript_id": "man_test",
          "manuscript_revision": 4,
          "reference_manifest": {
            "schema_version": "rka.manuscript-reference-manifest/v1",
            "authoritative_source": "rka",
            "project_id": "prj_test",
            "manuscript_id": "man_test",
            "manuscript_revision": 4,
            "members": [{
              "citation_key": "smith2024",
              "literature_id": "lit_1",
              "state": "active",
              "validation": {"current": true}
            }],
            "active_citation_keys": ["smith2024"],
            "approved_citation_keys": ["smith2024"],
            "all_members_verified": true
          }
        }
        """,
        encoding="utf-8",
    )
    manifest = verify_citations.load_manifest(path)
    assert manifest.errors == []
    assert manifest.active_keys == {"smith2024"}
    assert manifest.approved_keys == {"smith2024"}


def test_manifest_declared_approval_cannot_override_member_state(
    verify_citations,
    tmp_path,
):
    path = tmp_path / "manifest.json"
    path.write_text(
        """
        {
          "schema_version": "rka.manuscript-reference-manifest/v1",
          "authoritative_source": "rka",
          "project_id": "prj_test",
          "manuscript_id": "man_test",
          "manuscript_revision": 4,
          "members": [{
            "citation_key": "smith2024",
            "literature_id": "lit_1",
            "state": "active",
            "validation": {"current": false}
          }],
          "active_citation_keys": ["smith2024"],
          "approved_citation_keys": ["smith2024"],
          "all_members_verified": true
        }
        """,
        encoding="utf-8",
    )
    manifest = verify_citations.load_manifest(path)
    assert manifest.approved_keys == set()
    assert any(
        "approved_citation_keys does not match" in error
        for error in manifest.errors
    )
    rep = _audit(
        verify_citations,
        [r"\cite{smith2024}"],
        ["@article{smith2024,title={A}}"],
        manifest=manifest,
    )
    assert rep.verdict == "BLOCK"


def test_wrong_project_manifest_blocks(verify_citations):
    manifest = _manifest(verify_citations, active={"smith2024"})
    rep = verify_citations.audit(
        [r"\cite{smith2024}"],
        ["@article{smith2024,title={A}}"],
        manifest=manifest,
        expected_project_id="prj_other",
        expected_manuscript_id="man_test",
    )
    assert rep.verdict == "BLOCK"
    assert (
        "manifest project_id does not match expected_project_id"
        in rep.manifest_errors
    )


def test_wrong_manuscript_manifest_blocks(verify_citations):
    manifest = _manifest(verify_citations, active={"smith2024"})
    rep = verify_citations.audit(
        [r"\cite{smith2024}"],
        ["@article{smith2024,title={A}}"],
        manifest=manifest,
        expected_project_id="prj_test",
        expected_manuscript_id="man_other",
    )
    assert rep.verdict == "BLOCK"
    assert (
        "manifest manuscript_id does not match expected_manuscript_id"
        in rep.manifest_errors
    )


def test_cli_binds_manifest_to_explicit_project_and_manuscript(
    verify_citations,
    tmp_path,
    capsys,
):
    tex_path = tmp_path / "main.tex"
    bib_path = tmp_path / "refs.bib"
    manifest_path = tmp_path / "spine.json"
    tex_path.write_text(r"\cite{smith2024}", encoding="utf-8")
    bib_path.write_text("@article{smith2024,title={A}}", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "rka.manuscript-reference-manifest/v1",
                "authoritative_source": "rka",
                "project_id": "prj_test",
                "manuscript_id": "man_test",
                "manuscript_revision": 4,
                "members": [
                    {
                        "citation_key": "smith2024",
                        "literature_id": "lit_1",
                        "state": "active",
                        "validation": {"current": True},
                    }
                ],
                "active_citation_keys": ["smith2024"],
                "approved_citation_keys": ["smith2024"],
                "all_members_verified": True,
            }
        ),
        encoding="utf-8",
    )
    exit_code = verify_citations.main(
        [
            "--tex",
            str(tex_path),
            "--bib",
            str(bib_path),
            "--approved-manifest",
            str(manifest_path),
            "--project-id",
            "prj_wrong",
            "--manuscript-id",
            "man_test",
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert report["verdict"] == "BLOCK"
    assert (
        "manifest project_id does not match expected_project_id"
        in report["manifest_errors"]
    )
