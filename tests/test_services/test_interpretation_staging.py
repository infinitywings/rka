"""Interpretation Staging service invariants."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from rka.models.interpretation import (
    InterpretationCandidateCreate,
    InterpretationHintCreate,
    InterpretationTriage,
)
from rka.services.interpretation import (
    InterpretationConflictError,
    InterpretationNotFoundError,
    InterpretationService,
)


PROJECT = "proj_default"


async def _journal(db, entry_id: str, content: str = "Measured latency was 42 ms.") -> None:
    await db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES (?, ?, 'note', ?, 'executor', 'tested')""",
        [entry_id, PROJECT, content],
    )
    await db.commit()


def _candidate(entry_id: str, statement: str = "Latency was 42 ms.") -> InterpretationCandidateCreate:
    return InterpretationCandidateCreate(
        source_type="journal",
        source_id=entry_id,
        locator_kind="text_offset",
        locator_start=0,
        locator_end=27,
        statement=statement,
        epistemic_kind="observation",
        scope_conditions=["local testbed", "configured workload"],
        uncertainty="low",
        uncertainty_note="One recorded run.",
        falsifier="A repeated run does not reproduce the measurement.",
        proposed_claim_type="result",
        created_by="executor",
        extraction_tool="pytest",
    )


def test_locator_contract_rejects_missing_or_reversed_coordinates() -> None:
    with pytest.raises(ValidationError, match="requires locator_start"):
        InterpretationCandidateCreate(
            source_type="journal",
            source_id="jrn_x",
            locator_kind="text_offset",
            statement="atomic",
            epistemic_kind="observation",
            created_by="executor",
            extraction_tool="test",
        )

    with pytest.raises(ValidationError, match="reopen requires reason"):
        InterpretationTriage(
            action="reopen",
            expected_revision=1,
            actor="pi",
        )


@pytest.mark.asyncio
async def test_journal_text_locator_must_reference_real_content(db) -> None:
    await _journal(db, "jrn_stage_bad_span", "short")
    service = InterpretationService(db, project_id=PROJECT)

    with pytest.raises(ValueError, match="locator_start is outside"):
        await service.create(
            _candidate("jrn_stage_bad_span").model_copy(
                update={"locator_start": 99, "locator_end": None}
            )
        )
    with pytest.raises(ValueError, match="locator_end must be after"):
        await service.create(
            _candidate("jrn_stage_bad_span").model_copy(
                update={"locator_start": 0, "locator_end": 99}
            )
        )
    with pytest.raises(ValidationError, match="greater than or equal"):
        InterpretationCandidateCreate(
            source_type="journal",
            source_id="jrn_x",
            locator_kind="line_range",
            locator_start=9,
            locator_end=2,
            statement="atomic",
            epistemic_kind="observation",
            created_by="executor",
            extraction_tool="test",
        )


@pytest.mark.asyncio
async def test_create_is_source_scoped_and_has_immutable_origin_event(db) -> None:
    await _journal(db, "jrn_stage_create")
    service = InterpretationService(db, project_id=PROJECT)

    candidate = await service.create(_candidate("jrn_stage_create"))

    assert candidate.id.startswith("icd_")
    assert candidate.review_status == "pending"
    assert candidate.scope_conditions == ["local testbed", "configured workload"]
    detail = await service.get_detail(candidate.id)
    assert detail is not None
    assert [(event.action, event.to_status) for event in detail.review_events] == [
        ("created", "pending")
    ]
    link = await db.fetchone(
        """SELECT * FROM entity_links
           WHERE source_type = 'interpretation_candidate' AND source_id = ?""",
        [candidate.id],
    )
    assert link["target_type"] == "journal"
    assert link["target_id"] == "jrn_stage_create"

    with pytest.raises(InterpretationNotFoundError):
        await InterpretationService(db, project_id="prj_missing").create(
            _candidate("jrn_stage_create")
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db.execute(
            "UPDATE interpretation_review_events SET reason = 'changed' WHERE candidate_id = ?",
            [candidate.id],
        )


@pytest.mark.asyncio
async def test_hints_are_typed_deterministic_and_revision_guarded(db) -> None:
    await _journal(db, "jrn_stage_hints")
    service = InterpretationService(db, project_id=PROJECT)
    first = await service.create(_candidate("jrn_stage_hints", "Latency was 42 ms."))
    second = await service.create(_candidate("jrn_stage_hints", "The run measured 42 ms."))

    detail = await service.add_hint(
        first.id,
        InterpretationHintCreate(
            related_candidate_id=second.id,
            kind="duplicate",
            confidence=0.91,
            rationale="Same measurement and scope.",
            created_by="brain",
            expected_revision=first.revision,
        ),
    )
    assert detail.revision == 2
    assert detail.duplicate_hint_count == 1
    assert detail.hints[0].related_candidate_id == second.id
    assert detail.review_events[-1].action == "hint_added"

    with pytest.raises(InterpretationConflictError, match="revision"):
        await service.add_hint(
            first.id,
            InterpretationHintCreate(
                related_candidate_id=second.id,
                kind="conflict",
                rationale="stale client",
                created_by="brain",
                expected_revision=1,
            ),
        )


@pytest.mark.asyncio
async def test_disposition_preserves_candidate_and_append_only_history(db) -> None:
    await _journal(db, "jrn_stage_reject")
    service = InterpretationService(db, project_id=PROJECT)
    candidate = await service.create(_candidate("jrn_stage_reject"))

    reviewing = await service.triage(
        candidate.id,
        InterpretationTriage(
            action="start_review", expected_revision=1, actor="brain"
        ),
    )
    rejected = await service.triage(
        candidate.id,
        InterpretationTriage(
            action="reject",
            expected_revision=reviewing.revision,
            actor="brain",
            reason="The note records a plan, not an observed result.",
        ),
    )
    assert rejected.review_status == "resolved"
    assert rejected.disposition == "rejected"
    assert rejected.statement == candidate.statement
    assert [event.action for event in rejected.review_events] == [
        "created", "start_review", "reject"
    ]

    reopened = await service.triage(
        candidate.id,
        InterpretationTriage(
            action="reopen",
            expected_revision=rejected.revision,
            actor="pi",
            reason="New source context is available.",
        ),
    )
    assert reopened.review_status == "pending"
    assert reopened.disposition is None
    assert reopened.review_events[-1].action == "reopen"

    with pytest.raises(InterpretationConflictError, match="requires candidate status resolved"):
        await service.triage(
            candidate.id,
            InterpretationTriage(
                action="reopen",
                expected_revision=reopened.revision,
                actor="pi",
                reason="A duplicate reopen must not erase history.",
            ),
        )


@pytest.mark.asyncio
async def test_resolved_candidate_requires_reopen_and_candidate_meaning_is_immutable(db) -> None:
    await _journal(db, "jrn_stage_state")
    service = InterpretationService(db, project_id=PROJECT)
    candidate = await service.create(_candidate("jrn_stage_state"))
    resolved = await service.triage(
        candidate.id,
        InterpretationTriage(
            action="defer",
            expected_revision=1,
            actor="brain",
            reason="Await a repeated run.",
        ),
    )

    with pytest.raises(InterpretationConflictError, match="current status is resolved"):
        await service.triage(
            candidate.id,
            InterpretationTriage(
                action="reject",
                expected_revision=resolved.revision,
                actor="brain",
                reason="A stale reviewer must reopen first.",
            ),
        )
    with pytest.raises(sqlite3.IntegrityError, match="meaning is immutable"):
        await db.execute(
            "UPDATE interpretation_candidates SET statement = ?, revision = revision + 1 WHERE id = ?",
            ["Rewritten without an event.", candidate.id],
        )
    with pytest.raises(sqlite3.IntegrityError, match="project-authorized deletion"):
        await db.execute(
            "DELETE FROM interpretation_candidates WHERE id = ?",
            [candidate.id],
        )


@pytest.mark.asyncio
async def test_promotion_and_revocation_preserve_lineage_without_support_inference(db) -> None:
    await _journal(db, "jrn_stage_promote")
    service = InterpretationService(db, project_id=PROJECT)
    candidate = await service.create(_candidate("jrn_stage_promote"))

    promoted = await service.triage(
        candidate.id,
        InterpretationTriage(
            action="promote",
            expected_revision=1,
            actor="brain",
            reason="Checked exact text span against the journal record.",
            grounding_verified=True,
            claim_confidence=0.83,
        ),
    )
    assert promoted.disposition == "promoted"
    assert promoted.active_claim_id is not None
    claim = await db.fetchone("SELECT * FROM claims WHERE id = ?", [promoted.active_claim_id])
    assert claim["verified"] == 1
    assert claim["evidence_status"] == "unassessed"
    assert claim["stale"] == 0
    links = await db.fetchall(
        """SELECT target_type, target_id FROM entity_links
           WHERE source_type = 'claim' AND source_id = ?
           ORDER BY target_type""",
        [promoted.active_claim_id],
    )
    assert {(row["target_type"], row["target_id"]) for row in links} == {
        ("interpretation_candidate", candidate.id),
        ("journal", "jrn_stage_promote"),
    }

    revoked = await service.triage(
        candidate.id,
        InterpretationTriage(
            action="revoke_promotion",
            expected_revision=promoted.revision,
            actor="pi",
            reason="The source span was later found to be incomplete.",
        ),
    )
    assert revoked.review_status == "pending"
    assert revoked.active_claim_id is None
    assert revoked.promotions[0].status == "revoked"
    assert (await db.fetchone("SELECT stale FROM claims WHERE id = ?", [claim["id"]]))[
        "stale"
    ] == 1


@pytest.mark.asyncio
async def test_nonjournal_candidate_cannot_be_promoted_through_synthetic_note(db) -> None:
    await db.execute(
        """INSERT INTO literature (id, project_id, title, status, added_by)
           VALUES ('lit_stage', ?, 'A paper', 'read', 'brain')""",
        [PROJECT],
    )
    await db.commit()
    service = InterpretationService(db, project_id=PROJECT)
    candidate = await service.create(
        InterpretationCandidateCreate(
            source_type="literature",
            source_id="lit_stage",
            locator_kind="page",
            locator_start=4,
            statement="The paper reports lower latency.",
            epistemic_kind="reported_fact",
            proposed_claim_type="evidence",
            created_by="brain",
            extraction_tool="manual_review",
        )
    )
    with pytest.raises(ValueError, match="journal-backed"):
        await service.triage(
            candidate.id,
            InterpretationTriage(
                action="promote",
                expected_revision=1,
                actor="brain",
                reason="Reviewed the cited page.",
                grounding_verified=True,
            ),
        )
    assert await db.fetchall("SELECT id FROM claims") == []
