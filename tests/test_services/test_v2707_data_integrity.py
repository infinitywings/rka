"""v2.7.0.7 — search/embedding integrity + supersede atomicity tests.

Covers the data-integrity fixes from the v2.7.0.6 third-party review:
  - ClaimService.update re-syncs fts_claims (+ re-enqueues embed)
  - _sync_fts failure leaves no orphaned DELETE (savepoint rollback)
  - reshape_vec_table is crash-safe (failure leaves old table intact)
  - backfill leaves the pending flag intact when sqlite-vec is unavailable
  - store_embedding writes metadata only when a vector was stored
  - reindex_fts rebuilds the FTS index from source
  - supersede_decision bookkeeping is atomic (failure rolls back fully)
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from rka.models.claim import ClaimCreate, ClaimUpdate
from rka.models.decision import DecisionCreate, DecisionSupersedeBody
from rka.services.claims import ClaimService
from rka.services.decisions import DecisionService
from rka.services.reindex import reindex_fts

_PROJECT = "proj_default"


async def _seed_journal(db, jid="jrn_x", content="seed"):
    await db.execute(
        "INSERT INTO journal (id, project_id, type, content, source, confidence) "
        "VALUES (?, ?, 'note', ?, 'brain', 'tested')",
        [jid, _PROJECT, content],
    )
    await db.commit()


# ---------------------------------------------------------------------------
# ClaimService.update re-syncs FTS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_update_resyncs_fts(db):
    await _seed_journal(db, "jrn_c", "evidence source")
    svc = ClaimService(db, project_id=_PROJECT)
    claim = await svc.create(
        ClaimCreate(source_entry_id="jrn_c", claim_type="evidence",
                    content="original claim text", confidence=0.8)
    )
    # FTS should find the original text.
    hit = await db.fetchone(
        "SELECT id FROM fts_claims WHERE fts_claims MATCH 'original'"
    )
    assert hit is not None and hit["id"] == claim.id

    # Update the content.
    await svc.update(claim.id, ClaimUpdate(content="completely different wording"))

    # Old text gone from FTS; new text present.
    old_hit = await db.fetchone(
        "SELECT id FROM fts_claims WHERE fts_claims MATCH 'original'"
    )
    assert old_hit is None, "stale FTS row should be gone after content update"
    new_hit = await db.fetchone(
        "SELECT id FROM fts_claims WHERE fts_claims MATCH 'wording'"
    )
    assert new_hit is not None and new_hit["id"] == claim.id


@pytest.mark.asyncio
async def test_claim_update_non_content_does_not_touch_fts(db):
    """Updating only `verified`/`stale` must not re-sync FTS (no content change)."""
    await _seed_journal(db, "jrn_d", "keepme text")
    svc = ClaimService(db, project_id=_PROJECT)
    claim = await svc.create(
        ClaimCreate(source_entry_id="jrn_d", claim_type="evidence",
                    content="keepme text", confidence=0.5)
    )
    await svc.update(claim.id, ClaimUpdate(verified=True))
    hit = await db.fetchone(
        "SELECT id FROM fts_claims WHERE fts_claims MATCH 'keepme'"
    )
    assert hit is not None and hit["id"] == claim.id


# ---------------------------------------------------------------------------
# _sync_fts failure leaves no orphaned DELETE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_fts_failure_preserves_existing_row(db, monkeypatch):
    """If the INSERT half of _sync_fts fails, the SAVEPOINT rollback must
    restore the pre-existing FTS row rather than leaving an orphaned DELETE
    that a later commit makes permanent."""
    await _seed_journal(db, "jrn_e", "findable text")
    svc = ClaimService(db, project_id=_PROJECT)
    claim = await svc.create(
        ClaimCreate(source_entry_id="jrn_e", claim_type="evidence",
                    content="findable text", confidence=0.5)
    )
    assert await db.fetchone("SELECT id FROM fts_claims WHERE id = ?", [claim.id])

    # Force the INSERT to fail mid-_sync_fts by monkeypatching execute to raise
    # on the FTS INSERT only.
    real_execute = db.execute

    async def flaky(sql, params=None):
        if "INSERT INTO fts_claims" in sql:
            raise RuntimeError("simulated FTS insert failure")
        return await real_execute(sql, params)

    monkeypatch.setattr(db, "execute", flaky)
    # Trigger a re-sync via update; the FTS INSERT will fail but must not
    # leave the index row deleted.
    await svc.update(claim.id, ClaimUpdate(content="new text that wont index"))
    monkeypatch.setattr(db, "execute", real_execute)

    # The original FTS row must still be present (savepoint rolled back the
    # delete+failed-insert).
    surviving = await db.fetchone("SELECT id FROM fts_claims WHERE id = ?", [claim.id])
    assert surviving is not None, (
        "savepoint rollback should preserve the prior FTS row on insert failure"
    )


# ---------------------------------------------------------------------------
# reshape_vec_table crash-safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reshape_failure_leaves_old_table_intact(db, monkeypatch):
    """If CREATE VIRTUAL TABLE fails after DROP, the explicit transaction
    must roll the DROP back so the old vec table survives."""
    if not db.vec_available:
        pytest.skip("sqlite-vec not available in this environment")
    from rka.services import embedding_reshape

    # Confirm vec_claims exists at some dim first.
    before = await db.fetchone(
        "SELECT name FROM sqlite_master WHERE name = 'vec_claims'"
    )
    assert before is not None

    real_execute = db.execute

    async def flaky(sql, params=None):
        if sql.strip().startswith("CREATE VIRTUAL TABLE vec_claims"):
            raise RuntimeError("simulated CREATE failure mid-reshape")
        return await real_execute(sql, params)

    monkeypatch.setattr(db, "execute", flaky)
    with pytest.raises(RuntimeError):
        # Force a real reshape (different dim) so it hits the DROP+CREATE path.
        await embedding_reshape.reshape_vec_table(db, "vec_claims", dim=99)
    monkeypatch.setattr(db, "execute", real_execute)

    after = await db.fetchone(
        "SELECT name FROM sqlite_master WHERE name = 'vec_claims'"
    )
    assert after is not None, (
        "vec_claims must still exist after a failed reshape (DROP rolled back)"
    )


# ---------------------------------------------------------------------------
# backfill pending-clear gated on vec_available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_leaves_pending_when_vec_unavailable(db, monkeypatch):
    """When vec_available is False, the claim's embedding_pending flag must
    stay set (post_embed_sql is gated), so backfill retries once vec returns."""
    from dataclasses import dataclass, field as dc_field
    from rka.services.embedding_backfill import BackfillService, register_job

    await _seed_journal(db, "jrn_f", "claim source")
    await db.execute(
        "INSERT INTO claims (id, project_id, source_entry_id, content, claim_type, "
        "stale, embedding_pending) VALUES "
        "('clm_pending', ?, 'jrn_f', 'pending claim', 'evidence', 0, 1)",
        [_PROJECT],
    )
    await db.commit()

    # Force sqlite-vec unavailable on the db the backfill reads.
    monkeypatch.setattr(db, "_vec_loaded", False)

    @dataclass
    class FakeEmbedder:
        dim: int = 4
        async def embed_batch(self, texts, *, is_query: bool = False):
            return [[float(i)] * self.dim for i in range(len(texts))]

    svc = BackfillService(db=db, embeddings=FakeEmbedder(), batch_size=8)
    status = register_job()
    await svc.run_backfill(status, entity_types=("claim",))

    row = await db.fetchone(
        "SELECT embedding_pending FROM claims WHERE id = 'clm_pending'"
    )
    assert row["embedding_pending"] == 1, (
        "pending flag must remain set when no vector was written (vec unavailable)"
    )


# ---------------------------------------------------------------------------
# store_embedding metadata gated on vec_available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_embedding_skips_metadata_when_vec_unavailable(db, monkeypatch):
    """When sqlite-vec is unavailable, store_embedding must NOT write the
    metadata row (otherwise needs_reembed returns False forever)."""
    from rka.infra.embeddings import EmbeddingService

    await _seed_journal(db, "jrn_g", "embed me")
    monkeypatch.setattr(db, "_vec_loaded", False)

    class _Backend:
        dim = 8
        async def embed(self, text, is_query: bool = False):
            return [0.1] * 8

    es = EmbeddingService(db=db)
    es._backend = _Backend()  # type: ignore[attr-defined]
    es.model_name = "stub-model"

    await es.store_embedding("journal", "jrn_g", "embed me", project_id=_PROJECT)

    meta = await db.fetchone(
        "SELECT entity_id FROM embedding_metadata WHERE entity_id = 'jrn_g'"
    )
    assert meta is None, (
        "metadata must NOT be written when no vector was stored (vec unavailable)"
    )


# ---------------------------------------------------------------------------
# reindex_fts rebuilds the index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reindex_rebuilds_fts(db):
    await _seed_journal(db, "jrn_h", "reindex target content")
    # Manually corrupt the FTS index by deleting the row the create synced.
    # (notes created via raw INSERT above never synced FTS, so simulate a
    # decision instead which does sync, then drop its fts row.)
    svc = DecisionService(db, project_id=_PROJECT)
    dec = await svc.create(
        DecisionCreate(question="findable decision question", phase="design",
                       decided_by="brain", chosen="x", rationale="r",
                       related_journal=["jrn_h"])
    )
    # Confirm it's indexed, then delete the FTS row to simulate drift.
    assert await db.fetchone(
        "SELECT id FROM fts_decisions WHERE fts_decisions MATCH 'findable'"
    )
    await db.execute("DELETE FROM fts_decisions WHERE id = ?", [dec.id])
    await db.commit()
    assert not await db.fetchone(
        "SELECT id FROM fts_decisions WHERE fts_decisions MATCH 'findable'"
    )

    # Reindex should rebuild it.
    report = await reindex_fts(db)
    assert report.ok
    assert report.results["decision"] >= 1
    rebuilt = await db.fetchone(
        "SELECT id FROM fts_decisions WHERE fts_decisions MATCH 'findable'"
    )
    assert rebuilt is not None and rebuilt["id"] == dec.id


@pytest.mark.asyncio
async def test_reindex_scoped_to_project(db):
    report = await reindex_fts(db, project_id=_PROJECT, entity_types=["claim"])
    assert report.ok
    assert "claim" in report.results
    assert list(report.results.keys()) == ["claim"]


# ---------------------------------------------------------------------------
# supersede bookkeeping atomicity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supersede_bookkeeping_atomic_rollback(db, monkeypatch):
    """A failure during the post-create supersede bookkeeping must roll back
    the whole block: the OLD decision must NOT be left flipped to superseded,
    and no supersedes entity-link / event should persist."""
    await _seed_journal(db, "jrn_s", "supersede source")
    svc = DecisionService(db, project_id=_PROJECT)
    old = await svc.create(
        DecisionCreate(question="original q", phase="design", decided_by="brain",
                       chosen="a", rationale="r", related_journal=["jrn_s"])
    )

    # Make the events INSERT (inside the bookkeeping txn) fail.
    real_execute = db.execute

    async def flaky(sql, params=None):
        if "INSERT INTO events" in sql:
            raise RuntimeError("simulated event-insert failure")
        return await real_execute(sql, params)

    monkeypatch.setattr(db, "execute", flaky)
    with pytest.raises(RuntimeError):
        await svc.supersede_decision(
            old.id,
            DecisionSupersedeBody(question="new q", decided_by="brain",
                                  chosen="b", rationale="r2",
                                  related_journal=["jrn_s"]),
            actor="brain",
        )
    monkeypatch.setattr(db, "execute", real_execute)

    # OLD decision must still be active (rollback worked).
    old_row = await db.fetchone(
        "SELECT status, superseded_by FROM decisions WHERE id = ?", [old.id]
    )
    assert old_row["status"] == "active", (
        "old decision must NOT be superseded after a rolled-back bookkeeping txn"
    )
    assert old_row["superseded_by"] is None
    # No supersedes entity-link should persist.
    link = await db.fetchone(
        "SELECT id FROM entity_links WHERE link_type = 'supersedes' "
        "AND target_id = ?", [old.id]
    )
    assert link is None


@pytest.mark.asyncio
async def test_supersede_happy_path_still_works(db):
    """Sanity: the atomic rewrite preserves the normal supersede outcome."""
    await _seed_journal(db, "jrn_t", "src")
    await _seed_journal(db, "jrn_t2", "src2")
    svc = DecisionService(db, project_id=_PROJECT)
    old = await svc.create(
        DecisionCreate(question="q1", phase="design", decided_by="brain",
                       chosen="a", rationale="r", related_journal=["jrn_t"])
    )
    new = await svc.supersede_decision(
        old.id,
        DecisionSupersedeBody(question="q2", decided_by="brain", chosen="b",
                              rationale="r2", related_journal=["jrn_t2"]),
        actor="brain",
    )
    old_row = await db.fetchone(
        "SELECT status, superseded_by, scope_version FROM decisions WHERE id = ?",
        [old.id],
    )
    assert old_row["status"] == "superseded"
    assert old_row["superseded_by"] == new.id
    new_row = await db.fetchone(
        "SELECT scope_version FROM decisions WHERE id = ?", [new.id]
    )
    assert new_row["scope_version"] == 2
    link = await db.fetchone(
        "SELECT id FROM entity_links WHERE link_type = 'supersedes' "
        "AND source_id = ? AND target_id = ?", [new.id, old.id]
    )
    assert link is not None
    event = await db.fetchone(
        "SELECT id FROM events WHERE event_type = 'decision_superseded' "
        "AND entity_id = ?", [old.id]
    )
    assert event is not None
    assert new.phase == "design"  # inherited
