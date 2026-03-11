"""Tests for SummaryService and QAService."""

from __future__ import annotations

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.infra.llm import LLMUnavailableError
from rka.services.summary import SummaryService, QAService


@pytest_asyncio.fixture
async def seeded_db(db: Database) -> Database:
    """DB with journal/decision data for summary evidence gathering."""
    for i in range(5):
        await db.execute(
            "INSERT INTO journal (id, type, content, source, confidence, phase) VALUES (?, ?, ?, ?, ?, ?)",
            [f"jrn_{i:03d}", "finding", f"Research finding number {i}", "pi", "hypothesis", "phase_1"],
        )
    await db.execute(
        "INSERT INTO decisions (id, question, rationale, decided_by, status, phase) VALUES (?, ?, ?, ?, ?, ?)",
        ["dec_001", "Which model to use?", "Consider accuracy", "brain", "active", "phase_1"],
    )
    await db.execute(
        "INSERT INTO missions (id, objective, phase, status, context) VALUES (?, ?, ?, ?, ?)",
        ["mis_001", "Run experiment A", "phase_1", "active", "Experiment context"],
    )
    await db.execute(
        "INSERT INTO literature (id, title, abstract, status) VALUES (?, ?, ?, ?)",
        ["lit_001", "Paper on Models", "Abstract text here", "reading"],
    )
    # Insert FTS entries
    for i in range(5):
        await db.execute(
            "INSERT INTO fts_journal (id, content, summary) VALUES (?, ?, ?)",
            [f"jrn_{i:03d}", f"Research finding number {i}", ""],
        )
    await db.execute(
        "INSERT INTO fts_decisions (id, question, rationale) VALUES (?, ?, ?)",
        ["dec_001", "Which model to use?", "Consider accuracy"],
    )
    await db.commit()
    return db


@pytest_asyncio.fixture
async def summary_svc(seeded_db: Database) -> SummaryService:
    return SummaryService(db=seeded_db, llm=None)


@pytest_asyncio.fixture
async def qa_svc(seeded_db: Database) -> QAService:
    return QAService(db=seeded_db, llm=None)


class TestSummaryServiceRequiresLLM:
    @pytest.mark.asyncio
    async def test_generate_raises_without_llm(self, summary_svc: SummaryService):
        with pytest.raises(LLMUnavailableError):
            await summary_svc.generate("project")

    @pytest.mark.asyncio
    async def test_list_summaries_empty(self, summary_svc: SummaryService):
        result = await summary_svc.list_summaries()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, summary_svc: SummaryService):
        result = await summary_svc.get("sum_nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_bless_nonexistent(self, summary_svc: SummaryService):
        result = await summary_svc.bless("sum_nonexistent")
        assert result is None


class TestSummaryEvidenceGathering:
    """Test _gather_evidence directly — this doesn't require LLM."""

    @pytest.mark.asyncio
    async def test_gather_phase_evidence(self, summary_svc: SummaryService):
        evidence = await summary_svc._gather_evidence("phase", "phase_1")
        assert len(evidence) > 0
        types = {e["entity_type"] for e in evidence}
        assert "journal" in types
        assert "decision" in types

    @pytest.mark.asyncio
    async def test_gather_project_evidence(self, summary_svc: SummaryService):
        evidence = await summary_svc._gather_evidence("project", None)
        assert len(evidence) > 0
        types = {e["entity_type"] for e in evidence}
        assert "journal" in types

    @pytest.mark.asyncio
    async def test_gather_mission_evidence(self, summary_svc: SummaryService):
        evidence = await summary_svc._gather_evidence("mission", "mis_001")
        assert len(evidence) > 0
        assert any(e["entity_type"] == "mission" for e in evidence)

    @pytest.mark.asyncio
    async def test_gather_tag_no_tags(self, summary_svc: SummaryService):
        evidence = await summary_svc._gather_evidence("tag", "nonexistent_tag")
        assert evidence == []


class TestQAServiceRequiresLLM:
    @pytest.mark.asyncio
    async def test_ask_raises_without_llm(self, qa_svc: QAService):
        with pytest.raises(LLMUnavailableError):
            await qa_svc.ask("What is the main finding?")

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, qa_svc: QAService):
        result = await qa_svc.list_sessions()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_session_nonexistent(self, qa_svc: QAService):
        result = await qa_svc.get_session("qas_nonexistent")
        assert result is None


class TestQAEvidenceGathering:
    @pytest.mark.asyncio
    async def test_gather_qa_evidence_uses_fts(self, qa_svc: QAService):
        evidence = await qa_svc._gather_qa_evidence("research finding", None, None)
        assert len(evidence) > 0

    @pytest.mark.asyncio
    async def test_gather_qa_evidence_falls_back(self, qa_svc: QAService):
        evidence = await qa_svc._gather_qa_evidence("xyzzy nonsense query", None, None)
        assert len(evidence) > 0  # Should have recent entries as fallback


class TestQAVerifySource:
    @pytest.mark.asyncio
    async def test_verify_nonexistent_log(self, qa_svc: QAService):
        result = await qa_svc.verify_source("qal_nonexistent", 0)
        assert result["verified"] is False
        assert "not found" in result["reason"]
