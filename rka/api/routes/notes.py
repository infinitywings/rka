"""Journal (notes) routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.models.journal import JournalEntry, JournalEntryCreate, JournalEntryUpdate
from rka.services.notes import NoteService
from rka.api.deps import get_scoped_note_service

router = APIRouter()


@router.post("/notes", response_model=JournalEntry, status_code=201)
async def create_note(
    data: JournalEntryCreate,
    svc: NoteService = Depends(get_scoped_note_service),
):
    return await svc.create(data)


@router.get("/notes", response_model=list[JournalEntry])
async def list_notes(
    type: str | None = None,
    phase: str | None = None,
    confidence: str | None = None,
    importance: str | None = None,
    source: str | None = None,
    since: str | None = None,
    hide_superseded: bool = True,
    limit: int = Query(50, le=200),
    offset: int = 0,
    svc: NoteService = Depends(get_scoped_note_service),
):
    return await svc.list(
        type=type, phase=phase, confidence=confidence,
        importance=importance, source=source, since=since,
        hide_superseded=hide_superseded, limit=limit, offset=offset,
    )


@router.get("/notes/{note_id}", response_model=JournalEntry)
async def get_note(note_id: str, svc: NoteService = Depends(get_scoped_note_service)):
    entry = await svc.get(note_id)
    if entry is None:
        raise HTTPException(404, f"Note {note_id} not found")
    return entry


@router.put("/notes/{note_id}", response_model=JournalEntry)
async def update_note(
    note_id: str,
    data: JournalEntryUpdate,
    svc: NoteService = Depends(get_scoped_note_service),
):
    entry = await svc.get(note_id)
    if entry is None:
        raise HTTPException(404, f"Note {note_id} not found")
    return await svc.update(note_id, data)
