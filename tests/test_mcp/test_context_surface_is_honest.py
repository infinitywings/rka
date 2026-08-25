"""The advertised `context` surface must match what the dispatcher reads.

`depth` was removed from the context engine in #107 because it cost 226s to
return byte-identical output. The removal left three doc surfaces still
naming it and one preserved legacy body still building it into the request,
and it orphaned `options` — which existed only to carry `depth`, so after the
removal nothing in `dispatch_query` read it at all.

An advertised parameter that nothing reads is worse than a missing one: a
caller passes it, sees a normal 200, and believes it took effect.
"""

import inspect
import json
import re

import pytest

from rka.mcp import operations_schema as schema_module
from rka.mcp import verb_dispatch
from rka.mcp.operation_args import QueryContextArgs


def _context_branch_source() -> str:
    """The body of `if scope == "context":` inside dispatch_query."""
    src = inspect.getsource(verb_dispatch.dispatch_query)
    m = re.search(r'if scope == "context":\n(.*?)(?=\n    if scope|\n    # )', src, re.S)
    assert m, "could not locate the context branch in dispatch_query"
    return m.group(1)


class TestNothingAdvertisesDepth:
    def test_the_operation_schema_does_not_name_depth(self):
        entry = json.dumps(schema_module.OPERATIONS_SCHEMA["context"])
        assert "depth" not in entry, (
            "rka_describe('context') still advertises `depth`; the typed model "
            "rejects it with extra_forbidden, so the docs teach a call that fails"
        )

    def test_the_typed_model_does_not_name_depth(self):
        blob = json.dumps(QueryContextArgs.model_json_schema())
        assert "depth" not in blob

    def test_the_preserved_legacy_body_does_not_build_depth(self):
        from rka.mcp import server

        src = inspect.getsource(server._rka_query_legacy_impl)
        branch = re.search(r'if s == "context":\n(.*?)\n    if s ==', src, re.S)
        assert branch, "could not locate the context branch in the legacy impl"
        assert "depth" not in branch.group(1)


def _local_aliases() -> dict[str, str]:
    """dispatch_query rebinds its dict params: `f = filters or {}`.

    Resolve those so a branch reading `f.get(...)` counts as consuming
    `filters`. Without this the check produces false positives on every
    aliased parameter.
    """
    src = inspect.getsource(verb_dispatch.dispatch_query)
    return {
        param: local
        for local, param in re.findall(r"^    (\w+) = (\w+) or \{\}$", src, re.M)
    }


class TestNoAdvertisedParameterIsInert:
    """Forwarding is not consuming.

    `options` survived #107 because `dispatch_query_typed` still forwarded it
    while the context branch had stopped reading it. Any check that accepts
    forwarding as evidence misses exactly this case, so this one looks only at
    the branch that has to act on the value.
    """

    def test_every_advertised_field_is_consumed_by_the_context_branch(self):
        branch = _context_branch_source()
        aliases = _local_aliases()

        advertised = set(QueryContextArgs.model_fields) - {"operation", "project_id"}
        assert advertised, "guard against the set silently becoming empty"

        def _used(name: str) -> bool:
            # Word boundaries matter: the alias for `options` is the single
            # character `o`, which substring-matches "topic", "or" and
            # "project_id" in any branch body.
            return bool(re.search(rf"\b{re.escape(name)}\b", branch))

        unread = sorted(
            f for f in advertised
            if not _used(f) and not _used(aliases.get(f, "\0"))
        )
        assert not unread, (
            f"QueryContextArgs advertises {unread}, which the context dispatch "
            "branch never reads. A caller passing it gets a normal 200 and no "
            "effect — advertise it only once something consumes it."
        )

    def test_options_is_gone_from_the_query_dispatcher(self):
        assert "options" not in inspect.signature(verb_dispatch.dispatch_query).parameters, (
            "dispatch_query still takes `options`; no read scope consumes it"
        )

    def test_no_read_scope_consumes_options(self):
        """Not just context — `options` was read exactly once, for depth."""
        src = inspect.getsource(verb_dispatch.dispatch_query)
        assert not re.search(r"\bo\.get\(|\bo\[", src), (
            "something reads a local `o` again; if a scope needs options, "
            "restore the parameter and update this test"
        )


@pytest.mark.asyncio
async def test_context_still_dispatches(monkeypatch):
    """Removal must not break the operation itself."""
    seen = {}

    async def _fake(**kw):
        seen.update(kw)
        return {"entries": [], "sources": []}

    monkeypatch.setattr(verb_dispatch, "_legacy", lambda name: _fake)
    await verb_dispatch.dispatch_query(
        "context", project_id="prj_x", query="topic", filters={"phase": "p"},
    )
    assert seen == {"topic": "topic", "phase": "p", "project_id": "prj_x"}
