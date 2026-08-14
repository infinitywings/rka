"""Canonical claim-scope contracts are versioned, bounded, and auditable."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from rka.models.claim import (
    ClaimCreate,
    ClaimEdgeCreate,
    ClaimScopeCondition,
    ClaimScopeWrite,
    ClaimUpdate,
)
from rka.services.claims import ClaimScopeConflictError, ClaimService


PROJECT = "proj_default"


async def _claim(db, suffix: str = "main"):
    entry_id = f"jrn_scope_{suffix}"
    await db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES (?, ?, 'note', 'Delay was 42 ms.', 'executor', 'tested')""",
        [entry_id, PROJECT],
    )
    await db.commit()
    return await ClaimService(db, project_id=PROJECT).create(
        ClaimCreate(
            source_entry_id=entry_id,
            claim_type="result",
            content="Delay was 42 ms.",
            verified=True,
            evidence_status="supported",
        ),
        actor="executor",
    )


def _condition(value: str = "local testbed") -> ClaimScopeCondition:
    return ClaimScopeCondition(
        kind="environment",
        key="testbed",
        operator="equals",
        value=value,
    )


def _complete_scope(
    expected_revision: int,
    *,
    review_status: str = "reviewed",
    disconfirming_claim_ids: list[str] | None = None,
) -> ClaimScopeWrite:
    return ClaimScopeWrite(
        expected_revision=expected_revision,
        actor="brain",
        reason="Reviewed exact operating boundary.",
        conditions=[_condition()],
        uncertainty="low",
        uncertainty_note="Five isolated repetitions.",
        extension_policy="exact_only",
        prohibited_extensions=["Do not generalize beyond the local testbed or tested workload."],
        falsifier_status="applicable",
        falsifier="Repeated measurements do not reproduce the direction.",
        disconfirming_claim_ids=disconfirming_claim_ids or [],
        review_status=review_status,  # type: ignore[arg-type]
    )


def test_condition_and_review_models_reject_ambiguous_boundaries() -> None:
    with pytest.raises(ValidationError, match="one_of requires"):
        ClaimScopeCondition(
            kind="dataset",
            key="dataset",
            operator="one_of",
            value="Dataset A",
        )
    with pytest.raises(ValidationError, match="reviewed scope requires"):
        ClaimScopeWrite(
            expected_revision=0,
            actor="brain",
            reason="Incomplete review must fail.",
            review_status="reviewed",
        )
    with pytest.raises(ValidationError, match="exact_only"):
        ClaimScopeWrite(
            expected_revision=0,
            actor="brain",
            reason="Contradictory extension policy.",
            extension_policy="exact_only",
            allowed_extensions=["all platforms"],
        )


@pytest.mark.asyncio
async def test_legacy_claim_is_missing_until_versioned_review(db) -> None:
    claim = await _claim(db)
    service = ClaimService(db, project_id=PROJECT)

    assert claim.scope_revision == 0
    assert claim.scope_readiness == "missing"
    assert claim.scope_contract is None
    assert claim.scope_findings[0].code == "CLAIM_SCOPE_MISSING"

    draft = await service.append_scope(
        claim.id,
        ClaimScopeWrite(
            expected_revision=0,
            actor="executor",
            reason="Preserve preliminary source condition.",
            conditions=[_condition()],
            uncertainty="low",
            falsifier_status="applicable",
            falsifier="Direction fails to reproduce.",
        ),
    )
    assert draft.current_revision == 1
    assert draft.scope_readiness == "incomplete"
    assert draft.current is not None
    assert draft.current.review_status == "draft"

    reviewed = await service.append_scope(claim.id, _complete_scope(1))
    assert reviewed.current_revision == 2
    assert reviewed.scope_readiness == "ready"
    assert [version.revision for version in reviewed.versions] == [2, 1]
    assert reviewed.current is not None
    assert reviewed.current.supersedes_scope_id == reviewed.versions[1].id


@pytest.mark.asyncio
async def test_scope_revision_conflict_and_claim_edit_make_contract_stale(db) -> None:
    claim = await _claim(db, "stale")
    service = ClaimService(db, project_id=PROJECT)
    await service.append_scope(claim.id, _complete_scope(0))

    with pytest.raises(ClaimScopeConflictError, match="revision changed"):
        await service.append_scope(claim.id, _complete_scope(0))

    updated = await service.update(
        claim.id,
        ClaimUpdate(content="Delay was 41 ms."),
    )
    assert updated.scope_revision == 1
    assert updated.scope_readiness == "stale"
    assert any(finding.code == "CLAIM_SCOPE_STALE" for finding in updated.scope_findings)


@pytest.mark.asyncio
async def test_scope_history_is_immutable_outside_project_deletion(db) -> None:
    claim = await _claim(db, "immutable")
    service = ClaimService(db, project_id=PROJECT)
    history = await service.append_scope(claim.id, _complete_scope(0))
    scope_id = history.current.id  # type: ignore[union-attr]

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db.execute(
            "UPDATE claim_scope_versions SET reason = 'rewrite' WHERE id = ?",
            [scope_id],
        )
    with pytest.raises(sqlite3.IntegrityError, match="project-authorized"):
        await db.execute(
            "DELETE FROM claim_scope_versions WHERE id = ?",
            [scope_id],
        )


@pytest.mark.asyncio
async def test_reviewed_scope_keeps_contradiction_and_disconfirmation_visible(db) -> None:
    claim = await _claim(db, "contested")
    counter = await _claim(db, "counter")
    service = ClaimService(db, project_id=PROJECT)
    await service.create_edge(
        ClaimEdgeCreate(
            source_claim_id=counter.id,
            target_claim_id=claim.id,
            relation="contradicts",
            confidence=0.9,
        )
    )
    history = await service.append_scope(
        claim.id,
        _complete_scope(0, disconfirming_claim_ids=[counter.id]),
    )

    assert history.scope_readiness == "ready"
    assert history.current is not None
    assert history.current.disconfirming_claim_ids == [counter.id]
    refreshed = await service.get(claim.id)
    assert refreshed is not None
    assert refreshed.contradicted is True
    codes = {finding.code for finding in refreshed.scope_findings}
    assert "CLAIM_CONTRADICTION_PRESENT" in codes
    assert "CLAIM_SCOPE_DISCONFIRMING_OBSERVATIONS" in codes


@pytest.mark.asyncio
async def test_scope_rejects_missing_or_self_disconfirming_claims(db) -> None:
    claim = await _claim(db, "bad_refs")
    service = ClaimService(db, project_id=PROJECT)

    with pytest.raises(ValueError, match="cannot disconfirm itself"):
        await service.append_scope(
            claim.id,
            _complete_scope(0, disconfirming_claim_ids=[claim.id]),
        )
    with pytest.raises(ValueError, match="not available"):
        await service.append_scope(
            claim.id,
            _complete_scope(0, disconfirming_claim_ids=["clm_missing"]),
        )
