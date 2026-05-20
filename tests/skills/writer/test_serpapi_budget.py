"""Tests for SerpAPI credit budget tracking (T3 deliverable).

Per mis_01KS2S871YPQ3D5RVY5K3PSQY6 T6 acceptance criteria.
Covers CreditBudget class, SerpAPIBudgetExceededError, env-var override,
and per-project ai_tic_config.yaml overlay (T3 enhancement).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


class TestCreditBudgetBasics:
    """CreditBudget tracks used credits and refuses over-budget calls."""

    def test_default_budget_is_200(self, serpapi_backend) -> None:
        b = serpapi_backend.CreditBudget()
        assert b.budget == 200
        assert b.used == 0
        assert b.remaining == 200

    def test_custom_budget(self, serpapi_backend) -> None:
        b = serpapi_backend.CreditBudget(budget=50)
        assert b.budget == 50
        assert b.remaining == 50

    def test_increment_tracks_usage(self, serpapi_backend) -> None:
        b = serpapi_backend.CreditBudget(budget=5)
        b.increment()
        b.increment(2)
        assert b.used == 3
        assert b.remaining == 2

    def test_increment_beyond_budget_raises(self, serpapi_backend) -> None:
        b = serpapi_backend.CreditBudget(budget=3)
        b.increment(2)
        with pytest.raises(serpapi_backend.SerpAPIBudgetExceededError):
            b.increment(2)
        # Used stays at 2 (the failed increment did not partially consume).
        assert b.used == 2


class TestBudgetResolution:
    """resolve_budget order: project_dir -> SERPAPI_BUDGET env -> DEFAULT_BUDGET."""

    def test_default_no_env_no_project(self, serpapi_backend) -> None:
        os.environ.pop("SERPAPI_BUDGET", None)
        b = serpapi_backend.default_budget_from_env()
        assert b.budget == 200

    def test_env_override(self, serpapi_backend) -> None:
        os.environ["SERPAPI_BUDGET"] = "500"
        try:
            b = serpapi_backend.default_budget_from_env()
            assert b.budget == 500
        finally:
            os.environ.pop("SERPAPI_BUDGET", None)

    def test_project_config_overlay_takes_precedence(
        self, serpapi_backend, tmp_path: Path
    ) -> None:
        # Skip if PyYAML is not installed (graceful degradation per implementation).
        try:
            import yaml  # noqa: F401
        except ImportError:
            return
        (tmp_path / "ai_tic_config.yaml").write_text("serpapi:\n  budget: 750\n")
        os.environ["SERPAPI_BUDGET"] = "500"
        try:
            b = serpapi_backend.resolve_budget(project_dir=tmp_path)
            assert b.budget == 750, "project_dir budget should beat env"
        finally:
            os.environ.pop("SERPAPI_BUDGET", None)

    def test_project_config_absent_falls_back_to_env(
        self, serpapi_backend, tmp_path: Path
    ) -> None:
        os.environ["SERPAPI_BUDGET"] = "333"
        try:
            b = serpapi_backend.resolve_budget(project_dir=tmp_path)
            assert b.budget == 333
        finally:
            os.environ.pop("SERPAPI_BUDGET", None)
