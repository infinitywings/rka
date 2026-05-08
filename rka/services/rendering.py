"""Rendering helpers — text decoration applied across multiple Brain-facing surfaces.

This module exists so a single helper keeps STALE/freshness prefixes
consistent across rka_get_context, rka_get_research_map, rka_list_clusters,
and rka_multi_hop_retrieval. Per Mission B Affordance B
(mis_01KR209WY4M6WQFEXRH79KC2ZF), the alternative would be per-surface
duplication, which the bookkeeper-invariant principle explicitly rejects.

The helpers are pure functions (no DB / no IO / no async) — easy to call
from any surface and trivial to test in isolation.
"""

from __future__ import annotations


STALE_PREFIX = "[STALE — needs reprocessing]"


def with_staleness_prefix(text: str | None, needs_reprocessing: bool | int | None) -> str | None:
    """Return `text` prefixed with the STALE marker when the cluster (or any
    surface representing one) is flagged for reprocessing.

    - If `needs_reprocessing` is truthy (bool True or int 1+), prepend the
      STALE_PREFIX to `text` on its own line.
    - If `needs_reprocessing` is falsy, return `text` unchanged.
    - If `text` is None or empty AND staleness is set, still surface the
      prefix alone — the consumer surface should not silently drop the
      stale signal just because the synthesis hasn't been written yet.

    Idempotent: never double-prefixes a string already carrying the prefix.
    """
    is_stale = bool(needs_reprocessing)
    if not is_stale:
        return text
    if text is None:
        return STALE_PREFIX
    if text.startswith(STALE_PREFIX):
        return text  # idempotency
    if not text.strip():
        return STALE_PREFIX
    return f"{STALE_PREFIX}\n{text}"
