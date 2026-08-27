"""Tests for the plugin's RKA-backend compatibility gate.

The gate exists to refuse a backend too OLD for the plugin. It was written as
an allowlist of accepted version prefixes, which also refused backends that are
*newer* — and since the backend ships far more often than the plugin, that is
the common case. The list read ``("2.7", "2.8")`` while the backend was 2.9.0,
so a correctly-reported 2.9.0 was rejected by its own plugin.

These tests pin the direction of the check: old is refused, current and newer
are not.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_BRIDGE = Path(__file__).resolve().parents[2] / "plugin" / "bin" / "rka-mcp-bridge.py"
_spec = importlib.util.spec_from_file_location("rka_mcp_bridge", _BRIDGE)
assert _spec and _spec.loader
bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bridge)


class TestParseVersion:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2.9.0", (2, 9, 0)),
            ("2.7", (2, 7)),
            ("2.10.1", (2, 10, 1)),
            ("3.0.0", (3, 0, 0)),
            ("2.9.0-rc1", (2, 9, 0)),
            ("  2.9.0  ", (2, 9, 0)),
        ],
    )
    def test_parses_numeric_prefix(self, raw, expected):
        assert bridge.parse_version(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "dev", "vNext"])
    def test_unparseable_returns_none(self, raw):
        assert bridge.parse_version(raw) is None

    def test_ordering_is_numeric_not_lexicographic(self):
        """`"2.10" < "2.9"` as strings; the whole point is that it must not be."""
        assert bridge.parse_version("2.10.0") > bridge.parse_version("2.9.0")


class TestGateDirection:
    """The gate is a floor. Anything at or above the minimum must pass."""

    def test_minimum_is_accepted(self):
        assert bridge.parse_version("3.0.0") >= bridge.MINIMUM_BACKEND_VERSION

    @pytest.mark.parametrize("raw", ["3.0.0", "3.1.4", "4.0.0"])
    def test_current_and_newer_backends_pass(self, raw):
        assert bridge.parse_version(raw) >= bridge.MINIMUM_BACKEND_VERSION

    @pytest.mark.parametrize("raw", ["2.7.0", "2.9.99", "1.9.9"])
    def test_older_backends_are_refused(self, raw):
        assert bridge.parse_version(raw) < bridge.MINIMUM_BACKEND_VERSION

    def test_shipped_backend_version_satisfies_the_gate(self):
        """Guards the release that forgets to widen the gate.

        This is the assertion that would have failed when the backend went to
        2.9.0 while the allowlist still read ("2.7", "2.8").
        """
        pyproject = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
        line = next(l for l in pyproject.splitlines() if l.startswith("version"))
        shipped = line.split("=", 1)[1].strip().strip('"').strip("'")
        parsed = bridge.parse_version(shipped)
        assert parsed is not None, f"unparseable version in pyproject.toml: {shipped!r}"
        assert parsed >= bridge.MINIMUM_BACKEND_VERSION, (
            f"shipped backend {shipped} is below the plugin's minimum "
            f"{bridge.MINIMUM_BACKEND_VERSION} — the plugin would refuse its own backend"
        )


def _run_bridge(tmp_path: Path, version: str | None) -> subprocess.CompletedProcess:
    # A real executable is required: the bridge checks that binary_path is
    # runnable *before* it looks at the version, so a bogus path would exit
    # early and never reach the gate under test.
    stub = tmp_path / "rka-stub"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)

    integration = tmp_path / "integration.json"
    payload: dict[str, object] = {"binary_path": str(stub)}
    if version is not None:
        payload["version"] = version
    integration.write_text(json.dumps(payload))
    return subprocess.run(
        [sys.executable, str(_BRIDGE)],
        input="",
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "RKA_INTEGRATION_FILE": str(integration)},
    )


class TestEndToEnd:
    def test_old_backend_is_refused_with_a_version_message(self, tmp_path: Path):
        result = _run_bridge(tmp_path, "2.3.2")
        assert result.returncode == 1
        assert "older than this plugin supports" in result.stderr

    def test_refusal_points_at_the_file_that_reported_the_version(self, tmp_path: Path):
        """A stale integration.json is the likeliest cause; say so."""
        result = _run_bridge(tmp_path, "2.3.2")
        assert "integration.json" in result.stderr

    @pytest.mark.parametrize("raw", ["3.0.0", "3.1.0", "3.99.0", "4.0.0"])
    def test_newer_backend_runs(self, raw, tmp_path: Path):
        """A backend newer than the plugin must launch, not be refused.

        Asserted on the exit code rather than on the absence of one phrase:
        the allowlist this replaced refused newer backends with *different*
        wording, so a message-absence check would have passed against it.
        """
        result = _run_bridge(tmp_path, raw)
        assert result.returncode == 0, result.stderr
        assert "incompatible" not in result.stderr
        assert "older than this plugin supports" not in result.stderr

    def test_unparseable_version_warns_but_does_not_block(self, tmp_path: Path):
        result = _run_bridge(tmp_path, "dev")
        assert "skipping the compatibility check" in result.stderr
        assert "older than this plugin supports" not in result.stderr
