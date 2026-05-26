"""SerpAPI backend with credit budget tracking.

Phase 2 per dec_01KS0AXXASJ5GXV7M0SS39Y066 (SerpAPI tertiary policy):
  - Stage E.serpapi: google_scholar_author_search (third-source disambiguation
                     on AUTHOR_MISMATCH or LOW_CONFIDENCE).
  - Stage G:         google_scholar_search (niche-citation rescue before
                     marking HALLUCINATED).

Credit budget default: 200 searches per manuscript (configurable via
SERPAPI_BUDGET env). Budget exhaustion raises SerpAPIBudgetExceededError;
the caller decides how to handle (typically: mark HALLUCINATED with
note='budget-exceeded').

Graceful degradation: when SERPAPI_API_KEY env var is absent or the serpapi
package is not installed, is_available() returns False and all functions
return None / []. The validation pipeline then falls back to non-SerpAPI
paths (Stage E stays AUTHOR_MISMATCH; Stage G marks HALLUCINATED with
note='no-serpapi-budget').

Per Brain ratification 2026-05-20: PyPI package name is `serpapi` (not
"serpapi-python" as the original spec wording said). Pin: serpapi >= 1.0.2.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

try:
    import serpapi  # type: ignore
    _AVAILABLE = True
except ImportError:
    serpapi = None  # type: ignore
    _AVAILABLE = False


DEFAULT_BUDGET = 200


class SerpAPIBudgetExceededError(RuntimeError):
    """Raised when a SerpAPI call would push usage past the credit budget."""


@dataclass
class CreditBudget:
    """Tracks SerpAPI credit usage against a per-manuscript budget.

    The budget is consulted before each external SerpAPI call. Tests can
    inject a fresh CreditBudget per scenario; production code constructs
    one per manuscript-validation run and threads it through Stage E.serpapi
    and Stage G.
    """

    budget: int = DEFAULT_BUDGET
    used: int = 0

    def increment(self, amount: int = 1) -> None:
        if self.used + amount > self.budget:
            raise SerpAPIBudgetExceededError(
                f"SerpAPI budget exceeded: would use {self.used + amount} of {self.budget}"
            )
        self.used += amount

    @property
    def remaining(self) -> int:
        return self.budget - self.used

    def to_dict(self) -> dict[str, int]:
        return {"budget": self.budget, "used": self.used, "remaining": self.remaining}


def is_available() -> bool:
    """Return True only when both the serpapi package AND an API key are present."""
    if not _AVAILABLE:
        return False
    return bool(os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERPAPI_KEY"))


def _api_key() -> str | None:
    return os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERPAPI_KEY")


def _client():
    if not _AVAILABLE:
        raise ImportError("serpapi not installed.")
    key = _api_key()
    if not key:
        raise RuntimeError(
            "SERPAPI_API_KEY env var not set; caller should check is_available() first."
        )
    return serpapi.Client(api_key=key)


def default_budget_from_env() -> CreditBudget:
    """Construct a CreditBudget with budget pulled from SERPAPI_BUDGET if set."""
    try:
        budget = int(os.environ.get("SERPAPI_BUDGET", str(DEFAULT_BUDGET)))
    except ValueError:
        budget = DEFAULT_BUDGET
    return CreditBudget(budget=budget)


def budget_from_project_config(project_dir) -> CreditBudget | None:
    """Read per-project SerpAPI budget from ai_tic_config.yaml if present.

    Per dec_01KS2S22VV5P5SWWXNBXQDHMGX (Phase 2 scope): the SerpAPI credit
    budget is configurable via the SERPAPI_BUDGET env var OR a per-project
    ai_tic_config.yaml overlay. The YAML schema for the overlay is:

        # ai_tic_config.yaml (in a manuscripts/<project>/<venue>/ directory)
        serpapi:
          budget: 500

    Resolution order (caller chooses):
        1. Per-project ai_tic_config.yaml (this function)
        2. SERPAPI_BUDGET env var (default_budget_from_env)
        3. DEFAULT_BUDGET constant (200)

    Args:
        project_dir: Path-like pointing at a manuscript working directory
            (must contain ai_tic_config.yaml).

    Returns:
        CreditBudget configured from project YAML, or None if no override
        was found (caller falls back to env or default).
    """
    from pathlib import Path

    project_path = Path(project_dir)
    config_path = project_path / "ai_tic_config.yaml"
    if not config_path.exists():
        return None
    try:
        import yaml  # type: ignore
    except ImportError:
        # PyYAML is not a hard dep; project-config overlay degrades gracefully.
        return None
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    serpapi_section = (config or {}).get("serpapi") or {}
    raw_budget = serpapi_section.get("budget")
    if raw_budget is None:
        return None
    try:
        budget = int(raw_budget)
    except (TypeError, ValueError):
        return None
    return CreditBudget(budget=budget)


def resolve_budget(project_dir=None) -> CreditBudget:
    """Resolve a CreditBudget using the documented overlay order.

    Order: per-project ai_tic_config.yaml -> SERPAPI_BUDGET env -> DEFAULT_BUDGET.
    """
    if project_dir is not None:
        per_project = budget_from_project_config(project_dir)
        if per_project is not None:
            return per_project
    return default_budget_from_env()


def google_scholar_search(
    query: str,
    budget: CreditBudget,
) -> list[dict[str, Any]]:
    """Stage G niche-rescue: one Google Scholar lookup before HALLUCINATED.

    Returns the organic_results list (possibly empty) or [] on absence /
    error. Mutates budget.used (raises SerpAPIBudgetExceededError if budget
    would be exceeded).
    """
    if not is_available():
        return []
    budget.increment()
    try:
        client = _client()
        results = client.search({"engine": "google_scholar", "q": query})
        if hasattr(results, "as_dict"):
            results = results.as_dict()
        return results.get("organic_results", []) or []
    except Exception:
        return []


def google_scholar_author_search(
    name: str,
    budget: CreditBudget,
    affiliation_hints: list[str] | None = None,
) -> dict[str, Any] | None:
    """Stage E.serpapi: author profile lookup on AUTHOR_MISMATCH or LOW_CONFIDENCE.

    Returns the top-matching author profile or None on absence / error.
    """
    if not is_available():
        return None
    budget.increment()
    try:
        client = _client()
        results = client.search({"engine": "google_scholar_profiles", "mauthors": name})
        if hasattr(results, "as_dict"):
            results = results.as_dict()
        profiles = results.get("profiles", []) or []
        if not profiles:
            return None
        if affiliation_hints:
            hints_lower = [h.lower() for h in affiliation_hints]
            for p in profiles:
                aff = (p.get("affiliations") or "").lower()
                if any(h in aff for h in hints_lower):
                    return p
        return profiles[0]
    except Exception:
        return None
