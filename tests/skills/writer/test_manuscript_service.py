"""Tests for ManuscriptService (Phase 3 T3).

Verifies register / get / validate_reference operations against a real
sqlite Database fixture (provided by tests/conftest.py db_with_project)
through the actual NoteService surface, so manifest tagging and the
get-filter-by-tag behavior are exercised end-to-end.

Per mis_01KS2WW6MRN6AXP11EMCSCDFAR T4 acceptance criteria.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.services.manuscript import ManuscriptService
from rka.services.notes import NoteService


@pytest_asyncio.fixture
async def manuscript_service(db_with_project: Database) -> ManuscriptService:
    notes = NoteService(db_with_project, project_id="proj_default")
    return ManuscriptService(db_with_project, notes=notes, project_id="proj_default")


@pytest_asyncio.fixture
async def journal_service(db_with_project: Database) -> NoteService:
    return NoteService(db_with_project, project_id="proj_default")


class TestRegister:
    """register creates a journal entry tagged 'manuscript' + venue + phase:draft."""

    async def test_register_creates_journal_entry(self, manuscript_service) -> None:
        entry = await manuscript_service.register(
            venue="CHI",
            title="Permission Fatigue in LLM Agents",
            abstract="Diary study of N=24 participants.",
            sections=["Introduction", "Method"],
        )
        assert entry.id.startswith("jrn_")
        assert entry.verbatim_input is not None
        assert "Permission Fatigue" in entry.verbatim_input
        assert "Diary study" in entry.verbatim_input

    async def test_register_tags_include_manuscript_venue_phase(
        self, manuscript_service, journal_service
    ) -> None:
        entry = await manuscript_service.register(
            venue="EMNLP", title="Title X",
        )
        # Re-read via NoteService to confirm tags landed in storage. NoteService
        # tag layer normalizes case (existing system behavior); compare lowercase.
        fetched = await journal_service.get(entry.id)
        tags = getattr(fetched, "tags", None) or []
        tags_lower = [t.lower() for t in tags]
        assert "manuscript" in tags_lower
        assert "venue:emnlp" in tags_lower
        assert "phase:draft" in tags_lower

    async def test_register_writes_section_index(self, manuscript_service) -> None:
        entry = await manuscript_service.register(
            venue="CHI",
            title="T",
            sections=["Intro", "Related", "Method"],
        )
        assert "Intro" in entry.content
        assert "Method" in entry.content
        assert "outlined" in entry.content.lower()


class TestGet:
    """get reads a manuscript by id and verifies the 'manuscript' tag."""

    async def test_get_returns_manuscript_dict(self, manuscript_service) -> None:
        entry = await manuscript_service.register(
            venue="USENIX", title="Sample Manuscript",
        )
        result = await manuscript_service.get(entry.id)
        assert result is not None
        assert result["id"] == entry.id
        # NoteService tag layer normalizes case; venue parsed back as lowercase.
        assert result["venue"].lower() == "usenix"
        assert result["phase"] == "draft"
        assert result["title"] == "Sample Manuscript"

    async def test_get_missing_id_returns_none(self, manuscript_service) -> None:
        result = await manuscript_service.get("jrn_01_does_not_exist")
        assert result is None

    async def test_get_non_manuscript_journal_returns_none(
        self, manuscript_service, journal_service
    ) -> None:
        """A regular journal entry (no 'manuscript' tag) should NOT be returned as a manuscript."""
        from rka.models.journal import JournalEntryCreate

        entry = await journal_service.create(
            JournalEntryCreate(
                content="not a manuscript",
                type="note",
                source="executor",
                tags=["random-tag", "venue:CHI"],
            ),
        )
        result = await manuscript_service.get(entry.id)
        assert result is None, "Non-manuscript jrn_ entries should not be returned as manuscripts."


class TestValidateReference:
    """validate_reference proxies to validate_references.py via subprocess.

    Tests run with the real validate_references.py script; subprocess returns
    a verdict for the supplied reference dict. Since this test environment
    does not have habanero/pyalex/etc. installed for live API calls, the
    pipeline's Stage B returns no confirms; the verdict ends up UNVERIFIED
    (then Stage G falls back via no-serpapi-budget). The test asserts the
    structural contract (verdict dict shape), not specific status content.
    """

    async def test_validate_reference_returns_verdict_dict(self, manuscript_service) -> None:
        # Use a clearly fake DOI so all backends return None (offline-deterministic).
        manuscript = await manuscript_service.register(venue="CHI", title="Validation test")
        result = await manuscript_service.validate_reference(
            {"DOI": "10.9999/totally-fake-doi-for-test"},
            manuscript_id=manuscript.id,
        )
        assert isinstance(result, dict)
        assert result["manuscript_id"] == manuscript.id
        assert result["validation_id"].startswith("rvd_")
        assert "retraction_checked" in result

    async def test_validate_reference_handles_subprocess_error(self, manuscript_service) -> None:
        # Reject an empty reference before creating files or a subprocess.
        manuscript = await manuscript_service.register(venue="CHI", title="Error test")
        with pytest.raises(ValueError, match="at least DOI or title"):
            await manuscript_service.validate_reference(
                {},
                manuscript_id=manuscript.id,
            )
