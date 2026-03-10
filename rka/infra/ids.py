"""ULID-based ID generation with type prefixes."""

from __future__ import annotations

from ulid import ULID

# Prefix mapping: entity type → 3-char prefix
_PREFIXES = {
    "decision": "dec",
    "literature": "lit",
    "journal": "jrn",
    "mission": "mis",
    "checkpoint": "chk",
    "event": "evt",
    "scan": "scn",
}


def generate_id(entity_type: str) -> str:
    """Generate a prefixed ULID for the given entity type.

    Format: {prefix}_{ulid}
    Example: dec_01HXYZ...

    ULIDs are sortable by creation time and globally unique.
    """
    prefix = _PREFIXES.get(entity_type, entity_type[:3])
    return f"{prefix}_{ULID()}"
