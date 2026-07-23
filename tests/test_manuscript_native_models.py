"""Pydantic contracts for native manuscript persistence."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rka.models.manuscript_native import (
    ManuscriptClaimCreate,
    ManuscriptClaimVersion,
    ManuscriptClaimVersionCreate,
    ManuscriptClaimVerificationAttestation,
    ManuscriptCheckpointCreate,
    ManuscriptCheckpointResolve,
    ManuscriptCreate,
    ManuscriptUnitCreate,
    ManuscriptUpdate,
)


def test_create_and_update_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ManuscriptCreate(title="Paper", project_id="prj_wrong_layer")

    with pytest.raises(ValidationError):
        ManuscriptClaimCreate(
            manuscript_id="man_a",
            local_key="C1",
            kind="empirical",
            ratified=True,
        )
    with pytest.raises(ValidationError):
        ManuscriptCreate(title="Paper", phase="review")
    with pytest.raises(ValidationError):
        ManuscriptCreate(title="Paper", state="submitted")


def test_manuscript_update_supports_optimistic_revision_and_explicit_clear() -> None:
    update = ManuscriptUpdate(expected_revision=4, venue=None)
    assert update.expected_revision == 4
    assert update.model_fields_set == {"expected_revision", "venue"}
    assert update.model_dump(exclude_unset=True) == {
        "expected_revision": 4,
        "venue": None,
    }

    with pytest.raises(ValidationError, match="at least one"):
        ManuscriptUpdate(expected_revision=4)
    with pytest.raises(ValidationError):
        ManuscriptUpdate(expected_revision=0, title="Paper")


@pytest.mark.parametrize(
    "kind",
    ["empirical", "methodological", "theoretical", "survey", "position"],
)
def test_claim_kinds_are_closed(kind: str) -> None:
    claim = ManuscriptClaimCreate(
        manuscript_id="man_a",
        local_key="C1",
        kind=kind,
    )
    assert claim.kind == kind

    with pytest.raises(ValidationError):
        ManuscriptClaimCreate(
            manuscript_id="man_a",
            local_key="C2",
            kind="marketing",
        )


def test_claim_version_requires_explicit_prohibited_boundary() -> None:
    version = ManuscriptClaimVersionCreate(
        claim_id="mcl_a",
        exact_wording="The method improves recall on the tested datasets.",
        allowed_wording="Improves recall under the tested conditions.",
        prohibited_wording=["Improves every dataset universally."],
    )
    assert version.expected_previous_version == 0

    with pytest.raises(ValidationError):
        ManuscriptClaimVersionCreate(
            claim_id="mcl_a",
            exact_wording="A result",
            allowed_wording="A bounded result",
            prohibited_wording=[],
        )


def test_result_unit_requires_artifact_and_interpretation_boundaries() -> None:
    with pytest.raises(ValidationError, match="artifact_ref"):
        ManuscriptUnitCreate(
            manuscript_id="man_a",
            local_key="U-RESULT-1",
            kind="result",
            location="sections/results.tex#r1",
        )

    unit = ManuscriptUnitCreate(
        manuscript_id="man_a",
        local_key="U-RESULT-1",
        kind="result",
        location="sections/results.tex#r1",
        artifact_ref="figures/r1.pdf",
        allowed_interpretation="Measured on two tested platforms.",
        prohibited_interpretation="Universal across all platforms.",
    )
    assert unit.kind == "result"


@pytest.mark.parametrize(
    ("kind", "unit_id"),
    [
        ("venue", None),
        ("outline", None),
        ("table_figure_plan", None),
        ("reference_set", None),
        ("draft_section", "mun_a"),
        ("final_layout", None),
    ],
)
def test_exactly_six_checkpoint_kinds(kind: str, unit_id: str | None) -> None:
    checkpoint = ManuscriptCheckpointCreate(
        manuscript_id="man_a",
        kind=kind,
        unit_id=unit_id,
    )
    assert checkpoint.kind == kind

    with pytest.raises(ValidationError):
        ManuscriptCheckpointCreate(manuscript_id="man_a", kind="style")


def test_checkpoint_supersession_is_service_owned() -> None:
    with pytest.raises(ValidationError):
        ManuscriptCheckpointResolve(
            decision_id="dec_a",
            status="superseded",
            resolved_at="2026-07-22T12:00:00Z",
        )


def test_sqlite_json_fields_deserialize_in_output_models() -> None:
    version = ManuscriptClaimVersion.model_validate(
        {
            "claim_id": "mcl_a",
            "version": 1,
            "manuscript_id": "man_a",
            "project_id": "prj_a",
            "exact_wording": "Exact wording",
            "allowed_wording": "Allowed wording",
            "prohibited_wording": '["Universal wording"]',
            "created_at": "2026-07-22T12:00:00Z",
        }
    )
    assert version.prohibited_wording == ["Universal wording"]

    attestation = ManuscriptClaimVerificationAttestation.model_validate(
        {
            "id": "mva_a",
            "manuscript_id": "man_a",
            "project_id": "prj_a",
            "claim_id": "mcl_a",
            "claim_version": 1,
            "overall_verdict": "warn",
            "grounding_verdict": "pass",
            "evidence_verdict": "pass",
            "contradiction_verdict": "pass",
            "currency_verdict": "warn",
            "ratification_verdict": "pass",
            "unit_coverage_verdict": "pass",
            "changelog_cursor": "42",
            "dependency_snapshot": '{"clm_a":{"revision":2}}',
            "full_json_payload": '{"findings":[]}',
            "validator_version": "v1",
            "started_at": "2026-07-22T12:00:00Z",
            "completed_at": "2026-07-22T12:00:01Z",
            "created_at": "2026-07-22T12:00:01Z",
        }
    )
    assert attestation.dependency_snapshot == {"clm_a": {"revision": 2}}
    assert attestation.full_json_payload == {"findings": []}
