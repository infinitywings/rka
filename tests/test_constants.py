"""Regression tests for rka.constants — env-var-aware DEFAULT_PROJECT_ID.

Filed under mis_01KQN12Z03ZM9C8CDSFMW3WGBJ (Layer A of the wrong-project fix
bundle). Probe trail: jrn-driven by mis_01KQN0BJ96PJYYA50WNCC1PQAK.

Prior to the fix, DEFAULT_PROJECT_ID was hardcoded as the literal "proj_default"
in three places (api/deps.py:42, services/base.py:18, services/project.py:15).
Setting RKA_PROJECT in the environment had no effect on the server-side
resolution chain, only on the MCP `_session.project_id` default. Symptom: a
fresh MCP session without an explicit `rka_set_project` would silently route
writes to `proj_default`.

After the fix, all three sites import from `rka.constants`, which reads
`RKA_PROJECT` at module import. With `RKA_PROJECT=prj_X` set, the API-side
fallback resolves to `prj_X` instead of `proj_default`, so writes that omit
`X-RKA-Project` land in `prj_X`.

`SENTINEL_PROJECT_ID` remains the immutable "proj_default" used by the
delete guard and the legacy-state fallback.
"""

from __future__ import annotations

import importlib

import pytest


class TestSentinelProjectId:
    """SENTINEL_PROJECT_ID never changes based on environment."""

    def test_sentinel_is_proj_default(self):
        from rka.constants import SENTINEL_PROJECT_ID

        assert SENTINEL_PROJECT_ID == "proj_default"

    def test_sentinel_unaffected_by_env_var(self, monkeypatch):
        monkeypatch.setenv("RKA_PROJECT", "prj_test_should_not_change_sentinel")
        import rka.constants

        importlib.reload(rka.constants)
        try:
            assert rka.constants.SENTINEL_PROJECT_ID == "proj_default"
        finally:
            monkeypatch.delenv("RKA_PROJECT", raising=False)
            importlib.reload(rka.constants)


class TestDefaultProjectIdEnvVar:
    """DEFAULT_PROJECT_ID reads RKA_PROJECT at module import."""

    def test_default_is_sentinel_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("RKA_PROJECT", raising=False)
        import rka.constants

        importlib.reload(rka.constants)
        try:
            assert rka.constants.DEFAULT_PROJECT_ID == "proj_default"
            assert rka.constants.DEFAULT_PROJECT_ID == rka.constants.SENTINEL_PROJECT_ID
        finally:
            importlib.reload(rka.constants)

    def test_default_resolves_to_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("RKA_PROJECT", "prj_test_env_redirect")
        import rka.constants

        importlib.reload(rka.constants)
        try:
            assert rka.constants.DEFAULT_PROJECT_ID == "prj_test_env_redirect"
            assert rka.constants.DEFAULT_PROJECT_ID != rka.constants.SENTINEL_PROJECT_ID
        finally:
            monkeypatch.delenv("RKA_PROJECT", raising=False)
            importlib.reload(rka.constants)

    def test_default_strips_whitespace(self, monkeypatch):
        """Whitespace in the env var is normalized."""
        monkeypatch.setenv("RKA_PROJECT", "  prj_padded  ")
        import rka.constants

        importlib.reload(rka.constants)
        try:
            assert rka.constants.DEFAULT_PROJECT_ID == "prj_padded"
        finally:
            monkeypatch.delenv("RKA_PROJECT", raising=False)
            importlib.reload(rka.constants)

    def test_default_falls_back_when_env_var_is_empty_string(self, monkeypatch):
        """RKA_PROJECT='' must not produce an empty project id; falls through to sentinel."""
        monkeypatch.setenv("RKA_PROJECT", "")
        import rka.constants

        importlib.reload(rka.constants)
        try:
            assert rka.constants.DEFAULT_PROJECT_ID == "proj_default"
        finally:
            monkeypatch.delenv("RKA_PROJECT", raising=False)
            importlib.reload(rka.constants)

    def test_default_falls_back_when_env_var_is_only_whitespace(self, monkeypatch):
        """RKA_PROJECT='   ' must not produce an empty project id."""
        monkeypatch.setenv("RKA_PROJECT", "   ")
        import rka.constants

        importlib.reload(rka.constants)
        try:
            assert rka.constants.DEFAULT_PROJECT_ID == "proj_default"
        finally:
            monkeypatch.delenv("RKA_PROJECT", raising=False)
            importlib.reload(rka.constants)


class TestApiDepsImportsCanonicalConstant:
    """api/deps.py and services/base.py must import DEFAULT_PROJECT_ID from
    the canonical source (rka.constants), not redeclare it locally. Pre-fix,
    the literal `"proj_default"` was duplicated in three files; the duplication
    is the regression vector."""

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
        returns DEFAULT_PROJECT_ID."""
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
    """delete_project must always refuse to delete `proj_default` regardless of
    whether RKA_PROJECT is set. The guard uses SENTINEL_PROJECT_ID, not the
    env-var-aware DEFAULT_PROJECT_ID, to preserve the never-delete invariant."""

    async def test_delete_proj_default_is_refused(self, db):
        from rka.services.project import ProjectService

        svc = ProjectService(db)
        with pytest.raises(ValueError, match="Cannot delete the default project"):
            await svc.delete_project("proj_default", confirm=True)

    async def test_delete_proj_default_refused_even_when_env_var_set(
        self, db, monkeypatch
    ):
        """Even with RKA_PROJECT=prj_X redirecting DEFAULT_PROJECT_ID, the
        delete guard still refuses proj_default — sentinel semantics."""
        monkeypatch.setenv("RKA_PROJECT", "prj_test_env_should_not_unlock_delete")
        import rka.constants
        import rka.services.project

        importlib.reload(rka.constants)
        importlib.reload(rka.services.project)
        try:
            svc = rka.services.project.ProjectService(db)
            with pytest.raises(ValueError, match="Cannot delete the default project"):
                await svc.delete_project("proj_default", confirm=True)
        finally:
            monkeypatch.delenv("RKA_PROJECT", raising=False)
            importlib.reload(rka.constants)
            importlib.reload(rka.services.project)
