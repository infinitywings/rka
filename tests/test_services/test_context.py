"""Tests for the ContextEngine."""

from __future__ import annotations

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.services.context import ContextEngine
from rka.services.search import SearchService


@pytest_asyncio.fixture
async def context_engine(db_with_project: Database) -> ContextEngine:
    """Context engine with test data populated."""
    db = db_with_project
    search = SearchService(db=db, embeddings=None)
    engine = ContextEngine(db=db, search=search, llm=None, hot_days=3, warm_days=14)

    # Use strftime to produce ISO timestamps with 'Z' suffix — matches schema defaults
    # and ensures the classifier can parse them as timezone-aware datetimes.
    NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
    OLD = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-30 days')"

    # HOT: active + current phase + recent
    await db.execute(
        f"""INSERT INTO journal (id, type, content, source, confidence, phase, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, {NOW}, {NOW})""",
        ["jrn_hot", "finding", "Hot finding about timing attacks", "pi", "hypothesis", "phase_1"],
    )

    # Also HOT: active decision in current phase
    await db.execute(
        f"""INSERT INTO decisions (id, question, decided_by, status, phase, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, {NOW}, {NOW})""",
        ["dec_hot", "Should we use approach A or B?", "brain", "active", "phase_1"],
    )

    # WARM: active but different phase
    await db.execute(
        f"""INSERT INTO missions (id, objective, phase, status, created_at)
           VALUES (?, ?, ?, ?, {NOW})""",
        ["mis_warm", "Future phase mission", "phase_2", "active"],
    )

    # COLD: abandoned (note: _get_overview_candidates only fetches active decisions,
    #        so this won't appear in overview — but useful for direct classification tests)
    await db.execute(
        f"""INSERT INTO decisions (id, question, decided_by, status, phase, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, {OLD}, {OLD})""",
        ["dec_cold", "Old abandoned question", "brain", "abandoned", "phase_1"],
    )

    # COLD: completed long ago (verified + old → cold)
    await db.execute(
        f"""INSERT INTO journal (id, type, content, source, confidence, phase, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, {OLD}, {OLD})""",
        ["jrn_cold", "finding", "Very old verified entry", "pi", "verified", "phase_1"],
    )

    # FTS5 entries for search
    await db.execute(
        "INSERT INTO fts_journal (id, content, summary) VALUES (?, ?, ?)",
        ["jrn_hot", "Hot finding about timing attacks", ""],
    )
    await db.execute(
        "INSERT INTO fts_decisions (id, question, rationale) VALUES (?, ?, ?)",
        ["dec_hot", "Should we use approach A or B?", ""],
    )

    # Active literature
    await db.execute(
        f"""INSERT INTO literature (id, title, status, created_at, updated_at)
           VALUES (?, ?, ?, {NOW}, {NOW})""",
        ["lit_warm", "Some paper", "to_read"],
    )

    await db.commit()
    return engine


class TestTemperatureClassification:
    """Test HOT/WARM/COLD classification."""

    @pytest.mark.asyncio
    async def test_overview_classifies_hot(self, context_engine: ContextEngine):
        """Active + current phase + recent entries should be HOT."""
        package = await context_engine.get_context(phase="phase_1", max_tokens=5000)
        # hot_entries should include the recent hypothesis journal and active decision
        hot_ids = [e for e in package.hot_entries if "jrn_hot" in e or "dec_hot" in e]
        assert len(hot_ids) >= 1

    @pytest.mark.asyncio
    async def test_overview_classifies_cold(self, context_engine: ContextEngine):
        """Old completed entries should be COLD."""
        package = await context_engine.get_context(phase="phase_1", max_tokens=5000)
        # jrn_cold is 'verified' + 30 days old → COLD
        # The cold fallback renderer uses [entity_type] content (no ID),
        # so check for the content text.
        cold_content = [e for e in package.cold_entries if "Very old verified" in e]
        assert len(cold_content) >= 1

    @pytest.mark.asyncio
    async def test_overview_returns_context_package(self, context_engine: ContextEngine):
        """Verify ContextPackage structure."""
        package = await context_engine.get_context(max_tokens=5000)
        assert package.phase == "phase_1"
        assert isinstance(package.hot_entries, list)
        assert isinstance(package.warm_entries, list)
        assert isinstance(package.cold_entries, list)
        assert isinstance(package.sources, list)
        assert package.token_estimate > 0

    @pytest.mark.asyncio
    async def test_topic_search(self, context_engine: ContextEngine):
        """Topic-focused context should search and classify."""
        package = await context_engine.get_context(topic="timing attacks", max_tokens=5000)
        assert package.topic == "timing attacks"
        assert len(package.sources) >= 1

    @pytest.mark.asyncio
    async def test_token_budget_respected(self, context_engine: ContextEngine):
        """Token estimate should not exceed budget."""
        package = await context_engine.get_context(max_tokens=100)
        assert package.token_estimate <= 200  # Small buffer allowed


class TestClassifyTemperatureDirect:
    """Test _classify_temperature directly with synthetic entries."""

    def test_hot_classification(self):
        """Active + current phase + recent → HOT."""
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entries = [
            {"id": "j1", "entity_type": "journal", "confidence": "hypothesis",
             "phase": "p1", "updated_at": now_str},
        ]
        engine = ContextEngine(db=None, search=None, llm=None, hot_days=3, warm_days=14)
        hot, warm, cold = engine._classify_temperature(entries, "p1")
        assert len(hot) == 1
        assert hot[0]["id"] == "j1"

    def test_cold_abandoned(self):
        """Abandoned status → COLD regardless of recency."""
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entries = [
            {"id": "d1", "entity_type": "decision", "status": "abandoned",
             "phase": "p1", "updated_at": now_str},
        ]
        engine = ContextEngine(db=None, search=None, llm=None, hot_days=3, warm_days=14)
        hot, warm, cold = engine._classify_temperature(entries, "p1")
        assert len(cold) == 1

    def test_warm_active_wrong_phase(self):
        """Active + wrong phase → WARM (not HOT)."""
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entries = [
            {"id": "m1", "entity_type": "mission", "status": "active",
             "phase": "p2", "updated_at": now_str},
        ]
        engine = ContextEngine(db=None, search=None, llm=None, hot_days=3, warm_days=14)
        hot, warm, cold = engine._classify_temperature(entries, "p1")
        assert len(warm) == 1


class TestRenderEntry:
    """Test entry rendering."""

    def test_render_journal(self):
        entry = {"entity_type": "journal", "id": "jrn_1", "type": "finding", "confidence": "hypothesis", "content": "Test content"}
        text = ContextEngine._render_entry(entry)
        assert "finding" in text
        assert "hypothesis" in text
        assert "jrn_1" in text

    def test_render_decision(self):
        entry = {"entity_type": "decision", "id": "dec_1", "status": "active", "question": "Which approach?", "chosen": "A"}
        text = ContextEngine._render_entry(entry)
        assert "decision" in text
        assert "→ A" in text

    def test_render_literature(self):
        entry = {"entity_type": "literature", "id": "lit_1", "status": "reading", "title": "Some Paper"}
        text = ContextEngine._render_entry(entry)
        assert "lit" in text
        assert "Some Paper" in text

    def test_render_mission(self):
        entry = {"entity_type": "mission", "id": "mis_1", "status": "active", "objective": "Do something"}
        text = ContextEngine._render_entry(entry)
        assert "mission" in text
        assert "Do something" in text

    def test_render_truncates(self):
        entry = {"entity_type": "journal", "id": "j1", "type": "note", "confidence": "?", "content": "x" * 1000}
        text = ContextEngine._render_entry(entry, max_len=50)
        assert len(text) < 200  # Should be truncated


class TestTokenEstimation:
    """Test token estimation."""

    def test_estimate_tokens_basic(self):
        assert ContextEngine._estimate_tokens("hello world") >= 1

    def test_estimate_tokens_empty(self):
        assert ContextEngine._estimate_tokens("") == 1

    def test_estimate_tokens_long(self):
        text = "a" * 400
        tokens = ContextEngine._estimate_tokens(text)
        assert tokens == 100  # ~4 chars per token
