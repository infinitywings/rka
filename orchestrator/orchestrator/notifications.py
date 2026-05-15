"""PI notification daemon (T8).

Three delivery channels, in default order of preference:

  1. **terminal bell** — BEL char to stdout. Default-on.
  2. **macOS osascript** — `display notification ... with title "RKA"`.
     Default-on on Darwin; silently skipped elsewhere.
  3. **webhook** — opt-in only. The URL must not appear in
     `WEBHOOK_BLOCKLIST` (which lists known telemetry endpoints). The
     workflow_thread_id is included in the JSON body so external
     ingestion can correlate notifications to RKA artifacts.

Telemetry stance: zero outbound by default. The blocklist is a floor —
the user (or T11 audit) can extend it if more telemetry endpoints surface.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Callable

from orchestrator.state import NotificationRecord

WEBHOOK_BLOCKLIST: frozenset[str] = frozenset(
    {
        "api.segment.io",
        "api.amplitude.com",
        "api.mixpanel.com",
        "events.statsig.com",
        "api.posthog.com",
        "app.posthog.com",
        "api.heap.io",
    }
)
"""Hosts the webhook channel refuses to POST to. Compared as substrings
against the host portion of the URL so subdomains are also caught."""

DEFAULT_CHANNELS: tuple[str, ...] = ("bell", "osascript")
"""Channels that fire when the caller does not specify. Webhook is
deliberately excluded — it is opt-in only."""


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Internal channel implementations
# ---------------------------------------------------------------------------


def _ring_bell(stream=None) -> bool:
    """Write BEL to stdout. Always reports delivered=True (no failure mode)."""
    stream = stream or sys.stdout
    try:
        stream.write("\a")
        stream.flush()
        return True
    except Exception:  # noqa: BLE001
        return False


def _osascript_notify(message: str, *, runner: Callable | None = None) -> bool:
    """Invoke `osascript` to emit a macOS notification.

    On non-Darwin platforms we report `delivered=False` and skip the call;
    the test suite injects a runner so this works offline.
    """
    if runner is None:
        if platform.system() != "Darwin":
            return False
        runner = subprocess.run

    # AppleScript needs `"` escaped; we keep the message short to avoid
    # the 256-char display-notification limit.
    safe = message.replace('"', '\\"')[:240]
    script = f'display notification "{safe}" with title "RKA"'
    try:
        result = runner(["osascript", "-e", script], capture_output=True)
        return result.returncode == 0
    except (FileNotFoundError, Exception):  # noqa: BLE001
        return False


def _is_blocked_webhook(url: str) -> bool:
    """True if any blocklisted host appears in the URL string."""
    lower = url.lower()
    return any(host in lower for host in WEBHOOK_BLOCKLIST)


def _post_webhook(
    url: str,
    message: str,
    *,
    workflow_thread_id: str | None = None,
    http_fn: Callable | None = None,
) -> bool:
    """POST {message, workflow_thread_id} to the webhook. Returns delivered."""
    if _is_blocked_webhook(url):
        return False
    if http_fn is None:
        try:
            import httpx
        except ImportError:
            return False
        http_fn = lambda u, json: httpx.post(u, json=json, timeout=5.0)
    try:
        resp = http_fn(
            url,
            {"message": message, "workflow_thread_id": workflow_thread_id},
        )
        # The fake passes a simple object that may not have status_code; treat
        # anything that doesn't raise as delivered.
        status = getattr(resp, "status_code", 200)
        return 200 <= status < 300
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def notify_pi(
    message: str,
    *,
    channels: list[str] | tuple[str, ...] | None = None,
    workflow_thread_id: str | None = None,
    webhook_url: str | None = None,
    bell_stream: Any = None,
    osascript_runner: Callable | None = None,
    http_fn: Callable | None = None,
) -> list[NotificationRecord]:
    """Notify the PI through the configured channels.

    Returns one `NotificationRecord` per attempted channel (with
    `delivered=True/False`). The caller appends them to
    `state["notifications"]` via the LangGraph reducer.
    """
    if channels is None:
        channels = DEFAULT_CHANNELS

    records: list[NotificationRecord] = []
    for channel in channels:
        timestamp = _now_iso()
        if channel == "bell":
            delivered = _ring_bell(bell_stream)
        elif channel == "osascript":
            delivered = _osascript_notify(message, runner=osascript_runner)
        elif channel == "webhook":
            if not webhook_url:
                delivered = False
            else:
                delivered = _post_webhook(
                    webhook_url,
                    message,
                    workflow_thread_id=workflow_thread_id,
                    http_fn=http_fn,
                )
        else:
            # Unknown channel — record but mark not delivered.
            delivered = False
        records.append(
            {
                "channel": channel,  # type: ignore[typeddict-item]
                "message": message,
                "timestamp": timestamp,
                "delivered": delivered,
            }
        )
    return records
