"""Tests for `BackfillService.run_backfill` (Mission D T5)."""

from __future__ import annotations

from dataclasses import dataclass, field

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

    # v2.5.5: scope to claim type only — the v2.4 surface this test
    # locks down. With entity_types=None the loop sweeps all six types
    # which is exercised separately in the new T5 tests.
    result = await svc.run_backfill(status, entity_types=("claim",))
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
    result = await svc.run_backfill(status, entity_types=("claim",))

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
    await svc.run_backfill(status, progress_callback=cb, entity_types=("claim",))

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
    await svc.run_backfill(status, progress_callback=cb, entity_types=("claim",))
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
    result = await svc.run_backfill(status, entity_types=("claim",))

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
    r1 = await svc1.run_backfill(status1, entity_types=("claim",))
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
    r2 = await svc2.run_backfill(status2, entity_types=("claim",))
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
    await svc.run_backfill(status, entity_types=("claim",))

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
    result = await svc.run_backfill(status, entity_types=("claim",))
    assert result.total == 4


# ---------------------------------------------------------------------------
# v2.4.1 hotfix regression locks
# ---------------------------------------------------------------------------


@dataclass
class _NoMessageEmbedder:
    """Raises an exception with no string representation on every batch.

    Simulates `httpx.ReadTimeout()` which has an empty `__str__`. Before the
    v2.4.1 hotfix, `status.error` rendered as `"...): "` (empty after the
    colon) because the format string only consumed `str(exc)`. After the fix,
    `type(exc).__name__` is always present so the operator sees the class.
    """

    async def embed_batch(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        class _NoMsg(Exception):
            def __str__(self) -> str:
                return ""

        raise _NoMsg()


@pytest.mark.asyncio
async def test_backfill_error_includes_exception_class_when_message_empty(db):
    """v2.4.1: status.error always carries the exception class name."""
    clear_registry()
    await _setup_vec_claims_at_dim(db, dim=4)
    status = register_job()
    await _insert_journal(db, jid="jrn_v241_err")
    await _insert_pending_claims(db, jid="jrn_v241_err", count=2, prefix="clm_v241_err_")

    svc = BackfillService(db=db, embeddings=_NoMessageEmbedder(), batch_size=2)
    result = await svc.run_backfill(status, entity_types=("claim",))

    assert result.state == "failed"
    # The class name MUST appear in status.error even when the exception has
    # no message — otherwise PI sees a useless "...:" with nothing after.
    assert "_NoMsg" in result.error, (
        f"error must carry the exception class name; got: {result.error!r}"
    )


def test_backfill_default_batch_size_is_eight_v241():
    """v2.4.1: batch_size default lowered from 32 → 8 so local 8B-class
    embedding backends don't time out on a single batch."""
    svc = BackfillService(db=None, embeddings=None)
    assert svc._batch_size == 8


def test_openai_compat_default_timeout_is_600_v241():
    """v2.4.1: openai_compat timeout raised 30s → 600s for local heavy models."""
    from rka.infra.embedding_backends.openai_compat import OpenAICompatBackend

    b = OpenAICompatBackend(base_url="http://x", model="m", dim=4)
    assert b._timeout == 600.0


def test_ollama_default_timeout_is_600_v241():
    """v2.4.1: ollama timeout raised 30s → 600s for consistency."""
    from rka.infra.embedding_backends.ollama import OllamaBackend

    b = OllamaBackend(base_url="http://x", model="m", dim=4)
    assert b._timeout == 600.0


# ---------------------------------------------------------------------------
# v2.5.5 (mis_01KS1RFNM2T1HTB077G507T1FR T5) — all-entity-types iteration
# ---------------------------------------------------------------------------


@dataclass
class _AllTypesEmbedder:
    """FakeEmbedder variant exposing dim + model_name for metadata writes."""

    dim: int = 4
    model_name: str = "fake-embedder-v0"
    fail_on_text: str | None = None
    calls: list[list[str]] = field(default_factory=list)

    async def embed_batch(
        self, texts: list[str], *, is_query: bool = False
    ) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail_on_text is not None and any(self.fail_on_text in t for t in texts):
            raise RuntimeError(f"deliberate fault on text containing {self.fail_on_text!r}")
        return [[float(i)] * self.dim for i in range(len(texts))]


async def _seed_journal(db, *, jid: str, content: str = "journal body") -> None:
    await db.execute(
        "INSERT INTO journal (id, type, content, source, created_at) "
        "VALUES (?, 'note', ?, 'pi', strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
        [jid, content],
    )


async def _seed_decision(db, *, did: str, question: str = "Why?") -> None:
    await db.execute(
        "INSERT INTO decisions (id, phase, question, rationale, decided_by) "
        "VALUES (?, 'design', ?, ?, 'pi')",
        [did, question, "because reasons"],
    )


async def _seed_literature(db, *, lid: str) -> None:
    await db.execute(
        "INSERT INTO literature (id, title, abstract) VALUES (?, ?, ?)",
        [lid, f"title-{lid}", f"abstract-{lid}"],
    )


async def _seed_mission(db, *, mid: str) -> None:
    await db.execute(
        "INSERT INTO missions (id, phase, objective, context) "
        "VALUES (?, 'design', ?, ?)",
        [mid, f"objective-{mid}", f"context-{mid}"],
    )


async def _metadata_count_for(db, entity_type: str) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM embedding_metadata WHERE entity_type = ?",
        [entity_type],
    )
    return int(row["n"])


async def _reshape_all_to(db, dim: int) -> None:
    """Bring every vec_* table to `dim` so the FakeEmbedder dim works."""
    if not db.vec_available:
        return
    from rka.services.embedding_reshape import reshape_all_vec_tables_if_needed
    await reshape_all_vec_tables_if_needed(db, dim=dim)


@pytest.mark.asyncio
async def test_run_backfill_iterates_all_six_default_entity_types(db):
    """entity_types=None → claim + journal + decision + literature + mission
    + artifact get embedded. status.processed = sum across types."""
    clear_registry()
    await _reshape_all_to(db, dim=4)
    await _seed_journal(db, jid="jrn_all_a")
    await _insert_pending_claims(db, jid="jrn_all_a", count=2, prefix="clm_all_")
    await _seed_journal(db, jid="jrn_all_b")
    await _seed_decision(db, did="dec_all_a")
    await _seed_literature(db, lid="lit_all_a")
    await _seed_mission(db, mid="mis_all_a")

    status = register_job()
    svc = BackfillService(
        db=db, embeddings=_AllTypesEmbedder(dim=4), batch_size=4
    )
    result = await svc.run_backfill(status)  # default: all six types

    assert result.state == "complete"
    # 2 claims + 2 journals + 1 decision + 1 literature + 1 mission = 7
    # (artifact table is empty so it contributes 0)
    assert result.processed == 7
    assert result.total == 7
    # Metadata is populated for every embedded type.
    assert await _metadata_count_for(db, "claim") == 2
    assert await _metadata_count_for(db, "journal") == 2
    assert await _metadata_count_for(db, "decision") == 1
    assert await _metadata_count_for(db, "literature") == 1
    assert await _metadata_count_for(db, "mission") == 1
    # Recorded model + dim reflect the active embedder, not stale data.
    row = await db.fetchone(
        "SELECT model_name, dimensions FROM embedding_metadata "
        "WHERE entity_type='journal' LIMIT 1"
    )
    assert row["model_name"] == "fake-embedder-v0"
    assert int(row["dimensions"]) == 4


@pytest.mark.asyncio
async def test_run_backfill_restricts_to_named_entity_types(db):
    """entity_types=('journal',) → claims left untouched even though pending."""
    clear_registry()
    await _reshape_all_to(db, dim=4)
    await _seed_journal(db, jid="jrn_restrict")
    claim_ids = await _insert_pending_claims(
        db, jid="jrn_restrict", count=3, prefix="clm_restrict_"
    )
    await _seed_journal(db, jid="jrn_restrict_extra")

    status = register_job()
    svc = BackfillService(
        db=db, embeddings=_AllTypesEmbedder(dim=4), batch_size=2
    )
    result = await svc.run_backfill(status, entity_types=("journal",))

    assert result.state == "complete"
    # Only the 2 journals counted; claims excluded.
    assert result.total == 2
    assert result.processed == 2
    # Claims still pending (untouched).
    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM claims WHERE embedding_pending = 1 AND id IN "
        "(" + ",".join(["?"] * len(claim_ids)) + ")",
        claim_ids,
    )
    assert row["n"] == 3
    assert await _metadata_count_for(db, "claim") == 0
    assert await _metadata_count_for(db, "journal") == 2


@pytest.mark.asyncio
async def test_run_backfill_per_entity_type_failure_isolates(db):
    """A batch-embed failure for one entity type does not stop the others."""
    clear_registry()
    await _reshape_all_to(db, dim=4)
    await _seed_journal(db, jid="jrn_iso_target")  # FK for claims AND a journal we want embedded
    claim_ids = await _insert_pending_claims(
        db, jid="jrn_iso_target", count=2, prefix="clm_iso_fail_"
    )
    # Add another journal to ensure journals have rows to embed too.
    await _seed_journal(db, jid="jrn_iso_other")

    # Embedder fails when it sees the claim-text marker, but never the
    # journal text (journals seed with "journal body").
    embedder = _AllTypesEmbedder(dim=4, fail_on_text="clm_iso_fail_")
    status = register_job()
    svc = BackfillService(db=db, embeddings=embedder, batch_size=2)
    result = await svc.run_backfill(status)

    assert result.state == "failed", "any-type failure marks the run failed"
    assert "claim" in (result.error or "")
    # Journals still got embedded — failure isolation.
    assert await _metadata_count_for(db, "journal") == 2
    # Claims kept their pending flag for retry.
    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM claims WHERE embedding_pending = 1 AND id IN "
        "(" + ",".join(["?"] * len(claim_ids)) + ")",
        claim_ids,
    )
    assert row["n"] == 2


@pytest.mark.asyncio
async def test_run_backfill_rejects_unknown_entity_type(db):
    """entity_types containing an unknown name → ValueError up front."""
    clear_registry()
    status = register_job()
    svc = BackfillService(db=db, embeddings=_AllTypesEmbedder(dim=4))
    with pytest.raises(ValueError, match="unknown entity_type"):
        await svc.run_backfill(status, entity_types=("not_a_thing",))


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_reshape_then_backfill_clears_stale_metadata(db):
    """End-to-end: plant stale metadata for journal+decision → reshape
    invalidates it → backfill repopulates with current model/dim."""
    if not db.vec_available:
        pytest.skip("sqlite-vec extension not loaded")
    from rka.services.embedding_reshape import reshape_all_vec_tables_if_needed

    # Plant entities + stale metadata that simulates the production bug
    # state: rows exist, metadata says nomic-768, but the configured
    # backend is now hypothetically fake-embedder-v0 / dim=4.
    await _seed_journal(db, jid="jrn_e2e_a")
    await _seed_decision(db, did="dec_e2e_a")
    await db.execute(
        "INSERT INTO embedding_metadata "
        "(project_id, entity_type, entity_id, content_hash, model_name, dimensions) "
        "VALUES "
        "('proj_default', 'journal',  'jrn_e2e_a', 'stale', 'nomic-768', 768), "
        "('proj_default', 'decision', 'dec_e2e_a', 'stale', 'nomic-768', 768)"
    )
    await db.commit()

    # Reshape simulating PUT /api/config/embedding handler.
    await reshape_all_vec_tables_if_needed(db, dim=4)
    # Stale metadata gone for both types (non-claims path).
    assert await _metadata_count_for(db, "journal") == 0
    assert await _metadata_count_for(db, "decision") == 0

    # Backfill repopulates.
    clear_registry()
    status = register_job()
    svc = BackfillService(
        db=db, embeddings=_AllTypesEmbedder(dim=4), batch_size=4
    )
    result = await svc.run_backfill(status)

    assert result.state == "complete"
    assert await _metadata_count_for(db, "journal") == 1
    assert await _metadata_count_for(db, "decision") == 1
    # The repopulated rows carry the CURRENT model_name + dim, not the stale ones.
    row = await db.fetchone(
        "SELECT model_name, dimensions FROM embedding_metadata "
        "WHERE entity_type='journal' AND entity_id='jrn_e2e_a'"
    )
    assert row["model_name"] == "fake-embedder-v0"
    assert int(row["dimensions"]) == 4


@pytest.mark.asyncio
async def test_e2e_no_op_when_nothing_pending(db):
    """Fresh DB with no entities anywhere → default backfill completes
    immediately with total=0 (the v2.5.5 'idle' path covering all six
    types simultaneously)."""
    clear_registry()
    status = register_job()
    svc = BackfillService(db=db, embeddings=_AllTypesEmbedder(dim=4))
    result = await svc.run_backfill(status)  # default all-six entity_types
    assert result.state == "complete"
    assert result.total == 0
    assert result.processed == 0


# ---------------------------------------------------------------------------
# v2.5.8 Bug 1 regression: BackfillService metadata write coupled to vec_available
# ---------------------------------------------------------------------------
# Per dec_01KS3E1FGSK530N8HM04BNMCEW, surfaced empirically by corpus refresh
# mis_01KS0QEW21N2NG4EJTKJ3JTWTE. Pre-fix behavior: vec_* INSERT was guarded
# by `if vec_available` but the metadata INSERT was unconditional, leaving
# rows claiming "embedded at <model>/<dim>" with no actual vec_* row. The
# v2.5.5 3-tuple needs_reembed gate then returned False permanently. Fix
# moves metadata INSERT inside the same vec_available guard.


@pytest.mark.asyncio
async def test_metadata_not_written_when_vec_available_false(db, monkeypatch):
    """vec_available=False -> no vec_* INSERT and no metadata INSERT.

    The entity must remain in "needs embedding" state (no metadata row)
    so a later vec_available=True window triggers a re-embed instead of
    silently skipping the row because needs_reembed returned False.
    """
    clear_registry()
    status = register_job()
    await _insert_journal(db, jid="jrn_bug1_skip")
    ids = await _insert_pending_claims(db, jid="jrn_bug1_skip", count=3)

    # Simulate sqlite-vec disabled (the bug's trigger scenario).
    # vec_available is a property; patch at class level so getattr() resolves
    # to the False shadow rather than the descriptor.
    monkeypatch.setattr(type(db), "vec_available", False, raising=False)

    svc = BackfillService(db=db, embeddings=FakeEmbedder(dim=4), batch_size=3)
    result = await svc.run_backfill(status, entity_types=("claim",))

    # The backfill reports the rows as "processed" (they completed without
    # error), but the metadata table receives NO inserts because the
    # vec_available guard skipped both the vec_* and metadata writes.
    assert result.state == "complete"
    metadata_rows = await db.fetchone(
        "SELECT COUNT(*) AS n FROM embedding_metadata "
        "WHERE entity_type = 'claim' AND entity_id IN "
        "(" + ",".join(["?"] * len(ids)) + ")",
        ids,
    )
    assert metadata_rows["n"] == 0, (
        "vec_available=False must NOT write metadata; otherwise needs_reembed "
        "returns False permanently for the under-embedded row (Bug 1)."
    )


@pytest.mark.asyncio
async def test_metadata_written_when_vec_available_true(db):
    """vec_available=True -> both vec_* and metadata INSERT (backward compat).

    Explicit positive-case regression test: the pre-fix happy path must
    continue to write metadata when vec_available is True. Other tests in
    this file exercise this implicitly; this test makes it explicit so
    future refactors of the vec_available guard structure can be evaluated
    against both halves of the invariant.
    """
    if not db.vec_available:
        pytest.skip("vec_available=False in this test environment; positive case unreachable.")

    clear_registry()
    await _setup_vec_claims_at_dim(db, dim=4)
    status = register_job()
    await _insert_journal(db, jid="jrn_bug1_ok")
    ids = await _insert_pending_claims(db, jid="jrn_bug1_ok", count=2)

    svc = BackfillService(db=db, embeddings=FakeEmbedder(dim=4), batch_size=2)
    result = await svc.run_backfill(status, entity_types=("claim",))

    assert result.state == "complete"
    metadata_rows = await db.fetchone(
        "SELECT COUNT(*) AS n FROM embedding_metadata "
        "WHERE entity_type = 'claim' AND entity_id IN "
        "(" + ",".join(["?"] * len(ids)) + ")",
        ids,
    )
    assert metadata_rows["n"] == 2, (
        "vec_available=True must write metadata for each processed row "
        "(positive-case backward compat)."
    )


@pytest.mark.asyncio
async def test_row_write_failure_rolls_back_vector_metadata_and_pending_flag(
    db,
    monkeypatch,
):
    """One entity's vector, metadata, and pending flag are atomic."""
    clear_registry()
    await db.execute(
        """CREATE TABLE IF NOT EXISTS vec_claims (
               id TEXT PRIMARY KEY,
               embedding BLOB NOT NULL
           )"""
    )
    monkeypatch.setattr(db, "_vec_loaded", True)
    await _insert_journal(db, jid="jrn_atomic_embed")
    [claim_id] = await _insert_pending_claims(
        db,
        jid="jrn_atomic_embed",
        count=1,
        prefix="clm_atomic_embed_",
    )

    real_execute = db.execute

    async def fail_metadata(sql, params=None):
        if "INSERT OR REPLACE INTO embedding_metadata" in sql:
            raise RuntimeError("injected metadata failure")
        return await real_execute(sql, params)

    monkeypatch.setattr(db, "execute", fail_metadata)
    status = register_job()
    service = BackfillService(
        db=db,
        embeddings=FakeEmbedder(dim=4),
        batch_size=1,
    )
    result = await service.run_backfill(status, entity_types=("claim",))

    assert result.processed == 0
    assert await db.fetchone(
        "SELECT id FROM vec_claims WHERE id = ?",
        [claim_id],
    ) is None
    assert await db.fetchone(
        """SELECT entity_id FROM embedding_metadata
           WHERE entity_type = 'claim' AND entity_id = ?""",
        [claim_id],
    ) is None
    pending = await db.fetchone(
        "SELECT embedding_pending FROM claims WHERE id = ?",
        [claim_id],
    )
    assert pending["embedding_pending"] == 1
