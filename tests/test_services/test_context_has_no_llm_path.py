"""Building context must not touch a language model.

`context` is step one of the documented session start, and everything it does
is local: it ranks entries by `journal.importance`, `entity_links` centrality
and recency. One branch was the exception — `depth="detailed"` asked an LLM for
a narrative paragraph.

That branch was pure cost. Measured against a live instance whose configured
LLM host was unreachable:

    depth=summary     0.07s   182,719 bytes
    depth=detailed  226.35s   182,719 bytes   (byte-identical)

Three and a half thousand times slower for the same bytes, because the failure
is caught and logged at debug. Callers saw a timeout, or an identical answer
after four minutes, and no indication the narrative had been attempted at all.

`depth` also read as a verbosity control and was not one — it only chose
whether to append the narrative. A Brain agent hitting the payload-size limit
retried with `depth="summary"` to shrink it, which by construction could not
work.
"""

from __future__ import annotations

import inspect

import pytest

from rka.services import context as context_module
from rka.services.context import ContextEngine


class TestNoLanguageModelInTheContextPath:
    def test_the_engine_never_calls_an_llm(self):
        source = inspect.getsource(context_module)
        offenders = [
            line.strip()
            for line in source.splitlines()
            if "self.llm." in line and not line.strip().startswith("#")
        ]
        assert not offenders, (
            "context is a local ranking operation; an LLM call here makes it "
            f"fail or hang on an unrelated backend: {offenders}"
        )

    def test_the_render_cap_is_a_local_constant(self):
        """It used to be read off the LLM client, so a purely local rendering
        decision changed depending on whether a model was configured."""
        assert context_module._EVIDENCE_BLOCK_LIMIT == 400

    def test_narrative_generation_is_gone(self):
        assert "produce_narrative" not in inspect.getsource(context_module)


class TestDepthIsGone:
    """It named a choice that only ever meant "also call an LLM"."""

    def test_the_engine_signature_has_no_depth(self):
        assert "depth" not in inspect.signature(ContextEngine.get_context).parameters

    def test_the_request_model_has_no_depth(self):
        from rka.models.context import ContextRequest

        assert "depth" not in ContextRequest.model_fields

    def test_the_operation_advertises_no_depth_enum(self):
        from rka.mcp.operations_schema import OPERATIONS_SCHEMA

        assert "depth" not in (OPERATIONS_SCHEMA["context"].get("enums") or {})

    def test_no_example_passes_depth(self):
        from rka.mcp.operations_schema import OPERATIONS_SCHEMA

        for example in OPERATIONS_SCHEMA["context"]["examples"]:
            assert "depth" not in (example["call"].get("options") or {})


class TestContextStillWorks:
    """Removing the branch must not remove the operation."""

    @pytest.mark.asyncio
    async def test_it_returns_a_package_without_an_llm(self, db):
        from rka.services.search import SearchService

        engine = ContextEngine(db=db, search=SearchService(db=db, embeddings=None), llm=None)
        package = await engine.get_context(project_id="proj_default")
        assert package.entries is not None
        assert package.note

    @pytest.mark.asyncio
    async def test_an_engine_handed_an_llm_still_ignores_it(self, db):
        """Nothing should reach the model even if one is wired in."""
        from rka.services.search import SearchService

        class ExplodingLLM:
            def __getattr__(self, name):
                raise AssertionError(f"context reached the LLM: {name}")

        engine = ContextEngine(
            db=db, search=SearchService(db=db, embeddings=None), llm=ExplodingLLM()
        )
        await engine.get_context(project_id="proj_default")
