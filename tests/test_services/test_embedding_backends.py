"""Unit tests for the pluggable embedding backends (Mission D T1).

Each backend is exercised against a mocked `httpx` transport (for the
HTTP backends) so the suite runs offline. The FastEmbed backend is
covered by a Protocol-conformance test that doesn't touch the model
loader (we don't pull ~130 MB at test time).
"""

from __future__ import annotations

import json

import httpx
import pytest

from rka.infra.embedding_backends import (
    ConnectionTestResult,
    EmbeddingBackend,
    make_backend,
)
from rka.infra.embedding_backends.fastembed import FastEmbedBackend
from rka.infra.embedding_backends.ollama import OllamaBackend
from rka.infra.embedding_backends.openai_compat import OpenAICompatBackend


# ---------------------------------------------------------------------------
# httpx mock transports
# ---------------------------------------------------------------------------


def _openai_responder(dim: int = 4):
    """Return an httpx.MockTransport that mimics OpenAI's /v1/embeddings."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        body = json.loads(request.content) if request.content else {}
        inputs = body.get("input", [])
        if isinstance(inputs, str):
            inputs = [inputs]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [float(i)] * dim, "index": i}
                    for i in range(len(inputs))
                ],
                "model": body.get("model", "unknown"),
            },
        )

    return httpx.MockTransport(handler)


def _ollama_responder(dim: int = 4):
    """Return an httpx.MockTransport that mimics Ollama's /api/embeddings."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embeddings"
        body = json.loads(request.content) if request.content else {}
        # Ollama returns SINGULAR `embedding`, NOT list-wrapped data.
        return httpx.Response(
            200,
            json={"embedding": [0.1] * dim, "model": body.get("model")},
        )

    return httpx.MockTransport(handler)


def _flaky_responder(failures_first: int, dim: int = 4):
    """Return 503 a few times then succeed; for retry testing."""
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        if state["count"] <= failures_first:
            return httpx.Response(503, json={"error": "transient"})
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1] * dim, "index": 0}]},
        )

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_make_backend_fastembed_dispatch():
    b = make_backend({"backend": "fastembed", "config": {"model_name": "test-model"}})
    assert isinstance(b, FastEmbedBackend)
    assert b.model_name == "test-model"


def test_make_backend_openai_compat_dispatch():
    b = make_backend(
        {
            "backend": "openai_compat",
            "config": {"base_url": "http://x", "model": "m", "dim": 4},
        }
    )
    assert isinstance(b, OpenAICompatBackend)
    assert b.dim == 4
    assert b.model_name == "m"


def test_make_backend_ollama_dispatch():
    b = make_backend(
        {"backend": "ollama", "config": {"base_url": "http://x", "model": "m"}}
    )
    assert isinstance(b, OllamaBackend)
    assert b.model_name == "m"


def test_make_backend_unknown_raises_value_error():
    with pytest.raises(ValueError, match="unknown embedding backend"):
        make_backend({"backend": "magic", "config": {}})


def test_make_backend_missing_backend_raises():
    with pytest.raises(ValueError, match="unknown embedding backend"):
        make_backend({"config": {}})


# ---------------------------------------------------------------------------
# OpenAI-compat backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_compat_embed_returns_vector():
    client = httpx.AsyncClient(transport=_openai_responder(dim=4), base_url="http://x")
    b = OpenAICompatBackend(
        base_url="http://x", model="m", api_key=None, dim=4, http_client=client
    )
    vec = await b.embed("hello")
    assert len(vec) == 4


@pytest.mark.asyncio
async def test_openai_compat_embed_batch_preserves_order():
    client = httpx.AsyncClient(transport=_openai_responder(dim=3), base_url="http://x")
    b = OpenAICompatBackend(
        base_url="http://x", model="m", dim=3, http_client=client
    )
    out = await b.embed_batch(["a", "b", "c"])
    assert len(out) == 3
    # The mock returns distinct indices; assert per-input vectors come back
    assert out[0] != out[1]


@pytest.mark.asyncio
async def test_openai_compat_sends_authorization_header_when_api_key_present():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"data": [{"embedding": [0.1] * 3}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    b = OpenAICompatBackend(
        base_url="http://x", model="m", api_key="sk-secret", dim=3, http_client=client
    )
    await b.embed("x")
    assert captured["auth"] == "Bearer sk-secret"


@pytest.mark.asyncio
async def test_openai_compat_omits_authorization_when_api_key_absent():
    # LM Studio + several local-proxy backends don't require auth.
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"data": [{"embedding": [0.1] * 3}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    b = OpenAICompatBackend(
        base_url="http://x", model="m", api_key=None, dim=3, http_client=client
    )
    await b.embed("x")
    assert captured["auth"] is None


@pytest.mark.asyncio
async def test_openai_compat_test_connection_reports_dim_on_success():
    client = httpx.AsyncClient(transport=_openai_responder(dim=8), base_url="http://x")
    b = OpenAICompatBackend(
        base_url="http://x", model="m", dim=0, http_client=client
    )
    result = await b.test_connection()
    assert result.ok is True
    assert result.detected_dim == 8
    # After a successful test, backend remembers the detected dim.
    assert b.dim == 8


@pytest.mark.asyncio
async def test_openai_compat_test_connection_returns_not_ok_on_connect_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    b = OpenAICompatBackend(
        base_url="http://x", model="m", http_client=client
    )
    result = await b.test_connection()
    assert result.ok is False
    assert "connection refused" in result.detail


@pytest.mark.asyncio
async def test_openai_compat_retries_5xx(monkeypatch):
    # Patch sleep to be no-op so the test stays fast.
    import rka.infra.embedding_backends.openai_compat as oc

    async def _no_sleep(_):
        pass

    monkeypatch.setattr(oc.asyncio, "sleep", _no_sleep)
    client = httpx.AsyncClient(transport=_flaky_responder(failures_first=2, dim=3), base_url="http://x")
    b = OpenAICompatBackend(
        base_url="http://x", model="m", dim=0, http_client=client
    )
    vec = await b.embed("x")
    assert len(vec) == 3


def test_openai_compat_requires_base_url():
    with pytest.raises(ValueError, match="base_url"):
        OpenAICompatBackend(base_url="", model="m")


def test_openai_compat_requires_model():
    with pytest.raises(ValueError, match="model"):
        OpenAICompatBackend(base_url="http://x", model="")


# ---------------------------------------------------------------------------
# Ollama backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_parses_singular_embedding_field():
    client = httpx.AsyncClient(transport=_ollama_responder(dim=5), base_url="http://x")
    b = OllamaBackend(base_url="http://x", model="m", http_client=client)
    vec = await b.embed("hi")
    assert len(vec) == 5
    assert b.dim == 5


@pytest.mark.asyncio
async def test_ollama_rejects_unexpected_shape():
    # Ollama uses {"embedding": [...]} not {"data": [{"embedding": [...]}]}
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    b = OllamaBackend(base_url="http://x", model="m", http_client=client)
    with pytest.raises(RuntimeError, match="missing 'embedding'"):
        await b.embed("hi")


@pytest.mark.asyncio
async def test_ollama_embed_batch_loops_single_prompt_calls():
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        body = json.loads(request.content)
        assert "prompt" in body  # Ollama uses prompt (singular), not input
        return httpx.Response(200, json={"embedding": [0.1] * 4})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    b = OllamaBackend(base_url="http://x", model="m", http_client=client)
    out = await b.embed_batch(["a", "b", "c"])
    assert len(out) == 3
    assert state["count"] == 3


@pytest.mark.asyncio
async def test_ollama_test_connection_reports_dim():
    client = httpx.AsyncClient(transport=_ollama_responder(dim=7), base_url="http://x")
    b = OllamaBackend(base_url="http://x", model="m", http_client=client)
    result = await b.test_connection()
    assert result.ok is True
    assert result.detected_dim == 7


@pytest.mark.asyncio
async def test_ollama_test_connection_handles_connect_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("ollama down")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    b = OllamaBackend(base_url="http://x", model="m", http_client=client)
    result = await b.test_connection()
    assert result.ok is False
    assert "connection refused" in result.detail


def test_ollama_requires_base_url():
    with pytest.raises(ValueError, match="base_url"):
        OllamaBackend(base_url="", model="m")


def test_ollama_requires_model():
    with pytest.raises(ValueError, match="model"):
        OllamaBackend(base_url="http://x", model="")


# ---------------------------------------------------------------------------
# FastEmbed backend (Protocol conformance + lazy load)
# ---------------------------------------------------------------------------


def test_fastembed_backend_implements_protocol():
    b = FastEmbedBackend(model_name="nomic-ai/nomic-embed-text-v1.5")
    assert isinstance(b, EmbeddingBackend)
    # Don't actually load the model; just exercise attributes.
    assert b.model_name == "nomic-ai/nomic-embed-text-v1.5"
    assert b.dim == 768  # Nomic default before first inference


def test_fastembed_backend_uses_nomic_prefix_for_query():
    # Spot-check the prefix-builder; running the model is too heavy for unit tests.
    b = FastEmbedBackend(model_name="nomic-ai/nomic-embed-text-v1.5")
    assert b._prefix("hello", is_query=True) == "search_query: hello"
    assert b._prefix("hello", is_query=False) == "search_document: hello"


def test_fastembed_backend_skips_prefix_for_non_nomic_model():
    b = FastEmbedBackend(model_name="other-vendor/some-model")
    assert b._prefix("hello", is_query=True) == "hello"


# ---------------------------------------------------------------------------
# Round-trip via factory + Protocol
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_factory_built_openai_compat_backend_round_trips():
    cfg = {
        "backend": "openai_compat",
        "config": {"base_url": "http://x", "model": "m", "dim": 4},
    }
    b = make_backend(cfg)
    # Swap the client in so we can mock — using the real httpx client
    # would try to reach http://x.
    b._http = httpx.AsyncClient(transport=_openai_responder(dim=4), base_url="http://x")
    assert isinstance(b, EmbeddingBackend)
    vec = await b.embed("hi")
    assert len(vec) == 4


@pytest.mark.asyncio
async def test_connection_test_result_dataclass_shape():
    # `ConnectionTestResult` is the structured return type T3 will surface
    # over the REST API. Lock its field set.
    result = ConnectionTestResult(ok=True, detail="ready", detected_dim=4, latency_ms=12.3)
    assert result.ok is True
    assert result.detected_dim == 4
    assert result.latency_ms == 12.3
    # And the not-ok variant lets detected_dim/latency_ms be None.
    err = ConnectionTestResult(ok=False, detail="oops")
    assert err.detected_dim is None
    assert err.latency_ms is None
