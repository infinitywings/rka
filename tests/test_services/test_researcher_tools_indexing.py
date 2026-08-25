"""Rows this service writes must be findable.

`ResearcherToolsService` inserts journal entries, claims and clusters with
raw SQL, bypassing the services that own those entities — and with them, the
FTS and embedding sync those services perform. The rows existed and were
reachable by id; they were invisible to both keyword and semantic search.

Measured on the live instance before the fix: 15 recorded RQ conclusions, 0
of them in `fts_journal`. That is the answer to a research question — the
single thing most worth finding again — and no search could reach any of
them. Also 21 journal rows and 31 claims across five projects.
"""

import inspect
import re

import pytest

from rka.infra.database import Database
from rka.services import researcher_tools as rt_module
from rka.services.researcher_tools import ResearcherToolsService


async def _project(db: Database, pid: str) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO projects (id, name, description, created_by) "
        "VALUES (?, ?, ?, ?)",
        [pid, pid, pid, "system"],
    )
    await db.commit()


def _svc(db: Database, pid: str = "prj_rt") -> ResearcherToolsService:
    return ResearcherToolsService(db, project_id=pid)


class TestEveryRawInsertIndexes:
    """The structural check: no insert may be added without indexing it."""

    def test_no_raw_insert_is_left_unindexed(self):
        src = inspect.getsource(rt_module)
        indexed_entities = {"journal", "claims", "evidence_clusters"}
        inserts = re.findall(r"INSERT INTO (\w+)", src)
        relevant = [t for t in inserts if t in indexed_entities]
        assert relevant, "guard against the extraction matching nothing"
        assert len(re.findall(r"_index_new_row\(", src)) >= len(relevant), (
            f"{len(relevant)} inserts into indexed tables but fewer "
            "_index_new_row calls — a row was added that nothing can find"
        )

    def test_the_helper_covers_fts_and_embeddings(self):
        src = inspect.getsource(ResearcherToolsService._index_new_row)
        assert "_sync_fts" in src
        assert "enqueue" in src


class TestAnRqConclusionIsSearchable:
    """The one that mattered most: 15 existed, 0 were findable."""

    @pytest.mark.asyncio
    async def test_the_conclusion_reaches_fts(self, db: Database):
        await _project(db, "prj_rt")
        svc = _svc(db)

        await db.execute(
            "INSERT INTO decisions (id, project_id, question, chosen, rationale, "
            "decided_by, kind, phase, status) VALUES "
            "(?, ?, ?, '', '', 'brain', 'research_question', 'p', 'active')",
            ["dec_rq", "prj_rt", "Does the sampler drift?"],
        )
        await db.commit()

        await svc.advance_rq(
            "dec_rq", status="answered",
            conclusion="The pelagic sampler drifts by 4% per hour.",
        )

        rows = await db.fetchall(
            "SELECT id FROM fts_journal WHERE fts_journal MATCH ?", ["pelagic"],
        )
        assert rows, (
            "the recorded answer to a research question is not searchable"
        )

    @pytest.mark.asyncio
    async def test_it_is_queued_for_embedding_too(self, db: Database):
        await _project(db, "prj_rt")
        svc = _svc(db)
        svc.embeddings = object()  # presence is what gates the enqueue

        await db.execute(
            "INSERT INTO decisions (id, project_id, question, chosen, rationale, "
            "decided_by, kind, phase, status) VALUES "
            "(?, ?, ?, '', '', 'brain', 'research_question', 'p', 'active')",
            ["dec_rq2", "prj_rt", "Q?"],
        )
        await db.commit()

        await svc.advance_rq("dec_rq2", status="answered", conclusion="Yes.")

        jobs = await db.fetchall(
            "SELECT job_type FROM jobs WHERE project_id = ?", ["prj_rt"],
        )
        assert "note_embed" in {j["job_type"] for j in jobs}


class TestPaperProcessingIsSearchable:
    @pytest.mark.asyncio
    async def test_the_reading_note_and_its_claims_reach_fts(self, db: Database):
        await _project(db, "prj_rt")
        svc = _svc(db)

        await db.execute(
            "INSERT INTO literature (id, project_id, title, status) "
            "VALUES (?, ?, ?, 'read')",
            ["lit_x", "prj_rt", "A paper"],
        )
        await db.commit()

        await svc.process_paper(
            "lit_x",
            annotations=[{"passage": "Quorble resonance is measurable.",
                          "claim_type": "result"}],
            summary="Notes on quorble.",
        )

        assert await db.fetchall(
            "SELECT id FROM fts_claims WHERE fts_claims MATCH ?", ["quorble"],
        ), "claims extracted from a paper are not searchable"
