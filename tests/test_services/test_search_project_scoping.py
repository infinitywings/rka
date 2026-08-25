"""Search must spend its budget on the project being searched.

The FTS stage ranked across every project and applied `project_id` only when
hydrating the rows it had already chosen, so `limit` bought the global top N
and a project got whatever survived. Two projects hold 68% of the journal
corpus on this instance; measured against it, nine of thirteen projects got
**zero** candidates for `"design decision"` at limit=40 — indistinguishable,
to the caller, from having nothing on the topic.

Separately, the query sanitizer tokenized with `[a-zA-Z0-9]+` against tables
tokenized `porter unicode61`, which index accented words whole. That is not
recall loss but substitution: `résumé` became the fragment `sum`, a real
English word, which then floods the candidate pool with unrelated documents
that go on to receive the keyword weight.
"""

import inspect
import re

import pytest

from rka.infra.database import Database
from rka.services import search as search_module
from rka.services.search import SearchService


async def _project(db: Database, pid: str) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO projects (id, name, description, created_by) "
        "VALUES (?, ?, ?, ?)",
        [pid, pid, pid, "system"],
    )


async def _entry(db: Database, pid: str, eid: str, content: str) -> None:
    await db.execute(
        "INSERT INTO journal (id, project_id, type, content, source, confidence, "
        "importance, status) VALUES (?, ?, 'note', ?, 'executor', 'hypothesis', "
        "'normal', 'active')",
        [eid, pid, content],
    )
    await db.execute(
        "INSERT INTO fts_journal (id, content, summary) VALUES (?, ?, '')",
        [eid, content],
    )
    await db.commit()


class TestALargeProjectCannotStarveASmallOne:
    @pytest.mark.asyncio
    async def test_the_limit_buys_this_projects_top_n(self, db: Database):
        await _project(db, "prj_big")
        await _project(db, "prj_small")

        # The big project outranks the small one purely by volume.
        for i in range(50):
            await _entry(db, "prj_big", f"jrn_b{i}", "calibration drift analysis")
        await _entry(db, "prj_small", "jrn_s0", "calibration drift analysis")

        svc = SearchService(db=db, embeddings=None, project_id="prj_small")
        hits = await svc._fts_search("calibration drift", ["journal"], 10)

        assert hits, (
            "the small project's only matching entry was crowded out of the "
            "global top 10 — the caller cannot tell this from 'no matches'"
        )
        assert {h.entity_id for h in hits} == {"jrn_s0"}

    @pytest.mark.asyncio
    async def test_no_other_projects_rows_leak_in(self, db: Database):
        """The isolation property, asserted directly."""
        await _project(db, "prj_a")
        await _project(db, "prj_b")
        await _entry(db, "prj_a", "jrn_a0", "zarquon telemetry")
        await _entry(db, "prj_b", "jrn_b0", "zarquon telemetry")

        svc = SearchService(db=db, embeddings=None, project_id="prj_a")
        hits = await svc._fts_search("zarquon", ["journal"], 20)

        assert {h.entity_id for h in hits} == {"jrn_a0"}

    @pytest.mark.asyncio
    async def test_orphaned_index_rows_do_not_consume_the_budget(self, db: Database):
        """Deleting a project leaves its FTS rows behind — 2913 of them here.

        They were already excluded when the chosen ids were hydrated, so they
        never appeared in results. What they did do is occupy slots in the
        global top N before the filter ran, so a live entry ranked below them
        was never fetched at all. The JOIN drops them before the LIMIT, with
        no separate reaper.
        """
        await _project(db, "prj_live")
        # A live entry that ranks last among identical matches.
        for i in range(30):
            await db.execute(
                "INSERT INTO fts_journal (id, content, summary) VALUES (?, ?, '')",
                [f"jrn_ghost{i}", "quorble resonance"],
            )
        await _entry(db, "prj_live", "jrn_live", "quorble resonance")
        await db.commit()

        svc = SearchService(db=db, embeddings=None, project_id="prj_live")
        hits = await svc._fts_search("quorble", ["journal"], 10)

        assert {h.entity_id for h in hits} == {"jrn_live"}, (
            "30 orphaned index rows consumed the whole limit, so the one live "
            "entry was never fetched"
        )


class TestAccentedWordsSurviveTokenization:
    def test_the_sanitizer_keeps_them_whole(self):
        assert re.findall(r"\w+", "Buçinca résumé Größe", re.UNICODE) == [
            "Buçinca", "résumé", "Größe",
        ]

    def test_the_old_pattern_substituted_rather_than_dropped(self):
        """Why this mattered more than plain recall loss.

        `résumé` did not vanish — it became `sum`, a real English token that
        matches unrelated documents which then receive the keyword weight.
        """
        assert re.findall(r"[a-zA-Z0-9]+", "résumé") == ["r", "sum"]

    def test_underscores_still_split(self):
        r"""`\w` would have kept them, and that is a real behaviour change.

        `snake_case-mixed` splitting into three terms is deliberate and was
        evaluated empirically (eval-harness/tests/test_feature_flag.py, and
        the mission Q7 it cites). The first version of this fix used `\w+`,
        which admits the underscore; CI caught it. `[^\W_]+` keeps accented
        letters whole without keeping the underscore.
        """
        assert re.findall(r"[^\W_]+", "snake_case-mixed", re.UNICODE) == [
            "snake", "case", "mixed",
        ]

    def test_the_sanitizer_agrees(self):
        assert SearchService._sanitize_fts_query("snake_case") == '"snake" OR "case"'

    def test_no_ascii_only_tokenizer_remains(self):
        src = inspect.getsource(search_module)
        assert "[a-zA-Z0-9]" not in src, (
            "the FTS tables are tokenized `porter unicode61` and index "
            "accented words whole; an ASCII-only split shatters them"
        )

    @pytest.mark.asyncio
    async def test_an_accented_term_finds_its_entry(self, db: Database):
        await _project(db, "prj_acc")
        await _entry(db, "prj_acc", "jrn_acc", "Report by Buçinca on delegation")

        svc = SearchService(db=db, embeddings=None, project_id="prj_acc")
        hits = await svc._fts_search("Buçinca", ["journal"], 10)

        assert {h.entity_id for h in hits} == {"jrn_acc"}


class TestHostileInputStillDoesNotCrash:
    """The property the ASCII pattern was protecting; keep it."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("q", [
        '"unbalanced', "a NEAR b", "foo OR", "*", "()", "a AND (b", '""',
        "col:val", "-", "^", "NOT", "a*b", "'", "\\",
    ])
    async def test_no_query_raises(self, db: Database, q: str):
        await _project(db, "prj_h")
        await _entry(db, "prj_h", "jrn_h", "ordinary content")

        svc = SearchService(db=db, embeddings=None, project_id="prj_h")
        await svc._fts_search(q, ["journal"], 5)  # must not raise
