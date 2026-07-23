"""Atomic aggregate writes and row-to-edge reconciliation regressions."""

from __future__ import annotations

import json

import pytest

from rka.infra.database import Database
from rka.models.decision import DecisionCreate, DecisionUpdate
from rka.models.journal import JournalEntryCreate, JournalEntryUpdate
from rka.models.literature import LiteratureCreate, LiteratureUpdate
from rka.models.mission import MissionCreate, MissionReportCreate, MissionUpdate
from rka.services.decisions import DecisionService
from rka.services.literature import LiteratureService
from rka.services.missions import MissionService
from rka.services.notes import NoteService

PROJECT_ID = "proj_default"


async def _outgoing_ids(
    db: Database,
    *,
    source_type: str,
    source_id: str,
    link_type: str,
    target_type: str,
) -> set[str]:
    rows = await db.fetchall(
        """SELECT target_id FROM entity_links
           WHERE project_id = ?
             AND source_type = ? AND source_id = ?
             AND link_type = ? AND target_type = ?""",
        [PROJECT_ID, source_type, source_id, link_type, target_type],
    )
    return {row["target_id"] for row in rows}


async def _incoming_ids(
    db: Database,
    *,
    target_type: str,
    target_id: str,
    link_type: str,
    source_type: str,
) -> set[str]:
    rows = await db.fetchall(
        """SELECT source_id FROM entity_links
           WHERE project_id = ?
             AND target_type = ? AND target_id = ?
             AND link_type = ? AND source_type = ?""",
        [PROJECT_ID, target_type, target_id, link_type, source_type],
    )
    return {row["source_id"] for row in rows}


async def _decision(service: DecisionService, label: str):
    return await service.create(
        DecisionCreate(
            question=f"decision {label}",
            phase="design",
            decided_by="brain",
        )
    )


@pytest.mark.asyncio
async def test_note_update_replaces_and_removes_relation_sets(
    db_with_project: Database,
) -> None:
    db = db_with_project
    decision_service = DecisionService(db, project_id=PROJECT_ID)
    literature_service = LiteratureService(db, project_id=PROJECT_ID)
    mission_service = MissionService(db, project_id=PROJECT_ID)
    note_service = NoteService(db, project_id=PROJECT_ID)

    decisions = [
        await _decision(decision_service, label)
        for label in ("one", "two", "three")
    ]
    literature = [
        await literature_service.create(LiteratureCreate(title=f"paper {label}"))
        for label in ("one", "two")
    ]
    missions = [
        await mission_service.create(
            MissionCreate(phase="execution", objective=f"mission {label}")
        )
        for label in ("one", "two")
    ]
    note = await note_service.create(
        JournalEntryCreate(
            content="relation-set seed",
            related_decisions=[decisions[0].id, decisions[1].id],
            related_literature=[literature[0].id],
            related_mission=missions[0].id,
        )
    )

    await note_service.update(
        note.id,
        JournalEntryUpdate(
            related_decisions=[decisions[1].id, decisions[2].id],
            related_literature=[],
            related_mission=missions[1].id,
        ),
    )

    updated = await note_service.get(note.id)
    assert updated.related_decisions == [decisions[1].id, decisions[2].id]
    assert updated.related_literature == []
    assert updated.related_mission == missions[1].id
    assert await _outgoing_ids(
        db,
        source_type="journal",
        source_id=note.id,
        link_type="references",
        target_type="decision",
    ) == {decisions[1].id, decisions[2].id}
    assert await _outgoing_ids(
        db,
        source_type="journal",
        source_id=note.id,
        link_type="cites",
        target_type="literature",
    ) == set()
    assert await _incoming_ids(
        db,
        target_type="journal",
        target_id=note.id,
        link_type="produced",
        source_type="mission",
    ) == {missions[1].id}

    await note_service.update(
        note.id,
        JournalEntryUpdate(related_decisions=[]),
    )
    assert await _outgoing_ids(
        db,
        source_type="journal",
        source_id=note.id,
        link_type="references",
        target_type="decision",
    ) == set()


@pytest.mark.asyncio
async def test_decision_and_literature_updates_remove_stale_edges(
    db_with_project: Database,
) -> None:
    db = db_with_project
    decision_service = DecisionService(db, project_id=PROJECT_ID)
    literature_service = LiteratureService(db, project_id=PROJECT_ID)
    note_service = NoteService(db, project_id=PROJECT_ID)

    notes = [
        await note_service.create(JournalEntryCreate(content=f"evidence {label}"))
        for label in ("one", "two")
    ]
    literature = [
        await literature_service.create(LiteratureCreate(title=f"source {label}"))
        for label in ("one", "two")
    ]
    decision = await decision_service.create(
        DecisionCreate(
            question="linked decision",
            phase="design",
            decided_by="brain",
            related_journal=[note.id for note in notes],
            related_literature=[item.id for item in literature],
        )
    )

    await decision_service.update(
        decision.id,
        DecisionUpdate(related_journal=[], related_literature=[]),
    )
    assert await _outgoing_ids(
        db,
        source_type="decision",
        source_id=decision.id,
        link_type="justified_by",
        target_type="journal",
    ) == set()
    assert await _incoming_ids(
        db,
        target_type="decision",
        target_id=decision.id,
        link_type="informed_by",
        source_type="literature",
    ) == set()

    decisions = [
        await _decision(decision_service, label)
        for label in ("literature-one", "literature-two")
    ]
    item = await literature_service.create(
        LiteratureCreate(
            title="relation-owning paper",
            related_decisions=[decision.id, decisions[0].id],
        )
    )
    await literature_service.update(
        item.id,
        LiteratureUpdate(related_decisions=[decisions[1].id]),
    )
    assert await _outgoing_ids(
        db,
        source_type="literature",
        source_id=item.id,
        link_type="informed_by",
        target_type="decision",
    ) == {decisions[1].id}
    await literature_service.update(
        item.id,
        LiteratureUpdate(related_decisions=[]),
    )
    assert await _outgoing_ids(
        db,
        source_type="literature",
        source_id=item.id,
        link_type="informed_by",
        target_type="decision",
    ) == set()


@pytest.mark.asyncio
async def test_mission_motivation_replacement_and_blank_removal(
    db_with_project: Database,
) -> None:
    db = db_with_project
    decision_service = DecisionService(db, project_id=PROJECT_ID)
    mission_service = MissionService(db, project_id=PROJECT_ID)
    first = await _decision(decision_service, "first motive")
    second = await _decision(decision_service, "second motive")
    mission = await mission_service.create(
        MissionCreate(
            phase="execution",
            objective="replace motivation",
            motivated_by_decision=first.id,
        )
    )

    await mission_service.update(
        mission.id,
        MissionUpdate(motivated_by_decision=second.id),
    )
    assert (await mission_service.get(mission.id)).motivated_by_decision == second.id
    assert await _incoming_ids(
        db,
        target_type="mission",
        target_id=mission.id,
        link_type="motivated",
        source_type="decision",
    ) == {second.id}

    await mission_service.update(
        mission.id,
        MissionUpdate(motivated_by_decision=""),
    )
    assert (await mission_service.get(mission.id)).motivated_by_decision is None
    assert await _incoming_ids(
        db,
        target_type="mission",
        target_id=mission.id,
        link_type="motivated",
        source_type="decision",
    ) == set()


@pytest.mark.asyncio
async def test_note_create_failure_rolls_back_all_aggregate_rows(
    db_with_project: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = db_with_project
    decision = await _decision(
        DecisionService(db, project_id=PROJECT_ID),
        "rollback anchor",
    )
    service = NoteService(db, project_id=PROJECT_ID)

    async def fail_audit(*args, **kwargs) -> None:
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(service, "audit", fail_audit)
    with pytest.raises(RuntimeError, match="simulated audit failure"):
        await service.create(
            JournalEntryCreate(
                content="atomiccreaterollbacktoken",
                related_decisions=[decision.id],
                tags=["atomic-create-rollback"],
            )
        )

    assert await db.fetchone(
        "SELECT id FROM journal WHERE content = 'atomiccreaterollbacktoken'"
    ) is None
    assert await db.fetchone(
        "SELECT entity_id FROM tags WHERE tag = 'atomic-create-rollback'"
    ) is None
    assert await db.fetchone(
        "SELECT id FROM entity_links WHERE target_id = ? AND link_type = 'references'",
        [decision.id],
    ) is None
    assert await db.fetchone(
        "SELECT id FROM fts_journal WHERE fts_journal MATCH 'atomiccreaterollbacktoken'"
    ) is None
    assert await db.fetchone(
        "SELECT id FROM events WHERE summary LIKE '%atomiccreaterollbacktoken%'"
    ) is None


@pytest.mark.asyncio
async def test_note_update_failure_restores_row_edges_and_fts(
    db_with_project: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = db_with_project
    decision_service = DecisionService(db, project_id=PROJECT_ID)
    first = await _decision(decision_service, "rollback first")
    second = await _decision(decision_service, "rollback second")
    service = NoteService(db, project_id=PROJECT_ID)
    note = await service.create(
        JournalEntryCreate(
            content="atomicbeforetoken",
            related_decisions=[first.id],
        )
    )

    async def fail_audit(*args, **kwargs) -> None:
        raise RuntimeError("simulated update audit failure")

    monkeypatch.setattr(service, "audit", fail_audit)
    with pytest.raises(RuntimeError, match="simulated update audit failure"):
        await service.update(
            note.id,
            JournalEntryUpdate(
                content="atomicaftertoken",
                related_decisions=[second.id],
            ),
        )

    restored = await service.get(note.id)
    assert restored.content == "atomicbeforetoken"
    assert restored.related_decisions == [first.id]
    assert await _outgoing_ids(
        db,
        source_type="journal",
        source_id=note.id,
        link_type="references",
        target_type="decision",
    ) == {first.id}
    assert await db.fetchone(
        "SELECT id FROM fts_journal WHERE fts_journal MATCH 'atomicbeforetoken'"
    ) == {"id": note.id}
    assert await db.fetchone(
        "SELECT id FROM fts_journal WHERE fts_journal MATCH 'atomicaftertoken'"
    ) is None


@pytest.mark.asyncio
async def test_report_materialization_failure_rolls_back_whole_report(
    db_with_project: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = db_with_project
    mission_service = MissionService(db, project_id=PROJECT_ID)
    mission = await mission_service.create(
        MissionCreate(phase="execution", objective="atomic report")
    )

    real_create = NoteService.create
    calls = 0

    async def fail_second_create(self, data, actor=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated materialization failure")
        return await real_create(self, data, actor=actor)

    monkeypatch.setattr(NoteService, "create", fail_second_create)
    with pytest.raises(RuntimeError, match="simulated materialization failure"):
        await mission_service.submit_report(
            mission.id,
            MissionReportCreate(
                summary="should roll back",
                findings=["reportfirsttoken", "reportsecondtoken"],
            ),
        )

    restored = await mission_service.get(mission.id)
    assert restored.status == mission.status
    assert restored.report is None
    assert await db.fetchall(
        "SELECT id FROM journal WHERE related_mission = ? AND project_id = ?",
        [mission.id, PROJECT_ID],
    ) == []
    assert await db.fetchone(
        """SELECT id FROM events
           WHERE project_id = ? AND event_type = 'mission_completed'
             AND entity_id = ?""",
        [PROJECT_ID, mission.id],
    ) is None
    audit_rows = await db.fetchall(
        "SELECT details FROM audit_log WHERE project_id = ? AND entity_id = ?",
        [PROJECT_ID, mission.id],
    )
    assert not any(
        row["details"]
        and json.loads(row["details"]).get("action") == "submit_report"
        for row in audit_rows
    )
    assert await db.fetchone(
        "SELECT id FROM fts_journal WHERE fts_journal MATCH 'reportfirsttoken'"
    ) is None
