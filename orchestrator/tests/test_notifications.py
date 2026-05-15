"""Unit tests for the notification daemon (T8)."""

from __future__ import annotations

import io
import subprocess
from dataclasses import dataclass

import pytest

from orchestrator import notifications


# ---------------------------------------------------------------------------
# WEBHOOK_BLOCKLIST floor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "api.segment.io",
        "api.amplitude.com",
        "api.mixpanel.com",
        "events.statsig.com",
        "api.posthog.com",
        "app.posthog.com",
        "api.heap.io",
    ],
)
def test_webhook_blocklist_contains_known_telemetry(host):
    # Floor per the upfront Backbrief — locked at T1, reaffirmed here.
    assert host in notifications.WEBHOOK_BLOCKLIST


def test_is_blocked_webhook_catches_subdomains():
    assert notifications._is_blocked_webhook("https://api.segment.io/v1/track")
    assert notifications._is_blocked_webhook("https://us.api.posthog.com/x")


def test_is_blocked_webhook_passes_safe_urls():
    assert not notifications._is_blocked_webhook("https://hooks.example.com/notify")
    assert not notifications._is_blocked_webhook("https://localhost:8080/notify")


# ---------------------------------------------------------------------------
# Default channels (telemetry-zero stance)
# ---------------------------------------------------------------------------


def test_default_channels_exclude_webhook():
    # Telemetry-zero: webhook is opt-in only.
    assert "webhook" not in notifications.DEFAULT_CHANNELS
    assert "bell" in notifications.DEFAULT_CHANNELS
    assert "osascript" in notifications.DEFAULT_CHANNELS


# ---------------------------------------------------------------------------
# Bell channel
# ---------------------------------------------------------------------------


def test_bell_writes_BEL_to_stream():
    buf = io.StringIO()
    delivered = notifications._ring_bell(buf)
    assert delivered is True
    assert buf.getvalue() == "\a"


def test_notify_pi_bell_only():
    buf = io.StringIO()
    records = notifications.notify_pi(
        "hello",
        channels=["bell"],
        bell_stream=buf,
        osascript_runner=lambda *a, **k: None,  # unused
    )
    assert len(records) == 1
    assert records[0]["channel"] == "bell"
    assert records[0]["delivered"] is True
    assert records[0]["message"] == "hello"
    assert "\a" in buf.getvalue()


# ---------------------------------------------------------------------------
# osascript channel
# ---------------------------------------------------------------------------


@dataclass
class FakeProc:
    returncode: int = 0


def test_osascript_notify_passes_message_into_applescript():
    captured = {}

    def fake_runner(args, **kw):
        captured["args"] = args
        return FakeProc(returncode=0)

    delivered = notifications._osascript_notify("important", runner=fake_runner)
    assert delivered is True
    cmdline = captured["args"]
    assert cmdline[0] == "osascript"
    assert cmdline[1] == "-e"
    assert "important" in cmdline[2]
    assert "RKA" in cmdline[2]


def test_osascript_notify_escapes_double_quotes():
    captured = {}

    def fake_runner(args, **kw):
        captured["script"] = args[2]
        return FakeProc()

    notifications._osascript_notify('msg with "quotes"', runner=fake_runner)
    assert '\\"quotes\\"' in captured["script"]


def test_osascript_returns_false_on_runner_error():
    def fake_runner(args, **kw):
        raise FileNotFoundError

    assert notifications._osascript_notify("x", runner=fake_runner) is False


# ---------------------------------------------------------------------------
# Webhook channel
# ---------------------------------------------------------------------------


def test_webhook_not_delivered_when_url_blocked():
    calls = []

    def fake_http(url, json):
        calls.append((url, json))
        return FakeProc(returncode=0)  # 0 stand-in; should never reach

    records = notifications.notify_pi(
        "msg",
        channels=["webhook"],
        webhook_url="https://api.posthog.com/capture",
        http_fn=fake_http,
    )
    assert records[0]["delivered"] is False
    assert calls == []  # blocked → no HTTP call


def test_webhook_not_delivered_when_url_missing():
    records = notifications.notify_pi(
        "msg",
        channels=["webhook"],
        webhook_url=None,
    )
    assert records[0]["delivered"] is False


@dataclass
class FakeResponse:
    status_code: int = 200


def test_webhook_delivered_on_2xx_to_safe_url():
    captured = {}

    def fake_http(url, json):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse(status_code=200)

    records = notifications.notify_pi(
        "msg",
        channels=["webhook"],
        webhook_url="https://hooks.example.com/notify",
        workflow_thread_id="thr_xyz",
        http_fn=fake_http,
    )
    assert records[0]["delivered"] is True
    assert captured["json"] == {"message": "msg", "workflow_thread_id": "thr_xyz"}


def test_webhook_not_delivered_on_5xx():
    def fake_http(url, json):
        return FakeResponse(status_code=503)

    records = notifications.notify_pi(
        "msg",
        channels=["webhook"],
        webhook_url="https://hooks.example.com/notify",
        http_fn=fake_http,
    )
    assert records[0]["delivered"] is False


def test_webhook_not_delivered_when_http_raises():
    def fake_http(url, json):
        raise ConnectionError("nope")

    records = notifications.notify_pi(
        "msg",
        channels=["webhook"],
        webhook_url="https://hooks.example.com/notify",
        http_fn=fake_http,
    )
    assert records[0]["delivered"] is False


# ---------------------------------------------------------------------------
# Multi-channel + record shape
# ---------------------------------------------------------------------------


def test_notify_pi_default_channels_produce_two_records():
    buf = io.StringIO()
    records = notifications.notify_pi(
        "hello",
        bell_stream=buf,
        osascript_runner=lambda *a, **k: FakeProc(returncode=0),
    )
    assert len(records) == 2
    channels = {r["channel"] for r in records}
    assert channels == {"bell", "osascript"}


def test_notify_pi_records_carry_timestamp_and_message():
    records = notifications.notify_pi(
        "test-msg",
        channels=["bell"],
        bell_stream=io.StringIO(),
    )
    rec = records[0]
    assert rec["message"] == "test-msg"
    assert rec["timestamp"].endswith("Z")  # ISO-8601 UTC


def test_unknown_channel_records_not_delivered():
    records = notifications.notify_pi(
        "x",
        channels=["unknown-channel"],
    )
    assert records[0]["channel"] == "unknown-channel"
    assert records[0]["delivered"] is False
