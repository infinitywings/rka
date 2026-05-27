"""Phase B (Bootstrap) - orchestrator-level credential onboarding.

Phase D (existing) handles per-project tool credentials and writes
`~/rka-projects/<id>/.env`. Phase B handles the prerequisite step:
the orchestrator daemon's own credentials, written to
`orchestrator/.env`. A fresh install can't run Phase D until the
orchestrator can call Claude at all.

This module is pure logic - no LangGraph, no MCP. The Phase B nodes
in `nodes/bootstrap.py` and `nodes/pi.py` call into here.

Surfaces:
  - load_catalog()                      -> list[BootstrapEntry]
  - propose_for_intent(intent, catalog) -> list[BootstrapEntry]
  - render_env_template(entries, ...)   -> str
  - read_env_file(path)                 -> dict[str, str]
  - verify_filled(entries, env_values)  -> list[VerifyResult]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

CATALOG_PATH = Path(__file__).resolve().parent / "data" / "bootstrap_catalog.yaml"
SCHEMA_VERSION = "v1"

# Default orchestrator/.env location. Resolved relative to the orchestrator
# package install dir's parent so editable installs and uv-tool installs
# both land in the same place. Overridable per call.
DEFAULT_ENV_PATH = (
    Path(__file__).resolve().parent.parent / ".env"
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BootstrapProbe:
    """Validation metadata for one catalog entry."""
    method: str = "skip"           # GET | HEAD | skip
    url: str = ""
    auth_header: str = ""          # template with `{value}`; empty if no header auth
    extra_headers: dict[str, str] = field(default_factory=dict)
    reason: str = ""               # populated when method == "skip"


@dataclass
class BootstrapEntry:
    """One orchestrator-level credential the bootstrap can offer."""
    id: str
    label: str
    purpose: str
    env_var: str
    target_file: str
    criticality: str               # required | recommended | optional
    group: Optional[str] = None    # mutually-exclusive grouping
    signup_url: str = ""
    format_hint: str = ""
    probe: BootstrapProbe = field(default_factory=BootstrapProbe)


@dataclass
class VerifyResult:
    """Outcome of probing one entry post-fill."""
    entry_id: str
    env_var: str
    classification: str            # valid | rejected | missing | unreachable | deferred | skipped
    detail: str = ""


# ---------------------------------------------------------------------------
# Catalog loader
# ---------------------------------------------------------------------------


class BootstrapCatalogError(ValueError):
    """Raised when bootstrap_catalog.yaml is malformed."""


def load_catalog(path: Optional[Path] = None) -> list[BootstrapEntry]:
    """Read + validate the bootstrap catalog YAML. Returns the entry list
    in source order (no sort)."""
    src = path or CATALOG_PATH
    if not src.is_file():
        raise BootstrapCatalogError(f"{src}: file not found")
    data = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise BootstrapCatalogError(f"{src}: top-level must be a mapping")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise BootstrapCatalogError(
            f"{src}: schema_version must be {SCHEMA_VERSION!r}, "
            f"got {data.get('schema_version')!r}"
        )
    raw_entries = data.get("entries") or []
    if not isinstance(raw_entries, list):
        raise BootstrapCatalogError(f"{src}: entries must be a list")

    seen_ids: set[str] = set()
    seen_env_vars: set[str] = set()
    entries: list[BootstrapEntry] = []
    for i, e in enumerate(raw_entries):
        if not isinstance(e, dict):
            raise BootstrapCatalogError(f"{src}: entries[{i}] must be a mapping")
        eid = str(e.get("id") or "").strip()
        env_var = str(e.get("env_var") or "").strip()
        if not eid or not env_var:
            raise BootstrapCatalogError(
                f"{src}: entries[{i}] missing id or env_var"
            )
        if eid in seen_ids:
            raise BootstrapCatalogError(f"{src}: duplicate id {eid!r}")
        if env_var in seen_env_vars:
            raise BootstrapCatalogError(f"{src}: duplicate env_var {env_var!r}")
        seen_ids.add(eid)
        seen_env_vars.add(env_var)

        criticality = str(e.get("criticality") or "optional").strip()
        if criticality not in ("required", "recommended", "optional"):
            raise BootstrapCatalogError(
                f"{src}: entries[{i}].criticality invalid: {criticality!r}"
            )
        raw_probe = e.get("probe") or {}
        if not isinstance(raw_probe, dict):
            raise BootstrapCatalogError(
                f"{src}: entries[{i}].probe must be a mapping"
            )
        method = str(raw_probe.get("method") or "skip").upper()
        if method.lower() == "skip":
            method = "skip"
        if method not in ("GET", "HEAD", "skip"):
            raise BootstrapCatalogError(
                f"{src}: entries[{i}].probe.method invalid: {method!r}"
            )
        probe = BootstrapProbe(
            method=method,
            url=str(raw_probe.get("url") or ""),
            auth_header=str(raw_probe.get("auth_header") or ""),
            extra_headers=dict(raw_probe.get("extra_headers") or {}),
            reason=str(raw_probe.get("reason") or ""),
        )
        entries.append(
            BootstrapEntry(
                id=eid,
                label=str(e.get("label") or eid),
                purpose=str(e.get("purpose") or "").strip(),
                env_var=env_var,
                target_file=str(e.get("target_file") or "orchestrator/.env"),
                criticality=criticality,
                group=(e.get("group") or None) and str(e["group"]).strip(),
                signup_url=str(e.get("signup_url") or ""),
                format_hint=str(e.get("format_hint") or "").strip(),
                probe=probe,
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Intent matching -- which catalog entries to propose
# ---------------------------------------------------------------------------


def propose_for_intent(
    intent_text: str,
    catalog: list[BootstrapEntry],
    *,
    include_optional: bool = True,
) -> list[BootstrapEntry]:
    """Pick the subset of catalog entries that fit the PI's free-form intent.

    Always include `required` entries. Always include `recommended`.
    Include `optional` entries when their id/label/env_var appears in the
    intent text (case-insensitive substring match) OR when
    `include_optional=True` and the intent contains hints like "all",
    "everything", or "full".

    For groups (e.g., claude-auth) the caller is expected to keep all
    members so the PI can pick one at ratification. We do NOT collapse
    groups here -- the PI surface needs both candidates visible.
    """
    intent_lower = (intent_text or "").lower()
    full_install = bool(
        re.search(r"\b(all|everything|full|complete|every)\b", intent_lower)
    )
    selected: list[BootstrapEntry] = []
    for e in catalog:
        if e.criticality == "required" or e.criticality == "recommended":
            selected.append(e)
            continue
        # optional entries: mention check OR full-install hint
        if full_install and include_optional:
            selected.append(e)
            continue
        for needle in (e.id.lower(), e.label.lower(), e.env_var.lower()):
            if needle and needle in intent_lower:
                selected.append(e)
                break
    return selected


# ---------------------------------------------------------------------------
# Env template render
# ---------------------------------------------------------------------------


_TEMPLATE_HEADER = """\
# orchestrator/.env -- bootstrap template generated by Phase B.
#
# Replace each `<paste-here>` placeholder with the real value, save the
# file (file-mode 0600 -- owner-readable only), then resume the parked
# bootstrap interrupt via /orchestrator-bootstrap-continue (the
# orchestrator will probe each filled key and report pass/fail without
# logging the values).
#
# Mutually-exclusive groups: pick ONE entry per group and delete the
# unused one. The group is noted in the comment block above each var.
"""


def render_env_template(
    entries: list[BootstrapEntry],
    *,
    existing_values: Optional[dict[str, str]] = None,
) -> str:
    """Compose an annotated .env-format text for the PI to fill.

    Each entry gets a 5-9 line comment block followed by `VAR=<paste-here>`
    (or `VAR=<already-set>` if `existing_values` already has it -- the
    pre-fill is preserved as a comment so the PI can re-fill or leave it).
    """
    existing = existing_values or {}
    lines: list[str] = [_TEMPLATE_HEADER]

    by_group: dict[str, list[BootstrapEntry]] = {}
    standalone: list[BootstrapEntry] = []
    for e in entries:
        if e.group:
            by_group.setdefault(e.group, []).append(e)
        else:
            standalone.append(e)

    def _emit(e: BootstrapEntry, group_note: str = "") -> None:
        lines.append("")
        lines.append(f"# --- {e.label} ---")
        if group_note:
            lines.append(f"# {group_note}")
        lines.append(f"# Purpose:    {e.purpose.strip()}")
        lines.append(f"# Criticality: {e.criticality}")
        if e.format_hint:
            lines.append(f"# Format:     {e.format_hint.strip()}")
        if e.signup_url:
            lines.append(f"# Sign-up:    {e.signup_url}")
        if existing.get(e.env_var):
            lines.append(
                f"# (already set in existing .env; uncomment to replace)"
            )
            lines.append(f"# {e.env_var}=<paste-here>")
        else:
            lines.append(f"{e.env_var}=<paste-here>")

    # Group block: emit each member with a "mutually exclusive" note.
    for group_name, members in by_group.items():
        names = " | ".join(m.env_var for m in members)
        for e in members:
            _emit(
                e,
                group_note=f"GROUP `{group_name}` (pick ONE of: {names}); delete the unused one.",
            )

    # Standalone entries.
    for e in standalone:
        _emit(e)

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# .env file reader (no value logging)
# ---------------------------------------------------------------------------


_ENV_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a `.env`-formatted file. Returns `{var_name: value}` for
    non-comment, non-empty lines. Strips surrounding quotes. Values are
    NOT logged anywhere by this function -- the caller's
    responsibility is to never echo the dict.

    Lines that look like `VAR=<paste-here>` (the template placeholder)
    are dropped -- treated as "not filled yet".
    """
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0]  # strip end-of-line comments
        m = _ENV_LINE.match(line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        # strip matching surrounding quotes
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        # placeholder -> treat as unfilled
        if v == "<paste-here>" or v == "":
            continue
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Verify (probe each filled entry)
# ---------------------------------------------------------------------------


# Same HTTP-client shape as credential_validator (deliberate parallel so
# tests can share the injected fake).
HTTPClient = Callable[[str, str, dict[str, str], float], tuple[int, Optional[str]]]


def _default_http_client() -> HTTPClient:
    """Lazy-import httpx so the module stays import-cheap under test."""
    def _call(method: str, url: str, headers: dict[str, str], timeout: float):
        try:
            import httpx
        except ImportError:
            return (0, "httpx not installed")
        try:
            r = httpx.request(method, url, headers=headers, timeout=timeout)
            return (r.status_code, None)
        except Exception as e:  # noqa: BLE001
            return (0, f"{type(e).__name__}: {str(e)[:120]}")
    return _call


def _classify_status(status: int, network_err: Optional[str]) -> tuple[str, str]:
    """Map (status_code, network_err) -> (classification, detail).
    Same tiering as credential_validator: 2xx=valid, 401/403=rejected,
    network=unreachable."""
    if network_err:
        return "unreachable", f"network error: {network_err}"
    if 200 <= status < 300:
        return "valid", f"HTTP {status}"
    if status in (401, 403):
        return "rejected", f"HTTP {status} (endpoint reachable; key rejected)"
    if status == 0:
        return "unreachable", "no response (timeout or DNS failure)"
    return "unreachable", f"HTTP {status} (unexpected)"


def verify_filled(
    entries: list[BootstrapEntry],
    env_values: dict[str, str],
    *,
    http_client: Optional[HTTPClient] = None,
    timeout_seconds: float = 5.0,
) -> list[VerifyResult]:
    """For each entry, classify based on env_values and probe."""
    client = http_client or _default_http_client()
    results: list[VerifyResult] = []
    for e in entries:
        value = env_values.get(e.env_var, "")
        if not value:
            results.append(
                VerifyResult(
                    entry_id=e.id,
                    env_var=e.env_var,
                    classification="missing",
                    detail=f"{e.env_var} not set in .env",
                )
            )
            continue
        if e.probe.method == "skip":
            results.append(
                VerifyResult(
                    entry_id=e.id,
                    env_var=e.env_var,
                    classification="deferred",
                    detail=e.probe.reason or "no probe declared",
                )
            )
            continue
        # Render the probe URL + headers without logging the value.
        url = e.probe.url.replace("{value}", value) if "{value}" in e.probe.url else e.probe.url
        headers: dict[str, str] = dict(e.probe.extra_headers)
        if e.probe.auth_header:
            # format: "Header-Name: template-with-{value}"
            header_line = e.probe.auth_header.replace("{value}", value)
            if ":" in header_line:
                hk, hv = header_line.split(":", 1)
                headers[hk.strip()] = hv.strip()
        status, err = client(e.probe.method, url, headers, timeout_seconds)
        cls, detail = _classify_status(status, err)
        results.append(
            VerifyResult(
                entry_id=e.id,
                env_var=e.env_var,
                classification=cls,
                detail=detail,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Rendering (PI-facing summary; never includes values)
# ---------------------------------------------------------------------------


_GLYPHS = {
    "valid": "✓",
    "deferred": "·",
    "missing": "✗",
    "rejected": "✗",
    "unreachable": "?",
}


def render_verify_summary(
    results: list[VerifyResult], *, catalog: list[BootstrapEntry]
) -> str:
    """One-line-per-entry summary, safe for the PI transcript."""
    if not results:
        return "(no entries to verify)"
    label_by_id = {e.id: e.label for e in catalog}
    crit_by_id = {e.id: e.criticality for e in catalog}
    lines = ["Bootstrap verify results:"]
    for r in results:
        glyph = _GLYPHS.get(r.classification, "?")
        label = label_by_id.get(r.entry_id, r.entry_id)
        crit = crit_by_id.get(r.entry_id, "")
        lines.append(
            f"  {glyph} {label} ({r.env_var}, {crit}) - {r.classification}: {r.detail}"
        )
    return "\n".join(lines)
