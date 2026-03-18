"""Tests for v2.1 Phase 0: provenance roundtrip, role_id, backward compat, config."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from pathlib import Path

from rka.infra.database import Database
from rka.models.journal import JournalEntryCreate, JournalEntryUpdate
from rka.models.mission import MissionCreate
from rka.models.checkpoint import CheckpointCreate
from rka.models.decision import DecisionCreate
from rka.services.notes import NoteService
from rka.services.missions import MissionService
from rka.services.checkpoints import CheckpointService
from rka.services.decisions import DecisionService
from rka.services.base import validate_provenance, VALID_PROVENANCE_TYPES
from rka.config import RKAConfig


async def _ensure_project(db: Database, project_id: str = "proj_default") -> None:
    await db.execute(
        "INSERT OR IGNORE INTO projects (id, name, description, created_by) VALUES (?, ?, ?, ?)",
        [project_id, "Test", "Test project", "system"],
    )
    await db.execute(
        """INSERT OR IGNORE INTO project_states
           (project_id, project_name, project_description, phases_config, created_at, updated_at)
           VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'), strftime('%Y-%m-%dT%H:%M:%SZ','now'))""",
        [project_id, "Test", "Test project", "[]"],
    )
    await db.commit()


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    db_path = str(tmp_path / "test_v21.db")
    database = Database(db_path)
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    await _ensure_project(database)
    yield database
    await database.close()


# ---- validate_provenance tests ----

def test_validate_provenance_none():
    assert validate_provenance(None) is None


def test_validate_provenance_valid_dict():
    prov = {"type": "literature_derived", "source_id": "lit_123", "location": "section 3.2"}
    result = validate_provenance(prov)
    parsed = json.loads(result)
    assert parsed["type"] == "literature_derived"
    assert parsed["source_id"] == "lit_123"
    assert parsed["location"] == "section 3.2"


def test_validate_provenance_no_type():
    """type is optional — dict without it should pass."""
    prov = {"source_id": "lit_123", "summary": "Extracted from paper"}
    result = validate_provenance(prov)
    parsed = json.loads(result)
    assert parsed["source_id"] == "lit_123"


def test_validate_provenance_unknown_extra_fields():
    """Unknown extra fields are preserved."""
    prov = {"type": "manual_entry", "custom_field": "preserved"}
    result = validate_provenance(prov)
    parsed = json.loads(result)
    assert parsed["custom_field"] == "preserved"


def test_validate_provenance_invalid_type():
    """Invalid type raises ValueError."""
    with pytest.raises(ValueError, match="Invalid provenance type"):
        validate_provenance({"type": "totally_invalid"})


def test_validate_provenance_json_string():
    """JSON string input is parsed and validated."""
    result = validate_provenance('{"type": "imported", "origin": "bibtex"}')
    parsed = json.loads(result)
    assert parsed["type"] == "imported"


def test_validate_provenance_raw_string():
    """Non-JSON string is stored as-is."""
    result = validate_provenance("manual notes from meeting")
    assert result == "manual notes from meeting"


# ---- Note provenance + role_id roundtrip ----

@pytest.mark.asyncio
async def test_note_create_with_provenance(db: Database):
    svc = NoteService(db)
    data = JournalEntryCreate(
        content="Derived from literature review",
        type="note",
        source="brain",
        provenance={"type": "literature_derived", "source_id": "lit_abc", "location": "Table 2"},
        role_id="researcher_brain",
    )
    entry = await svc.create(data)
    assert entry.provenance is not None
    assert entry.provenance["type"] == "literature_derived"
    assert entry.provenance["source_id"] == "lit_abc"
    assert entry.role_id == "researcher_brain"


@pytest.mark.asyncio
async def test_note_create_without_provenance(db: Database):
    """Backward compat: creating a note without provenance still works."""
    svc = NoteService(db)
    data = JournalEntryCreate(
        content="Plain note without provenance",
        type="note",
        source="executor",
    )
    entry = await svc.create(data)
    assert entry.provenance is None
    assert entry.role_id is None
    assert entry.id.startswith("jrn_")


@pytest.mark.asyncio
async def test_note_update_provenance(db: Database):
    svc = NoteService(db)
    data = JournalEntryCreate(content="Initial note", source="brain")
    entry = await svc.create(data)
    assert entry.provenance is None

    updated = await svc.update(
        entry.id,
        JournalEntryUpdate(provenance={"type": "experiment_result", "trial": 3}),
    )
    assert updated.provenance is not None
    assert updated.provenance["type"] == "experiment_result"
    assert updated.provenance["trial"] == 3


@pytest.mark.asyncio
async def test_note_provenance_invalid_type_rejected(db: Database):
    svc = NoteService(db)
    with pytest.raises(ValueError, match="Invalid provenance type"):
        data = JournalEntryCreate(
            content="Bad provenance",
            source="brain",
            provenance={"type": "nonexistent_type"},
        )
        await svc.create(data)


# ---- Mission role_id ----

@pytest.mark.asyncio
async def test_mission_create_with_role_id(db: Database):
    svc = MissionService(db)
    data = MissionCreate(
        phase="p1",
        objective="Test mission with role",
        role_id="executor_impl",
    )
    mission = await svc.create(data)
    assert mission.role_id == "executor_impl"


@pytest.mark.asyncio
async def test_mission_create_without_role_id(db: Database):
    svc = MissionService(db)
    data = MissionCreate(phase="p1", objective="Test mission no role")
    mission = await svc.create(data)
    assert mission.role_id is None


# ---- Checkpoint role_id ----

@pytest.mark.asyncio
async def test_checkpoint_create_with_role_id(db: Database):
    # Create a mission first to satisfy FK constraint
    msvc = MissionService(db)
    mission = await msvc.create(MissionCreate(phase="p1", objective="For checkpoint"))

    svc = CheckpointService(db)
    data = CheckpointCreate(
        mission_id=mission.id,
        type="decision",
        description="Need PI input",
        role_id="executor_impl",
    )
    chk = await svc.create(data)
    assert chk.role_id == "executor_impl"


# ---- Decision role_id ----

@pytest.mark.asyncio
async def test_decision_create_with_role_id(db: Database):
    svc = DecisionService(db)
    data = DecisionCreate(
        question="Which approach to use?",
        phase="p1",
        decided_by="brain",
        role_id="reviewer_brain",
    )
    dec = await svc.create(data)
    assert dec.role_id == "reviewer_brain"


# ---- Worker no-LLM graceful behavior ----

@pytest.mark.asyncio
async def test_note_worker_no_llm_skips_gracefully(db: Database):
    """When LLM is None, worker jobs skip gracefully."""
    svc = NoteService(db, llm=None)
    data = JournalEntryCreate(content="Test content", source="executor")
    entry = await svc.create(data)

    # All LLM-dependent jobs should skip
    result = await svc.process_auto_tag_job(entry.id)
    assert result["outcome"] == "skipped"
    assert result["reason"] == "llm_disabled"

    result = await svc.process_auto_link_job(entry.id)
    assert result["outcome"] == "skipped"
    assert result["reason"] == "llm_disabled"

    result = await svc.process_auto_summarize_job(entry.id)
    assert result["outcome"] == "skipped"
    assert result["reason"] == "llm_disabled"


@pytest.mark.asyncio
async def test_mission_worker_no_llm_skips_gracefully(db: Database):
    svc = MissionService(db, llm=None)
    data = MissionCreate(phase="p1", objective="Test mission")
    mission = await svc.create(data)

    result = await svc.process_auto_tag_job(mission.id)
    assert result["outcome"] == "skipped"
    assert result["reason"] == "llm_disabled"


@pytest.mark.asyncio
async def test_decision_worker_no_llm_skips_gracefully(db: Database):
    svc = DecisionService(db, llm=None)
    data = DecisionCreate(question="Q?", phase="p1", decided_by="brain")
    dec = await svc.create(data)

    result = await svc.process_auto_tag_job(dec.id)
    assert result["outcome"] == "skipped"
    assert result["reason"] == "llm_disabled"


# ---- Config tests ----

def test_config_workspace_root_default():
    cfg = RKAConfig()
    assert cfg.workspace_root is None


def test_config_model_tiers_default():
    cfg = RKAConfig()
    assert "fast" in cfg.model_tiers
    assert "standard" in cfg.model_tiers
    assert "reasoning" in cfg.model_tiers


def test_config_model_tiers_custom():
    cfg = RKAConfig(model_tiers={"fast": "haiku", "standard": "sonnet"})
    assert cfg.model_tiers["fast"] == "haiku"
    assert cfg.model_tiers["standard"] == "sonnet"
