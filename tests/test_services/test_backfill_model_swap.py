"""Swapping the embedding model must re-embed, even at an unchanged dimension.

`reshape_all_vec_tables_if_needed` keys on dimension: at an equal dim it is a
no-op and every `embedding_metadata` row survives. The backfill cursor decided
"pending" by the *presence* of such a row, so after a same-dim model swap it
found nothing to do. The index kept vectors produced by the retired model while
queries were encoded by the new one — two different embedding spaces compared
by cosine similarity, silently, with no error anywhere.

`EmbeddingService.needs_reembed` already gates on the full identity tuple
(content_hash, model_name, dimensions). The per-row gate was right; the query
that chose which rows to look at disagreed with it. These tests pin the two
together.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from rka.services.embedding_backfill import (
    BackfillService,
    clear_registry,
    register_job,
)
from rka.services.embedding_reshape import reshape_vec_claims


@dataclass
class FakeEmbedder:
    """Deterministic vectors, with a model identity the backfill can read."""

    model_name: str = "model-a"
    dim: int = 4
    calls: list[list[str]] = field(default_factory=list)

    async def embed_batch(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(i)] * self.dim for i in range(len(texts))]


async def _seed(db, *, count: int = 3) -> list[str]:
    if db.vec_available:
        await reshape_vec_claims(db, dim=4)
    await db.execute(
        "INSERT INTO journal (id, type, content, source, created_at) "
        "VALUES ('jrn_swap', 'note', 'x', 'pi', strftime('%Y-%m-%dT%H:%M:%SZ','now'))"
    )
    ids = [f"clm_swap_{i:03d}" for i in range(count)]
    for cid in ids:
        await db.execute(
            "INSERT INTO claims (id, source_entry_id, claim_type, content, embedding_pending) "
            "VALUES (?, 'jrn_swap', 'observation', ?, 1)",
            [cid, f"text-{cid}"],
        )
    await db.commit()
    return ids


async def _run(db, embedder) -> object:
    clear_registry()
    return await BackfillService(db=db, embeddings=embedder, batch_size=8).run_backfill(
        register_job(), entity_types=("claim",)
    )


@pytest.mark.asyncio
async def test_first_pass_embeds_everything(db):
    ids = await _seed(db)
    result = await _run(db, FakeEmbedder(model_name="model-a"))
    assert result.processed == len(ids)


@pytest.mark.asyncio
async def test_rerunning_the_same_model_is_a_no_op(db):
    """The guard against the fix over-firing: same model must stay done."""
    await _seed(db)
    await _run(db, FakeEmbedder(model_name="model-a"))

    second = await _run(db, FakeEmbedder(model_name="model-a"))

    assert second.total == 0
    assert second.processed == 0


@pytest.mark.asyncio
async def test_a_model_swap_at_the_same_dim_re_embeds(db):
    """The regression. Same dim, different model — everything is pending."""
    ids = await _seed(db)
    await _run(db, FakeEmbedder(model_name="model-a", dim=4))

    swapped = FakeEmbedder(model_name="model-b", dim=4)
    result = await _run(db, swapped)

    assert result.total == len(ids), (
        "a same-dim model swap must report the full corpus as pending; "
        "reshape no-ops at an equal dim, so nothing else will catch it"
    )
    assert result.processed == len(ids)
    assert swapped.calls, "the new model must actually be asked to embed"


@pytest.mark.asyncio
async def test_metadata_records_the_new_model_after_a_swap(db):
    ids = await _seed(db)
    await _run(db, FakeEmbedder(model_name="model-a"))
    await _run(db, FakeEmbedder(model_name="model-b"))

    rows = await db.fetchall(
        "SELECT DISTINCT model_name FROM embedding_metadata "
        "WHERE entity_type = 'claim' AND entity_id IN "
        "(" + ",".join(["?"] * len(ids)) + ")",
        ids,
    )
    assert [r["model_name"] for r in rows] == ["model-b"], (
        "stale metadata left behind would make the corpus look pending forever"
    )


@pytest.mark.asyncio
async def test_the_reported_total_matches_what_gets_processed(db):
    """The count and the cursor must agree.

    They are separate SQL statements. If only one learned about the model,
    the job would report 0 pending and then embed the whole corpus, or the
    reverse — progress that never completes.
    """
    ids = await _seed(db, count=5)
    await _run(db, FakeEmbedder(model_name="model-a"))

    result = await _run(db, FakeEmbedder(model_name="model-b"))

    assert result.total == result.processed == len(ids)
