"""A branch's best hit must not be sorted to the back of its own list.

`_fts_search` and `_vector_search` number their hits from zero, so the best
one carries rank 0 — and both sorted with `h.fts_rank or 999`. Since
`0 or 999 == 999`, the best hit went to the END of its branch list. `_rrf_merge`
then takes each hit's rank from its `enumerate()` position over that list, not
from the rank attribute, so the best hit received the WORST reciprocal-rank
contribution.

Both branches are built at `limit * 2`, so the branch grows with `limit` and
the demoted hit sits at `len(branch) - 1`. Its fused score is therefore

    0.3/(60 + len_fts) + 0.7/(59 + len_vec)

which strictly decreases as `limit` grows, while every competitor's score is
limit-invariant. Measured against the live instance on a token appearing once
in the whole corpus:

    limit=3  -> rank 1      limit=10 -> absent
    limit=5  -> rank 1      limit=20 -> absent
    limit=8  -> rank 6      limit=30 -> absent

Enlarging a cap removed the answer. The caller's natural response to a
disappointing search — ask for more results — made it strictly worse.
"""

import inspect

import pytest

from rka.infra.database import Database
from rka.services.search import SearchHit, SearchService


async def _project(db: Database, pid: str) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO projects (id, name, description, created_by) "
        "VALUES (?, ?, ?, ?)",
        [pid, pid, pid, "system"],
    )
    await db.commit()


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


class TestZeroIsARankNotAMissingValue:
    def test_the_sentinel_no_longer_swallows_rank_zero(self):
        """`0 or 999` is 999. That one expression is the whole defect."""
        src = inspect.getsource(SearchService)
        assert "fts_rank or 999" not in src
        assert "vec_rank or 999" not in src

    @pytest.mark.asyncio
    async def test_a_branch_returns_its_hits_best_first(self, db: Database):
        """Needs two hits in ONE entity type — with one per type both carry
        rank 0 and the stable sort hides the inversion."""
        await _project(db, "prj_r")
        await _entry(db, "prj_r", "jrn_best", "calibration calibration calibration")
        await _entry(db, "prj_r", "jrn_worse", "calibration of something else entirely")

        svc = SearchService(db=db, embeddings=None, project_id="prj_r")
        hits = await svc._fts_search("calibration", ["journal"], 10)

        ranks = [h.fts_rank for h in hits]
        assert ranks == sorted(ranks), (
            f"branch returned ranks {ranks}; rank 0 was sorted to the back"
        )


class _StubBackend:
    """Every document gets a vector; the needle gets a distinct one."""

    model_name = "stub"
    dim = 768

    async def embed(self, text: str, is_query: bool = False) -> list[float]:
        v = [0.0] * 768
        v[0 if "vorplezium" in text else 1] = 1.0
        return v

    async def embed_batch(self, texts, is_query: bool = False):
        return [await self.embed(t) for t in texts]


class TestWideningTheLimitCannotLoseAnAnswer:
    """The user-visible symptom, and it needs BOTH branches.

    A keyword-only harness cannot show it: with one branch there is nothing
    for the demoted hit's shrinking contribution to lose to, and the test
    passes over a live bug. This one embeds the corpus so the vector branch
    contributes competitors whose scores do not move with `limit`.
    """

    @pytest.mark.asyncio
    async def test_the_rank_never_degrades_as_the_limit_grows(self, db: Database):
        """The contract `limit` actually breaks.

        Asserting mere presence is not enough and passes over the live bug:
        the corpus has to exceed `limit * 2` before the vector branch grows
        with the limit at all, and even then the answer degrades before it
        disappears. Measured here against main — the needle sits at vector
        position 5, 19, 39, 59 for limits 3, 10, 20, 30, and its final rank
        goes 1, 1, 1, 6. Against the fix it is position 0 and rank 1 at every
        limit.
        """
        from rka.infra.embeddings import EmbeddingService

        if not db.vec_available:
            pytest.skip("sqlite-vec not loaded in this environment")

        emb = EmbeddingService(model_name="stub", db=db, backend=_StubBackend())
        await _project(db, "prj_m")

        await _entry(db, "prj_m", "jrn_needle", "identifier vorplezium appears here")
        await emb.store_embedding(
            "journal", "jrn_needle", "identifier vorplezium appears here",
            project_id="prj_m",
        )
        # Must exceed 2 * the largest limit below, or the vector branch is
        # capped by the corpus and stops growing.
        for i in range(70):
            text = f"identifier of some other kind number {i}"
            await _entry(db, "prj_m", f"jrn_noise{i}", text)
            await emb.store_embedding("journal", f"jrn_noise{i}", text, project_id="prj_m")

        svc = SearchService(db=db, embeddings=emb, project_id="prj_m")
        ranks = {}
        for limit in (3, 10, 20, 30):
            ids = [h.entity_id for h in await svc.search("vorplezium", limit=limit)]
            ranks[limit] = ids.index("jrn_needle") + 1 if "jrn_needle" in ids else None

        assert all(r is not None for r in ranks.values()), (
            f"the answer disappeared: {ranks}"
        )
        # Non-INCREASING: a bigger limit may improve the rank or leave it
        # alone, never worsen it. Asserting the list is sorted ascending — my
        # first attempt — is satisfied by exactly the degradation it was
        # meant to catch, since [1, 1, 1, 6] is already in ascending order.
        ordered = sorted(ranks)
        offenders = [
            (a, ranks[a], b, ranks[b])
            for a, b in zip(ordered, ordered[1:])
            if ranks[b] > ranks[a]
        ]
        assert not offenders, (
            f"rank degraded as the limit grew: {ranks} — widening a cap made "
            "the answer worse, which is the caller's natural response to a "
            f"disappointing search. Offending steps: {offenders}"
        )


class TestARetiredEntityRanksBelowItsReplacement:
    """Exposed by the sort fix, decided on its own merits.

    `test_supersession_correctness` passed before only because the reversed
    sort happened to lift the replacement above the superseded entity. With
    the branches ordered correctly the stale one wins on match quality, so
    the tie has to be decided rather than left to an accident.
    """

    def test_retired_hits_sort_after_current_ones(self):
        hits = [
            SearchHit(entity_type="decision", entity_id="old", title="", snippet="",
                      status="superseded"),
            SearchHit(entity_type="decision", entity_id="new", title="", snippet="",
                      status="active"),
        ]
        assert [h.entity_id for h in SearchService._current_first(hits)] == ["new", "old"]

    def test_the_partition_is_stable(self):
        """It decides the current-vs-retired tie and nothing else."""
        hits = [
            SearchHit(entity_type="journal", entity_id=f"a{i}", title="", snippet="")
            for i in range(5)
        ]
        assert [h.entity_id for h in SearchService._current_first(hits)] == [
            "a0", "a1", "a2", "a3", "a4",
        ]

    def test_every_currency_signal_demotes(self):
        for field, value in (("status", "superseded"),
                             ("superseded_by", "dec_new"),
                             ("stale", True)):
            hits = [
                SearchHit(entity_type="claim", entity_id="retired", title="",
                          snippet="", **{field: value}),
                SearchHit(entity_type="claim", entity_id="current", title="", snippet=""),
            ]
            order = [h.entity_id for h in SearchService._current_first(hits)]
            assert order == ["current", "retired"], f"{field} did not demote"
