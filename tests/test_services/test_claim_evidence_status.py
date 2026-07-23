"""Claim grounding and scientific evidence assessment remain independent."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rka.models.claim import ClaimCreate, ClaimUpdate
from rka.services.claims import ClaimService


PROJECT_ID = "proj_default"


async def _seed_source(db, entry_id: str) -> None:
    await db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES (?, ?, 'note', 'The measured result was 42 ms.', 'executor', 'tested')""",
        [entry_id, PROJECT_ID],
    )
    await db.commit()


def test_models_reject_unknown_evidence_status() -> None:
    with pytest.raises(ValidationError):
        ClaimCreate(
            source_entry_id="jrn_x",
            claim_type="result",
            content="A claim",
            evidence_status="verified",  # type: ignore[arg-type]
        )

    with pytest.raises(ValidationError):
        ClaimUpdate(evidence_status="likely")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_verified_create_defaults_to_unassessed(db) -> None:
    """Grounding fidelity never auto-promotes scientific evidence support."""
    await _seed_source(db, "jrn_evidence_default")
    service = ClaimService(db, project_id=PROJECT_ID)

    claim = await service.create(
        ClaimCreate(
            source_entry_id="jrn_evidence_default",
            claim_type="result",
            content="The measured result was 42 ms.",
            verified=True,
        )
    )

    assert claim.verified is True
    assert claim.evidence_status == "unassessed"


@pytest.mark.asyncio
async def test_evidence_status_create_update_and_filter_round_trip(db) -> None:
    await _seed_source(db, "jrn_evidence_roundtrip")
    service = ClaimService(db, project_id=PROJECT_ID)

    supported = await service.create(
        ClaimCreate(
            source_entry_id="jrn_evidence_roundtrip",
            claim_type="evidence",
            content="Independent runs support the observation.",
            verified=True,
            evidence_status="supported",
        )
    )
    unassessed = await service.create(
        ClaimCreate(
            source_entry_id="jrn_evidence_roundtrip",
            claim_type="hypothesis",
            content="A possible explanation remains to be tested.",
        )
    )

    after = await service.get(supported.id)
    assert after is not None
    assert after.verified is True
    assert after.evidence_status == "supported"

    updated = await service.update(
        unassessed.id,
        ClaimUpdate(evidence_status="inconclusive"),
    )
    assert updated.verified is False
    assert updated.evidence_status == "inconclusive"

    supported_results = await service.list(evidence_status="supported")
    assert [claim.id for claim in supported_results] == [supported.id]
    inconclusive_results = await service.list(evidence_status="inconclusive")
    assert [claim.id for claim in inconclusive_results] == [unassessed.id]


@pytest.mark.asyncio
async def test_grounding_update_does_not_change_evidence_assessment(db) -> None:
    await _seed_source(db, "jrn_grounding_update")
    service = ClaimService(db, project_id=PROJECT_ID)
    claim = await service.create(
        ClaimCreate(
            source_entry_id="jrn_grounding_update",
            claim_type="result",
            content="The measured result was 42 ms.",
            evidence_status="partially_supported",
        )
    )

    updated = await service.update(claim.id, ClaimUpdate(verified=True))
    assert updated.verified is True
    assert updated.evidence_status == "partially_supported"
