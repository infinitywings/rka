"""Loader for the curated tool registry (Phase D, Q3 ratification).

Provides high-confidence priors for `research_toolkit_node` before it
augments with SerpAPI web search. The registry is a small YAML catalog
at `orchestrator/data/tool_registry.yaml` — see that file for the
canonical schema and entries.

Two consumers:
  1. `research_toolkit_node` reads the registry to seed its candidate
     list before web-searching for gaps.
  2. Tests + tooling can introspect what defaults the orchestrator
     would offer for a given domain.

YAML dependency: this module uses PyYAML if available, falling back to
a structural JSON-style parse for the few cases where PyYAML isn't on
PATH (CI containers without PyYAML, etc.). To keep dependencies light,
we don't add PyYAML to orchestrator/pyproject.toml — we depend on the
host environment having it for now.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from orchestrator.manifest import SecretDecl, ToolDecl

logger = logging.getLogger(__name__)


REGISTRY_PATH = (
    Path(__file__).resolve().parent / "data" / "tool_registry.yaml"
)


def _load_yaml(text: str) -> dict:
    """Load YAML text into a Python dict.

    Tries PyYAML first; if unavailable, raises ImportError with a clear
    message. We don't ship a hand-rolled YAML parser — research projects
    that need the registry will install PyYAML, and CI fixtures can
    monkeypatch `load_registry` directly to skip YAML loading.
    """
    try:
        import yaml  # type: ignore
    except ImportError as e:
        raise ImportError(
            "PyYAML is required to load the orchestrator tool registry. "
            "Install with `pip install pyyaml` (already a transitive dep of "
            "claude-agent-sdk in the orchestrator container)."
        ) from e
    return yaml.safe_load(text) or {}


def load_registry(
    path: Optional[Path] = None,
) -> dict:
    """Read the registry YAML and return the parsed structure.

    Returns the raw nested dict with keys `always_on` and `by_domain`.
    Callers typically use the higher-level helpers below
    (`always_on_tools`, `tools_for_domain`) which return ToolDecl
    objects rather than raw dicts.

    Raises FileNotFoundError if the registry file is missing (a
    deployment error — the registry ships as package data).
    """
    p = path or REGISTRY_PATH
    if not p.is_file():
        raise FileNotFoundError(f"tool registry not found at {p}")
    return _load_yaml(p.read_text(encoding="utf-8"))


def _to_tool_decl(entry: dict, *, source: str = "registry") -> ToolDecl:
    """Convert a raw registry entry dict into a ToolDecl."""
    secrets_raw = entry.get("secrets") or []
    secrets = [SecretDecl(**s) for s in secrets_raw]
    return ToolDecl(
        name=entry["name"],
        type=entry.get("type", "mcp_stdio"),
        command=entry.get("command"),
        args=list(entry.get("args") or []),
        install_hint=entry.get("install_hint"),
        secrets=secrets,
        always_on=bool(entry.get("always_on", False)),
        rationale=(entry.get("rationale") or "").strip() or None,
        source=source,
    )


def always_on_tools(*, path: Optional[Path] = None) -> list[ToolDecl]:
    """Return the canonical always-on tool list from the registry.

    Every project's baseline manifest should include these (PI can
    opt-out individual entries at pi_toolkit_ratify if not relevant).
    """
    reg = load_registry(path=path)
    entries = reg.get("always_on") or []
    return [_to_tool_decl(e, source="registry") for e in entries]


def tools_for_domain(
    domain: str, *, path: Optional[Path] = None
) -> list[ToolDecl]:
    """Return the registry-suggested tools for one domain.

    `domain` matches a key under `by_domain` in the registry (e.g.,
    `finance`, `bioinformatics`, `ml_systems`, `legal`,
    `natural_sciences`). Returns [] for unknown domains.
    """
    reg = load_registry(path=path)
    domain_block = (reg.get("by_domain") or {}).get(domain) or {}
    entries = domain_block.get("tools") or []
    return [_to_tool_decl(e, source="registry") for e in entries]


def list_domains(*, path: Optional[Path] = None) -> dict[str, str]:
    """Return a {domain_key: description} map of every domain shortlist
    in the registry. Used by `research_toolkit_node` to let the Brain
    decide which domains apply to the project's topic.
    """
    reg = load_registry(path=path)
    by_domain = reg.get("by_domain") or {}
    return {k: (v.get("description") or "").strip() for k, v in by_domain.items()}


def find_tool_by_name(
    name: str, *, path: Optional[Path] = None
) -> Optional[ToolDecl]:
    """Look up a single tool by name across the entire registry
    (always-on baseline + every by_domain section).

    Used by the mid-stream manifest-extension flow (v2.6.0+agentic.4):
    `orchestrator_extend_manifest(project_id, tool_name)` calls this
    to resolve a registry-known tool spec into a `ToolDecl` it can
    append to the project's existing manifest.

    Returns None when no tool with that name exists in any section.
    Matching is case-sensitive (mirrors the rest of the registry
    surface: `always_on_tools()` / `tools_for_domain()` both return
    case-sensitive names).
    """
    reg = load_registry(path=path)
    for entry in reg.get("always_on") or []:
        if entry.get("name") == name:
            return _to_tool_decl(entry, source="registry")
    for _domain_key, domain_block in (reg.get("by_domain") or {}).items():
        for entry in domain_block.get("tools") or []:
            if entry.get("name") == name:
                return _to_tool_decl(entry, source="registry")
    return None
