"""Credential probe + criticality categorization (Phase D, D4).

The orchestrator's onboarding subgraph uses these helpers after the
`pi_credentials_ready` interrupt resumes: the PI has signaled they've
edited `~/rka-projects/{project_id}/.env`, and we now validate each
declared secret by probing its API.

Validation contract:
  - `probe_url` is HEAD-or-GET'd with the secret value injected per
    `probe_header` template.
  - Status 2xx (or 401/403 explicitly indicating "endpoint reachable
    but credential rejected" — used to distinguish "no creds at all"
    from "wrong creds") classifies the probe.
  - Network errors, DNS failures, timeouts → InternalErrorProbeResult
    (different from CredentialRejected — the runner should suggest
    "check your network" not "check your credentials").

Security invariants enforced here:
  - Probe results NEVER contain the secret value.
  - Probe results NEVER contain the response body (which could echo
    back the credential).
  - Logs at this layer never log the value either; the secret name
    + outcome is the entire diagnostic surface.

Criticality enforcement (Q2 ratification):
  - `required` missing/failed → escalate via checkpoint
  - `recommended` missing/failed → escalate once at session start
  - `optional` missing/failed → skip with journal note
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from orchestrator.manifest import Criticality, SecretDecl, ToolDecl

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Probe result enums + dataclass
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    """The outcome of probing a single secret.

    Fields:
      ok: True if the probe succeeded (2xx). False otherwise.
      classification:
        - "valid"      — probe returned 2xx; credential accepted
        - "rejected"   — probe returned 401 or 403; credential present
                          but rejected by the API
        - "missing"    — no value was provided for this secret in .env
        - "no_probe"   — the secret has no probe_url declared (e.g.,
                          public-API-key-with-rate-limit cases like
                          NCBI's optional key); we treat the value
                          as accepted on PI's word
        - "unreachable"— probe URL timed out, DNS failed, or returned
                          a non-2xx-non-401/403 status (5xx, etc.)
        - "skipped"    — auth_type not supported by Phase-D MVP
                          (e.g., oauth_browser); the probe layer doesn't
                          try
      detail: short human-readable summary (no secret value, no
              response body content; just status + reason)
    """

    ok: bool
    classification: str  # "valid" | "rejected" | "missing" | "no_probe" | "unreachable" | "skipped"
    detail: str = ""


# Default HTTP-client callable signature for dependency injection:
#   (method, url, headers, timeout) -> (status_code, error_message_or_none)
# In production this wraps httpx.request; in tests we inject a deterministic fake.
HTTPClient = Callable[[str, str, dict[str, str], float], tuple[int, Optional[str]]]


def _default_http_client() -> HTTPClient:
    """Production HTTP client — lazy import so the credential_validator
    module is import-cheap and testable without httpx installed."""

    def _call(method: str, url: str, headers: dict[str, str], timeout: float):
        try:
            import httpx
        except ImportError:
            return (0, "httpx not installed")
        try:
            r = httpx.request(method, url, headers=headers, timeout=timeout)
            return (r.status_code, None)
        except httpx.HTTPError as e:
            # Network class: DNS failure, timeout, connection refused, etc.
            return (0, f"{type(e).__name__}: {str(e)[:120]}")
        except Exception as e:  # noqa: BLE001
            return (0, f"{type(e).__name__}: {str(e)[:120]}")

    return _call


# ---------------------------------------------------------------------------
# Probe a single secret
# ---------------------------------------------------------------------------


def probe_secret(
    secret: SecretDecl,
    value: Optional[str],
    *,
    http_client: Optional[HTTPClient] = None,
    timeout_seconds: float = 5.0,
) -> ProbeResult:
    """Validate one declared secret against its probe_url.

    Returns a ProbeResult. The secret value never appears in the
    result. If `value` is None / empty / a placeholder, the probe is
    skipped and `classification="missing"`.

    Auth types currently supported in the probe layer:
      - `api_key` and `oauth_token` (both work the same way: pass the
        value via the probe_header template).
      - `none` → classification="no_probe" (the tool needs no
        credential; PI's `.env` doesn't carry an entry for it).

    Other auth types return `classification="skipped"` — Phase D2 will
    add their probe paths.
    """
    if secret.auth_type == "none":
        return ProbeResult(
            ok=True, classification="no_probe", detail="tool requires no credentials"
        )

    if secret.auth_type not in ("api_key", "oauth_token"):
        return ProbeResult(
            ok=False,
            classification="skipped",
            detail=f"auth_type {secret.auth_type!r} not supported by Phase-D probe layer",
        )

    if value is None or not value.strip() or value.startswith("<"):
        return ProbeResult(
            ok=False,
            classification="missing",
            detail="no value in .env (or still a <paste-here> placeholder)",
        )

    if not secret.probe_url:
        # Caller provided a value but the registry/manifest didn't
        # declare a probe URL. Trust the PI — mark as no_probe.
        return ProbeResult(
            ok=True,
            classification="no_probe",
            detail="no probe_url declared; value accepted on PI's word",
        )

    headers: dict[str, str] = {}
    if secret.probe_header:
        # Template like "Authorization: Bearer {value}" — split on first
        # ": " into header-name + header-value template, then substitute.
        if ": " in secret.probe_header:
            name, _, vtemplate = secret.probe_header.partition(": ")
        else:
            # Treat the whole string as a header name; value is the secret literal.
            name, vtemplate = secret.probe_header, "{value}"
        if "{value}" in vtemplate:
            header_value = vtemplate.replace("{value}", value)
        else:
            # Caller forgot the placeholder — substitute by appending.
            header_value = f"{vtemplate} {value}".strip()
        headers[name] = header_value

    client = http_client or _default_http_client()
    # HEAD is cheap and rarely echoes credentials in the body; fall back to
    # GET on 405 (Method Not Allowed) which some APIs return.
    status, error = client("HEAD", secret.probe_url, headers, timeout_seconds)
    if status == 405 or status == 501:
        status, error = client("GET", secret.probe_url, headers, timeout_seconds)

    if error is not None and status == 0:
        return ProbeResult(
            ok=False,
            classification="unreachable",
            detail=f"network error: {error}",
        )

    if 200 <= status < 300:
        return ProbeResult(
            ok=True,
            classification="valid",
            detail=f"HTTP {status}",
        )

    if status in (401, 403):
        return ProbeResult(
            ok=False,
            classification="rejected",
            detail=f"HTTP {status} — credential present but rejected",
        )

    # 4xx (other than 401/403) or 5xx
    return ProbeResult(
        ok=False,
        classification="unreachable",
        detail=f"HTTP {status} — endpoint reachable but unexpected status",
    )


# ---------------------------------------------------------------------------
# Sweep across all tools in a manifest
# ---------------------------------------------------------------------------


@dataclass
class CredentialReport:
    """Summary of probing every secret declared in a tool list.

    Per-secret entries are keyed by `(tool_name, secret_name)`. The
    categorized fields are convenience views the runner uses to decide
    escalation per Q2:

      - `failed_required`: required-tier secrets that are missing,
                           rejected, or unreachable. Escalate via
                           checkpoint.
      - `failed_recommended`: recommended-tier with same failure modes.
                              Escalate once at session start.
      - `failed_optional`: optional-tier failures. Skip the tool;
                            write a journal note.
    """

    results: dict[tuple[str, str], ProbeResult]
    failed_required: list[tuple[str, SecretDecl, ProbeResult]]
    failed_recommended: list[tuple[str, SecretDecl, ProbeResult]]
    failed_optional: list[tuple[str, SecretDecl, ProbeResult]]
    # Tools where every required+recommended secret probed valid — these
    # are safe to add to the subprocess MCP config without escalation.
    healthy_tools: list[str]
    # Tools with failing required secrets — these CANNOT be added to
    # the subprocess MCP config in the current session (would crash
    # the subprocess at MCP-launch time).
    blocked_tools: list[str]


def probe_all_secrets(
    tools: list[ToolDecl],
    env_values: dict[str, str],
    *,
    http_client: Optional[HTTPClient] = None,
    timeout_seconds: float = 5.0,
) -> CredentialReport:
    """Probe every secret in every tool. Returns a CredentialReport.

    Helpful classification: a tool is "healthy" iff every one of its
    `required` AND `recommended` secrets is `ok=True`. A tool is
    "blocked" iff any `required` secret fails — those tools must be
    omitted from the subprocess MCP config or the subprocess will
    fail to launch the server.

    Both lists are computed eagerly so the runner can branch on them
    without re-scanning.
    """
    results: dict[tuple[str, str], ProbeResult] = {}
    failed_required: list[tuple[str, SecretDecl, ProbeResult]] = []
    failed_recommended: list[tuple[str, SecretDecl, ProbeResult]] = []
    failed_optional: list[tuple[str, SecretDecl, ProbeResult]] = []
    healthy_tools: list[str] = []
    blocked_tools: list[str] = []

    for tool in tools:
        tool_healthy = True  # no failures of ANY tier
        tool_blocked = False  # at least one required failure
        for secret in tool.secrets:
            value = env_values.get(secret.name)
            result = probe_secret(
                secret,
                value,
                http_client=http_client,
                timeout_seconds=timeout_seconds,
            )
            results[(tool.name, secret.name)] = result
            if not result.ok:
                tool_healthy = False  # any failure → not "healthy"
                if secret.criticality == "required":
                    failed_required.append((tool.name, secret, result))
                    tool_blocked = True
                elif secret.criticality == "recommended":
                    failed_recommended.append((tool.name, secret, result))
                else:  # optional
                    failed_optional.append((tool.name, secret, result))
            # `no_probe` results are ok=True; they don't count against health.
        if tool_blocked:
            blocked_tools.append(tool.name)
        elif tool_healthy:
            healthy_tools.append(tool.name)
        # Tools that are neither blocked nor healthy are "degraded":
        # at least one non-required failure. The runner can branch on
        # `tool.name in healthy_tools` vs `tool.name in blocked_tools`
        # to decide whether to include the tool in the subprocess
        # config — degraded tools ARE included; they just had some
        # recommended/optional secret missing.

    return CredentialReport(
        results=results,
        failed_required=failed_required,
        failed_recommended=failed_recommended,
        failed_optional=failed_optional,
        healthy_tools=healthy_tools,
        blocked_tools=blocked_tools,
    )


# ---------------------------------------------------------------------------
# Render a PI-facing report (no secret values; safe for the transcript)
# ---------------------------------------------------------------------------


def render_credential_report(report: CredentialReport) -> str:
    """Compose a human-readable summary suitable for emitting in a
    journal entry or PI interrupt payload. Never includes secret values.

    Shape:
      "Credential validation results:
        ✓ tool_a: 2/2 secrets valid
        ✗ tool_b: SECRET_X missing (required) — escalating
        ⚠ tool_c: SECRET_Y rejected (recommended) — degraded operation
        — tool_d: SECRET_Z missing (optional) — tool skipped"
    """
    if not report.results:
        return "Credential validation: no secrets to probe."

    lines = ["Credential validation results:"]
    # Group by tool for readability.
    by_tool: dict[str, list[tuple[str, ProbeResult]]] = {}
    for (tool_name, secret_name), result in report.results.items():
        by_tool.setdefault(tool_name, []).append((secret_name, result))

    for tool_name, entries in sorted(by_tool.items()):
        ok_count = sum(1 for _, r in entries if r.ok)
        total = len(entries)
        if tool_name in report.blocked_tools:
            marker = "✗"
            status = "BLOCKED (required secret failure)"
        elif tool_name in report.healthy_tools:
            marker = "✓"
            status = f"{ok_count}/{total} valid"
        else:
            marker = "⚠"
            status = f"{ok_count}/{total} valid (degraded — recommended secret(s) missing)"
        lines.append(f"  {marker} {tool_name}: {status}")
        for secret_name, result in entries:
            if result.ok:
                continue
            lines.append(f"     - {secret_name}: {result.classification} ({result.detail})")
    return "\n".join(lines)
