"""Tests for `BackfillService.run_backfill` (Mission D T5)."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

import pytest

from rka.services.embedding_backfill import (
    BackfillService,
    JobStatus,
    clear_registry,
    register_job,
)
from rka.services.embedding_reshape import reshape_vec_claims


async def _setup_vec_claims_at_dim(db, *, dim: int) -> None:
    """Tests use FakeEmbedder with small dims; reshape vec_claims to match."""
    if db.vec_available:
        await reshape_vec_claims(db, dim=dim)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class FakeEmbedder:
    """Returns deterministic vectors per input; tracks calls."""

    dim: int = 4
    fail_on_text: str | None = None
    calls: list[list[str]] = field(default_factory=list)

    async def embed_batch(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail_on_text is not None and any(self.fail_on_text in t for t in texts):
            raise RuntimeError(f"deliberate fault on text containing {self.fail_on_text!r}")
        return [[float(i)] * self.dim for i in range(len(texts))]


async def _insert_journal(db, *, jid: str = "jrn_t5") -> None:
    await db.execute(
        "INSERT INTO journal (id, type, content, source, created_at) "
        "VALUES (?, 'note', ?, 'pi', strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
        [jid, "x"],
    )


async def _insert_pending_claims(db, *, jid: str, count: int, prefix: str = "clm_t5_") -> list[str]:
    ids = [f"{prefix}{i:03d}" for i in range(count)]
    for cid in ids:
        await db.execute(
            "INSERT INTO claims (id, source_entry_id, claim_type, content, embedding_pending) "
            "VALUES (?, ?, 'observation', ?, 1)",
            [cid, jid, f"text-{cid}"],
        )
    await db.commit()
    return ids


# ---------------------------------------------------------------------------
# Empty-pending no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_backfill_empty_pending_completes_immediately(db):
    clear_registry()
    status = register_job()
    svc = BackfillService(db=db, embeddings=FakeEmbedder(), batch_size=8)
    # Make sure no claims with flag=1 exist by clearing.
    await db.execute("UPDATE claims SET embedding_pending = 0")
    await db.commit()

    result = await svc.run_backfill(status)
    assert result.state == "complete"
    assert result.total == 0
    assert result.processed == 0


# ---------------------------------------------------------------------------
# Full backfill — all pending claims get embedded + flag cleared
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_backfill_processes_all_pending_claims(db):
    clear_registry()
    await _setup_vec_claims_at_dim(db, dim=4)
    status = register_job()
    await _insert_journal(db, jid="jrn_t5_full")
    ids = await _insert_pending_claims(db, jid="jrn_t5_full", count=7)

    svc = BackfillService(db=db, embeddings=FakeEmbedder(dim=4), batch_size=3)
    result = await svc.run_backfill(status)

    assert result.state == "complete"
    assert result.total == 7
    assert result.processed == 7

    # All claims should now have embedding_pending = 0.
    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM claims WHERE embedding_pending = 1 AND id IN "
        "(" + ",".join(["?"] * len(ids)) + ")",
        ids,
    )
    assert row["n"] == 0

    # If sqlite-vec is available, vec_claims should now hold rows for every id.
    if db.vec_available:
        row = await db.fetchone(
            "SELECT COUNT(*) AS n FROM vec_claims WHERE id IN "
            "(" + ",".join(["?"] * len(ids)) + ")",
            ids,
        )
        assert row["n"] == 7


# ---------------------------------------------------------------------------
# Progress callback fires + payload shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_backfill_progress_callback_receives_status(db):
    clear_registry()
    await _setup_vec_claims_at_dim(db, dim=4)
    status = register_job()
    await _insert_journal(db, jid="jrn_t5_cb")
    await _insert_pending_claims(db, jid="jrn_t5_cb", count=5)

    captured: list[dict] = []

    def cb(s: JobStatus) -> None:
        captured.append(s.snapshot())

    svc = BackfillService(db=db, embeddings=FakeEmbedder(dim=4), batch_size=2)
    await svc.run_backfill(status, progress_callback=cb)

    # Callback fires at least at start + per-batch + at end.
    assert len(captured) >= 3
    final = captured[-1]
    # Snapshot shape matches A15 spec
    assert {"job_id", "state", "processed", "total", "started_at", "elapsed_seconds", "error"} <= set(final)
    assert final["state"] == "complete"
    assert final["processed"] == 5
    assert final["total"] == 5


@pytest.mark.asyncio
async def test_run_backfill_progress_callback_can_be_async(db):
    clear_registry()
    await _setup_vec_claims_at_dim(db, dim=4)
    status = register_job()
    await _insert_journal(db, jid="jrn_t5_async_cb")
    await _insert_pending_claims(db, jid="jrn_t5_async_cb", count=3)

    captured: list[int] = []

    async def cb(s: JobStatus) -> None:
        captured.append(s.processed)

    svc = BackfillService(db=db, embeddings=FakeEmbedder(dim=4), batch_size=2)
    await svc.run_backfill(status, progress_callback=cb)
    assert captured  # at least one progress event recorded


# ---------------------------------------------------------------------------
# Partial / batch-level failure semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_backfill_marks_failed_on_batch_embed_error(db):
    clear_registry()
    await _setup_vec_claims_at_dim(db, dim=4)
    status = register_job()
    await _insert_journal(db, jid="jrn_t5_fail")
    ids = await _insert_pending_claims(db, jid="jrn_t5_fail", count=4, prefix="clm_t5_fail_")

    # The embedder explodes when it sees content "text-clm_t5_fail_002".
    embedder = FakeEmbedder(dim=4, fail_on_text="clm_t5_fail_002")
    svc = BackfillService(db=db, embeddings=embedder, batch_size=4)
    result = await svc.run_backfill(status)

    assert result.state == "failed"
    assert "batch embed failed" in result.error

    # No claims were processed because the whole batch failed.
    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM claims WHERE embedding_pending = 1 AND id IN "
        "(" + ",".join(["?"] * len(ids)) + ")",
        ids,
    )
    assert row["n"] == 4, "all claims must keep embedding_pending=1 when batch fails"


@pytest.mark.asyncio
async def test_run_backfill_resumes_remaining_after_partial_completion(db):
    """If a backfill fails mid-stream, a second run picks up the remainder.

    Simulates a real-world recovery: first call's embedder explodes on
    a known claim AFTER some batches succeeded; second call's embedder
    is healthy and completes the rest.
    """
    clear_registry()
    await _setup_vec_claims_at_dim(db, dim=4)
    await _insert_journal(db, jid="jrn_t5_resume")
    ids = await _insert_pending_claims(
        db, jid="jrn_t5_resume", count=6, prefix="clm_t5_resume_"
    )

    # First run: explode on the 5th claim's text. Batch size 2 means the
    # first two batches (claims 000-003) succeed, third batch (004-005) fails.
    status1 = register_job()
    embedder1 = FakeEmbedder(dim=4, fail_on_text="clm_t5_resume_004")
    svc1 = BackfillService(db=db, embeddings=embedder1, batch_size=2)
    r1 = await svc1.run_backfill(status1)
    assert r1.state == "failed"
    # 4 claims succeeded before the failure.
    assert r1.processed == 4

    # Two claims should still have flag=1 (the failed batch).
    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM claims WHERE embedding_pending = 1 AND id IN "
        "(" + ",".join(["?"] * len(ids)) + ")",
        ids,
    )
    assert row["n"] == 2

    # Second run: healthy embedder, completes the rest.
    status2 = register_job()
    embedder2 = FakeEmbedder(dim=4)  # no fault
    svc2 = BackfillService(db=db, embeddings=embedder2, batch_size=2)
    r2 = await svc2.run_backfill(status2)
    assert r2.state == "complete"
    assert r2.total == 2
    assert r2.processed == 2

    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM claims WHERE embedding_pending = 1 AND id IN "
        "(" + ",".join(["?"] * len(ids)) + ")",
        ids,
    )
    assert row["n"] == 0, "all claims should be processed after the resume"


# ---------------------------------------------------------------------------
# Cursor pagination — id-ascending forward progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_backfill_iterates_in_id_ascending_order(db):
    """The cursor uses `id > last_id ORDER BY id` so a per-claim
    failure (rare in v2.4.0 — the loop's per-claim try/except is for
    sqlite-vec errors, not embed failures) won't trigger an infinite
    re-fetch loop. We can't easily inject a per-claim sqlite-vec error
    from outside the service; verify the call ordering instead."""
    clear_registry()
    await _setup_vec_claims_at_dim(db, dim=4)
    status = register_job()
    await _insert_journal(db, jid="jrn_t5_order")
    await _insert_pending_claims(db, jid="jrn_t5_order", count=5, prefix="clm_t5_order_")

    embedder = FakeEmbedder(dim=4)
    svc = BackfillService(db=db, embeddings=embedder, batch_size=2)
    await svc.run_backfill(status)

    # Flatten all embed_batch calls in order and verify the texts are
    # monotonically increasing in id (which equals text order since the
    # text is f"text-{cid}").
    seen_order = [text for batch in embedder.calls for text in batch]
    assert seen_order == sorted(seen_order), (
        f"backfill must process claims in id-ascending order; got {seen_order}"
    )


@pytest.mark.asyncio
async def test_run_backfill_status_total_set_to_initial_count(db):
    """status.total is fixed at the count snapshot taken before iteration."""
    clear_registry()
    await _setup_vec_claims_at_dim(db, dim=4)
    status = register_job()
    await _insert_journal(db, jid="jrn_t5_total")
    await _insert_pending_claims(db, jid="jrn_t5_total", count=4, prefix="clm_t5_total_")

    svc = BackfillService(db=db, embeddings=FakeEmbedder(dim=4), batch_size=2)
    result = await svc.run_backfill(status)
    assert result.total == 4
