"""PI notification daemon.

Scaffold stub. T8 will implement:

- terminal bell (BEL char) — default-on
- macOS `osascript` notification — default-on
- opt-in webhook with a blocklist of known telemetry endpoints

Telemetry stance: zero outbound by default.
"""

from __future__ import annotations

WEBHOOK_BLOCKLIST: frozenset[str] = frozenset(
    {
        # Known telemetry / analytics endpoints — refuse to POST here even
        # if the user supplies them via env. Extend in T8 if more surface.
        "api.segment.io",
        "api.amplitude.com",
        "api.mixpanel.com",
        "events.statsig.com",
        "api.posthog.com",
        "app.posthog.com",
        "api.heap.io",
    }
)


def notify_pi(message: str) -> None:
    """Placeholder. Real impl arrives in T8."""
    raise NotImplementedError("notify_pi arrives in T8")
