"""Tests for rka.constants.

v2.6+: `DEFAULT_PROJECT_ID` is hardcoded to `SENTINEL_PROJECT_ID`. The
pre-v2.6 `RKA_PROJECT` env-var override was removed because it
reintroduced the silent-default failure mode that v2.6 explicitly
eliminates at the MCP layer (every MCP tool now requires `project_id`
as a kwarg). Non-MCP REST callers that don't pass `X-RKA-Project` or
`?project_id=…` still resolve to `proj_default`.

Filed under the v2.6 `feat/project-id-required` PR. Historical
context for the env-var-aware behavior lives in this file's git
history (mis_01KQN12Z03ZM9C8CDSFMW3WGBJ).

`SENTINEL_PROJECT_ID` remains the immutable "proj_default" used by the
delete guard and the legacy-state fallback.
"""

from __future__ import annotations

import importlib

import pytest


class TestSentinelProjectId:
    """SENTINEL_PROJECT_ID never changes."""

    def test_sentinel_is_proj_default(self):
        from rka.constants import SENTINEL_PROJECT_ID

        assert SENTINEL_PROJECT_ID == "proj_default"

    def test_sentinel_unaffected_by_env_var(self, monkeypatch):
        """RKA_PROJECT env var is no longer read (v2.6+). The sentinel
        stays as `proj_default` regardless of what's in the env."""
        monkeypatch.setenv("RKA_PROJECT", "prj_test_should_not_change_sentinel")
        import rka.constants

        importlib.reload(rka.constants)
        try:
            assert rka.constants.SENTINEL_PROJECT_ID == "proj_default"
        finally:
            monkeypatch.delenv("RKA_PROJECT", raising=False)
            importlib.reload(rka.constants)


class TestDefaultProjectIdIsHardcodedSentinel:
    """v2.6+: DEFAULT_PROJECT_ID is hardcoded to SENTINEL_PROJECT_ID.

    The pre-v2.6 env-var override (RKA_PROJECT → DEFAULT_PROJECT_ID)
    was removed for consistency with the new MCP-layer contract that
    every tool requires `project_id` explicitly.
    """

    def test_default_is_sentinel(self):
        import rka.constants

        assert rka.constants.DEFAULT_PROJECT_ID == "proj_default"
        assert rka.constants.DEFAULT_PROJECT_ID == rka.constants.SENTINEL_PROJECT_ID

    def test_default_ignores_env_var(self, monkeypatch):
        """Setting RKA_PROJECT has no effect — explicitly removed in v2.6
        to eliminate the silent-default failure mode."""
        monkeypatch.setenv("RKA_PROJECT", "prj_test_env_should_be_ignored")
        import rka.constants

        importlib.reload(rka.constants)
        try:
            assert rka.constants.DEFAULT_PROJECT_ID == "proj_default"
            assert rka.constants.DEFAULT_PROJECT_ID != "prj_test_env_should_be_ignored"
        finally:
            monkeypatch.delenv("RKA_PROJECT", raising=False)
            importlib.reload(rka.constants)


class TestApiDepsImportsCanonicalConstant:
    """api/deps.py and services/base.py must import DEFAULT_PROJECT_ID from
    the canonical source (rka.constants), not redeclare it locally."""

    def test_api_deps_imports_default_project_id_from_constants(self):
        from rka.api import deps
        from rka import constants

        assert deps.DEFAULT_PROJECT_ID == constants.DEFAULT_PROJECT_ID

    def test_services_base_imports_default_project_id_from_constants(self):
        from rka.services import base
        from rka import constants

        assert base.DEFAULT_PROJECT_ID == constants.DEFAULT_PROJECT_ID

    def test_get_project_id_falls_back_to_default(self):
        """When neither header nor query param is provided, get_project_id
        returns DEFAULT_PROJECT_ID (= 'proj_default')."""
        from rka.api.deps import get_project_id, DEFAULT_PROJECT_ID

        result = get_project_id(x_rka_project=None, project_id=None)
        assert result == DEFAULT_PROJECT_ID

    def test_get_project_id_prefers_header(self):
        from rka.api.deps import get_project_id

        result = get_project_id(x_rka_project="prj_from_header", project_id="prj_from_query")
        assert result == "prj_from_header"

    def test_get_project_id_falls_back_to_query(self):
        from rka.api.deps import get_project_id

        result = get_project_id(x_rka_project=None, project_id="prj_from_query")
        assert result == "prj_from_query"


class TestProjectServiceDeleteGuardUsesSentinel:
    """delete_project must always refuse to delete `proj_default`. The
    guard uses SENTINEL_PROJECT_ID directly (which is identical to
    DEFAULT_PROJECT_ID in v2.6+ but kept as a separate symbol for
    clarity at call sites)."""

    @pytest.mark.asyncio
    async def test_delete_proj_default_is_refused(self, db):
        from rka.services.project import ProjectService

        svc = ProjectService(db)
        with pytest.raises(ValueError, match="Cannot delete the default project"):
            await svc.delete_project("proj_default", confirm=True)
