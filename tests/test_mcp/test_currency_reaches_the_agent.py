"""Two gaps between a fix landing and an agent being able to see it.

`/api/search` returns `status`, `superseded_by` and `stale` per hit. The MCP
`rka_search` tool renders hits as lines of text and emitted only type, id,
title and snippet — the fields arrived and were dropped. Agents read the
rendered text, not the JSON, so the currency signal did not reach the only
consumer that needed it: a superseded decision printed identically to the
decision that replaced it.

`orphan_supersedes` was registered in the scope->tool map and listed in the
operations index, but had no branch in the dispatch chain. It resolved to a
tool name and then fell through to `invalid_scope` — advertised and uncallable.

The second class is the more dangerous one, so it gets a general test rather
than a single case: every scope the index advertises must actually dispatch.
"""

from __future__ import annotations

import inspect
import re

import pytest

from rka.mcp import verb_dispatch
from rka.mcp.server import _currency_marker


class TestCurrencyMarker:
    def test_superseded_by_is_named_so_the_reader_can_follow_it(self):
        marker = _currency_marker({"superseded_by": "dec_01NEW", "status": "superseded"})
        assert "SUPERSEDED" in marker
        assert "dec_01NEW" in marker

    def test_superseded_without_a_successor_still_warns(self):
        """An orphaned chain has no pointer, but is still not current."""
        marker = _currency_marker({"status": "superseded", "superseded_by": None})
        assert "SUPERSEDED" in marker

    @pytest.mark.parametrize("status", ["retracted", "abandoned"])
    def test_other_dead_states_warn(self, status):
        assert status.upper() in _currency_marker({"status": status})

    def test_stale_warns_when_status_is_otherwise_fine(self):
        assert "STALE" in _currency_marker({"status": "active", "stale": True})

    @pytest.mark.parametrize(
        "hit",
        [
            {},
            {"status": "active"},
            {"status": "active", "stale": False, "superseded_by": None},
            {"status": "to_read"},
        ],
    )
    def test_current_hits_are_unmarked(self, hit):
        """Marking everything is the same as marking nothing."""
        assert _currency_marker(hit) == ""

    def test_status_case_and_padding_do_not_hide_a_dead_hit(self):
        assert "SUPERSEDED" in _currency_marker({"status": "  Superseded  "})


class TestSearchRenderingCarriesTheMarker:
    def test_the_render_calls_the_marker(self):
        """Pins the wiring: the marker existing is not the same as it being used."""
        from rka.mcp import server

        source = inspect.getsource(server.rka_search)
        assert "_currency_marker" in source

    def test_the_marker_is_on_the_header_line_not_the_snippet(self):
        """A snippet is truncated; a reader skimming ids must still see it."""
        from rka.mcp import server

        source = inspect.getsource(server.rka_search)
        header = re.search(r"lines\.append\(\s*\n?\s*f\"\[\{res\['entity_type'\]\}\].*?\)", source, re.S)
        assert header and "_currency_marker" in header.group(0)


class TestEveryAdvertisedScopeDispatches:
    """The general form of the `orphan_supersedes` bug.

    A scope can be listed in the operations index and mapped to a legacy tool
    and still have no branch in the dispatch chain, in which case it falls
    through to `invalid_scope`. Nothing caught that, because each layer was
    individually consistent.
    """

    @staticmethod
    def _dispatch_source() -> str:
        return inspect.getsource(verb_dispatch.dispatch_query)

    def test_every_mapped_scope_has_a_dispatch_branch(self):
        source = self._dispatch_source()
        missing = [
            scope
            for scope in verb_dispatch._QUERY_DISPATCH
            if f'scope == "{scope}"' not in source and f'"{scope}"' not in source
        ]
        assert not missing, (
            "scopes mapped to a tool but never matched in dispatch_query — "
            f"they resolve to invalid_scope: {missing}"
        )

    def test_orphan_supersedes_specifically(self):
        """The instance that surfaced this."""
        assert "orphan_supersedes" in verb_dispatch._QUERY_DISPATCH
        assert 'scope == "orphan_supersedes"' in self._dispatch_source()
