"""An unreachable backend must fail fast, not hold the caller for minutes.

Measured against a black-holed host with `llm_request_timeout=120`:

    as shipped                     227.89s   3 HTTP sends
    + num_retries=0                 75.04s   1 send
    + httpx.Timeout(connect=5.0)    16.27s   3 sends
    + both                           5.04s   1 send

Two separate causes, and neither is the setting that looks responsible:

  * Three sends come from the openai SDK client's own `max_retries=2`
    default, nested inside litellm. `extract()`'s `max_retries` is consumed
    by instructor as a response-validation counter and never reaches the
    HTTP client — 0, 1, 2 and 3 all produce exactly three sends.
  * Passing a bare number as `timeout` replaces openai's whole
    `httpx.Timeout`, connect included, so a budget meant for generation
    became the connect budget as well.
"""

import inspect

import httpx

from rka.config import RKAConfig
from rka.infra import llm as llm_module
from rka.infra.llm import LLMClient


def _kwargs_from(monkeypatch, coro_factory):
    captured: dict = {}

    class _FakeCompletions:
        async def create(self, **kw):
            captured.update(kw)
            raise RuntimeError("stop here; only the kwargs matter")

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeInstructor:
        chat = _FakeChat()

    monkeypatch.setattr(LLMClient, "_get_instructor", lambda self: _FakeInstructor())
    return captured


class TestConnectIsBoundedSeparately:
    def test_the_connect_budget_is_not_the_request_budget(self):
        assert llm_module._CONNECT_TIMEOUT_S == 5.0

    def test_extract_passes_a_split_timeout(self, monkeypatch):
        import asyncio

        from pydantic import BaseModel

        class _R(BaseModel):
            answer: str

        captured = _kwargs_from(monkeypatch, None)
        client = LLMClient(
            RKAConfig(
                llm_enabled=True,
                llm_model="openai/test",
                llm_api_base="http://example.test/v1",
                llm_request_timeout=90,
            )
        )
        try:
            asyncio.run(client.extract(_R, messages=[{"role": "user", "content": "x"}]))
        except Exception:
            pass

        timeout = captured.get("timeout")
        assert isinstance(timeout, httpx.Timeout), (
            "a bare number replaces openai's whole Timeout, connect included, "
            "so an unreachable host holds the call for the full request budget"
        )
        assert timeout.connect == 5.0
        assert timeout.read == 90


class TestConnectionFailuresAreNotRetried:
    def test_extract_pins_the_client_level_retry_count(self):
        src = inspect.getsource(LLMClient.extract)
        assert "num_retries=0" in src, (
            "without num_retries the openai SDK client retries twice more; "
            "a refused connection fails identically each time"
        )

    def test_max_retries_is_not_mistaken_for_the_http_retry_count(self):
        """instructor eats `max_retries`; it never reaches the HTTP client."""
        src = inspect.getsource(LLMClient.extract)
        assert "max_retries=max_retries" in src and "num_retries=0" in src, (
            "both must be present and distinct; collapsing them re-creates the "
            "228s stall while looking like it bounds retries"
        )

    def test_the_health_probe_is_bounded_too(self):
        src = inspect.getsource(LLMClient.is_available)
        assert "num_retries=0" in src
        assert "_CONNECT_TIMEOUT_S" in src
