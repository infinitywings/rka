"""No literal route may be shadowed by an earlier parameterised one.

FastAPI matches in registration order, so `/decisions/{dec_id}` registered
before `/decisions/mermaid` answers the latter with "Decision mermaid not
found". It is a silent class of bug: the route exists, appears in OpenAPI, and
returns a plausible 404 that reads like missing data rather than a missing
route.

Two instances have shipped — `/decisions/orphan-supersedes` (caught only when
someone called it) and `/decisions/mermaid` (found by sweeping every literal
GET). `decisions.py` carries a NOTE about the ordering requirement, which was
not enough on its own: the second instance was declared in a different module
whose router is included later, so the file-local convention could not see it.

This test checks the assembled application, which is where the ordering
actually resolves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rka.api.app import create_app
from rka.config import RKAConfig


def _routes(app) -> list[tuple[str, set[str]]]:
    """Every (path, methods) pair in registration order.

    Two shapes to handle. Up to FastAPI 0.135 `include_router` flattens its
    routes into the parent. From 0.141 it inserts an `_IncludedRouter` that
    keeps the sub-router intact and carries the prefix on an include context,
    so a walker that only follows `.routes` sees five top-level routes and
    nothing else — which is why `test_the_route_table_is_readable` exists.
    """
    found: list[tuple[str, set[str]]] = []

    def children(route):
        """(sub-routes, prefix) for a route that contains other routes."""
        included = getattr(route, "original_router", None)
        if included is not None:
            context = getattr(route, "include_context", None)
            return getattr(included, "routes", None), getattr(context, "prefix", "") or ""
        nested = getattr(route, "routes", None)
        if nested:
            return nested, getattr(route, "path", "") or ""
        return None, ""

    def walk(routes, prefix: str = "") -> None:
        for route in routes or []:
            sub, sub_prefix = children(route)
            if sub:
                walk(sub, prefix + sub_prefix)
                continue
            path = getattr(route, "path", "") or ""
            methods = getattr(route, "methods", None)
            if path and methods:
                found.append((prefix + path, set(methods)))

    walk(getattr(app.router, "routes", []))
    return found


def _segments(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/") if s]


def _is_param(segment: str) -> bool:
    return segment.startswith("{") and segment.endswith("}")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    return create_app(
        RKAConfig(
            project_dir=tmp_path_factory.mktemp("routes"),
            db_path=Path("routes.db"),
            llm_enabled=False,
            embeddings_enabled=False,
        )
    )


def test_the_route_table_is_readable(app):
    """Guards the test itself: a traversal that finds nothing proves nothing."""
    routes = _routes(app)
    assert len(routes) > 100, f"only {len(routes)} routes found — traversal is wrong"
    assert any(p == "/api/health" for p, _ in routes)


def test_no_literal_route_is_shadowed(app):
    routes = _routes(app)
    shadowed: list[str] = []

    for index, (path, methods) in enumerate(routes):
        segments = _segments(path)
        if any(_is_param(s) for s in segments):
            continue  # only literal paths can be shadowed
        for earlier_index in range(index):
            earlier, earlier_methods = routes[earlier_index]
            earlier_segments = _segments(earlier)
            if len(earlier_segments) != len(segments):
                continue
            if not methods & earlier_methods:
                continue
            if not any(_is_param(s) for s in earlier_segments):
                continue
            if all(
                _is_param(a) or a == b
                for a, b in zip(earlier_segments, segments)
            ):
                shadowed.append(
                    f"{sorted(methods)} {path} is matched first by {earlier} "
                    f"(registered at #{earlier_index}, this at #{index})"
                )
                break

    assert not shadowed, "literal routes unreachable behind a parameterised route:\n  " + "\n  ".join(shadowed)
