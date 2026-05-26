"""Phase D, D4 — credential probe + criticality categorization tests.

Covers:
  - probe_secret: classification across all outcomes
    (valid/rejected/missing/no_probe/unreachable/skipped)
  - Header template substitution (`Authorization: Bearer {value}`)
  - HEAD → GET fallback on 405/501
  - probe_all_secrets: per-tool health/blocked classification
  - CredentialReport: failed_required vs failed_recommended vs
    failed_optional bucketing
  - render_credential_report: no secret value ever appears
"""

from __future__ import annotations

import pytest

from orchestrator.credential_validator import (
    CredentialReport,
    ProbeResult,
    probe_all_secrets,
    probe_secret,
    render_credential_report,
)
from orchestrator.manifest import SecretDecl, ToolDecl


# ---------------------------------------------------------------------------
# Fake HTTP client: deterministic, records calls
# ---------------------------------------------------------------------------


class _FakeHTTP:
    """Records all calls and returns scripted (status, error) tuples."""

    def __init__(self, responses: list[tuple[int, str | None]] | None = None):
        self.responses = list(responses or [])
        self.calls: list[dict] = []

    def script(self, status: int, error: str | None = None) -> None:
        self.responses.append((status, error))

    def __call__(self, method: str, url: str, headers: dict, timeout: float):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "timeout": timeout}
        )
        if not self.responses:
            return (200, None)
        return self.responses.pop(0)


# ---------------------------------------------------------------------------
# probe_secret — classification matrix
# ---------------------------------------------------------------------------


def _api_key_secret(probe_url="https://example.org/health", probe_header="X-API-Key: {value}"):
    return SecretDecl(
        name="X_KEY",
        auth_type="api_key",
        criticality="required",
        probe_url=probe_url,
        probe_header=probe_header,
        description="X API key",
    )


def test_probe_secret_valid_classification_on_2xx():
    http = _FakeHTTP([(200, None)])
    result = probe_secret(_api_key_secret(), "real-key-value", http_client=http)
    assert result.ok is True
    assert result.classification == "valid"
    assert "200" in result.detail


def test_probe_secret_rejected_classification_on_401():
    http = _FakeHTTP([(401, None)])
    result = probe_secret(_api_key_secret(), "bad-key", http_client=http)
    assert result.ok is False
    assert result.classification == "rejected"
    assert "401" in result.detail


def test_probe_secret_rejected_classification_on_403():
    http = _FakeHTTP([(403, None)])
    result = probe_secret(_api_key_secret(), "bad-key", http_client=http)
    assert result.classification == "rejected"


def test_probe_secret_unreachable_on_network_error():
    http = _FakeHTTP([(0, "ConnectError: failed")])
    result = probe_secret(_api_key_secret(), "k", http_client=http)
    assert result.ok is False
    assert result.classification == "unreachable"
    assert "network error" in result.detail


def test_probe_secret_unreachable_on_5xx():
    http = _FakeHTTP([(500, None)])
    result = probe_secret(_api_key_secret(), "k", http_client=http)
    assert result.classification == "unreachable"


def test_probe_secret_missing_when_value_none():
    result = probe_secret(_api_key_secret(), None, http_client=_FakeHTTP())
    assert result.ok is False
    assert result.classification == "missing"


def test_probe_secret_missing_when_value_empty():
    result = probe_secret(_api_key_secret(), "  ", http_client=_FakeHTTP())
    assert result.classification == "missing"


def test_probe_secret_missing_when_value_is_placeholder():
    result = probe_secret(_api_key_secret(), "<paste-here>", http_client=_FakeHTTP())
    assert result.classification == "missing"


def test_probe_secret_no_probe_classification_when_auth_type_none():
    s = SecretDecl(name="X", auth_type="none", criticality="required")
    result = probe_secret(s, value=None, http_client=_FakeHTTP())
    assert result.ok is True
    assert result.classification == "no_probe"


def test_probe_secret_no_probe_when_value_given_but_no_probe_url():
    # Caller provided a value but the manifest didn't declare probe metadata.
    s = SecretDecl(
        name="X", auth_type="api_key", criticality="required",
        probe_url=None, probe_header=None,
    )
    result = probe_secret(s, "some-key", http_client=_FakeHTTP())
    assert result.ok is True
    assert result.classification == "no_probe"
    assert "on PI's word" in result.detail


def test_probe_secret_skipped_when_auth_type_unsupported():
    s = SecretDecl(name="X", auth_type="oauth_browser", criticality="required")
    result = probe_secret(s, "tok", http_client=_FakeHTTP())
    assert result.ok is False
    assert result.classification == "skipped"


# ---------------------------------------------------------------------------
# Header template substitution
# ---------------------------------------------------------------------------


def test_probe_secret_substitutes_value_into_bearer_template():
    http = _FakeHTTP([(200, None)])
    s = SecretDecl(
        name="X", auth_type="api_key", criticality="required",
        probe_url="https://example.org/health",
        probe_header="Authorization: Bearer {value}",
    )
    probe_secret(s, "abc123secret", http_client=http)
    # Verify the header was sent with the substituted value.
    headers = http.calls[0]["headers"]
    assert headers["Authorization"] == "Bearer abc123secret"


def test_probe_secret_substitutes_value_into_custom_header_name():
    http = _FakeHTTP([(200, None)])
    s = SecretDecl(
        name="X", auth_type="api_key", criticality="required",
        probe_url="https://example.org/", probe_header="X-Custom-Key: {value}",
    )
    probe_secret(s, "kv", http_client=http)
    assert http.calls[0]["headers"]["X-Custom-Key"] == "kv"


def test_probe_secret_header_without_value_placeholder_appends_value():
    """Defensive: if probe_header has no {value} placeholder, the
    helper appends the value rather than dropping it."""
    http = _FakeHTTP([(200, None)])
    s = SecretDecl(
        name="X", auth_type="api_key", criticality="required",
        probe_url="https://example.org/", probe_header="Authorization: Bearer",
    )
    probe_secret(s, "tok", http_client=http)
    # The header value contains 'tok' even though the template had no {value}.
    assert "tok" in http.calls[0]["headers"]["Authorization"]


# ---------------------------------------------------------------------------
# HEAD → GET fallback
# ---------------------------------------------------------------------------


def test_probe_secret_falls_back_to_get_on_405():
    """HEAD returns 405 (Method Not Allowed); fall back to GET."""
    http = _FakeHTTP([(405, None), (200, None)])
    result = probe_secret(_api_key_secret(), "k", http_client=http)
    assert result.classification == "valid"
    # Two calls: HEAD then GET.
    assert [c["method"] for c in http.calls] == ["HEAD", "GET"]


def test_probe_secret_falls_back_to_get_on_501():
    http = _FakeHTTP([(501, None), (200, None)])
    result = probe_secret(_api_key_secret(), "k", http_client=http)
    assert result.classification == "valid"


def test_probe_secret_does_not_fall_back_on_401():
    """401 is conclusive — no fallback (the credential was rejected,
    not the method)."""
    http = _FakeHTTP([(401, None)])
    result = probe_secret(_api_key_secret(), "k", http_client=http)
    assert result.classification == "rejected"
    # Only one call.
    assert len(http.calls) == 1


# ---------------------------------------------------------------------------
# probe_all_secrets — per-tool classification
# ---------------------------------------------------------------------------


def test_probe_all_secrets_healthy_tools_when_all_valid():
    http = _FakeHTTP([(200, None)])
    tools = [
        ToolDecl(
            name="tool_a",
            type="mcp_stdio",
            secrets=[_api_key_secret()],
        )
    ]
    report = probe_all_secrets(tools, {"X_KEY": "real-value"}, http_client=http)
    assert report.healthy_tools == ["tool_a"]
    assert report.blocked_tools == []
    assert report.failed_required == []
    assert report.failed_recommended == []


def test_probe_all_secrets_blocks_tool_when_required_secret_missing():
    http = _FakeHTTP()  # never called — value is missing
    tools = [
        ToolDecl(name="tool_a", type="mcp_stdio", secrets=[_api_key_secret()]),
    ]
    report = probe_all_secrets(tools, env_values={}, http_client=http)
    assert "tool_a" in report.blocked_tools
    assert report.healthy_tools == []
    assert len(report.failed_required) == 1
    tname, sd, result = report.failed_required[0]
    assert tname == "tool_a"
    assert sd.name == "X_KEY"
    assert result.classification == "missing"


def test_probe_all_secrets_marks_recommended_failures_separately():
    """Recommended-tier failures don't block the tool — but they show up
    in failed_recommended for the runner to escalate-once at session start."""
    s = _api_key_secret()
    s.criticality = "recommended"
    tools = [ToolDecl(name="tool_a", type="mcp_stdio", secrets=[s])]
    report = probe_all_secrets(tools, env_values={}, http_client=_FakeHTTP())
    assert report.blocked_tools == []
    assert len(report.failed_recommended) == 1
    assert tools[0].name not in report.healthy_tools  # degraded, not healthy


def test_probe_all_secrets_marks_optional_failures_separately():
    """Optional-tier failures don't block AND don't trigger
    session-start escalation — they just record for the journal note."""
    s = _api_key_secret()
    s.criticality = "optional"
    tools = [ToolDecl(name="tool_a", type="mcp_stdio", secrets=[s])]
    report = probe_all_secrets(tools, env_values={}, http_client=_FakeHTTP())
    assert report.failed_optional and report.failed_optional[0][0] == "tool_a"
    assert report.failed_required == []
    assert report.failed_recommended == []


def test_probe_all_secrets_handles_mixed_tools():
    """One healthy tool + one blocked + one degraded + one
    optional-skipped, all in the same probe sweep."""
    healthy_s = SecretDecl(
        name="HEALTHY", auth_type="api_key", criticality="required",
        probe_url="https://example.org/", probe_header="X-Key: {value}",
    )
    blocked_s = SecretDecl(
        name="BLOCKED", auth_type="api_key", criticality="required",
        probe_url="https://example.org/", probe_header="X-Key: {value}",
    )
    degraded_s = SecretDecl(
        name="DEGRADED", auth_type="api_key", criticality="recommended",
        probe_url="https://example.org/", probe_header="X-Key: {value}",
    )
    optional_s = SecretDecl(
        name="OPTIONAL", auth_type="api_key", criticality="optional",
        probe_url="https://example.org/", probe_header="X-Key: {value}",
    )
    tools = [
        ToolDecl(name="tool_h", type="mcp_stdio", secrets=[healthy_s]),
        ToolDecl(name="tool_b", type="mcp_stdio", secrets=[blocked_s]),
        ToolDecl(name="tool_d", type="mcp_stdio", secrets=[degraded_s]),
        ToolDecl(name="tool_o", type="mcp_stdio", secrets=[optional_s]),
    ]
    # tool_h: probe returns 200 (healthy)
    # Others: no value provided → missing, no HTTP call
    http = _FakeHTTP([(200, None)])
    report = probe_all_secrets(
        tools, env_values={"HEALTHY": "real-value"}, http_client=http
    )
    assert "tool_h" in report.healthy_tools
    assert "tool_b" in report.blocked_tools
    # degraded + optional don't appear in healthy OR blocked.
    assert "tool_d" not in report.healthy_tools
    assert "tool_d" not in report.blocked_tools
    assert "tool_o" not in report.healthy_tools
    assert "tool_o" not in report.blocked_tools


# ---------------------------------------------------------------------------
# Rendered report safety: never contains secret values
# ---------------------------------------------------------------------------


def test_render_credential_report_omits_secret_values():
    """Critical safety check: the rendered report must never include
    a secret value. Probe results are summary-only.

    Tests both the all-healthy case (the report says '1/1 valid' without
    naming the secret) and a mixed failure case (failed secrets ARE
    named so PI knows which one to fix, but the value is never echoed).
    """
    http = _FakeHTTP([(200, None), (401, None)])
    healthy_s = SecretDecl(
        name="HEALTHY_KEY", auth_type="api_key", criticality="required",
        probe_url="https://example.org/", probe_header="X-Key: {value}",
    )
    bad_s = SecretDecl(
        name="BAD_KEY", auth_type="api_key", criticality="required",
        probe_url="https://example.org/", probe_header="X-Key: {value}",
    )
    tools = [
        ToolDecl(name="tool_a", type="mcp_stdio", secrets=[healthy_s]),
        ToolDecl(name="tool_b", type="mcp_stdio", secrets=[bad_s]),
    ]
    SUPER_SECRET = "absolutely-must-not-leak-this"
    BAD_VALUE = "this-also-must-not-leak"
    report = probe_all_secrets(
        tools,
        env_values={"HEALTHY_KEY": SUPER_SECRET, "BAD_KEY": BAD_VALUE},
        http_client=http,
    )
    rendered = render_credential_report(report)
    # Tool names appear.
    assert "tool_a" in rendered
    assert "tool_b" in rendered
    # Failed secret's NAME appears (so PI knows which to fix).
    assert "BAD_KEY" in rendered
    # CRITICAL: neither secret VALUE appears.
    assert SUPER_SECRET not in rendered
    assert BAD_VALUE not in rendered


def test_render_credential_report_lists_blocked_tools_clearly():
    """Blocked tools should be visually distinct from healthy ones."""
    http = _FakeHTTP()
    tools = [
        ToolDecl(name="tool_b", type="mcp_stdio", secrets=[_api_key_secret()]),
    ]
    report = probe_all_secrets(tools, env_values={}, http_client=http)
    rendered = render_credential_report(report)
    assert "tool_b" in rendered
    assert "BLOCKED" in rendered or "✗" in rendered


def test_render_credential_report_empty_when_no_secrets():
    report = CredentialReport(
        results={},
        failed_required=[],
        failed_recommended=[],
        failed_optional=[],
        healthy_tools=[],
        blocked_tools=[],
    )
    rendered = render_credential_report(report)
    assert "no secrets" in rendered.lower()
