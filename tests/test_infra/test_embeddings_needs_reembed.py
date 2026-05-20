"""needs_reembed 3-tuple gate tests (v2.5.5 / mis_01KS1RFNM2T1HTB077G507T1FR T3).

Before v2.5.5, needs_reembed only compared content_hash, so a backend
swap (e.g. nomic-embed-text-v1.5 @ 768 → qwen3-embedding-8b @ 4096)
silently left every unchanged entity flagged "not stale" — its stored
vector belonged to a retired model + dim. These tests lock down the
3-tuple gate (content_hash, model_name, dimensions) plus the defensive
behavior when the backend hasn't reported a dim yet.
"""

from __future__ import annotations

import hashlib

import pytest

from rka.infra.database import Database
from rka.infra.embeddings import EmbeddingService


class _StubBackend:
    """Minimal EmbeddingBackend stub configurable per-test."""

    def __init__(self, *, model_name: str, dim: int) -> None:
        self.model_name = model_name
        self.dim = dim

    async def embed(self, text: str, is_query: bool = False) -> list[float]:
        return [0.0] * self.dim

    async def embed_batch(
        self, texts: list[str], is_query: bool = False
    ) -> list[list[float]]:
        return [[0.0] * self.dim for _ in texts]


def _service(db: Database, *, model_name: str = "nomic-768", dim: int = 768) -> EmbeddingService:
    backend = _StubBackend(model_name=model_name, dim=dim)
    return EmbeddingService(model_name=model_name, db=db, backend=backend)


async def _plant_metadata(
    db: Database,
    *,
    entity_type: str,
    entity_id: str,
    content_hash: str,
    model_name: str,
    dimensions: int,
    project_id: str = "proj_default",
) -> None:
    await db.execute(
        """INSERT OR REPLACE INTO embedding_metadata
           (project_id, entity_type, entity_id, content_hash, model_name, dimensions)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [project_id, entity_type, entity_id, content_hash, model_name, dimensions],
    )
    await db.commit()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# False when the full identity tuple matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_needs_reembed_false_when_full_tuple_matches(db):
    """All three of content_hash, model_name, dimensions match → False."""
    svc = _service(db, model_name="nomic-768", dim=768)
    text = "hello"
    await _plant_metadata(
        db,
        entity_type="journal",
        entity_id="jrn_match",
        content_hash=_hash(text),
        model_name="nomic-768",
        dimensions=768,
    )
    result = await svc.needs_reembed("journal", "jrn_match", text)
    assert result is False


# ---------------------------------------------------------------------------
# True on any single field mismatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_needs_reembed_true_when_content_hash_mismatches(db):
    """v2.4 behavior preserved: content change → stale."""
    svc = _service(db, model_name="nomic-768", dim=768)
    await _plant_metadata(
        db,
        entity_type="journal",
        entity_id="jrn_content_drift",
        content_hash=_hash("OLD content"),
        model_name="nomic-768",
        dimensions=768,
    )
    result = await svc.needs_reembed("journal", "jrn_content_drift", "NEW content")
    assert result is True


@pytest.mark.asyncio
async def test_needs_reembed_true_when_model_name_mismatches(db):
    """The Bug-2 trigger: nomic→qwen3 swap MUST flag every entity stale."""
    text = "hello"
    # Service runs the qwen3-4096 backend; metadata still claims nomic-768.
    svc = _service(db, model_name="qwen3-4096", dim=4096)
    await _plant_metadata(
        db,
        entity_type="journal",
        entity_id="jrn_model_swap",
        content_hash=_hash(text),
        model_name="nomic-768",  # mismatch
        dimensions=4096,         # match
    )
    result = await svc.needs_reembed("journal", "jrn_model_swap", text)
    assert result is True


@pytest.mark.asyncio
async def test_needs_reembed_true_when_dimensions_mismatches(db):
    """Same model name string but different dim → stale (defensive)."""
    text = "hello"
    svc = _service(db, model_name="some-model", dim=4096)
    await _plant_metadata(
        db,
        entity_type="journal",
        entity_id="jrn_dim_swap",
        content_hash=_hash(text),
        model_name="some-model",  # match
        dimensions=768,           # mismatch
    )
    result = await svc.needs_reembed("journal", "jrn_dim_swap", text)
    assert result is True


@pytest.mark.asyncio
async def test_needs_reembed_true_when_metadata_row_absent(db):
    """No prior embedding ever recorded → stale (the backfill trigger)."""
    svc = _service(db, model_name="nomic-768", dim=768)
    result = await svc.needs_reembed("journal", "jrn_never_embedded", "hello")
    assert result is True


# ---------------------------------------------------------------------------
# Defensive: zero-dim backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_needs_reembed_true_when_backend_dim_zero(db):
    """Un-initialized backend (dim == 0) is treated as needs-reembed so
    the next embed cycle re-handshakes instead of writing a zero-dim row."""
    svc = _service(db, model_name="zero-dim", dim=0)
    # Even with a perfectly matching metadata row, dim=0 short-circuits to True.
    await _plant_metadata(
        db,
        entity_type="journal",
        entity_id="jrn_zero_dim",
        content_hash=_hash("hello"),
        model_name="zero-dim",
        dimensions=0,
    )
    result = await svc.needs_reembed("journal", "jrn_zero_dim", "hello")
    assert result is True
