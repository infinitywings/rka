"""LLM availability probing tests."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from rka.config import RKAConfig
from rka.infra import llm as llm_module
from rka.infra.llm import LLMClient


class _FakeResponse:
    def __init__(self, url: str, payload: dict | list, status_code: int = 200):
        self._url = url
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("GET", self._url),
                response=httpx.Response(self.status_code, request=httpx.Request("GET", self._url)),
            )

    def json(self) -> dict | list:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, responses: dict[str, _FakeResponse], *args, **kwargs):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str):
        response = self._responses.get(url)
        if response is None:
            raise AssertionError(f"Unexpected URL {url}")
        return response


@pytest.mark.asyncio
async def test_is_available_uses_model_probe_before_generation(monkeypatch: pytest.MonkeyPatch):
    responses = {
        "http://example.test/api/v0/models": _FakeResponse(
            "http://example.test/api/v0/models",
            {"data": [{"id": "qwen3.5-35b-a3b"}]},
        ),
    }

    monkeypatch.setattr(
        llm_module.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(responses, *args, **kwargs),
    )

    client = LLMClient(
        RKAConfig(
            llm_enabled=True,
            llm_model="openai/qwen3.5-35b-a3b",
            llm_api_base="http://example.test/v1",
        )
    )

    assert await client.is_available() is True
    assert client.available is True


@pytest.mark.asyncio
async def test_is_available_falls_back_to_minimal_completion(monkeypatch: pytest.MonkeyPatch):
    responses = {
        "http://example.test/api/v0/models": _FakeResponse(
            "http://example.test/api/v0/models",
            {"data": [{"id": "different-model"}]},
        ),
    }
    completion_calls: list[dict] = []

    async def fake_acompletion(**kwargs):
        completion_calls.append(kwargs)
        return {"id": "cmpl-test"}

    monkeypatch.setattr(
        llm_module.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(responses, *args, **kwargs),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion),
    )

    client = LLMClient(
        RKAConfig(
            llm_enabled=True,
            llm_model="openai/qwen3.5-35b-a3b",
            llm_api_base="http://example.test/v1",
        )
    )

    assert await client.is_available() is True
    assert client.available is True
    assert completion_calls == [
        {
            "model": "openai/qwen3.5-35b-a3b",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "timeout": 60,
            "api_base": "http://example.test/v1",
            "api_key": "lm-studio",
        }
    ]
