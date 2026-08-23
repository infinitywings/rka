"""Objective contracts for private Writer discourse-planning artifacts."""

from __future__ import annotations

import json


def _style_profile(*, approved: bool = True) -> dict:
    return {
        "schema_version": "rka.writer-style-profile/v1",
        "status": "approved" if approved else "draft",
        "samples_registered": True,
        "sample_inventory": ["good/paper-a.pdf", "bad/draft-a.pdf"],
        "positive_patterns": {
            "introduction_opening": ["concrete consequence before abstraction"]
        },
        "prohibitions": ["catalog controls before explaining their purpose"],
        "approval": {
            "approved_by": "pi" if approved else None,
            "approved_at": "2026-08-19T12:00:00-04:00" if approved else None,
        },
    }


def _discourse_plan() -> dict:
    return {
        "schema_version": "rka.writer-discourse-plan/v1",
        "status": "reviewed",
        "section_id": "intro",
        "takeaway": "Cross-step context reveals attacks hidden from local checks.",
        "style_profile": {
            "required": True,
            "path": ".planning/STYLE_PROFILE.yaml",
            "status": "approved",
        },
        "required_unit_keys": ["problem", "insight", "evidence"],
        "mandatory_disclosure_ids": ["risk_feedback_bundle"],
        "propositions": [
            {
                "id": "p1",
                "statement": "Local checks miss unsafe cross-step effects.",
                "role": "gap",
                "evidence_ids": ["clm_01ABCDEFGHIJKLMNOPQRSTUVWX"],
                "qualifier_ids": [],
                "citation_keys": [],
                "next_inference": "The monitor needs cross-step context.",
            },
            {
                "id": "p2",
                "statement": "Prior monitors inspect steps independently.",
                "role": "prior_work",
                "evidence_ids": ["lit_01ABCDEFGHIJKLMNOPQRSTUVWX"],
                "qualifier_ids": [],
                "citation_keys": ["author2025monitor"],
                "next_inference": "This leaves a causal-history gap.",
            },
        ],
        "paragraphs": [
            {
                "id": "para1",
                "job": "establish the gap and motivating consequence",
                "proposition_ids": ["p1", "p2"],
                "unit_keys": ["problem", "insight", "evidence"],
                "opening": "A concrete unsafe cross-step effect",
                "bridge": "The failure identifies the missing context",
                "takeaway": "Independent checks cannot reconstruct causality",
            }
        ],
        "mandatory_disclosure_map": {
            "risk_feedback_bundle": ["paragraph:para1"]
        },
        "coherence_review": {
            "status": "pass",
            "reviewer": "fresh-reviewer-1",
            "answers": {
                "single_takeaway": True,
                "paragraph_sequence": True,
                "one_job_per_paragraph": True,
                "challenge_response": True,
                "idea_before_mechanism": True,
                "evidence_advances_argument": True,
                "opening_promise_delivered": True,
                "prose_self_contained": True,
            },
        },
    }


def _codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def test_valid_artifacts_pass_without_claiming_coherence(
    validate_discourse_artifacts,
) -> None:
    style_report = validate_discourse_artifacts.validate_style_profile(_style_profile())
    discourse_report = validate_discourse_artifacts.validate_discourse_plan(
        _discourse_plan()
    )

    assert style_report.verdict == "PASS"
    assert discourse_report.verdict == "PASS"
    assert "does not establish prose coherence" in discourse_report.as_dict()["note"]


def test_registered_samples_require_pi_approval(validate_discourse_artifacts) -> None:
    report = validate_discourse_artifacts.validate_style_profile(
        _style_profile(approved=False)
    )

    assert report.verdict == "BLOCK"
    assert "STYLE_APPROVAL" in _codes(report)


def test_registered_samples_must_be_linked_from_section(
    validate_discourse_artifacts,
) -> None:
    plan = _discourse_plan()
    plan["style_profile"]["required"] = False
    plan["style_profile"]["status"] = "not_required"

    report = validate_discourse_artifacts.validate_profile_linkage(
        _style_profile(), plan
    )

    assert "STYLE_PROFILE_REQUIRED" in _codes(report)


def test_cli_blocks_unlinked_registered_samples(
    validate_discourse_artifacts, tmp_path, capsys
) -> None:
    style_path = tmp_path / "STYLE_PROFILE.json"
    plan_path = tmp_path / "DISCOURSE_intro.json"
    plan = _discourse_plan()
    plan["style_profile"]["required"] = False
    plan["style_profile"]["status"] = "not_required"
    style_path.write_text(json.dumps(_style_profile()), encoding="utf-8")
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    exit_code = validate_discourse_artifacts.main(
        [
            "--style-profile",
            str(style_path),
            "--discourse-plan",
            str(plan_path),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["verdict"] == "BLOCK"
    assert output["artifacts"]["profile_linkage"]["findings"][0]["code"] == (
        "STYLE_PROFILE_REQUIRED"
    )


def test_mandatory_disclosures_require_exact_public_mapping(
    validate_discourse_artifacts,
) -> None:
    plan = _discourse_plan()
    plan["mandatory_disclosure_map"] = {}

    report = validate_discourse_artifacts.validate_discourse_plan(plan)

    assert "DISCLOSURE_COVERAGE" in _codes(report)


def test_paragraph_cards_must_cover_exact_required_unit_set(
    validate_discourse_artifacts,
) -> None:
    plan = _discourse_plan()
    plan["paragraphs"][0]["unit_keys"] = ["problem", "insight"]

    report = validate_discourse_artifacts.validate_discourse_plan(plan)

    assert "UNIT_COVERAGE" in _codes(report)


def test_prior_work_propositions_retain_citation_keys(
    validate_discourse_artifacts,
) -> None:
    plan = _discourse_plan()
    plan["propositions"][1]["citation_keys"] = []

    report = validate_discourse_artifacts.validate_discourse_plan(plan)

    assert "PRIOR_WORK_CITATION" in _codes(report)


def test_fresh_context_review_must_be_complete(validate_discourse_artifacts) -> None:
    plan = _discourse_plan()
    plan["coherence_review"]["answers"]["paragraph_sequence"] = False

    report = validate_discourse_artifacts.validate_discourse_plan(plan)

    assert "COHERENCE_ANSWERS" in _codes(report)
