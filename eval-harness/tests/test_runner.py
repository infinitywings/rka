"""Tests for the eval-harness runner — RKA call + hybrid re-rank logic.

External services (RKA `/api/search` + LM Studio embeddings) are
mocked via httpx fixtures, so the tests run offline and don't depend
on container state.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from eval_harness.runner import (
    Config,
    QueryResult,
    ResultRow,
    _cosine,
    _rrf_fuse,
    call_rka_search,
    load_queries,
    run_config,
)


# ---------------------------------------------------------------------------
# Cosine + RRF — pure functions
# ---------------------------------------------------------------------------


def test_cosine_identical_vectors_is_1():
    assert _cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors_is_0():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_empty_or_mismatched_returns_0():
    assert _cosine([], [1.0]) == 0.0
    assert _cosine([1.0, 2.0], [3.0]) == 0.0


def test_cosine_zero_vector_returns_0():
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_rrf_fuse_prefers_agreement():
    # Both rankings put `a` first → `a` should top the fused list.
    fts = ["a", "b", "c"]
    sem = ["a", "c", "b"]
    fused = _rrf_fuse(fts, sem, top_k=3)
    assert fused[0][0] == "a"
    # Each result should carry both ranks.
    for rid, score, fts_rank, sem_rank in fused:
        assert fts_rank is not None
        assert sem_rank is not None


def test_rrf_fuse_disagreement_keeps_both_candidates():
    fts = ["a", "b"]
    sem = ["c", "d"]
    fused = _rrf_fuse(fts, sem, top_k=4)
    ids = {row[0] for row in fused}
    assert ids == {"a", "b", "c", "d"}


def test_rrf_fuse_truncates_to_k():
    fts = [f"r{i}" for i in range(10)]
    sem = [f"r{i}" for i in range(10)][::-1]
    fused = _rrf_fuse(fts, sem, top_k=3)
    assert len(fused) == 3


# ---------------------------------------------------------------------------
# RKA call adapter — both response shapes
# ---------------------------------------------------------------------------


def _mock_transport(responder):
    return httpx.MockTransport(responder)


def test_call_rka_search_handles_bare_list_shape():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"id": "a", "entity_type": "decision", "score": 0.9},
                {"id": "b", "entity_type": "note", "score": 0.5},
            ],
        )

    client = httpx.Client(
        transport=_mock_transport(respond), base_url="http://x"
    )
    hits = call_rka_search(
        client, query="anything", limit=10, project_id=None, entity_types=None
    )
    assert [h["id"] for h in hits] == ["a", "b"]


def test_call_rka_search_handles_dict_envelope_shape():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "hits": [{"id": "x", "score": 1.0}],
                "total": 1,
            },
        )

    client = httpx.Client(
        transport=_mock_transport(respond), base_url="http://x"
    )
    hits = call_rka_search(
        client, query="anything", limit=10, project_id="prj_abc", entity_types=None
    )
    assert [h["id"] for h in hits] == ["x"]


def test_call_rka_search_passes_entity_types_param():
    captured: dict = {}

    def respond(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=[])

    client = httpx.Client(
        transport=_mock_transport(respond), base_url="http://x"
    )
    call_rka_search(
        client,
        query="q",
        limit=10,
        project_id="prj_abc",
        entity_types=["decision", "journal"],
    )
    assert captured["params"]["entity_types"] == "decision,journal"
    assert captured["params"]["project_id"] == "prj_abc"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def test_config_load_minimal(tmp_path):
    cfg_path = tmp_path / "minimal.yaml"
    cfg_path.write_text(
        "name: minimal\n"
        "rka_fts_query_mode: and\n"
        "rka_embeddings_enabled: false\n"
        "semantic_backend: null\n"
        "top_k: 5\n"
    )
    c = Config.load(cfg_path)
    assert c.name == "minimal"
    assert c.rka_fts_query_mode == "and"
    assert c.rka_embeddings_enabled is False
    assert c.semantic_backend is None
    assert c.top_k == 5


def test_config_load_hybrid_defaults_qwen3(tmp_path):
    cfg_path = tmp_path / "hybrid.yaml"
    cfg_path.write_text(
        "name: hybrid_test\n"
        "rka_fts_query_mode: or\n"
        "rka_embeddings_enabled: false\n"
        "semantic_backend: qwen3\n"
    )
    c = Config.load(cfg_path)
    assert c.semantic_backend == "qwen3"
    assert c.qwen3_model.startswith("qwen3-embedding")
    assert c.search_limit_for_hybrid >= c.top_k


# ---------------------------------------------------------------------------
# Full FTS-only run via mocked transport
# ---------------------------------------------------------------------------


def test_run_config_fts_only_writes_per_query_jsonl(tmp_path, monkeypatch):
    # Build a tiny query corpus + mock RKA returning two hits per query.
    queries_path = tmp_path / "queries.jsonl"
    queries_path.write_text(
        json.dumps({"query": "alpha", "category": "x", "source": "synthetic"}) + "\n"
        + json.dumps({"query": "beta", "category": "x", "source": "synthetic"}) + "\n"
    )

    def respond(request: httpx.Request) -> httpx.Response:
        q = request.url.params.get("q") or request.url.params.get("query") or ""
        return httpx.Response(
            200,
            json=[
                {"id": f"{q}-1", "score": 0.9, "snippet": f"hit one for {q}"},
                {"id": f"{q}-2", "score": 0.5, "snippet": f"hit two for {q}"},
            ],
        )

    # Patch httpx.Client globally so the runner's internal client uses the
    # mock transport.
    real_client = httpx.Client

    def _patched_client(*args, **kwargs):
        kwargs["transport"] = _mock_transport(respond)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("eval_harness.runner.httpx.Client", _patched_client)

    cfg = Config(
        name="fts_only_test",
        rka_fts_query_mode="or",
        rka_embeddings_enabled=False,
        semantic_backend=None,
        top_k=10,
    )
    queries = load_queries(queries_path)
    output_path = tmp_path / "out.jsonl"

    rows = run_config(
        config=cfg,
        queries=queries,
        project_id=None,
        api_url="http://x",
        output_path=output_path,
    )
    assert rows == 2

    written = [json.loads(line) for line in output_path.read_text().splitlines() if line]
    assert {row["query"] for row in written} == {"alpha", "beta"}
    for row in written:
        # Each query saw 2 mock hits → 2 rows in `results`.
        assert len(row["results"]) == 2
        # ranks start at 1 in output.
        assert [r["rank"] for r in row["results"]] == [1, 2]


def test_run_config_aborts_on_unreachable_qwen3_per_observation_2(
    tmp_path, monkeypatch
):
    """Hybrid runs probe LM Studio first; unreachable → exit -1 (checkpoint).

    Mirrors observation #2: no retry-loop on infra failures.
    """
    queries_path = tmp_path / "queries.jsonl"
    queries_path.write_text(json.dumps({"query": "x"}) + "\n")

    # Mock httpx.Client raising on connect — LM Studio is "down".
    class _ExplodingClient:
        def __init__(self, *args, **kwargs):
            pass

        def post(self, *args, **kwargs):
            raise httpx.ConnectError("nope")

        def close(self):
            pass

    monkeypatch.setattr("eval_harness.embedder.httpx.Client", _ExplodingClient)

    cfg = Config(
        name="hybrid_unreachable",
        rka_fts_query_mode="or",
        rka_embeddings_enabled=False,
        semantic_backend="qwen3",
        qwen3_base_url="http://localhost:1234",
    )
    queries = load_queries(queries_path)
    rows = run_config(
        config=cfg,
        queries=queries,
        project_id=None,
        api_url="http://x",
        output_path=tmp_path / "out.jsonl",
    )
    # `run_config` returns -1 to signal checkpoint per observation #2.
    assert rows == -1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_load_queries_skips_blank_lines(tmp_path):
    path = tmp_path / "queries.jsonl"
    path.write_text(
        '{"query": "q1"}\n'
        "\n"
        '{"query": "q2"}\n'
    )
    assert load_queries(path) == [{"query": "q1"}, {"query": "q2"}]
