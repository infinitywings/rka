"""Hybrid search service: FTS5 keyword + sqlite-vec vector + Reciprocal Rank Fusion."""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field

from rka.infra.database import Database
from rka.infra.embeddings import EmbeddingService

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    """A single search result."""

    entity_type: str
    entity_id: str
    title: str
    snippet: str
    score: float = 0.0
    fts_rank: int | None = None
    vec_rank: int | None = None


class SearchService:
    """Hybrid FTS5 + vector search across all entity types.

    Behaviour adapts to available backends:
      - FTS5 is always available (built into SQLite).
      - Vector search requires sqlite-vec extension + embeddings.
      - When only FTS5 is available, falls back to keyword-only.
      - When only LIKE is available (no FTS5 data), falls back to Phase 1 search.
    """

    # Maps entity types to their FTS5 table and columns
    FTS_MAP = {
        "journal": {
            "table": "fts_journal",
            "source": "journal",
            "title_expr": "'[' || j.type || ']'",
            "snippet_col": "content",
            "join_alias": "j",
        },
        "decision": {
            "table": "fts_decisions",
            "source": "decisions",
            "title_expr": "d.question",
            "snippet_col": "question",
            "join_alias": "d",
        },
        "literature": {
            "table": "fts_literature",
            "source": "literature",
            "title_expr": "l.title",
            "snippet_col": "title",
            "join_alias": "l",
        },
        "mission": {
            "table": "fts_missions",
            "source": "missions",
            "title_expr": "m.objective",
            "snippet_col": "objective",
            "join_alias": "m",
        },
    }

    VEC_MAP = {
        "journal": "vec_journal",
        "decision": "vec_decisions",
        "literature": "vec_literature",
        "mission": "vec_missions",
    }

    def __init__(
        self,
        db: Database,
        embeddings: EmbeddingService | None = None,
        project_id: str = "proj_default",
    ):
        self.db = db
        self.embeddings = embeddings
        self.project_id = project_id

    def with_project(self, project_id: str) -> "SearchService":
        return SearchService(db=self.db, embeddings=self.embeddings, project_id=project_id)

    async def search(
        self,
        query: str,
        entity_types: list[str] | None = None,
        limit: int = 20,
        keyword_weight: float = 0.3,
        semantic_weight: float = 0.7,
    ) -> list[SearchHit]:
        """Hybrid search combining FTS5 keyword and vector semantic search.

        Falls back gracefully:
          - No embeddings → keyword only
          - No FTS5 data → LIKE fallback
          - No sqlite-vec → keyword only
        """
        types = entity_types or ["decision", "literature", "journal", "mission"]

        # 1. FTS5 keyword search
        fts_results = await self._fts_search(query, types, limit * 2)

        # 2. Vector search (if available)
        vec_results: list[SearchHit] = []
        if self.embeddings and self.db.vec_available:
            try:
                query_vec = await self.embeddings.embed(query)
                vec_results = await self._vector_search(query_vec, types, limit * 2)
            except Exception as exc:
                logger.warning("Vector search failed, using keyword only: %s", exc)

        # 3. If both are empty, fall back to LIKE search
        if not fts_results and not vec_results:
            return await self._like_fallback(query, types, limit)

        # 4. If only one source has results, return that
        if not vec_results:
            return fts_results[:limit]
        if not fts_results:
            return vec_results[:limit]

        # 5. Reciprocal Rank Fusion
        fused = self._rrf_merge(fts_results, vec_results, keyword_weight, semantic_weight)
        return fused[:limit]

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Convert a natural-language query to a safe FTS5 query.

        Strategy: split into words, quote each individually, join with OR.
        This avoids issues with hyphens, special chars, and FTS5 operators.
        """
        import re
        # Split on non-word chars (hyphens, punctuation, etc.)
        words = re.findall(r"[a-zA-Z0-9]+", query)
        if not words:
            return query
        # Quote each word and combine with OR for recall, but also try the full phrase
        quoted = " ".join(f'"{w}"' for w in words)
        return quoted

    async def _fts_search(
        self, query: str, entity_types: list[str], limit: int,
    ) -> list[SearchHit]:
        """Full-text search across FTS5 virtual tables."""
        results: list[SearchHit] = []
        fts_query = self._sanitize_fts_query(query)

        for etype in entity_types:
            info = self.FTS_MAP.get(etype)
            if not info:
                continue

            try:
                rows = await self.db.fetchall(
                    f"""SELECT f.id, f.rank
                        FROM {info['table']} f
                        WHERE {info['table']} MATCH ?
                        ORDER BY f.rank
                        LIMIT ?""",
                    [fts_query, limit],
                )
            except Exception:
                # FTS5 table might be empty or query invalid
                continue

            if not rows:
                continue

            # Fetch full data for matched IDs
            ids = [row["id"] for row in rows]
            rank_map = {row["id"]: i for i, row in enumerate(rows)}
            placeholders = ",".join("?" for _ in ids)

            data_rows = await self.db.fetchall(
                f"SELECT * FROM {info['source']} WHERE id IN ({placeholders}) AND project_id = ?",
                ids + [self.project_id],
            )

            for row in data_rows:
                title, snippet = self._extract_title_snippet(etype, row)
                results.append(SearchHit(
                    entity_type=etype,
                    entity_id=row["id"],
                    title=title,
                    snippet=snippet,
                    fts_rank=rank_map.get(row["id"], 999),
                ))

        # Sort by FTS rank (lower is better)
        results.sort(key=lambda h: h.fts_rank or 999)
        return results

    async def _vector_search(
        self, query_vec: list[float], entity_types: list[str], limit: int,
    ) -> list[SearchHit]:
        """KNN search across sqlite-vec virtual tables."""
        results: list[SearchHit] = []
        vec_blob = struct.pack(f"{len(query_vec)}f", *query_vec)

        for etype in entity_types:
            table = self.VEC_MAP.get(etype)
            if not table:
                continue

            source = self.FTS_MAP[etype]["source"]

            try:
                rows = await self.db.fetchall(
                    f"""SELECT id, distance
                        FROM {table}
                        WHERE embedding MATCH ?
                        ORDER BY distance
                        LIMIT ?""",
                    [vec_blob, limit],
                )
            except Exception:
                continue

            if not rows:
                continue

            ids = [row["id"] for row in rows]
            dist_map = {row["id"]: row["distance"] for row in rows}
            rank_map = {row["id"]: i for i, row in enumerate(rows)}
            placeholders = ",".join("?" for _ in ids)

            data_rows = await self.db.fetchall(
                f"SELECT * FROM {source} WHERE id IN ({placeholders}) AND project_id = ?",
                ids + [self.project_id],
            )

            for row in data_rows:
                title, snippet = self._extract_title_snippet(etype, row)
                dist = dist_map.get(row["id"], 1.0)
                results.append(SearchHit(
                    entity_type=etype,
                    entity_id=row["id"],
                    title=title,
                    snippet=snippet,
                    score=max(0.0, 1.0 - dist),  # cosine similarity
                    vec_rank=rank_map.get(row["id"], 999),
                ))

        # Sort by distance (lower distance = more similar)
        results.sort(key=lambda h: h.vec_rank or 999)
        return results

    def _rrf_merge(
        self,
        fts_results: list[SearchHit],
        vec_results: list[SearchHit],
        keyword_weight: float,
        semantic_weight: float,
        k: int = 60,
    ) -> list[SearchHit]:
        """Reciprocal Rank Fusion — merge ranked lists from different sources.

        RRF score = w_kw / (k + rank_fts) + w_sem / (k + rank_vec)
        """
        # Build score maps
        scores: dict[str, float] = {}
        hits: dict[str, SearchHit] = {}

        for rank, hit in enumerate(fts_results):
            key = f"{hit.entity_type}:{hit.entity_id}"
            scores[key] = scores.get(key, 0.0) + keyword_weight / (k + rank + 1)
            hits[key] = hit

        for rank, hit in enumerate(vec_results):
            key = f"{hit.entity_type}:{hit.entity_id}"
            scores[key] = scores.get(key, 0.0) + semantic_weight / (k + rank + 1)
            if key not in hits:
                hits[key] = hit

        # Sort by fused score descending
        sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
        result = []
        for key in sorted_keys:
            hit = hits[key]
            hit.score = scores[key]
            result.append(hit)

        return result

    async def _like_fallback(
        self, query: str, entity_types: list[str], limit: int,
    ) -> list[SearchHit]:
        """Phase 1 LIKE-based fallback search."""
        results: list[SearchHit] = []
        q = f"%{query}%"

        if "decision" in entity_types:
            rows = await self.db.fetchall(
                "SELECT * FROM decisions WHERE project_id = ? AND (question LIKE ? OR rationale LIKE ?) LIMIT ?",
                [self.project_id, q, q, limit],
            )
            for row in rows:
                results.append(SearchHit(
                    entity_type="decision", entity_id=row["id"],
                    title=row["question"][:100], snippet=row["question"][:200],
                ))

        if "literature" in entity_types:
            rows = await self.db.fetchall(
                "SELECT * FROM literature WHERE project_id = ? AND (title LIKE ? OR abstract LIKE ?) LIMIT ?",
                [self.project_id, q, q, limit],
            )
            for row in rows:
                results.append(SearchHit(
                    entity_type="literature", entity_id=row["id"],
                    title=row["title"][:100], snippet=(row.get("abstract") or "")[:200],
                ))

        if "journal" in entity_types:
            rows = await self.db.fetchall(
                "SELECT * FROM journal WHERE project_id = ? AND content LIKE ? LIMIT ?",
                [self.project_id, q, limit],
            )
            for row in rows:
                results.append(SearchHit(
                    entity_type="journal", entity_id=row["id"],
                    title=f"[{row['type']}]", snippet=row["content"][:200],
                ))

        if "mission" in entity_types:
            rows = await self.db.fetchall(
                "SELECT * FROM missions WHERE project_id = ? AND objective LIKE ? LIMIT ?",
                [self.project_id, q, limit],
            )
            for row in rows:
                results.append(SearchHit(
                    entity_type="mission", entity_id=row["id"],
                    title=row["objective"][:100], snippet=row["objective"][:200],
                ))

        return results[:limit]

    @staticmethod
    def _extract_title_snippet(etype: str, row: dict) -> tuple[str, str]:
        """Extract display title and snippet from a raw DB row."""
        if etype == "journal":
            return f"[{row.get('type', 'note')}]", (row.get("content") or "")[:200]
        elif etype == "decision":
            return (row.get("question") or "")[:100], (row.get("rationale") or row.get("question") or "")[:200]
        elif etype == "literature":
            return (row.get("title") or "")[:100], (row.get("abstract") or "")[:200]
        elif etype == "mission":
            return (row.get("objective") or "")[:100], (row.get("context") or row.get("objective") or "")[:200]
        return "", ""
