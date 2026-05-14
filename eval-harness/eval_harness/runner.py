"""Eval-harness runner — executes ONE config × all queries.

Mission `mis_01KRKJ9G20EM5XMA147JTKQCFF` Task T2 (runner) + T3
(execution entry point).

Per-config invocation:

    python -m eval_harness.runner \\
        --config configs/current_or.yaml \\
        --queries corpus/queries.jsonl \\
        --output results/raw/current_or.jsonl \\
        --project-id prj_01KKQM9JFG67GT5FGWTAHD9YE4

The runner does NOT manage the container's env. It assumes the
caller has already restarted the RKA container with the right
`RKA_FTS_QUERY_MODE` + `RKA_EMBEDDINGS_ENABLED` for this config.
The 4-config orchestration (sequencing env-restarts) belongs to a
T3 wrapper script (`run-eval.sh`); the runner stays single-config so
its failure modes are isolated.

Per-query flow:

    1. Call `/api/search` with the config's params (limit=top_k,
       project_id, optional entity_types filter).
    2. If `semantic_backend: qwen3`, re-rank top-K via qwen3-cosine
       (Option C, eval-harness-direct) using Reciprocal Rank Fusion.
    3. Persist top-10 ids + rank + score + snippet to the output
       JSONL (one line per query).

Hybrid (qwen3) details for configs `*_hybrid.yaml`:

    - Embed the query string via `EmbeddingClient.embed`.
    - Fetch each FTS candidate's content text via `/api/notes/{id}`,
      `/api/decisions/{id}`, etc. Embed each (or use precomputed
      vectors loaded from `results/qwen3_vectors.jsonl` if present).
    - Compute cosine similarity between query and each candidate.
    - Combine the FTS rank and semantic rank via Reciprocal Rank
      Fusion (RRF with k=60, standard).

The hybrid path runs an LM Studio reachability probe FIRST per
observation #2 (reachability-first; no retry-loop on infra failure).
Probe failure → checkpoint, NOT silent fallback to FTS-only.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from eval_harness.embedder import (
    EmbeddingClient,
    EmbeddingError,
    ProbeResult,
)


DEFAULT_API_URL = "http://127.0.0.1:9712"
DEFAULT_TOP_K = 10
SEARCH_LIMIT_FOR_HYBRID = 30  # broader candidate pool for the qwen3 re-rank
RRF_K = 60.0  # Reciprocal Rank Fusion smoothing constant
PROGRESS_HEARTBEAT_EVERY = 5  # log a heartbeat every N queries (observation #4)


@dataclass
class Config:
    """One eval configuration loaded from configs/<name>.yaml."""

    name: str
    rka_fts_query_mode: str          # informational mirror of the container env
    rka_embeddings_enabled: bool     # informational mirror of the container env
    semantic_backend: str | None     # None | "qwen3"
    top_k: int = DEFAULT_TOP_K
    entity_types: list[str] | None = None
    # Hybrid-only:
    qwen3_base_url: str = "http://192.168.86.24:1234"
    qwen3_model: str = "qwen3-embedding-8b-dwq"
    search_limit_for_hybrid: int = SEARCH_LIMIT_FOR_HYBRID

    @classmethod
    def load(cls, path: Path) -> "Config":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            name=raw.get("name") or path.stem,
            rka_fts_query_mode=str(raw.get("rka_fts_query_mode", "or")),
            rka_embeddings_enabled=bool(raw.get("rka_embeddings_enabled", False)),
            semantic_backend=raw.get("semantic_backend"),
            top_k=int(raw.get("top_k", DEFAULT_TOP_K)),
            entity_types=raw.get("entity_types"),
            qwen3_base_url=raw.get("qwen3_base_url", "http://192.168.86.24:1234"),
            qwen3_model=raw.get("qwen3_model", "qwen3-embedding-8b-dwq"),
            search_limit_for_hybrid=int(
                raw.get("search_limit_for_hybrid", SEARCH_LIMIT_FOR_HYBRID)
            ),
        )


@dataclass
class ResultRow:
    """One ranked result inside a query's top-K output."""

    id: str
    rank: int
    score: float
    snippet: str = ""
    fts_rank: int | None = None       # original FTS rank if hybrid was applied
    semantic_rank: int | None = None  # qwen3-cosine rank if hybrid was applied


@dataclass
class QueryResult:
    """One line of the per-config results JSONL output."""

    query: str
    results: list[ResultRow] = field(default_factory=list)
    latency_ms: float = 0.0


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# RKA /api/search adapter
# ---------------------------------------------------------------------------


def call_rka_search(
    client: httpx.Client,
    query: str,
    limit: int,
    project_id: str | None,
    entity_types: list[str] | None,
) -> list[dict]:
    """Call `/api/search` and return the raw hits list.

    Hits shape (per `rka/services/search.py::SearchHit`):
        {id, entity_type, score, snippet?, ...}
    """
    params: dict[str, Any] = {"q": query, "limit": limit}
    if project_id is not None:
        params["project_id"] = project_id
    if entity_types:
        params["entity_types"] = ",".join(entity_types)
    response = client.get("/api/search", params=params)
    response.raise_for_status()
    payload = response.json()
    # The /api/search route may return either a list of hits OR
    # {"hits": [...], "total": N, ...} depending on version. Normalize.
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("hits") or payload.get("results") or []
    raise ValueError(f"unexpected /api/search shape: {type(payload).__name__}")


# ---------------------------------------------------------------------------
# Hybrid: qwen3 cosine re-rank + RRF
# ---------------------------------------------------------------------------


def _fetch_content_for_hit(client: httpx.Client, hit: dict, project_id: str | None) -> str:
    """Get the candidate's text content for qwen3 embedding.

    Different entity types live at different endpoints. We try a few
    common shapes and fall back to whatever snippet/content RKA already
    returned in the hit payload.
    """
    if hit.get("content"):
        return str(hit["content"])
    if hit.get("snippet"):
        return str(hit["snippet"])

    eid = hit.get("id", "")
    etype = hit.get("entity_type", "")
    endpoint_map = {
        "journal": "/api/notes",
        "note": "/api/notes",
        "decision": "/api/decisions",
        "literature": "/api/literature",
        "mission": "/api/missions",
        "claim": "/api/claims",
        "evidence_cluster": "/api/clusters",
        "cluster": "/api/clusters",
    }
    base = endpoint_map.get(etype)
    if not base or not eid:
        return ""
    try:
        params: dict[str, Any] = {}
        if project_id is not None:
            params["project_id"] = project_id
        r = client.get(f"{base}/{eid}", params=params)
        r.raise_for_status()
        body = r.json()
    except Exception:
        return ""
    for k in ("content", "summary", "question", "objective", "title"):
        if isinstance(body, dict) and body.get(k):
            return str(body[k])
    return ""


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    if da <= 0 or db <= 0:
        return 0.0
    return num / (da * db)


def _rrf_fuse(
    fts_order: list[str],
    semantic_order: list[str],
    top_k: int,
) -> list[tuple[str, float, int | None, int | None]]:
    """Reciprocal Rank Fusion across the two orderings.

    Returns `[(id, rrf_score, fts_rank, semantic_rank), ...]` sorted by
    rrf_score desc, truncated to `top_k`.
    """
    fts_rank = {rid: i + 1 for i, rid in enumerate(fts_order)}
    sem_rank = {rid: i + 1 for i, rid in enumerate(semantic_order)}
    all_ids = set(fts_rank) | set(sem_rank)
    scored: list[tuple[str, float, int | None, int | None]] = []
    for rid in all_ids:
        score = 0.0
        if rid in fts_rank:
            score += 1.0 / (RRF_K + fts_rank[rid])
        if rid in sem_rank:
            score += 1.0 / (RRF_K + sem_rank[rid])
        scored.append((rid, score, fts_rank.get(rid), sem_rank.get(rid)))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:top_k]


def _load_precomputed_vectors(path: Path) -> dict[str, list[float]]:
    """Load `{entity_id: vector}` from a JSONL file written by the
    backfill step. Returns an empty dict if the file is absent."""
    if not path.exists():
        return {}
    out: dict[str, list[float]] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out[row["id"]] = list(row["vector"])
    return out


def hybrid_rerank(
    *,
    fts_hits: list[dict],
    query: str,
    embedder: EmbeddingClient,
    client: httpx.Client,
    project_id: str | None,
    precomputed: dict[str, list[float]],
    top_k: int,
) -> list[ResultRow]:
    """Re-rank FTS hits using qwen3 cosine + RRF (Option C)."""
    if not fts_hits:
        return []

    fts_order = [h["id"] for h in fts_hits if "id" in h]

    # 1. Embed the query once.
    query_vec = embedder.embed(query)

    # 2. Ensure we have a vector for each FTS candidate (use precomputed
    #    when available; embed live otherwise).
    candidate_vectors: dict[str, list[float]] = {}
    to_embed: list[tuple[str, str]] = []
    for hit in fts_hits:
        rid = hit["id"]
        if rid in precomputed:
            candidate_vectors[rid] = precomputed[rid]
            continue
        content = _fetch_content_for_hit(client, hit, project_id)
        to_embed.append((rid, content))

    if to_embed:
        vectors = embedder.embed_batch([content for _, content in to_embed])
        for (rid, _), vec in zip(to_embed, vectors):
            candidate_vectors[rid] = vec

    # 3. Cosine-rank candidates.
    cosine_scored = sorted(
        (
            (rid, _cosine(query_vec, candidate_vectors.get(rid, [])))
            for rid in fts_order
        ),
        key=lambda t: t[1],
        reverse=True,
    )
    semantic_order = [rid for rid, _ in cosine_scored]

    # 4. RRF fuse the two rankings.
    fused = _rrf_fuse(fts_order, semantic_order, top_k=top_k)

    by_id = {h["id"]: h for h in fts_hits}
    rows: list[ResultRow] = []
    for new_rank, (rid, score, fts_rank, sem_rank) in enumerate(fused, start=1):
        hit = by_id.get(rid, {})
        rows.append(
            ResultRow(
                id=rid,
                rank=new_rank,
                score=score,
                snippet=(hit.get("snippet") or "")[:200],
                fts_rank=fts_rank,
                semantic_rank=sem_rank,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Per-config run
# ---------------------------------------------------------------------------


def run_config(
    *,
    config: Config,
    queries: list[dict],
    project_id: str | None,
    api_url: str,
    output_path: Path,
    precomputed_vectors_path: Path | None = None,
) -> int:
    """Run one config over all queries; write results JSONL.

    Returns the number of queries processed (== rows written to output)."""

    use_hybrid = config.semantic_backend == "qwen3"

    # T3 pre-flight: reachability probe BEFORE running queries.
    # Observation #2 — reachability-first; no retry-loop on infra failure.
    embedder: EmbeddingClient | None = None
    if use_hybrid:
        embedder = EmbeddingClient(
            base_url=config.qwen3_base_url, model=config.qwen3_model
        )
        probe = embedder.probe()
        sys.stderr.write(f"[runner] {probe}\n")
        if not probe.reachable:
            sys.stderr.write(
                "[runner] CHECKPOINT — LM Studio unreachable; not retrying. "
                "Surface to PI per observation #2.\n"
            )
            embedder.close()
            return -1

    precomputed: dict[str, list[float]] = {}
    if use_hybrid and precomputed_vectors_path is not None:
        precomputed = _load_precomputed_vectors(precomputed_vectors_path)
        if precomputed:
            sys.stderr.write(
                f"[runner] using {len(precomputed)} precomputed qwen3 vectors\n"
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0

    with (
        httpx.Client(base_url=api_url, timeout=30.0) as rka_client,
        output_path.open("w", encoding="utf-8") as out_fh,
    ):
        for i, qrow in enumerate(queries, start=1):
            query = qrow["query"]
            start = time.perf_counter()

            fts_limit = (
                config.search_limit_for_hybrid if use_hybrid else config.top_k
            )
            try:
                hits = call_rka_search(
                    rka_client,
                    query=query,
                    limit=fts_limit,
                    project_id=project_id,
                    entity_types=config.entity_types,
                )
            except httpx.HTTPError as e:
                sys.stderr.write(f"[runner] query {i} HTTP error: {e}\n")
                hits = []

            if use_hybrid and embedder is not None:
                try:
                    result_rows = hybrid_rerank(
                        fts_hits=hits,
                        query=query,
                        embedder=embedder,
                        client=rka_client,
                        project_id=project_id,
                        precomputed=precomputed,
                        top_k=config.top_k,
                    )
                except EmbeddingError as e:
                    sys.stderr.write(
                        f"[runner] CHECKPOINT — qwen3 retries exhausted on query "
                        f"{i!r}: {e}\n"
                    )
                    embedder.close()
                    return -1
            else:
                result_rows = [
                    ResultRow(
                        id=h.get("id", ""),
                        rank=rank,
                        score=float(h.get("score", 0.0)),
                        snippet=(h.get("snippet") or "")[:200],
                    )
                    for rank, h in enumerate(hits[: config.top_k], start=1)
                ]

            latency_ms = (time.perf_counter() - start) * 1000.0
            line = QueryResult(query=query, results=result_rows, latency_ms=latency_ms)
            out_fh.write(json.dumps(_serialize(line), ensure_ascii=False))
            out_fh.write("\n")
            rows_written += 1

            if i % PROGRESS_HEARTBEAT_EVERY == 0:
                sys.stderr.write(
                    f"[runner] {_now_iso()} · {config.name} · "
                    f"{i}/{len(queries)} queries done\n"
                )

    if embedder is not None:
        embedder.close()
    return rows_written


def _serialize(line: QueryResult) -> dict:
    return {
        "query": line.query,
        "results": [asdict(r) for r in line.results],
        "latency_ms": round(line.latency_ms, 2),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one eval configuration × all queries; write JSONL.",
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument(
        "--precomputed-vectors",
        type=Path,
        default=None,
        help=(
            "Optional JSONL of {id, vector} rows for hybrid configs. "
            "Generated by the T3 backfill step; if absent, the runner "
            "embeds each candidate live."
        ),
    )
    return parser


def load_queries(path: Path) -> list[dict]:
    """Return the canonical query rows from corpus/queries.jsonl."""
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    config = Config.load(args.config)
    queries = load_queries(args.queries)
    sys.stderr.write(
        f"[runner] starting {config.name} · {len(queries)} queries · "
        f"semantic={config.semantic_backend or 'none'}\n"
    )
    n = run_config(
        config=config,
        queries=queries,
        project_id=args.project_id,
        api_url=args.api_url,
        output_path=args.output,
        precomputed_vectors_path=args.precomputed_vectors,
    )
    if n < 0:
        return 2  # checkpoint exit code
    sys.stderr.write(f"[runner] {config.name} complete · {n} queries written\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
